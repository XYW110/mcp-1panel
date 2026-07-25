"""dashboard 模块工具测试（端到端，用 respx mock）。

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


# ---- 注册验证 ----

async def test_dashboard_tools_registered():
    """dashboard 模块的 12 个工具应被注册到 mcp。"""
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    expected = {
        "dashboard_base", "dashboard_os", "dashboard_current",
        "dashboard_current_node", "dashboard_top_cpu", "dashboard_top_mem",
        "dashboard_app_launcher", "dashboard_app_launcher_option",
        "dashboard_app_launcher_show", "dashboard_quick_option",
        "dashboard_quick_change", "dashboard_system_restart",
    }
    missing = expected - names
    assert not missing, f"缺少工具: {missing}"


# ---- 读工具端到端 ----

@pytest.mark.asyncio
@respx.mock
async def test_dashboard_base_returns_data():
    """dashboard_base 应调 GET /dashboard/base/all/all 并返回 data。"""
    respx.get("http://1panel.test/api/v2/dashboard/base/all/all").respond(
        json={"code": 200, "message": "", "data": {
            "hostname": "devin-ubuntu", "os": "linux",
            "websiteNumber": 12, "cpuCores": 8,
        }}
    )
    result = await mcp.call_tool("dashboard_base", {})
    data = parse_tool_result(result)
    assert data["hostname"] == "devin-ubuntu"
    assert data["websiteNumber"] == 12


@pytest.mark.asyncio
@respx.mock
async def test_dashboard_base_passes_path_options():
    """dashboard_base 应把 io_option/net_option 拼进路径。"""
    route = respx.get(
        "http://1panel.test/api/v2/dashboard/base/default/default"
    ).respond(json={"code": 200, "message": "", "data": {"os": "linux"}})
    await mcp.call_tool(
        "dashboard_base", {"io_option": "default", "net_option": "default"}
    )
    assert route.called


@pytest.mark.asyncio
@respx.mock
async def test_dashboard_current_returns_data():
    """dashboard_current 应调 GET /dashboard/current/all/all 并返回实时快照。"""
    respx.get("http://1panel.test/api/v2/dashboard/current/all/all").respond(
        json={"code": 200, "message": "", "data": {
            "cpuUsedPercent": 1.25, "memoryUsedPercent": 42.0,
            "load1": 0.33, "uptime": 728846,
        }}
    )
    result = await mcp.call_tool("dashboard_current", {})
    data = parse_tool_result(result)
    assert data["cpuUsedPercent"] == 1.25
    assert data["uptime"] == 728846


@pytest.mark.asyncio
@respx.mock
async def test_dashboard_os_returns_data():
    """dashboard_os 应调 GET /dashboard/base/os 并返回 OS 静态信息。"""
    respx.get("http://1panel.test/api/v2/dashboard/base/os").respond(
        json={"code": 200, "message": "", "data": {
            "os": "linux", "platform": "ubuntu",
            "prettyDistro": "Ubuntu 26.04 LTS",
        }}
    )
    result = await mcp.call_tool("dashboard_os", {})
    data = parse_tool_result(result)
    assert data["platform"] == "ubuntu"


@pytest.mark.asyncio
@respx.mock
async def test_dashboard_app_launcher_option_posts_filter():
    """dashboard_app_launcher_option 应 POST filter 请求体。"""
    route = respx.post(
        "http://1panel.test/api/v2/dashboard/app/launcher/option"
    ).respond(json={"code": 200, "message": "", "data": [
        {"key": "openresty", "isShow": True},
    ]})
    result = await mcp.call_tool(
        "dashboard_app_launcher_option", {"filter": "open"}
    )
    data = parse_tool_result(result)
    # data 是 list 时 FastMCP 逐元素展平，parse_tool_result 返回 list
    items = data if isinstance(data, list) else [data]
    assert items[0]["key"] == "openresty"
    # 验证请求体带 filter
    assert route.calls.last.request.content.decode() == '{"filter":"open"}'


# ---- 写工具安全校验 ----

@pytest.mark.asyncio
async def test_dashboard_system_restart_requires_confirm():
    """dashboard_system_restart 不传 confirm=true 应拒绝（不发起请求）。"""
    with respx.mock:
        route = respx.post(
            "http://1panel.test/api/v2/dashboard/system/restart/system"
        )
        with pytest.raises(Exception):
            await mcp.call_tool(
                "dashboard_system_restart", {"operation": "system"}
            )
        assert not route.called


@pytest.mark.asyncio
@respx.mock
async def test_dashboard_system_restart_with_confirm_calls_api():
    """dashboard_system_restart 传 confirm=true 应真正调用 API。"""
    respx.post(
        "http://1panel.test/api/v2/dashboard/system/restart/1panel-agent"
    ).respond(json={"code": 200, "message": "", "data": None})
    await mcp.call_tool(
        "dashboard_system_restart",
        {"operation": "1panel-agent", "confirm": True},
    )
    assert respx.calls.last  # 确实发了请求


@pytest.mark.asyncio
@respx.mock
async def test_dashboard_app_launcher_show_write_calls_api():
    """dashboard_app_launcher_show 是写操作，应 POST 请求体。"""
    route = respx.post(
        "http://1panel.test/api/v2/dashboard/app/launcher/show"
    ).respond(json={"code": 200, "message": "", "data": None})
    await mcp.call_tool(
        "dashboard_app_launcher_show", {"key": "n8n", "value": "true"}
    )
    assert route.called
    body = route.calls.last.request.content.decode()
    assert '"key":"n8n"' in body and '"value":"true"' in body


@pytest.mark.asyncio
async def test_write_ops_rejected_in_readonly_mode(monkeypatch):
    """只读模式下写操作应被拒绝（FastMCP 包成 ToolError）。"""
    monkeypatch.setenv("PANEL_READONLY", "true")
    get_settings.cache_clear()
    assert get_settings().panel_readonly is True

    with respx.mock:
        route = respx.post(
            "http://1panel.test/api/v2/dashboard/app/launcher/show"
        )
        with pytest.raises(Exception) as exc_info:
            await mcp.call_tool(
                "dashboard_app_launcher_show", {"key": "n8n", "value": "true"}
            )
        assert "只读模式" in str(exc_info.value)
        assert not route.called

    monkeypatch.setenv("PANEL_READONLY", "false")
    get_settings.cache_clear()
