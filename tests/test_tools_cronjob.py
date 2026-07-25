"""cronjob 模块工具测试（端到端，用 respx mock）。

FastMCP 1.28.1 调用方式：
- list_tools() -> list[Tool]  （只有元数据）
- call_tool(name, args) -> Sequence[ContentBlock] | dict  （实际执行）

注意：cronjob 模块尚未加入 server.py 的 register_all 列表（由主 agent 统一加），
因此本测试在全局 mcp 实例上显式调用 cronjob.register(mcp) 完成注册（仅一次，
用 session 级标志防止重复注册）。

测试要点：
1. 工具注册（通过 list_tools 检查 16 个工具名）
2. 读工具端到端（search / detail / records / record_log / next_run / script_options）
3. 写工具安全校验（delete confirm / records_clean confirm / 只读模式拦截）
"""

from __future__ import annotations

import pytest
import respx

from mcp_1panel.config import get_settings
from mcp_1panel.server import mcp
from mcp_1panel.tools import cronjob as cronjob_module
from .helpers import parse_tool_result


# ---- 一次性注册 cronjob 模块到全局 mcp ----
# （server.py 的 register_all 暂未包含 cronjob，主 agent 会统一加入；
#  本测试通过模块级 flag 保证只注册一次，避免重复工具名报错）

if not getattr(mcp, "_cronjob_registered", False):
    cronjob_module.register(mcp)
    mcp._cronjob_registered = True  # type: ignore[attr-defined]


# ---- 注册验证 ----

async def test_cronjob_tools_registered():
    """cronjob 模块的 16 个工具应被注册到 mcp。"""
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    expected = {
        "cronjob_search", "cronjob_detail", "cronjob_records",
        "cronjob_record_log", "cronjob_next_run", "cronjob_script_options",
        "cronjob_create", "cronjob_update", "cronjob_delete",
        "cronjob_group_update", "cronjob_run", "cronjob_stop",
        "cronjob_status", "cronjob_records_clean", "cronjob_export",
        "cronjob_import",
    }
    missing = expected - names
    assert not missing, f"缺少工具: {missing}"
    assert len(expected) == 16, "应有 16 个工具"


# ---- 读工具端到端 ----

@pytest.mark.asyncio
@respx.mock
async def test_cronjob_search_returns_data():
    """cronjob_search 应调 POST /cronjobs/search 并返回 data。"""
    respx.post("http://1panel.test/api/v2/cronjobs/search").respond(
        json={"code": 200, "message": "", "data": {
            "items": [{"id": 1, "name": "backup-db", "type": "shell"}],
            "total": 1,
        }}
    )
    result = await mcp.call_tool("cronjob_search", {"page": 1})
    data = parse_tool_result(result)
    assert data["total"] == 1
    assert data["items"][0]["name"] == "backup-db"
    # 校验请求体含分页 + info/groupIDs 字段（httpx 用紧凑 JSON，无多余空格）
    body = respx.calls.last.request.content.decode()
    assert '"orderBy":"createdAt"' in body
    assert '"info":""' in body
    assert '"groupIDs":[]' in body


@pytest.mark.asyncio
@respx.mock
async def test_cronjob_detail_returns_config():
    """cronjob_detail 应调 POST /cronjobs/load/info with id。"""
    respx.post("http://1panel.test/api/v2/cronjobs/load/info").respond(
        json={"code": 200, "message": "", "data": {
            "id": 5, "name": "daily-backup", "type": "shell", "spec": "0 3 * * *",
        }}
    )
    result = await mcp.call_tool("cronjob_detail", {"id": 5})
    data = parse_tool_result(result)
    assert data["id"] == 5
    assert data["spec"] == "0 3 * * *"
    request = respx.calls.last.request
    assert '"id":5' in request.content.decode()


@pytest.mark.asyncio
@respx.mock
async def test_cronjob_records_returns_list():
    """cronjob_records 应调 POST /cronjobs/search/records with cronjobID。"""
    respx.post("http://1panel.test/api/v2/cronjobs/search/records").respond(
        json={"code": 200, "message": "", "data": {
            "items": [{"id": 100, "status": "Success", "startTime": "2026-07-25 03:00:00"}],
            "total": 1,
        }}
    )
    result = await mcp.call_tool("cronjob_records", {"cronjob_id": 7, "status": "Success"})
    data = parse_tool_result(result)
    assert data["items"][0]["status"] == "Success"
    body = respx.calls.last.request.content.decode()
    assert '"cronjobID":7' in body
    assert '"status":"Success"' in body


@pytest.mark.asyncio
@respx.mock
async def test_cronjob_record_log_returns_log():
    """cronjob_record_log 应调 POST /cronjobs/records/log with id。"""
    respx.post("http://1panel.test/api/v2/cronjobs/records/log").respond(
        json={"code": 200, "message": "", "data": {
            "records": "[2026-07-25] backup done",
        }}
    )
    result = await mcp.call_tool("cronjob_record_log", {"record_id": 100})
    data = parse_tool_result(result)
    assert data["records"].startswith("[2026-07-25]")
    assert '"id":100' in respx.calls.last.request.content.decode()


@pytest.mark.asyncio
@respx.mock
async def test_cronjob_next_run_returns_times():
    """cronjob_next_run 应调 POST /cronjobs/next with spec。"""
    respx.post("http://1panel.test/api/v2/cronjobs/next").respond(
        json={"code": 200, "message": "", "data": {
            "next": ["2026-07-26 03:00:00", "2026-07-27 03:00:00"],
        }}
    )
    result = await mcp.call_tool("cronjob_next_run", {"spec": "0 3 * * *"})
    data = parse_tool_result(result)
    assert len(data["next"]) == 2
    assert '"spec":"0 3 * * *"' in respx.calls.last.request.content.decode()


@pytest.mark.asyncio
@respx.mock
async def test_cronjob_script_options_get():
    """cronjob_script_options 应调 GET /cronjobs/script/options。"""
    respx.get("http://1panel.test/api/v2/cronjobs/script/options").respond(
        json={"code": 200, "message": "", "data": [{"id": 1, "name": "clean-cache.sh"}]}
    )
    result = await mcp.call_tool("cronjob_script_options", {})
    data = parse_tool_result(result)
    # data 是 list 时 FastMCP 逐元素展平
    items = data if isinstance(data, list) else [data]
    assert items[0]["name"] == "clean-cache.sh"


# ---- 写工具端到端（confirm 校验通过后真正调 API）----

@pytest.mark.asyncio
@respx.mock
async def test_cronjob_create_calls_api():
    """cronjob_create 应调 POST /cronjobs 并携带完整 body。"""
    respx.post("http://1panel.test/api/v2/cronjobs").respond(
        json={"code": 200, "message": "", "data": None}
    )
    await mcp.call_tool("cronjob_create", {
        "name": "backup-db", "type": "shell", "spec": "0 3 * * *",
        "script": "pg_dumpall > /tmp/all.sql", "retain_copies": 7,
    })
    body = respx.calls.last.request.content.decode()
    assert '"name":"backup-db"' in body
    assert '"type":"shell"' in body
    assert '"retainCopies":7' in body
    assert '"groupID":0' in body  # 默认值被注入


@pytest.mark.asyncio
@respx.mock
async def test_cronjob_run_calls_api():
    """cronjob_run 应调 POST /cronjobs/handle with id。"""
    respx.post("http://1panel.test/api/v2/cronjobs/handle").respond(
        json={"code": 200, "message": "", "data": None}
    )
    await mcp.call_tool("cronjob_run", {"id": 5})
    assert respx.calls.last
    assert '"id":5' in respx.calls.last.request.content.decode()


@pytest.mark.asyncio
@respx.mock
async def test_cronjob_status_enable_toggle():
    """cronjob_status 应把 enable=true 映射成 status=enable。"""
    respx.post("http://1panel.test/api/v2/cronjobs/status").respond(
        json={"code": 200, "message": "", "data": None}
    )
    await mcp.call_tool("cronjob_status", {"id": 3, "enable": False})
    body = respx.calls.last.request.content.decode()
    assert '"id":3' in body
    assert '"status":"disable"' in body


# ---- 写工具安全校验（confirm / 只读模式）----

@pytest.mark.asyncio
async def test_cronjob_delete_requires_confirm():
    """cronjob_delete 不传 confirm=true 应拒绝（不发起请求）。"""
    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/cronjobs/del")
        with pytest.raises(Exception):
            await mcp.call_tool("cronjob_delete", {"ids": [1], "confirm": False})
        assert not route.called


@pytest.mark.asyncio
async def test_cronjob_delete_with_confirm_calls_api():
    """cronjob_delete 传 confirm=true 应真正调用 API。"""
    with respx.mock as mock:
        mock.post("http://1panel.test/api/v2/cronjobs/del").respond(
            json={"code": 200, "message": "", "data": None}
        )
        await mcp.call_tool("cronjob_delete", {
            "ids": [1, 2], "confirm": True, "clean_data": True,
        })
        assert mock.calls.last
        body = mock.calls.last.request.content.decode()
        assert '"ids":[1,2]' in body
        assert '"cleanData":true' in body


@pytest.mark.asyncio
async def test_cronjob_records_clean_requires_confirm():
    """cronjob_records_clean 不传 confirm=true 应拒绝。"""
    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/cronjobs/records/clean")
        with pytest.raises(Exception):
            await mcp.call_tool(
                "cronjob_records_clean", {"cronjob_id": 1, "confirm": False}
            )
        assert not route.called


@pytest.mark.asyncio
async def test_write_ops_rejected_in_readonly_mode(monkeypatch):
    """只读模式下写操作（cronjob_run）应被拒绝，不发起请求。"""
    monkeypatch.setenv("PANEL_READONLY", "true")
    get_settings.cache_clear()
    assert get_settings().panel_readonly is True

    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/cronjobs/handle")
        with pytest.raises(Exception) as exc_info:
            await mcp.call_tool("cronjob_run", {"id": 1})
        assert "只读模式" in str(exc_info.value)
        assert not route.called

    # 恢复
    monkeypatch.setenv("PANEL_READONLY", "false")
    get_settings.cache_clear()
