"""pytest 全局 fixtures。

测试不打真实 1Panel，统一用：
- respx mock httpx（拦截 PanelClient 的请求）
- monkeypatch 注入测试用配置（PANEL_ENDPOINT / PANEL_API_KEY）
- FastMCP in-memory Client 做端到端工具测试
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import AsyncIterator

import pytest

# 测试用固定配置（不触碰真实环境）
TEST_ENDPOINT = "http://1panel.test"
TEST_API_KEY = "test-key-1234"


@pytest.fixture(autouse=True)
def _mock_settings(monkeypatch):
    """注入测试用配置，覆盖环境变量。"""
    monkeypatch.setenv("PANEL_ENDPOINT", TEST_ENDPOINT)
    monkeypatch.setenv("PANEL_API_KEY", TEST_API_KEY)
    monkeypatch.setenv("PANEL_TIMEOUT", "5")
    monkeypatch.setenv("PANEL_READONLY", "false")
    # 重置 settings lru_cache，让新环境变量生效
    from mcp_1panel.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _reset_client():
    """每个测试前后重置全局 client 单例。"""
    from mcp_1panel import client as client_mod
    client_mod._client = None
    yield
    client_mod._client = None


@pytest.fixture
def make_signed_headers():
    """返回一个函数，生成与 PanelClient.sign 一致的签名 header。

    测试用 respx 拦截请求时，用此 fixture 校验请求是否带正确签名，
    或匹配任意签名直接放行。
    """
    def _sign(api_key: str = TEST_API_KEY, ts: int | None = None) -> dict[str, str]:
        ts = ts or int(time.time())
        token = hashlib.md5(f"1panel{api_key}{ts}".encode()).hexdigest()
        return {"1Panel-Token": token, "1Panel-Timestamp": str(ts)}
    return _sign


@pytest.fixture
def ok_response():
    """构造 1Panel 成功响应体。"""
    def _make(data=None):
        return {"code": 200, "message": "", "data": data if data is not None else {}}
    return _make
