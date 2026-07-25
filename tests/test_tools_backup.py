"""backup 模块工具测试（端到端，用 respx mock）。

FastMCP 1.28.1 调用方式：
- list_tools() -> list[Tool]  （只有元数据）
- call_tool(name, args) -> Sequence[ContentBlock] | dict  （实际执行）

测试要点：
1. 工具注册（通过 list_tools 检查名字）
2. 读工具端到端（call_tool → respx mock 1Panel → 返回 data）
3. 写工具的安全校验（confirm / readonly）

注意：backup 模块默认未注册到 server.py 的 register_all（主 agent 统一加），
这里通过单独构造一个 FastMCP 实例并注册 backup.register 来测试，避免依赖
全局 mcp 是否已挂载 backup。
"""

from __future__ import annotations

import pytest
import respx
from mcp.server.fastmcp import FastMCP

from mcp_1panel.config import get_settings
from mcp_1panel.tools import backup
from .helpers import parse_tool_result


@pytest.fixture(scope="module")
def mcp() -> FastMCP:
    """模块级 mcp：仅注册 backup 工具，供本测试文件所有用例复用。"""
    server = FastMCP("backup-test")
    backup.register(server)
    return server


# ---- 注册验证 ----

async def test_backup_tools_registered(mcp: FastMCP):
    """backup 模块的 25 个工具应被注册到 mcp。"""
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    expected = {
        # 账号管理（主控端）
        "backup_account_search", "backup_account_options",
        "backup_account_local_dir", "backup_account_buckets",
        "backup_account_files", "backup_account_check",
        "backup_account_create", "backup_account_update",
        "backup_account_delete", "backup_account_refresh_token",
        # 备份 / 恢复 / 上传
        "backup_run", "backup_restore", "backup_upload",
        "backup_restore_by_upload",
        # 备份记录
        "backup_record_search", "backup_record_search_by_cronjob",
        "backup_record_size", "backup_record_download_url",
        "backup_record_update_description", "backup_record_delete",
        # 节点端账号管理
        "backup_account_node_info", "backup_account_node_create",
        "backup_account_node_update", "backup_account_node_delete",
        "backup_account_node_refresh_token",
    }
    missing = expected - names
    assert not missing, f"缺少工具: {missing}"
    # 确保没有意外多注册
    extra = names - expected
    assert not extra, f"多出未预期的工具: {extra}"


# ---- 读工具端到端 ----

@pytest.mark.asyncio
@respx.mock
async def test_backup_account_search_returns_data(mcp: FastMCP):
    """backup_account_search 应调 POST /backups/search 并返回 data。"""
    respx.post("http://1panel.test/api/v2/backups/search").respond(
        json={"code": 200, "message": "", "data": {
            "items": [{"id": 1, "name": "my-s3", "type": "S3"}], "total": 1,
        }}
    )
    result = await mcp.call_tool("backup_account_search", {"page": 1, "type": "S3"})
    data = parse_tool_result(result)
    assert data["total"] == 1
    assert data["items"][0]["name"] == "my-s3"


@pytest.mark.asyncio
@respx.mock
async def test_backup_account_options_get(mcp: FastMCP):
    """backup_account_options 应调 GET /backups/options。"""
    respx.get("http://1panel.test/api/v2/backups/options").respond(
        json={"code": 200, "message": "", "data": [
            {"id": 1, "name": "local", "type": "LOCAL", "isPublic": False},
        ]}
    )
    result = await mcp.call_tool("backup_account_options", {})
    data = parse_tool_result(result)
    # data 是 list 时，FastMCP 逐元素展平，parse_tool_result 返回 list
    items = data if isinstance(data, list) else [data]
    assert items[0]["type"] == "LOCAL"


@pytest.mark.asyncio
@respx.mock
async def test_backup_account_buckets(mcp: FastMCP):
    """backup_account_buckets 应调 POST /backups/buckets。"""
    route = respx.post("http://1panel.test/api/v2/backups/buckets").respond(
        json={"code": 200, "message": "", "data": ["bucket-a", "bucket-b"]}
    )
    result = await mcp.call_tool("backup_account_buckets", {
        "type": "S3", "access_key": "AK", "credential": "SK", "vars": "{}",
    })
    assert route.called
    # 返回的是字符串数组（桶名列表），FastMCP 逐元素展平为 TextContent，
    # 每个 .text 是裸字符串（非 JSON），parse_tool_result 无法解析。
    # 这里直接断言原始 ContentBlock 序列里含期望桶名。
    blocks = result if isinstance(result, list) else [result]
    blob = " ".join(getattr(b, "text", str(b)) for b in blocks)
    assert "bucket-a" in blob


@pytest.mark.asyncio
@respx.mock
async def test_backup_record_search(mcp: FastMCP):
    """backup_record_search 应调 POST /backups/record/search。"""
    respx.post("http://1panel.test/api/v2/backups/record/search").respond(
        json={"code": 200, "message": "", "data": {
            "items": [{"id": 9, "fileName": "app.tar.gz"}], "total": 1,
        }}
    )
    result = await mcp.call_tool("backup_record_search", {"type": "app"})
    data = parse_tool_result(result)
    assert data["items"][0]["fileName"] == "app.tar.gz"


@pytest.mark.asyncio
@respx.mock
async def test_backup_account_node_info_get(mcp: FastMCP):
    """backup_account_node_info 应调 GET /core/backups/client/{clientType}。"""
    route = respx.get("http://1panel.test/api/v2/core/backups/client/onedrive").respond(
        json={"code": 200, "message": "", "data": {"client_id": "cid", "redirect_uri": "https://x"}}
    )
    result = await mcp.call_tool("backup_account_node_info", {"client_type": "onedrive"})
    assert route.called
    data = parse_tool_result(result)
    assert data["client_id"] == "cid"


# ---- 写工具：confirm 安全校验 ----

@pytest.mark.asyncio
async def test_backup_account_delete_requires_confirm(mcp: FastMCP):
    """backup_account_delete 不传 confirm=true 应拒绝（不发起请求）。"""
    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/backups/del")
        with pytest.raises(Exception):
            await mcp.call_tool("backup_account_delete", {"id": 1, "confirm": False})
        assert not route.called


@pytest.mark.asyncio
@respx.mock
async def test_backup_account_delete_with_confirm(mcp: FastMCP):
    """backup_account_delete 传 confirm=true 应真正调用 API。"""
    route = respx.post("http://1panel.test/api/v2/backups/del").respond(
        json={"code": 200, "message": "", "data": None}
    )
    await mcp.call_tool("backup_account_delete", {"id": 7, "confirm": True})
    assert route.called


@pytest.mark.asyncio
async def test_backup_restore_requires_confirm(mcp: FastMCP):
    """backup_restore 不传 confirm=true 应拒绝。"""
    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/backups/recover")
        with pytest.raises(Exception):
            await mcp.call_tool("backup_restore", {
                "type": "app", "name": "myapp", "file": "/x/y.tar.gz",
            })
        assert not route.called


@pytest.mark.asyncio
async def test_backup_record_delete_requires_confirm(mcp: FastMCP):
    """backup_record_delete 不传 confirm=true 应拒绝。"""
    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/backups/record/del")
        with pytest.raises(Exception):
            await mcp.call_tool("backup_record_delete", {"ids": [1, 2]})
        assert not route.called


@pytest.mark.asyncio
async def test_backup_account_node_delete_requires_confirm(mcp: FastMCP):
    """backup_account_node_delete 不传 confirm=true 应拒绝。"""
    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/core/backups/del")
        with pytest.raises(Exception):
            await mcp.call_tool("backup_account_node_delete", {"name": "s3acct"})
        assert not route.called


# ---- 写工具：只读模式拦截 ----

@pytest.mark.asyncio
async def test_write_ops_rejected_in_readonly_mode(mcp: FastMCP, monkeypatch):
    """只读模式下写操作应被 require_write() 拒绝（FastMCP 包装成 ToolError）。"""
    monkeypatch.setenv("PANEL_READONLY", "true")
    get_settings.cache_clear()
    assert get_settings().panel_readonly is True

    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/backups")
        with pytest.raises(Exception) as exc_info:
            await mcp.call_tool("backup_account_create", {
                "type": "S3", "vars": "{}", "access_key": "AK", "credential": "SK",
            })
        assert "只读模式" in str(exc_info.value)
        assert not route.called

    monkeypatch.setenv("PANEL_READONLY", "false")
    get_settings.cache_clear()


# ---- 写工具：confirm=true 真正调用 API ----

@pytest.mark.asyncio
@respx.mock
async def test_backup_run_writes(mcp: FastMCP):
    """backup_run（无 confirm，普通写）应直接调用 POST /backups/backup。"""
    route = respx.post("http://1panel.test/api/v2/backups/backup").respond(
        json={"code": 200, "message": "", "data": None}
    )
    await mcp.call_tool("backup_run", {"type": "app", "name": "wordpress"})
    assert route.called


@pytest.mark.asyncio
@respx.mock
async def test_backup_account_create_calls_api(mcp: FastMCP):
    """backup_account_create 应调 POST /backups。"""
    route = respx.post("http://1panel.test/api/v2/backups").respond(
        json={"code": 200, "message": "", "data": None}
    )
    await mcp.call_tool("backup_account_create", {
        "type": "OSS", "vars": '{"region":"cn-hangzhou"}',
        "access_key": "AK", "credential": "SK", "bucket": "b1",
    })
    assert route.called


@pytest.mark.asyncio
@respx.mock
async def test_backup_restore_by_upload_with_confirm(mcp: FastMCP):
    """backup_restore_by_upload 传 confirm=true 应真正调用 API。"""
    route = respx.post("http://1panel.test/api/v2/backups/recover/byupload").respond(
        json={"code": 200, "message": "", "data": None}
    )
    await mcp.call_tool("backup_restore_by_upload", {
        "type": "mysql", "name": "db1", "file": "/tmp/x.sql",
        "download_account_id": 0, "confirm": True,
    })
    assert route.called
