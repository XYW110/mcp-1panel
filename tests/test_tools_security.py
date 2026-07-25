"""security 模块工具测试（端到端，用 respx mock）。

FastMCP 1.28.1 调用方式：
- list_tools() -> list[Tool]  （只有元数据）
- call_tool(name, args) -> Sequence[ContentBlock] | dict  （实际执行）

注意：security 模块尚未加入 server.register_all（由主 agent 统一改 server.py），
因此本测试自建一个独立的 FastMCP 实例并注册 security，避免依赖 server.py。

测试要点：
1. 工具注册（通过 list_tools 检查名字，覆盖 Clam/Fail2ban/FTP 三组）
2. 读工具端到端（每组至少 1 个：clam_status / fail2ban_ssh_search / ftp_search）
3. 写工具安全校验（confirm / readonly）
"""

from __future__ import annotations

import json

import pytest
import respx
from mcp.server.fastmcp import FastMCP

from mcp_1panel.config import get_settings
from mcp_1panel.tools import security
from .helpers import parse_tool_result


# ---- fixtures ----

@pytest.fixture
def mcp():
    """独立的 FastMCP 实例，注册 security 模块。

    不复用 server.mcp（其 register_all 未含 security），保证本测试自洽。
    """
    server = FastMCP("1Panel-test-security")
    security.register(server)
    return server


def _request_body(result) -> dict:
    """从 respx 捕获的请求里解析 JSON body。"""
    return json.loads(result.request.content.decode())


# ---- 注册验证 ----

async def test_security_tools_registered(mcp):
    """security 模块的 27 个工具应被注册到 mcp（Clam 12 + Fail2ban 7 + FTP 8）。"""
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    expected = {
        # Clam (12)
        "clam_status", "clam_setting_get", "clam_scan_search",
        "clam_rule_search", "clam_scan_run", "clam_scan_record_clean",
        "clam_setting_update", "clam_rule_create", "clam_rule_update",
        "clam_rule_status_update", "clam_rule_delete", "clam_operate",
        # Fail2ban (7)
        "fail2ban_status", "fail2ban_conf_get", "fail2ban_ssh_search",
        "fail2ban_conf_update", "fail2ban_conf_update_byconf",
        "fail2ban_ssh_operate", "fail2ban_operate",
        # FTP (8)
        "ftp_status", "ftp_search", "ftp_log_search",
        "ftp_create", "ftp_update", "ftp_delete",
        "ftp_operate", "ftp_sync",
    }
    missing = expected - names
    assert not missing, f"缺少工具: {missing}"


# ---- 读工具端到端（每组 1 个）----

@pytest.mark.asyncio
@respx.mock
async def test_clam_status_returns_data(mcp):
    """clam_status 应调 POST /toolbox/clam/base 并返回服务状态。"""
    respx.post("http://1panel.test/api/v2/toolbox/clam/base").respond(
        json={"code": 200, "message": "", "data": {
            "isExist": True, "isActive": True, "version": "1.2.0",
            "freshIsExist": True, "freshIsActive": False, "freshVersion": "1.2.0",
        }}
    )
    result = await mcp.call_tool("clam_status", {})
    data = parse_tool_result(result)
    assert data["isExist"] is True
    assert data["version"] == "1.2.0"
    # 验证确实命中并带空 body（1Panel base 接口需 POST）
    last = respx.calls.last
    assert last.request.url.path == "/api/v2/toolbox/clam/base"


@pytest.mark.asyncio
@respx.mock
async def test_fail2ban_ssh_search_returns_data(mcp):
    """fail2ban_ssh_search 应调 POST /toolbox/fail2ban/search 并返回 IP 列表。"""
    respx.post("http://1panel.test/api/v2/toolbox/fail2ban/search").respond(
        json={"code": 200, "message": "", "data": [
            {"ip": "1.2.3.4", "reason": "maxretry", "bannedAt": "2024-01-01"},
        ]}
    )
    result = await mcp.call_tool("fail2ban_ssh_search", {"status": "banned"})
    data = parse_tool_result(result)
    # data 是 list 时 FastMCP 逐元素展平
    if isinstance(data, list):
        assert data[0]["ip"] == "1.2.3.4"
    else:
        assert data["ip"] == "1.2.3.4"
    # 验证请求 body 含 status=banned
    body = _request_body(respx.calls.last)
    assert body == {"status": "banned"}


@pytest.mark.asyncio
@respx.mock
async def test_ftp_search_returns_data(mcp):
    """ftp_search 应调 POST /toolbox/ftp/search 并返回账号列表。"""
    respx.post("http://1panel.test/api/v2/toolbox/ftp/search").respond(
        json={"code": 200, "message": "", "data": {
            "items": [{"id": 1, "user": "alice", "path": "/data/alice"}],
            "total": 1,
        }}
    )
    result = await mcp.call_tool("ftp_search", {"info": "ali", "page": 1})
    data = parse_tool_result(result)
    assert data["total"] == 1
    assert data["items"][0]["user"] == "alice"
    body = _request_body(respx.calls.last)
    assert body == {"info": "ali", "page": 1, "pageSize": 100}


# ---- 写工具安全校验 ----

@pytest.mark.asyncio
async def test_ftp_delete_requires_confirm(mcp):
    """ftp_delete 不传 confirm=true 应拒绝（不发起请求）。"""
    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/toolbox/ftp/del")
        with pytest.raises(Exception):
            await mcp.call_tool("ftp_delete", {"ids": [1], "confirm": False})
        assert not route.called


@pytest.mark.asyncio
@respx.mock
async def test_ftp_delete_with_confirm_calls_api(mcp):
    """ftp_delete 传 confirm=true 应真正调用 API。"""
    respx.post("http://1panel.test/api/v2/toolbox/ftp/del").respond(
        json={"code": 200, "message": "", "data": None}
    )
    await mcp.call_tool("ftp_delete", {"ids": [1, 2], "confirm": True})
    last = respx.calls.last
    assert last.request.url.path == "/api/v2/toolbox/ftp/del"
    body = _request_body(last)
    assert body == {"ids": [1, 2]}


@pytest.mark.asyncio
async def test_clam_rule_delete_requires_confirm(mcp):
    """clam_rule_delete 不传 confirm=true 应拒绝。"""
    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/toolbox/clam/del")
        with pytest.raises(Exception):
            await mcp.call_tool("clam_rule_delete", {"ids": [1]})
        assert not route.called


@pytest.mark.asyncio
async def test_write_ops_rejected_in_readonly_mode(monkeypatch, mcp):
    """只读模式下写操作（如 clam_setting_update）应被拒绝。"""
    monkeypatch.setenv("PANEL_READONLY", "true")
    get_settings.cache_clear()
    assert get_settings().panel_readonly is True

    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/toolbox/clam/file/update")
        with pytest.raises(Exception) as exc_info:
            await mcp.call_tool("clam_setting_update", {
                "name": "clamd.conf", "file": "new content",
            })
        assert "只读模式" in str(exc_info.value)
        assert not route.called

    monkeypatch.setenv("PANEL_READONLY", "false")
    get_settings.cache_clear()
