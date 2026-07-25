"""website 模块工具测试（端到端，用 respx mock）。

测试要点：
1. 工具注册（通过 list_tools 检查关键名字）
2. 读工具端到端，**重点覆盖两个踩坑点**：
   - website_proxies_get：必须用 POST /websites/proxies body {"id"} 取真实后端
   - website_domains_list：必须用 GET /websites/domains/{websiteId} 取生效域名
3. 写工具安全校验（delete 需 confirm / 只读模式拒绝）

注意：这里使用独立的 FastMCP 实例（只注册 website 模块），而非 server.py 的
全局 mcp，避免被其他并行开发模块的临时语法错误拖累（register_all 会导入全部模块）。
"""

from __future__ import annotations

import pytest
import respx
from mcp.server.fastmcp import FastMCP

from mcp_1panel.config import get_settings
from mcp_1panel.tools import website as website_mod
from .helpers import parse_tool_result


def _as_list(data):
    """FastMCP 对单元素 list 返回会扁平化成单个 dict，这里统一成 list。"""
    if isinstance(data, list):
        return data
    return [data]


@pytest.fixture
def mcp():
    """独立 FastMCP 实例，只注册 website 模块。"""
    server = FastMCP("test-website")
    website_mod.register(server)
    return server


# ---- 注册验证 ----

async def test_website_tools_registered(mcp):
    """website 模块的核心工具应被注册到 mcp。"""
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    expected = {
        # 主体 CRUD
        "website_search", "website_list", "website_options", "website_detail",
        "website_create", "website_update", "website_delete", "website_operate",
        "website_batch_operate", "website_log", "website_resource",
        # 域名（踩坑点）
        "website_domains_list", "website_domains_create",
        "website_domains_update", "website_domains_delete",
        # 反代（踩坑点）
        "website_proxies_get", "website_proxies_create", "website_proxies_update",
        "website_proxies_delete", "website_proxies_status",
        # SSL / HTTPS / Nginx
        "website_ssl_search", "website_ssl_detail", "website_ssl_create",
        "website_ssl_apply", "website_ssl_delete", "website_ssl_upload",
        "website_https_get", "website_https_update",
        "website_nginx_get", "website_nginx_raw_update",
        # Acme / CA / DNS
        "website_acme_list", "website_acme_create", "website_acme_delete",
        "website_ca_list", "website_ca_create", "website_ca_obtain",
        "website_dns_list", "website_dns_create", "website_dns_delete",
        # PHP / 运行时
        "website_php_version_update", "runtime_search", "runtime_detail",
        "runtime_operate", "runtime_delete",
    }
    missing = expected - names
    assert not missing, f"缺少工具: {missing}"


# ---- 读工具端到端 ----

@pytest.mark.asyncio
@respx.mock
async def test_website_search_returns_data(mcp):
    """website_search 应调 POST /websites/search 并返回 data。"""
    respx.post("http://1panel.test/api/v2/websites/search").respond(
        json={"code": 200, "message": "", "data": {"items": [{"id": 1, "primaryDomain": "a.com"}], "total": 1}}
    )
    result = await mcp.call_tool("website_search", {"page": 1})
    data = parse_tool_result(result)
    assert data["total"] == 1
    assert data["items"][0]["primaryDomain"] == "a.com"


@pytest.mark.asyncio
@respx.mock
async def test_website_proxies_get_uses_correct_endpoint(mcp):
    """⚠️ 踩坑点：website_proxies_get 必须用 POST /websites/proxies body {"id"}。

    确认请求走的是 POST /websites/proxies（带 body），而非 GET /websites/{id}，
    且能从 data[].proxyPass 拿到真实后端。
    """
    route = respx.post("http://1panel.test/api/v2/websites/proxies").respond(
        json={"code": 200, "message": "", "data": [{"name": "proxy1", "proxyPass": "http://127.0.0.1:8080"}]}
    )
    # 反向断言：GET /websites/{id} 不应被命中
    bad_route = respx.get("http://1panel.test/api/v2/websites/1").respond(
        json={"code": 200, "message": "", "data": {"id": 1, "proxy": "http://stale-snapshot"}}
    )
    result = await mcp.call_tool("website_proxies_get", {"website_id": 1})
    data = parse_tool_result(result)
    assert route.called, "website_proxies_get 应调用 POST /websites/proxies"
    assert not bad_route.called, "website_proxies_get 不应回退到 GET /websites/{id}"
    # 验证 body 携带 id
    assert route.calls.last.request.content
    import json as _json
    sent = _json.loads(route.calls.last.request.content)
    assert sent["id"] == 1
    # 验证拿到的是真实后端（FastMCP 单元素 list 会扁平化成 dict，统一成 list）
    assert _as_list(data)[0]["proxyPass"] == "http://127.0.0.1:8080"


@pytest.mark.asyncio
@respx.mock
async def test_website_domains_list_uses_correct_endpoint(mcp):
    """⚠️ 踩坑点：website_domains_list 必须用 GET /websites/domains/{websiteId}。

    确认请求走的是 GET /websites/domains/{websiteId}，而非 GET /websites/{id}
    的 name 字段（那只是网站名）。
    """
    route = respx.get("http://1panel.test/api/v2/websites/domains/2").respond(
        json={"code": 200, "message": "", "data": [{"id": 10, "domain": "real.example.com", "port": 80}]}
    )
    bad_route = respx.get("http://1panel.test/api/v2/websites/2").respond(
        json={"code": 200, "message": "", "data": {"id": 2, "name": "just-a-name"}}
    )
    result = await mcp.call_tool("website_domains_list", {"website_id": 2})
    data = parse_tool_result(result)
    assert route.called, "website_domains_list 应调用 GET /websites/domains/{websiteId}"
    assert not bad_route.called, "website_domains_list 不应回退到 GET /websites/{id}"
    # FastMCP 单元素 list 会扁平化成 dict，统一成 list 后取第一项
    assert _as_list(data)[0]["domain"] == "real.example.com"


@pytest.mark.asyncio
@respx.mock
async def test_website_ssl_search_returns_data(mcp):
    """website_ssl_search 应调 POST /websites/ssl/search 并返回 data。"""
    respx.post("http://1panel.test/api/v2/websites/ssl/search").respond(
        json={"code": 200, "message": "", "data": {"items": [{"id": 1, "primaryDomain": "ssl.example.com"}], "total": 1}}
    )
    result = await mcp.call_tool("website_ssl_search", {"page": 1})
    data = parse_tool_result(result)
    assert data["total"] == 1
    assert data["items"][0]["primaryDomain"] == "ssl.example.com"


# ---- 写工具安全校验 ----

@pytest.mark.asyncio
async def test_website_delete_requires_confirm(mcp):
    """website_delete 不传 confirm=true 应拒绝（不发起请求）。"""
    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/websites/del")
        with pytest.raises(Exception):
            await mcp.call_tool("website_delete", {"website_id": 1, "confirm": False})
        assert not route.called


@pytest.mark.asyncio
@respx.mock
async def test_website_delete_with_confirm_calls_api(mcp):
    """website_delete 传 confirm=true 应真正调用 API。"""
    with respx.mock as mock:
        mock.post("http://1panel.test/api/v2/websites/del").respond(
            json={"code": 200, "message": "", "data": None}
        )
        await mcp.call_tool("website_delete", {"website_id": 1, "confirm": True})
        assert mock.calls.last


@pytest.mark.asyncio
async def test_website_create_rejected_in_readonly_mode(mcp, monkeypatch):
    """只读模式下写操作（website_create）应被拒绝。"""
    monkeypatch.setenv("PANEL_READONLY", "true")
    get_settings.cache_clear()
    assert get_settings().panel_readonly is True

    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/websites")
        with pytest.raises(Exception) as exc_info:
            await mcp.call_tool("website_create", {
                "alias": "x", "type": "static", "web_site_group_id": 1,
            })
        assert "只读模式" in str(exc_info.value)
        assert not route.called

    monkeypatch.setenv("PANEL_READONLY", "false")
    get_settings.cache_clear()


@pytest.mark.asyncio
@respx.mock
async def test_website_detail_uses_path_param(mcp):
    """website_detail 应调 GET /websites/{id}。"""
    respx.get("http://1panel.test/api/v2/websites/5").respond(
        json={"code": 200, "message": "", "data": {"id": 5, "alias": "my-site"}}
    )
    result = await mcp.call_tool("website_detail", {"website_id": 5})
    data = parse_tool_result(result)
    assert data["id"] == 5
    assert data["alias"] == "my-site"
