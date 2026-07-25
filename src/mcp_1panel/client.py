"""1Panel v2 签名 HTTP 客户端。

这是整个 MCP server 的核心复用资产。所有工具 handler 都通过这个客户端调 1Panel API。

签名算法（精确，来自 1Panel 官方 + 本地 SKILL.md 验证）：
    Token = md5("1panel" + API_KEY + str(UnixTimestamp秒)).hexdigest()
    Header: 1Panel-Token = Token, 1Panel-Timestamp = 时间戳字符串
    URL: {endpoint}/api/v2{path}

关键点：
- 时间戳每请求重算（签名只在那一秒有效，不能缓存）
- 统一用 Python hashlib.md5（避免 shell md5 跨平台差异）
- v2 API 用 MD5 签名，v1 用明文 key，绝不混用
- search 类接口分页参数必填，缺 orderBy/order 会 400
"""

from __future__ import annotations

import hashlib
import time
from typing import TYPE_CHECKING, Any, Mapping

import httpx

from .config import get_settings
from .errors import PanelAPIError, PanelAuthError, PanelConfigError, PanelTransportError

if TYPE_CHECKING:
    from typing import Self

# v2 API 统一前缀
API_V2_PREFIX = "/api/v2"

# search 类接口的分页参数默认值（缺 orderBy/order 会 400）
DEFAULT_PAGE_PARAMS: dict[str, Any] = {
    "page": 1,
    "pageSize": 100,
    "orderBy": "created_at",
    "order": "descending",
}


class PanelClient:
    """1Panel v2 签名 HTTP 客户端。

    生命周期：MCP server 启动时创建一个实例（async），所有工具 handler 共享。
    httpx.AsyncClient 在 __aenter__/__aexit__ 管理，或通过 aclose() 显式关闭。
    """

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        *,
        timeout: float = 30.0,
        verify_tls: bool = True,
    ):
        if not endpoint or not api_key:
            raise PanelConfigError("endpoint 和 api_key 不能为空")
        # endpoint 去尾斜杠，确保拼接干净
        self._endpoint = endpoint.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    @classmethod
    def from_settings(cls) -> Self:
        """从环境变量配置创建客户端（生产路径）。"""
        s = get_settings()
        s.assert_panel_configured()
        return cls(
            endpoint=s.panel_endpoint,
            api_key=s.panel_api_key,
            timeout=s.panel_timeout,
            verify_tls=True,
        )

    # ---- 签名 ----

    @staticmethod
    def sign(api_key: str, timestamp: int | None = None) -> dict[str, str]:
        """计算签名 Header。

        Args:
            api_key: 1Panel API 密钥
            timestamp: Unix 秒时间戳，None 则取当前时间

        Returns:
            {"1Panel-Token": <md5hex>, "1Panel-Timestamp": <ts>}
        """
        ts = int(time.time()) if timestamp is None else timestamp
        raw = f"1panel{api_key}{ts}".encode()
        token = hashlib.md5(raw).hexdigest()
        return {"1Panel-Token": token, "1Panel-Timestamp": str(ts)}

    def _headers(self) -> dict[str, str]:
        """每请求实时计算签名（时间戳不能复用）。"""
        return self.sign(self._api_key)

    # ---- httpx 客户端管理 ----

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._endpoint + API_V2_PREFIX,
                timeout=self._timeout,
                verify=True,
                follow_redirects=True,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> Self:
        await self._ensure_client()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    # ---- 核心请求方法 ----

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: Any | None = None,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        """发送签名请求并返回 data 字段。

        Args:
            method: HTTP 方法（1Panel 几乎全用 POST，少量 GET）
            path: 接口路径，如 "/containers/search"（不含 /api/v2 前缀）
            json: 请求体（POST 的 body）
            params: URL query 参数（GET 用）
            headers: 额外 header（会与签名 header 合并）

        Returns:
            1Panel 响应的 data 字段内容

        Raises:
            PanelAuthError: 401 鉴权失败
            PanelAPIError: 非 200 业务错误
            PanelTransportError: 网络/HTTP 错误
        """
        client = await self._ensure_client()
        req_headers = {**self._headers(), **(headers or {})}

        try:
            resp = await client.request(method, path, json=json, params=params, headers=req_headers)
        except httpx.RequestError as e:
            raise PanelTransportError(f"请求 1Panel 失败: {e}") from e

        # HTTP 层错误
        if resp.status_code >= 500:
            raise PanelTransportError(f"1Panel 服务端错误 {resp.status_code}: {resp.text[:200]}")
        if resp.status_code == 401 or resp.status_code == 403:
            raise PanelAuthError(f"1Panel 鉴权失败 {resp.status_code}: {resp.text[:200]}")
        if resp.status_code >= 400:
            raise PanelTransportError(f"1Panel HTTP {resp.status_code}: {resp.text[:200]}")

        try:
            payload = resp.json()
        except ValueError as e:
            raise PanelTransportError(f"1Panel 响应非 JSON: {resp.text[:200]}") from e

        code = payload.get("code")
        # 1Panel 业务错误码
        if code == 401:
            raise PanelAuthError(f"1Panel 鉴权失败: {payload.get('message')}")
        if code is None or code != 200:
            raise PanelAPIError(
                code if isinstance(code, int) else -1,
                payload.get("message", "未知错误"),
            )

        return payload.get("data")

    # ---- 便捷方法 ----

    async def get(self, path: str, **kw: Any) -> Any:
        return await self.request("GET", path, **kw)

    async def post(self, path: str, body: Any | None = None, **kw: Any) -> Any:
        return await self.request("POST", path, json=body, **kw)

    async def search(
        self,
        path: str,
        filters: Mapping[str, Any] | None = None,
        *,
        page: int = 1,
        page_size: int = 100,
        order_by: str = "createdAt",
        order: str = "descending",
    ) -> Any:
        """search 类接口的便捷封装：自动注入分页参数。

        1Panel 的 search 接口 page/pageSize/orderBy/order 全部必填，
        缺 orderBy/order 会返回 400。此方法保证这些字段总被填上。

        注意：order_by 默认 'createdAt'（1Panel 多数模块用驼峰），
        但不同模块的可选值不同（container 只接受 name/createdAt/state，
        website 用 created_at），调用方需按 openapi.json 指定正确的值。
        """
        body: dict[str, Any] = {
            "page": page,
            "pageSize": page_size,
            "orderBy": order_by,
            "order": order,
        }
        if filters:
            body.update(filters)
        return await self.post(path, body)


# ---- 模块级单例 ----

_client: PanelClient | None = None


async def get_client() -> PanelClient:
    """获取全局共享的客户端实例。

    在 MCP server 启动后首次调用时从配置初始化。工具 handler 通过
    `await get_client()` 拿到同一个实例，复用 httpx 连接池。
    """
    global _client
    if _client is None:
        _client = PanelClient.from_settings()
    return _client


async def close_client() -> None:
    """关闭客户端（server 退出时调用）。"""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
