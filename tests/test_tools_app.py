"""app 模块工具测试（端到端，用 respx mock）。

FastMCP 1.28.1 调用方式：
- list_tools() -> list[Tool]  （只有元数据）
- call_tool(name, args) -> Sequence[ContentBlock] | dict  （实际执行）

测试要点：
1. 工具注册（通过 list_tools 检查名字）
2. 读工具端到端（call_tool → respx mock 1Panel → 返回 data）
3. 写工具的安全校验（confirm / readonly）
"""

from __future__ import annotations

import pytest
import respx

from mcp_1panel.config import get_settings
from mcp_1panel.server import mcp
from .helpers import parse_tool_result


# app 模块全部工具（31 个接口 → 30 个工具；op/delete 共用 app_uninstall，
# op/upgrade 共用 app_upgrade，op 仍是底层 app_operate）
APP_TOOLS = {
    # 商店搜索与详情
    "app_search", "app_get_by_key", "app_detail_by_id",
    "app_detail_by_key", "app_get_detail", "app_check_update",
    "app_icon", "app_services",
    # 已安装应用查询
    "app_installed_search", "app_installed_list", "app_installed_info",
    "app_params", "app_default_config", "app_connection_info",
    "app_port", "app_installed_check", "app_update_versions",
    "app_uninstall_check", "app_ignored_list", "app_store_config",
    # 安装与生命周期（写）
    "app_install", "app_operate", "app_upgrade", "app_uninstall",
    "app_params_update", "app_config_update", "app_port_change",
    "app_ignore_upgrade", "app_ignore_cancel",
    "app_installed_sync", "app_sync_local", "app_sync_remote",
    "app_store_config_update",
}


# ---- 注册验证 ----

async def test_app_tools_registered():
    """app 模块的工具应被注册到 mcp。"""
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    missing = APP_TOOLS - names
    assert not missing, f"缺少工具: {missing}"


# ---- 读工具端到端 ----

@pytest.mark.asyncio
@respx.mock
async def test_app_search_calls_search_endpoint():
    """app_search 应调 POST /apps/search 并返回 data。"""
    respx.post("http://1panel.test/api/v2/apps/search").respond(
        json={"code": 200, "message": "", "data": {"items": [{"key": "wordpress"}], "total": 1}}
    )
    result = await mcp.call_tool("app_search", {"name": "wp", "page": 1, "page_size": 20})
    data = parse_tool_result(result)
    assert data["total"] == 1
    assert data["items"][0]["key"] == "wordpress"
    # 校验请求体（无 orderBy/order，符合 AppSearch schema）
    request = respx.calls.last.request
    assert "orderBy" not in request.content.decode()


@pytest.mark.asyncio
@respx.mock
async def test_app_installed_search_returns_data():
    """app_installed_search 应调 POST /apps/installed/search 并返回 data。"""
    respx.post("http://1panel.test/api/v2/apps/installed/search").respond(
        json={"code": 200, "message": "",
              "data": {"items": [{"name": "mysql-instance"}], "total": 1}}
    )
    result = await mcp.call_tool(
        "app_installed_search", {"update": True, "page": 1, "page_size": 10}
    )
    data = parse_tool_result(result)
    assert data["total"] == 1
    assert data["items"][0]["name"] == "mysql-instance"


@pytest.mark.asyncio
@respx.mock
async def test_app_get_by_key():
    """app_get_by_key 应调 GET /apps/:key。"""
    respx.get("http://1panel.test/api/v2/apps/wordpress").respond(
        json={"code": 200, "message": "", "data": {"key": "wordpress", "name": "WordPress"}}
    )
    result = await mcp.call_tool("app_get_by_key", {"key": "wordpress"})
    data = parse_tool_result(result)
    assert data["key"] == "wordpress"


@pytest.mark.asyncio
@respx.mock
async def test_app_params_get_endpoint():
    """app_params 应调 GET /apps/installed/params/:appInstallId。"""
    respx.get("http://1panel.test/api/v2/apps/installed/params/42").respond(
        json={"code": 200, "message": "", "data": {"dockerCompose": "services: ..."}}
    )
    result = await mcp.call_tool("app_params", {"app_install_id": 42})
    data = parse_tool_result(result)
    assert "dockerCompose" in data


@pytest.mark.asyncio
@respx.mock
async def test_app_update_versions_uses_post_body():
    """app_update_versions 应 POST /apps/installed/update/versions 并 body 含 appInstallID。"""
    respx.post("http://1panel.test/api/v2/apps/installed/update/versions").respond(
        json={"code": 200, "message": "", "data": [{"version": "8.0.0"}]}
    )
    result = await mcp.call_tool("app_update_versions", {"app_install_id": 7})
    data = parse_tool_result(result)
    # FastMCP 对 list data 逐元素展平；parse_tool_result 单元素返回 dict，
    # 多元素返回 list。这里两种都兼容。
    item = data[0] if isinstance(data, list) else data
    assert item["version"] == "8.0.0"
    body = respx.calls.last.request.content.decode()
    assert "appInstallID" in body
    assert '"appInstallID":7' in body.replace(" ", "")


# ---- 写工具安全校验 ----

@pytest.mark.asyncio
async def test_app_uninstall_requires_confirm():
    """app_uninstall 不传 confirm=true 应拒绝（不发起请求）。"""
    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/apps/installed/op")
        with pytest.raises(Exception):
            await mcp.call_tool("app_uninstall", {"install_id": 5, "confirm": False})
        assert not route.called


@pytest.mark.asyncio
async def test_app_upgrade_requires_confirm():
    """app_upgrade 不传 confirm=true 应拒绝（不发起请求）。"""
    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/apps/installed/op")
        with pytest.raises(Exception):
            await mcp.call_tool(
                "app_upgrade",
                {"install_id": 5, "detail_id": 9, "confirm": False},
            )
        assert not route.called


@pytest.mark.asyncio
@respx.mock
async def test_app_uninstall_with_confirm_calls_api():
    """app_uninstall 传 confirm=true 应真正调用 API 并以 operate=delete 发起。"""
    respx.post("http://1panel.test/api/v2/apps/installed/op").respond(
        json={"code": 200, "message": "", "data": None}
    )
    await mcp.call_tool("app_uninstall", {"install_id": 5, "confirm": True})
    assert respx.calls.last
    body = respx.calls.last.request.content.decode()
    # JSON 序列化无空格，按压缩形式断言
    assert '"operate":"delete"' in body
    assert '"installId":5' in body


@pytest.mark.asyncio
@respx.mock
async def test_app_install_posts_install_endpoint():
    """app_install 应 POST /apps/install 并带 appDetailId + params。"""
    respx.post("http://1panel.test/api/v2/apps/install").respond(
        json={"code": 200, "message": "", "data": {"taskID": "abc"}}
    )
    result = await mcp.call_tool(
        "app_install",
        {"app_detail_id": 12, "params": {"port": 3306}, "name": "my-mysql"},
    )
    data = parse_tool_result(result)
    assert data["taskID"] == "abc"
    body = respx.calls.last.request.content.decode()
    # JSON 序列化带空格（httpx 默认），按实际格式断言
    import json
    parsed = json.loads(body)
    assert parsed["appDetailId"] == 12
    assert parsed["params"]["port"] == 3306


@pytest.mark.asyncio
async def test_write_ops_rejected_in_readonly_mode(monkeypatch):
    """只读模式下写操作应被拒绝（FastMCP 包装成异常）。"""
    monkeypatch.setenv("PANEL_READONLY", "true")
    get_settings.cache_clear()
    assert get_settings().panel_readonly is True

    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/apps/sync/remote")
        with pytest.raises(Exception) as exc_info:
            await mcp.call_tool("app_sync_remote", {})
        assert "只读模式" in str(exc_info.value)
        assert not route.called

    monkeypatch.setenv("PANEL_READONLY", "false")
    get_settings.cache_clear()
