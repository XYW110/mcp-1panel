"""签名 HTTP 客户端测试（Phase 0 核心验收）。

重点验证：
1. MD5 签名算法正确（用固定时间戳比对已知 hash）
2. 请求确实带正确 header
3. v2 API URL 拼接正确（/api/v2 前缀）
4. 业务错误码正确分类抛异常
5. 分页参数自动注入
"""

from __future__ import annotations

import hashlib

import httpx
import pytest
import respx

from mcp_1panel.client import API_V2_PREFIX, PanelClient
from mcp_1panel.errors import PanelAPIError, PanelAuthError, PanelTransportError


# ---- 签名算法正确性 ----

class TestSigningAlgorithm:
    """验证 MD5 签名算法与 1Panel 官方一致。"""

    def test_sign_deterministic_with_fixed_timestamp(self):
        """固定时间戳，签名应是确定性的 md5 值。"""
        api_key = "mykey"
        ts = 1700000000
        expected = hashlib.md5(f"1panel{api_key}{ts}".encode()).hexdigest()
        headers = PanelClient.sign(api_key, ts)
        assert headers["1Panel-Token"] == expected
        assert headers["1Panel-Timestamp"] == "1700000000"

    def test_sign_format_is_md5_hex(self):
        """token 应是 32 位小写十六进制（md5 hexdigest）。"""
        headers = PanelClient.sign("k", 123)
        token = headers["1Panel-Token"]
        assert len(token) == 32
        assert all(c in "0123456789abcdef" for c in token)

    def test_sign_includes_1panel_prefix(self):
        """签名必须含 '1panel' 前缀（v2 协议要求，混用 v1 明文会 401）。"""
        key, ts = "abc", 100
        with_prefix = hashlib.md5(f"1panel{key}{ts}".encode()).hexdigest()
        without_prefix = hashlib.md5(f"{key}{ts}".encode()).hexdigest()
        headers = PanelClient.sign(key, ts)
        assert headers["1Panel-Token"] == with_prefix
        assert headers["1Panel-Token"] != without_prefix

    def test_sign_different_timestamp_different_token(self):
        """时间戳变化，token 必须变化（不能缓存签名）。"""
        h1 = PanelClient.sign("k", 1000)
        h2 = PanelClient.sign("k", 1001)
        assert h1["1Panel-Token"] != h2["1Panel-Token"]


# ---- 实际请求行为 ----

@pytest.mark.asyncio
async def test_request_carries_signed_headers():
    """请求必须带 1Panel-Token 和 1Panel-Timestamp header。"""
    client = PanelClient("http://1panel.test", "key")
    try:
        with respx.mock(base_url="http://1panel.test") as mock:
            mock.post("/api/v2/containers/search").respond(
                json={"code": 200, "message": "", "data": {"items": []}}
            )
            await client.post("/containers/search", {"page": 1})
            call = mock.calls.last
            header_keys = {k.lower() for k in call.request.headers}
            assert "1panel-token" in header_keys
            assert "1panel-timestamp" in header_keys
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_url_uses_api_v2_prefix():
    """URL 必须拼接 /api/v2 前缀（base_url 已含前缀，path 不重复）。"""
    assert API_V2_PREFIX == "/api/v2"
    client = PanelClient("http://1panel.test/", "key")  # 带尾斜杠
    assert client._endpoint == "http://1panel.test"  # 去尾斜杠


@pytest.mark.asyncio
async def test_post_sends_json_body():
    """POST 的 body 应作为 JSON 发送。"""
    client = PanelClient("http://1panel.test", "key")
    try:
        with respx.mock(base_url="http://1panel.test") as mock:
            mock.post("/api/v2/containers/search").respond(
                json={"code": 200, "message": "", "data": []}
            )
            await client.post("/containers/search", {"page": 1, "pageSize": 10})
            call = mock.calls.last
            import json
            body = json.loads(call.request.content)
            assert body["page"] == 1
            assert body["pageSize"] == 10
    finally:
        await client.aclose()


# ---- 错误分类 ----

@pytest.mark.asyncio
async def test_401_raises_auth_error():
    client = PanelClient("http://1panel.test", "key")
    try:
        with respx.mock(base_url="http://1panel.test") as mock:
            mock.post("/api/v2/containers/search").respond(
                json={"code": 401, "message": "API 接口密钥错误"}
            )
            with pytest.raises(PanelAuthError):
                await client.post("/containers/search")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_non200_code_raises_api_error():
    client = PanelClient("http://1panel.test", "key")
    try:
        with respx.mock(base_url="http://1panel.test") as mock:
            mock.post("/api/v2/x").respond(json={"code": 500, "message": "内部错误"})
            with pytest.raises(PanelAPIError) as exc:
                await client.post("/x")
            assert exc.value.code == 500
            assert "内部错误" in exc.value.message
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_http_500_raises_transport_error():
    client = PanelClient("http://1panel.test", "key")
    try:
        with respx.mock(base_url="http://1panel.test") as mock:
            mock.post("/api/v2/x").respond(status_code=502)
            with pytest.raises(PanelTransportError):
                await client.post("/x")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_network_error_raises_transport_error():
    client = PanelClient("http://1panel.test", "key")
    try:
        with respx.mock(base_url="http://1panel.test") as mock:
            mock.post("/api/v2/x").mock(side_effect=httpx.ConnectError("conn refused"))
            with pytest.raises(PanelTransportError):
                await client.post("/x")
    finally:
        await client.aclose()


# ---- search 便捷封装 ----

@pytest.mark.asyncio
async def test_search_injects_pagination_defaults():
    """search 方法必须自动注入 page/pageSize/orderBy/order。"""
    client = PanelClient("http://1panel.test", "key")
    try:
        with respx.mock(base_url="http://1panel.test") as mock:
            mock.post("/api/v2/containers/search").respond(
                json={"code": 200, "message": "", "data": {}}
            )
            await client.search("/containers/search", filters={"name": "nginx"})
            import json
            body = json.loads(mock.calls.last.request.content)
            assert body["page"] == 1
            assert body["pageSize"] == 100
            assert body["orderBy"] == "createdAt"
            assert body["order"] == "descending"
            assert body["name"] == "nginx"
    finally:
        await client.aclose()


# ---- 配置校验 ----

def test_empty_endpoint_raises_config_error():
    with pytest.raises(Exception):  # PanelConfigError
        PanelClient("", "key")


def test_empty_key_raises_config_error():
    with pytest.raises(Exception):
        PanelClient("http://x", "")
