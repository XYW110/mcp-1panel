"""misc 模块工具测试（端到端，用 respx mock）。

覆盖 ScriptLibrary / TaskLog / Menu Setting 三个 tag（共 8 个工具）。

测试要点：
1. 工具注册（list_tools 检查 8 个工具名齐全）
2. 每个 tag 至少 1 个读工具端到端
3. ⚠️ 踩坑点：script_library_search 不能发 orderBy/order（dto.SearchPageWithGroup
   只有 page/pageSize/groupID/info，多了会 400）—— 用 respx 断言请求体
4. 写工具安全校验（delete 需 confirm / 只读模式拒绝）

使用独立的 FastMCP 实例（只注册 misc 模块），避免被其他并行开发模块的临时
语法错误拖累（register_all 会导入全部模块）。
"""

from __future__ import annotations

import json

import pytest
import respx
from mcp.server.fastmcp import FastMCP

from mcp_1panel.config import get_settings
from mcp_1panel.tools import misc as misc_mod
from .helpers import parse_tool_result


@pytest.fixture
def mcp():
    """独立 FastMCP 实例，只注册 misc 模块。"""
    server = FastMCP("test-misc")
    misc_mod.register(server)
    return server


# ---- 注册验证 ----

async def test_misc_tools_registered(mcp):
    """misc 模块的 8 个工具应全部注册。"""
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    expected = {
        # ScriptLibrary（5）
        "script_library_search", "script_library_create",
        "script_library_update", "script_library_delete",
        "script_library_sync",
        # TaskLog（2）
        "task_log_search", "task_log_executing_count",
        # Menu Setting（1）
        "menu_setting_reset_default",
    }
    missing = expected - names
    assert not missing, f"缺少工具: {missing}"
    # 确保没有意外多注册
    extra = names - expected
    assert not extra, f"多出未预期的工具: {extra}"


# ---- 读工具端到端（每个 tag 至少 1 个）----

@pytest.mark.asyncio
@respx.mock
async def test_script_library_search_returns_data(mcp):
    """script_library_search 应调 POST /core/script/search 并返回 data。"""
    respx.post("http://1panel.test/api/v2/core/script/search").respond(
        json={"code": 200, "message": "", "data": {
            "items": [{"id": 1, "name": "install-docker"}], "total": 1,
        }}
    )
    result = await mcp.call_tool("script_library_search", {"page": 1})
    data = parse_tool_result(result)
    assert data["total"] == 1
    assert data["items"][0]["name"] == "install-docker"


@pytest.mark.asyncio
@respx.mock
async def test_script_library_search_does_not_send_orderby(mcp):
    """⚠️ 踩坑点：script_library_search 不能发 orderBy / order。

    dto.SearchPageWithGroup 只接受 page/pageSize/groupID/info 四个字段，
    多发 orderBy/order 后端会报错。用 respx 断言请求体里没有这两个键。
    """
    route = respx.post("http://1panel.test/api/v2/core/script/search").respond(
        json={"code": 200, "message": "", "data": {"items": [], "total": 0}}
    )
    await mcp.call_tool("script_library_search", {
        "info": "docker", "group_id": 0, "page": 1, "page_size": 50,
    })
    assert route.called
    sent = json.loads(route.calls.last.request.content)
    # 必须有的字段
    assert sent["page"] == 1
    assert sent["pageSize"] == 50
    assert sent["groupID"] == 0
    assert sent["info"] == "docker"
    # 绝不能有的字段（多发了会被后端拒）
    assert "orderBy" not in sent, "script_library_search 不应发 orderBy"
    assert "order" not in sent, "script_library_search 不应发 order"


@pytest.mark.asyncio
@respx.mock
async def test_task_log_search_returns_data(mcp):
    """task_log_search 应调 POST /logs/tasks/search 并返回 data。"""
    respx.post("http://1panel.test/api/v2/logs/tasks/search").respond(
        json={"code": 200, "message": "", "data": {
            "items": [{"id": 7, "type": "backup", "status": "Success"}],
            "total": 1,
        }}
    )
    result = await mcp.call_tool("task_log_search", {"status": "Success"})
    data = parse_tool_result(result)
    assert data["total"] == 1
    assert data["items"][0]["type"] == "backup"


@pytest.mark.asyncio
@respx.mock
async def test_task_log_executing_count_returns_int(mcp):
    """task_log_executing_count 应调 GET /logs/tasks/executing/count 并返回 {"count": int}。"""
    respx.get("http://1panel.test/api/v2/logs/tasks/executing/count").respond(
        json={"code": 200, "message": "", "data": 3}
    )
    result = await mcp.call_tool("task_log_executing_count", {})
    data = parse_tool_result(result)
    assert data["count"] == 3


# ---- 写工具端到端（Menu Setting：唯一的写工具且无 confirm）----

@pytest.mark.asyncio
@respx.mock
async def test_menu_setting_reset_default_calls_api(mcp):
    """menu_setting_reset_default 应调 POST /core/settings/menu/default。"""
    route = respx.post("http://1panel.test/api/v2/core/settings/menu/default").respond(
        json={"code": 200, "message": "", "data": None}
    )
    await mcp.call_tool("menu_setting_reset_default", {})
    assert route.called


@pytest.mark.asyncio
@respx.mock
async def test_script_library_create_calls_api(mcp):
    """script_library_create 应调 POST /core/script 且 body 字段驼峰正确。"""
    route = respx.post("http://1panel.test/api/v2/core/script").respond(
        json={"code": 200, "message": "", "data": None}
    )
    await mcp.call_tool("script_library_create", {
        "name": "hello", "script": "echo hi", "is_interactive": True,
    })
    assert route.called
    sent = json.loads(route.calls.last.request.content)
    assert sent["name"] == "hello"
    assert sent["script"] == "echo hi"
    assert sent["isInteractive"] is True


# ---- 写工具安全校验 ----

@pytest.mark.asyncio
async def test_script_library_delete_requires_confirm(mcp):
    """script_library_delete 不传 confirm=true 应拒绝（不发起请求）。"""
    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/core/script/del")
        with pytest.raises(Exception):
            await mcp.call_tool("script_library_delete", {"ids": [1], "confirm": False})
        assert not route.called


@pytest.mark.asyncio
@respx.mock
async def test_script_library_delete_with_confirm_calls_api(mcp):
    """script_library_delete 传 confirm=true 应真正调用 API。"""
    with respx.mock as mock:
        mock.post("http://1panel.test/api/v2/core/script/del").respond(
            json={"code": 200, "message": "", "data": None}
        )
        await mcp.call_tool("script_library_delete", {"ids": [1, 2], "confirm": True})
        assert mock.calls.last


@pytest.mark.asyncio
async def test_menu_setting_rejected_in_readonly_mode(mcp, monkeypatch):
    """只读模式下写操作（menu_setting_reset_default）应被拒绝。"""
    monkeypatch.setenv("PANEL_READONLY", "true")
    get_settings.cache_clear()
    assert get_settings().panel_readonly is True

    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/core/settings/menu/default")
        with pytest.raises(Exception) as exc_info:
            await mcp.call_tool("menu_setting_reset_default", {})
        assert "只读模式" in str(exc_info.value)
        assert not route.called

    monkeypatch.setenv("PANEL_READONLY", "false")
    get_settings.cache_clear()
