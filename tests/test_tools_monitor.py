"""monitor 模块工具测试（端到端，用 respx mock）。

FastMCP 1.28.1 调用方式：
- list_tools() -> list[Tool]  （只有元数据）
- call_tool(name, args) -> Sequence[ContentBlock] | dict  （实际执行）

测试要点：
1. 工具注册（通过 list_tools 检查名字）
2. 读工具端到端（call_tool → respx mock 1Panel → 返回 data）
3. 写工具安全校验（confirm / readonly）
"""

from __future__ import annotations

import json

import pytest
import respx

from mcp_1panel.config import get_settings
from mcp_1panel.server import mcp
from .helpers import parse_tool_result


def _request_body(result) -> dict:
    """从 respx 捕获的请求里解析 JSON body（httpx 序列化无空格，直接 JSON 解析更稳）。"""
    return json.loads(result.request.content.decode())


# ---- 注册验证 ----

async def test_monitor_tools_registered():
    """monitor 模块的 10 个工具应被注册到 mcp。"""
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    expected = {
        "monitor_cpu", "monitor_memory", "monitor_load",
        "monitor_io", "monitor_network", "monitor_search",
        "monitor_gpu", "monitor_setting_get", "monitor_setting_update",
        "monitor_clean",
    }
    missing = expected - names
    assert not missing, f"缺少工具: {missing}"


# ---- 读工具端到端 ----

@pytest.mark.asyncio
@respx.mock
async def test_monitor_cpu_returns_data():
    """monitor_cpu 应调 POST /hosts/monitor/search with param=cpu。"""
    respx.post("http://1panel.test/api/v2/hosts/monitor/search").respond(
        json={"code": 200, "message": "", "data": {
            "param": "cpu",
            "date": ["2026-07-25 10:00:00", "2026-07-25 10:05:00"],
            "value": [12.3, 45.6],
        }}
    )
    result = await mcp.call_tool("monitor_cpu", {
        "start_time": "2026-07-25 10:00:00",
        "end_time": "2026-07-25 11:00:00",
    })
    data = parse_tool_result(result)
    assert data["param"] == "cpu"
    assert data["value"] == [12.3, 45.6]
    # 确认请求体 param 字段
    body = _request_body(respx.calls.last)
    assert body["param"] == "cpu"
    assert body["startTime"] == "2026-07-25 10:00:00"
    assert body["endTime"] == "2026-07-25 11:00:00"


@pytest.mark.asyncio
@respx.mock
async def test_monitor_network_passes_network_param():
    """monitor_network 应把 network 字段带进请求体。"""
    respx.post("http://1panel.test/api/v2/hosts/monitor/search").respond(
        json={"code": 200, "message": "", "data": {
            "param": "network", "date": [], "value": [],
        }}
    )
    result = await mcp.call_tool("monitor_network", {"network": "eth0"})
    data = parse_tool_result(result)
    assert data["param"] == "network"
    body = _request_body(respx.calls.last)
    assert body["param"] == "network"
    assert body["network"] == "eth0"


@pytest.mark.asyncio
@respx.mock
async def test_monitor_gpu_returns_data():
    """monitor_gpu 应调 POST /hosts/monitor/gpu/search。"""
    respx.post("http://1panel.test/api/v2/hosts/monitor/gpu/search").respond(
        json={"code": 200, "message": "", "data": {
            "gpuValue": [10.0], "memoryUsed": [1024],
            "temperatureValue": [55.0],
        }}
    )
    result = await mcp.call_tool("monitor_gpu", {"product_name": "Tesla T4"})
    data = parse_tool_result(result)
    assert data["gpuValue"] == [10.0]
    body = _request_body(respx.calls.last)
    assert body["productName"] == "Tesla T4"


@pytest.mark.asyncio
@respx.mock
async def test_monitor_setting_get():
    """monitor_setting_get 应调 GET /hosts/monitor/setting。"""
    respx.get("http://1panel.test/api/v2/hosts/monitor/setting").respond(
        json={"code": 200, "message": "", "data": {
            "monitorStatus": "enable",
            "monitorInterval": "5",
            "monitorStoreDays": "30",
            "defaultNetwork": "eth0",
            "defaultIO": "sda",
        }}
    )
    result = await mcp.call_tool("monitor_setting_get", {})
    data = parse_tool_result(result)
    assert data["monitorStatus"] == "enable"
    assert data["defaultNetwork"] == "eth0"


@pytest.mark.asyncio
@respx.mock
async def test_monitor_search_generic_all():
    """monitor_search 通用查询应支持 param=all。"""
    respx.post("http://1panel.test/api/v2/hosts/monitor/search").respond(
        json={"code": 200, "message": "", "data": {
            "param": "all", "date": [], "value": [],
        }}
    )
    result = await mcp.call_tool("monitor_search", {"param": "all"})
    data = parse_tool_result(result)
    assert data["param"] == "all"
    body = _request_body(respx.calls.last)
    assert body["param"] == "all"


# ---- 写工具安全校验 ----

@pytest.mark.asyncio
async def test_monitor_clean_requires_confirm():
    """monitor_clean 不传 confirm=true 应拒绝（不发起请求）。"""
    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/hosts/monitor/clean")
        with pytest.raises(Exception):
            await mcp.call_tool("monitor_clean", {"confirm": False})
        assert not route.called


@pytest.mark.asyncio
async def test_monitor_clean_with_confirm_calls_api():
    """monitor_clean 传 confirm=true 应真正调用 API。"""
    with respx.mock as mock:
        mock.post("http://1panel.test/api/v2/hosts/monitor/clean").respond(
            json={"code": 200, "message": "", "data": None}
        )
        await mcp.call_tool("monitor_clean", {"confirm": True})
        assert mock.calls.last  # 确实发了请求


@pytest.mark.asyncio
@respx.mock
async def test_monitor_setting_update_calls_api():
    """monitor_setting_update 写操作应正确传 key/value。"""
    respx.post("http://1panel.test/api/v2/hosts/monitor/setting/update").respond(
        json={"code": 200, "message": "", "data": None}
    )
    await mcp.call_tool("monitor_setting_update", {
        "key": "DefaultNetwork", "value": "ens33",
    })
    body = _request_body(respx.calls.last)
    assert body["key"] == "DefaultNetwork"
    assert body["value"] == "ens33"


@pytest.mark.asyncio
async def test_write_ops_rejected_in_readonly_mode(monkeypatch):
    """只读模式下写操作应被拒绝（FastMCP 包装成 ToolError）。"""
    monkeypatch.setenv("PANEL_READONLY", "true")
    get_settings.cache_clear()
    assert get_settings().panel_readonly is True

    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/hosts/monitor/clean")
        with pytest.raises(Exception) as exc_info:
            await mcp.call_tool("monitor_clean", {"confirm": True})
        assert "只读模式" in str(exc_info.value)
        assert not route.called

    # 恢复
    monkeypatch.setenv("PANEL_READONLY", "false")
    get_settings.cache_clear()
