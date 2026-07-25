"""组合便捷接口测试（combos）。

验证组合接口能正确聚合多个原子调用，并正确处理错误容错。
"""

from __future__ import annotations

import pytest
import respx

from mcp.server.fastmcp import FastMCP

from mcp_1panel.tools import combos as combos_pkg
from .helpers import parse_tool_result


@pytest.fixture
def server():
    """独立 FastMCP 实例，只注册 combos。"""
    s = FastMCP("test-combos")
    combos_pkg.register_all(s)
    return s


# ---- 注册验证 ----

async def test_combo_tools_registered(server):
    """组合接口应被注册。"""
    tools = await server.list_tools()
    names = {t.name for t in tools}
    expected = {
        "combo_website_full_status",
        "combo_website_safe_delete",
        "combo_container_inspect_full",
        "combo_container_safe_restart",
    }
    assert expected.issubset(names), f"缺少: {expected - names}"


# ---- combo_website_full_status 端到端 ----

@pytest.mark.asyncio
@respx.mock
async def test_combo_website_full_status_aggregates(server):
    """full_status 应并发聚合 base + domains + proxies + ssl 四个查询。"""
    respx.get("http://1panel.test/api/v2/websites/1").respond(
        json={"code": 200, "message": "", "data": {"id": 1, "primaryDomain": "a.com", "type": "runtime"}}
    )
    respx.get("http://1panel.test/api/v2/websites/domains/1").respond(
        json={"code": 200, "message": "", "data": [{"domain": "a.com", "port": 80}]}
    )
    respx.post("http://1panel.test/api/v2/websites/proxies").respond(
        json={"code": 200, "message": "", "data": [{"name": "p1", "proxyPass": "http://127.0.0.1:8080"}]}
    )
    respx.post("http://1panel.test/api/v2/websites/ssl/search").respond(
        json={"code": 200, "message": "", "data": {"items": [{"id": 5}], "total": 1}}
    )

    result = await server.call_tool("combo_website_full_status", {"website_id": 1})
    data = parse_tool_result(result)

    assert data["base"]["primaryDomain"] == "a.com"
    assert data["proxy_pass"] == "http://127.0.0.1:8080"
    assert data["domains"][0]["domain"] == "a.com"


@pytest.mark.asyncio
@respx.mock
async def test_combo_website_full_status_tolerates_partial_failure(server):
    """单项查询失败不应导致整体崩溃（容错）。"""
    respx.get("http://1panel.test/api/v2/websites/1").respond(
        json={"code": 200, "message": "", "data": {"id": 1}}
    )
    # proxies 接口 500 错误
    respx.post("http://1panel.test/api/v2/websites/proxies").respond(status_code=500)
    respx.get("http://1panel.test/api/v2/websites/domains/1").respond(
        json={"code": 200, "message": "", "data": []}
    )
    respx.post("http://1panel.test/api/v2/websites/ssl/search").respond(
        json={"code": 200, "message": "", "data": {"items": [], "total": 0}}
    )

    result = await server.call_tool("combo_website_full_status", {"website_id": 1})
    data = parse_tool_result(result)
    # base 成功
    assert data["base"]["id"] == 1
    # proxies 失败被容错
    assert "error" in data["proxies_raw"] or data["proxy_pass"] == ""


# ---- combo_website_safe_delete 安全校验 ----

@pytest.mark.asyncio
async def test_combo_website_safe_delete_requires_confirm(server):
    """不传 confirm 应拒绝。"""
    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/websites/del")
        with pytest.raises(Exception):
            await server.call_tool("combo_website_safe_delete", {"website_id": 1, "confirm": False})
        assert not route.called


@pytest.mark.asyncio
@respx.mock
async def test_combo_website_safe_delete_nonexistent_rejected(server):
    """删除不存在的网站应拒绝。"""
    respx.get("http://1panel.test/api/v2/websites/99").respond(
        json={"code": 200, "message": "", "data": None}
    )
    with pytest.raises(Exception) as exc:
        await server.call_tool("combo_website_safe_delete", {"website_id": 99, "confirm": True})
    assert "不存在" in str(exc.value)


# ---- combo_container_inspect_full ----

@pytest.mark.asyncio
@respx.mock
async def test_combo_container_inspect_full_aggregates(server):
    respx.post("http://1panel.test/api/v2/containers/inspect").respond(
        json={"code": 200, "message": "", "data": {"Id": "abc", "State": {"Running": True}}}
    )
    respx.post("http://1panel.test/api/v2/containers/item/stats").respond(
        json={"code": 200, "message": "", "data": {"cpu_percent": 5.2}}
    )
    result = await server.call_tool("combo_container_inspect_full", {"container_name": "nginx"})
    data = parse_tool_result(result)
    assert data["container"] == "nginx"
    assert data["inspect"]["State"]["Running"] is True
    assert data["stats"]["cpu_percent"] == 5.2


# ---- combo_container_safe_restart ----

@pytest.mark.asyncio
async def test_combo_container_safe_restart_requires_confirm(server):
    """不传 confirm 应拒绝。"""
    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/containers/operate")
        with pytest.raises(Exception):
            await server.call_tool("combo_container_safe_restart", {"container_name": "x"})
        assert not route.called
