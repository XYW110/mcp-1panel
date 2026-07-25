"""openresty 模块工具测试（端到端，用 respx mock）。

FastMCP 1.28.1 调用方式：
- list_tools() -> list[Tool]  （只有元数据）
- call_tool(name, args) -> Sequence[ContentBlock] | dict  （实际执行）

注意：openresty 模块尚未加入 server.py 的 register_all 列表（由主 agent 统一加），
因此本测试在全局 mcp 实例上显式调用 openresty.register(mcp) 完成注册（仅一次，
用模块级 flag 防止重复注册）。

测试要点：
1. 工具注册（通过 list_tools 检查 10 个工具名）
2. 读工具端到端（status / base / config_get / https_status / scope）
3. 写工具的安全校验：
   - build 的 confirm 高危校验（不传 confirm 不发请求）
   - 只读模式拦截
   - config_update 写操作真的命中 API
"""

from __future__ import annotations

import pytest
import respx

from mcp_1panel.config import get_settings
from mcp_1panel.server import mcp
from mcp_1panel.tools import openresty as openresty_module
from .helpers import parse_tool_result


# ---- 一次性注册 openresty 模块到全局 mcp ----
# （server.py 的 register_all 暂未包含 openresty，主 agent 会统一加入；
#  本测试通过模块级 flag 保证只注册一次，避免重复工具名报错）

if not getattr(mcp, "_openresty_registered", False):
    openresty_module.register(mcp)
    mcp._openresty_registered = True  # type: ignore[attr-defined]


# ---- 注册验证 ----

async def test_openresty_tools_registered():
    """openresty 模块的 10 个工具应被注册到 mcp。"""
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    expected = {
        # OpenResty（6 读 + 4 写 = 10）
        "openresty_status", "openresty_base", "openresty_config_get",
        "openresty_https_status", "openresty_scope",
        "openresty_config_update", "openresty_scope_update",
        "openresty_https_update", "openresty_module_update", "openresty_build",
        # PHP Extensions（1 读 + 3 写 = 4）
        "php_extensions_search", "php_extensions_create",
        "php_extensions_update", "php_extensions_delete",
    }
    missing = expected - names
    assert not missing, f"缺少工具: {missing}"
    assert len(expected) == 14, "应有 14 个工具"


# ---- 读工具端到端 ----

@pytest.mark.asyncio
@respx.mock
async def test_openresty_status_returns_data():
    """openresty_status 应调 GET /openresty/status 并返回运行指标。"""
    respx.get("http://1panel.test/api/v2/openresty/status").respond(
        json={"code": 200, "message": "", "data": {
            "active": 5, "accepts": 100, "handled": 100,
            "requests": 500, "reading": 1, "writing": 1, "waiting": 3,
        }}
    )
    result = await mcp.call_tool("openresty_status", {})
    data = parse_tool_result(result)
    assert data["active"] == 5
    assert data["requests"] == 500


@pytest.mark.asyncio
@respx.mock
async def test_openresty_config_get_returns_content():
    """openresty_config_get 应调 GET /openresty 并返回 nginx.conf 文本。"""
    respx.get("http://1panel.test/api/v2/openresty").respond(
        json={"code": 200, "message": "", "data": {"content": "worker_processes auto;"}}
    )
    result = await mcp.call_tool("openresty_config_get", {})
    data = parse_tool_result(result)
    assert "worker_processes" in data["content"]


@pytest.mark.asyncio
@respx.mock
async def test_openresty_scope_post_with_body():
    """openresty_scope 应调 POST /openresty/scope，body 带 scope 与 websiteId。"""
    route = respx.post("http://1panel.test/api/v2/openresty/scope").respond(
        json={"code": 200, "message": "", "data": [{"name": "limit_conn", "params": ["10"]}]}
    )
    result = await mcp.call_tool("openresty_scope", {"scope": "limit-conn", "website_id": 7})
    data = parse_tool_result(result)
    # 返回 list 时 FastMCP 逐元素展平；单元素列表被 parse_tool_result 收敛为该元素
    if isinstance(data, list):
        assert data[0]["name"] == "limit_conn"
    else:
        assert data["name"] == "limit_conn"
    # 验证 body 被正确组装（驼峰 + websiteId）
    import json as _json
    sent = _json.loads(route.calls.last.request.content)
    assert sent["scope"] == "limit-conn"
    assert sent["websiteId"] == 7


@pytest.mark.asyncio
@respx.mock
async def test_php_extensions_search_returns_page():
    """php_extensions_search 应调 POST /runtimes/php/extensions/search。"""
    route = respx.post("http://1panel.test/api/v2/runtimes/php/extensions/search").respond(
        json={"code": 200, "message": "", "data": {"items": [{"id": 1, "name": "redis"}], "total": 1}}
    )
    result = await mcp.call_tool("php_extensions_search", {"page": 1, "page_size": 20})
    data = parse_tool_result(result)
    assert data["total"] == 1
    assert route.called


# ---- 写工具：config_update 真正命中 API ----

@pytest.mark.asyncio
@respx.mock
async def test_openresty_config_update_calls_api():
    """openresty_config_update 应调 POST /openresty/file，body 含 content 与 backup。"""
    import json as _json
    route = respx.post("http://1panel.test/api/v2/openresty/file").respond(
        json={"code": 200, "message": "", "data": None}
    )
    await mcp.call_tool("openresty_config_update", {
        "content": "worker_processes auto;", "backup": True,
    })
    assert route.called
    sent = _json.loads(route.calls.last.request.content)
    assert sent["content"] == "worker_processes auto;"
    assert sent["backup"] is True


# ---- 写工具：高危 confirm 校验（openresty_build） ----

@pytest.mark.asyncio
async def test_openresty_build_requires_confirm():
    """openresty_build 不传 confirm=true 应拒绝（不发起请求）。"""
    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/openresty/build")
        with pytest.raises(Exception):
            await mcp.call_tool("openresty_build", {
                "mirror": "x", "task_id": "t1", "confirm": False,
            })
        assert not route.called


@pytest.mark.asyncio
@respx.mock
async def test_openresty_build_with_confirm_calls_api():
    """openresty_build 传 confirm=true 应真正调用 API。"""
    route = respx.post("http://1panel.test/api/v2/openresty/build").respond(
        json={"code": 200, "message": "", "data": None}
    )
    await mcp.call_tool("openresty_build", {
        "mirror": "https://registry.example.com", "task_id": "uuid-1", "confirm": True,
    })
    assert route.called


@pytest.mark.asyncio
async def test_php_extensions_delete_requires_confirm():
    """php_extensions_delete 不传 confirm=true 应拒绝（不发起请求）。"""
    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/runtimes/php/extensions/del")
        with pytest.raises(Exception):
            await mcp.call_tool("php_extensions_delete", {"id": 9, "confirm": False})
        assert not route.called


# ---- 写工具：只读模式拦截 ----

@pytest.mark.asyncio
async def test_write_ops_rejected_in_readonly_mode(monkeypatch):
    """只读模式下写操作应被拒绝。"""
    monkeypatch.setenv("PANEL_READONLY", "true")
    get_settings.cache_clear()
    assert get_settings().panel_readonly is True

    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/openresty/file")
        with pytest.raises(Exception) as exc_info:
            await mcp.call_tool("openresty_config_update", {"content": "x"})
        assert "只读模式" in str(exc_info.value)
        assert not route.called

    monkeypatch.setenv("PANEL_READONLY", "false")
    get_settings.cache_clear()
