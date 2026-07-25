"""system 模块工具测试（端到端，用 respx mock）。

覆盖：
1. 工具注册：system 模块的全部 52 个工具
2. 读工具端到端：system_info / system_setting_get_by_key / system_snapshot_search / system_upgrade_info
3. 写工具安全校验：
   - require_write（只读模式拦截）
   - 高危 confirm 参数（system_snapshot_delete / system_upgrade 不传 true 拒绝，传 true 放行）
   - 普通写工具 system_port_update 真正调用 API
"""

from __future__ import annotations

import pytest
import respx

from mcp_1panel.config import get_settings
from mcp_1panel.server import mcp

from .helpers import parse_tool_result


# ---- 注册验证 ----

async def test_system_tools_registered():
    """system 模块的全部 52 个工具应被注册到 mcp。"""
    tools = await mcp.list_tools()
    names = {t.name for t in tools if t.name.startswith("system_")}
    expected = {
        # System Group
        "system_group_search", "system_group_create",
        "system_group_update", "system_group_delete",
        # 面板信息 / 系统状态（读）
        "system_info", "system_setting_get", "system_setting_get_by_key",
        "system_setting_by_key", "system_available_status", "system_base_dir",
        "system_interface_list", "system_memo_get",
        # 面板基础设置（写）
        "system_setting_update", "system_setting_core_update",
        "system_memo_update", "system_menu_update", "system_description_save",
        # 端口 / 绑定 / 代理
        "system_port_update", "system_bind_update", "system_proxy_update",
        # SSL
        "system_ssl_info", "system_ssl_update", "system_ssl_download",
        # 账号安全：密码 / MFA / Passkey / API
        "system_password_update", "system_password_expired_handle",
        "system_mfa_info", "system_mfa_bind",
        "system_passkey_list", "system_passkey_register_begin",
        "system_passkey_register_finish", "system_passkey_delete",
        "system_api_key_generate", "system_api_config_update",
        # 终端 / SSH
        "system_terminal_get", "system_terminal_update",
        "system_ssh_conn_get", "system_ssh_check",
        "system_ssh_save", "system_ssh_default_conn",
        # 升级
        "system_upgrade_info", "system_upgrade_releases",
        "system_upgrade", "system_upgrade_notes",
        # 快照
        "system_snapshot_search", "system_snapshot_load",
        "system_snapshot_create", "system_snapshot_delete",
        "system_snapshot_description_update", "system_snapshot_import",
        "system_snapshot_recover", "system_snapshot_rollback",
        "system_snapshot_recreate",
    }
    missing = expected - names
    assert not missing, f"缺少工具: {missing}"
    # 数量也应匹配（避免工具被意外删掉却没更新 expected）
    assert len(names) >= len(expected), (
        f"system 工具数 {len(names)} 少于期望 {len(expected)}"
    )


# ---- 读工具端到端 ----

@pytest.mark.asyncio
@respx.mock
async def test_system_info_returns_data():
    """system_info 应调 POST /settings/search 并返回 SettingInfo。"""
    respx.post("http://1panel.test/api/v2/settings/search").respond(
        json={"code": 200, "message": "", "data": {"systemVersion": "v2.0.0", "timeZone": "Asia/Shanghai"}}
    )
    result = await mcp.call_tool("system_info", {})
    data = parse_tool_result(result)
    assert data["systemVersion"] == "v2.0.0"
    assert data["timeZone"] == "Asia/Shanghai"


@pytest.mark.asyncio
@respx.mock
async def test_system_setting_get_by_key():
    """system_setting_get_by_key 应调 GET /settings/get/{key}。"""
    respx.get("http://1panel.test/api/v2/settings/get/ServerPort").respond(
        json={"code": 200, "message": "", "data": {"systemVersion": "v2", "serverPort": "9999"}}
    )
    result = await mcp.call_tool("system_setting_get_by_key", {"key": "ServerPort"})
    data = parse_tool_result(result)
    assert data["serverPort"] == "9999"


@pytest.mark.asyncio
@respx.mock
async def test_system_snapshot_search():
    """system_snapshot_search 应调 POST /settings/snapshot/search 带分页。"""
    route = respx.post("http://1panel.test/api/v2/settings/snapshot/search").respond(
        json={"code": 200, "message": "", "data": {"items": [{"id": 1, "name": "snap-1"}], "total": 1}}
    )
    result = await mcp.call_tool("system_snapshot_search", {"page": 1, "page_size": 10})
    data = parse_tool_result(result)
    assert data["total"] == 1
    assert data["items"][0]["name"] == "snap-1"
    assert route.called


@pytest.mark.asyncio
@respx.mock
async def test_system_upgrade_info():
    """system_upgrade_info 应调 GET /core/settings/upgrade。"""
    respx.get("http://1panel.test/api/v2/core/settings/upgrade").respond(
        json={"code": 200, "message": "", "data": {"currentVersion": "v2.0.0", "latestVersion": "v2.1.0"}}
    )
    result = await mcp.call_tool("system_upgrade_info", {})
    data = parse_tool_result(result)
    assert data["latestVersion"] == "v2.1.0"


# ---- 写工具安全校验：confirm 参数 ----

@pytest.mark.asyncio
async def test_system_snapshot_delete_requires_confirm():
    """system_snapshot_delete 不传 confirm=true 应拒绝（不发起请求）。"""
    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/settings/snapshot/del")
        with pytest.raises(Exception):
            await mcp.call_tool("system_snapshot_delete", {"ids": [1], "confirm": False})
        assert not route.called


@pytest.mark.asyncio
async def test_system_snapshot_delete_with_confirm_calls_api():
    """system_snapshot_delete 传 confirm=true 应真正调用 API。"""
    with respx.mock as mock:
        mock.post("http://1panel.test/api/v2/settings/snapshot/del").respond(
            json={"code": 200, "message": "", "data": None}
        )
        await mcp.call_tool(
            "system_snapshot_delete", {"ids": [1, 2], "delete_with_file": True, "confirm": True}
        )
        assert mock.calls.last


@pytest.mark.asyncio
async def test_system_upgrade_requires_confirm():
    """system_upgrade（升级面板）不传 confirm=true 应拒绝。"""
    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/core/settings/upgrade")
        with pytest.raises(Exception):
            await mcp.call_tool("system_upgrade", {"version": "v2.1.0", "confirm": False})
        assert not route.called


@pytest.mark.asyncio
@respx.mock
async def test_system_upgrade_with_confirm_calls_api():
    """system_upgrade 传 confirm=true 应真正调用 API。"""
    route = respx.post("http://1panel.test/api/v2/core/settings/upgrade").respond(
        json={"code": 200, "message": "", "data": None}
    )
    await mcp.call_tool("system_upgrade", {"version": "v2.1.0", "confirm": True})
    assert route.called


# ---- 写工具安全校验：只读模式 ----

@pytest.mark.asyncio
async def test_write_ops_rejected_in_readonly_mode(monkeypatch):
    """只读模式下写操作（system_port_update）应被拒绝。"""
    monkeypatch.setenv("PANEL_READONLY", "true")
    get_settings.cache_clear()
    assert get_settings().panel_readonly is True

    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/core/settings/port/update")
        with pytest.raises(Exception) as exc_info:
            await mcp.call_tool("system_port_update", {"server_port": 8888})
        assert "只读模式" in str(exc_info.value)
        assert not route.called

    # 恢复（autouse fixture 也会清，但显式 reset 更稳）
    monkeypatch.setenv("PANEL_READONLY", "false")
    get_settings.cache_clear()


# ---- 普通写工具真正调用 API ----

@pytest.mark.asyncio
@respx.mock
async def test_system_port_update_calls_api():
    """system_port_update（非高危）应直接调用 API（无需 confirm）。"""
    route = respx.post("http://1panel.test/api/v2/core/settings/port/update").respond(
        json={"code": 200, "message": "", "data": None}
    )
    await mcp.call_tool("system_port_update", {"server_port": 9999})
    assert route.called
