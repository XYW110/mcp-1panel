"""firewall 模块工具测试（端到端，用 respx mock）。

FastMCP 1.28.1 调用方式：
- list_tools() -> list[Tool]  （只有元数据）
- call_tool(name, args) -> Sequence[ContentBlock] | dict  （实际执行）

测试要点：
1. 工具注册（通过 list_tools 检查名字）
2. 读工具端到端（call_tool → respx mock 1Panel → 返回 data）
3. 写工具的安全校验（confirm / readonly）—— 防火墙写操作全部需要 confirm
"""

from __future__ import annotations

import json

import pytest
import respx

from mcp_1panel.config import get_settings
from mcp_1panel.server import mcp
from .helpers import parse_tool_result


# ---- 注册验证 ----

async def test_firewall_tools_registered():
    """firewall 模块的 15 个工具应被注册到 mcp。"""
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    expected = {
        # 读
        "firewall_base",
        "firewall_filter_chain_status",
        "firewall_rules_search",
        "firewall_filter_search",
        # 端口规则
        "firewall_port_operate",
        "firewall_port_update",
        # IP 规则
        "firewall_ip_operate",
        "firewall_ip_update",
        # 端口转发 / 描述 / 批量
        "firewall_forward_operate",
        "firewall_rule_description_update",
        "firewall_rule_batch",
        # 防火墙启停（高危）
        "firewall_operate",
        # iptables filter（高危）
        "firewall_filter_operate",
        "firewall_filter_rule_operate",
        "firewall_filter_rule_batch",
    }
    missing = expected - names
    assert not missing, f"缺少工具: {missing}"


# ---- 读工具端到端 ----

@pytest.mark.asyncio
@respx.mock
async def test_firewall_base_returns_data():
    """firewall_base 应调 POST /hosts/firewall/base 并返回 base info。"""
    respx.post("http://1panel.test/api/v2/hosts/firewall/base").respond(
        json={"code": 200, "message": "", "data": {
            "name": "ufw", "version": "0.36.1",
            "isActive": True, "isBind": True,
            "isExist": True, "isInit": True, "pingStatus": "enabled",
        }}
    )
    result = await mcp.call_tool("firewall_base", {"name": "node1"})
    data = parse_tool_result(result)
    assert data["isActive"] is True
    assert data["name"] == "ufw"


@pytest.mark.asyncio
@respx.mock
async def test_firewall_rules_search_returns_list():
    """firewall_rules_search 应调 POST /hosts/firewall/search，按 rule_type 传 type。"""
    route = respx.post("http://1panel.test/api/v2/hosts/firewall/search").respond(
        json={"code": 200, "message": "", "data": {
            "items": [{"id": 1, "port": "22", "strategy": "accept"}], "total": 1,
        }}
    )
    result = await mcp.call_tool("firewall_rules_search", {"rule_type": "port"})
    data = parse_tool_result(result)
    assert data["total"] == 1
    assert data["items"][0]["port"] == "22"

    # 校验请求体含正确的分页与 type
    req = route.calls.last.request
    body = json.loads(req.content.decode())
    assert body["type"] == "port"
    assert body["page"] == 1
    assert body["pageSize"] == 100


@pytest.mark.asyncio
@respx.mock
async def test_firewall_rules_search_filters_optional():
    """firewall_rules_search 的可选过滤字段只在传入时才进入 body。"""
    route = respx.post("http://1panel.test/api/v2/hosts/firewall/search").respond(
        json={"code": 200, "message": "", "data": {"items": [], "total": 0}}
    )
    await mcp.call_tool("firewall_rules_search", {
        "rule_type": "addr",
        "info": "10.0.0.1",
        "strategy": "drop",
        "page": 2, "page_size": 20,
    })
    body = json.loads(route.calls.last.request.content.decode())
    assert body["type"] == "addr"
    assert body["info"] == "10.0.0.1"
    assert body["strategy"] == "drop"
    assert body["page"] == 2 and body["pageSize"] == 20
    # 未传入的可选字段不应出现
    assert "status" not in body


# ---- 写工具安全校验：confirm 拦截 ----

@pytest.mark.asyncio
async def test_firewall_port_operate_requires_confirm():
    """firewall_port_operate 不传 confirm=true 应拒绝（不发起请求）。"""
    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/hosts/firewall/port")
        with pytest.raises(Exception):
            await mcp.call_tool("firewall_port_operate", {
                "operation": "add", "port": "8080",
                "protocol": "tcp", "strategy": "accept", "confirm": False,
            })
        assert not route.called


@pytest.mark.asyncio
@respx.mock
async def test_firewall_port_operate_with_confirm_calls_api():
    """firewall_port_operate 传 confirm=true 应真正调用 API 并发送 PortRuleOperate body。"""
    route = respx.post("http://1panel.test/api/v2/hosts/firewall/port").respond(
        json={"code": 200, "message": "", "data": None}
    )
    await mcp.call_tool("firewall_port_operate", {
        "operation": "add", "port": "443",
        "protocol": "tcp", "strategy": "accept",
        "address": "192.168.1.0/24", "description": "https",
        "confirm": True,
    })
    body = json.loads(route.calls.last.request.content.decode())
    assert body["operation"] == "add"
    assert body["port"] == "443"
    assert body["protocol"] == "tcp"
    assert body["strategy"] == "accept"
    assert body["address"] == "192.168.1.0/24"
    assert body["description"] == "https"


@pytest.mark.asyncio
async def test_firewall_operate_requires_confirm():
    """firewall_operate（启停防火墙）不传 confirm=true 应拒绝，绝不能误关防火墙。"""
    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/hosts/firewall/operate")
        with pytest.raises(Exception):
            await mcp.call_tool("firewall_operate", {"operation": "stop", "confirm": False})
        assert not route.called


@pytest.mark.asyncio
@respx.mock
async def test_firewall_operate_with_confirm_calls_api():
    """firewall_operate 传 confirm=true 应真正调用 API。"""
    route = respx.post("http://1panel.test/api/v2/hosts/firewall/operate").respond(
        json={"code": 200, "message": "", "data": None}
    )
    await mcp.call_tool("firewall_operate", {
        "operation": "restart", "with_docker_restart": True, "confirm": True,
    })
    body = json.loads(route.calls.last.request.content.decode())
    assert body["operation"] == "restart"
    assert body["withDockerRestart"] is True


@pytest.mark.asyncio
async def test_firewall_ip_operate_requires_confirm():
    """firewall_ip_operate 不传 confirm=true 应拒绝。"""
    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/hosts/firewall/ip")
        with pytest.raises(Exception):
            await mcp.call_tool("firewall_ip_operate", {
                "address": "10.0.0.1", "operation": "add",
                "strategy": "drop", "confirm": False,
            })
        assert not route.called


# ---- 只读模式拦截写操作 ----

@pytest.mark.asyncio
async def test_write_ops_rejected_in_readonly_mode(monkeypatch):
    """只读模式下写操作应被 require_write() 拒绝。"""
    monkeypatch.setenv("PANEL_READONLY", "true")
    get_settings.cache_clear()
    assert get_settings().panel_readonly is True

    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/hosts/firewall/port")
        with pytest.raises(Exception) as exc_info:
            await mcp.call_tool("firewall_port_operate", {
                "operation": "add", "port": "80",
                "protocol": "tcp", "strategy": "accept", "confirm": True,
            })
        assert "只读模式" in str(exc_info.value)
        assert not route.called

    monkeypatch.setenv("PANEL_READONLY", "false")
    get_settings.cache_clear()


# ---- 批量 / 转发 / filter 高危写工具（confirm + body 校验）----

@pytest.mark.asyncio
@respx.mock
async def test_firewall_rule_batch_with_confirm():
    """firewall_rule_batch 传 confirm=true 应发送 BatchRuleOperate body。"""
    route = respx.post("http://1panel.test/api/v2/hosts/firewall/batch").respond(
        json={"code": 200, "message": "", "data": None}
    )
    await mcp.call_tool("firewall_rule_batch", {
        "type": "port",
        "rules": [{"operation": "add", "port": "80", "protocol": "tcp", "strategy": "accept"}],
        "confirm": True,
    })
    body = json.loads(route.calls.last.request.content.decode())
    assert body["type"] == "port"
    assert body["rules"][0]["port"] == "80"


@pytest.mark.asyncio
@respx.mock
async def test_firewall_forward_operate_with_confirm():
    """firewall_forward_operate 传 confirm=true 应发送 ForwardRuleOperate body。"""
    route = respx.post("http://1panel.test/api/v2/hosts/firewall/forward").respond(
        json={"code": 200, "message": "", "data": None}
    )
    await mcp.call_tool("firewall_forward_operate", {
        "rules": [{
            "operation": "add", "port": "8080", "protocol": "tcp",
            "targetPort": "80", "targetIP": "192.168.1.5",
        }],
        "force_delete": False, "confirm": True,
    })
    body = json.loads(route.calls.last.request.content.decode())
    assert body["forceDelete"] is False
    assert body["rules"][0]["targetPort"] == "80"


@pytest.mark.asyncio
async def test_firewall_filter_rule_operate_requires_confirm():
    """firewall_filter_rule_operate（iptables 高危）不传 confirm=true 应拒绝。"""
    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/hosts/firewall/filter/rule/operate")
        with pytest.raises(Exception):
            await mcp.call_tool("firewall_filter_rule_operate", {
                "chain": "1PANEL_INPUT", "operation": "add",
                "strategy": "drop", "confirm": False,
            })
        assert not route.called


@pytest.mark.asyncio
async def test_firewall_filter_operate_requires_confirm():
    """firewall_filter_operate（链级高危）不传 confirm=true 应拒绝。"""
    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/hosts/firewall/filter/operate")
        with pytest.raises(Exception):
            await mcp.call_tool("firewall_filter_operate", {
                "name": "1PANEL_INPUT", "operate": "bind", "confirm": False,
            })
        assert not route.called


# ---- 读工具：filter chain status / filter search ----

@pytest.mark.asyncio
@respx.mock
async def test_firewall_filter_chain_status():
    """firewall_filter_chain_status 应调 POST /hosts/firewall/filter/chain/status。"""
    route = respx.post("http://1panel.test/api/v2/hosts/firewall/filter/chain/status").respond(
        json={"code": 200, "message": "", "data": {"used": True}}
    )
    result = await mcp.call_tool("firewall_filter_chain_status", {"name": "node1"})
    data = parse_tool_result(result)
    assert data["used"] is True
    body = json.loads(route.calls.last.request.content.decode())
    assert body["name"] == "node1"


@pytest.mark.asyncio
@respx.mock
async def test_firewall_filter_search():
    """firewall_filter_search 应调 POST /hosts/firewall/filter/search，含分页字段。"""
    route = respx.post("http://1panel.test/api/v2/hosts/firewall/filter/search").respond(
        json={"code": 200, "message": "", "data": {"items": [], "total": 0}}
    )
    await mcp.call_tool("firewall_filter_search", {"filter_type": "1PANEL_INPUT"})
    body = json.loads(route.calls.last.request.content.decode())
    assert body["type"] == "1PANEL_INPUT"
    assert body["page"] == 1 and body["pageSize"] == 100
