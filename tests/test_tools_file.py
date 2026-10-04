"""file 模块工具测试（端到端，用 respx mock）。

测试要点：
1. 工具注册（通过 list_tools 检查名字）
2. 读工具端到端（call_tool → respx mock 1Panel → 返回 data）
3. 写工具的安全校验（require_write 拦截只读模式 / 高危 confirm 拦截）
"""

from __future__ import annotations

import pytest
import respx

from mcp_1panel.config import get_settings
from mcp_1panel.server import mcp
from .helpers import parse_tool_result


# ---- 注册验证 ----

async def test_file_tools_registered():
    """file 模块的全部工具应被注册到 mcp。"""
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    expected = {
        # 读
        "file_list", "file_tree", "file_content", "file_read", "file_preview",
        "file_size", "file_dir_size", "file_check", "file_batch_check",
        "file_mount", "file_user_group", "file_favorite_list", "file_remarks",
        "file_convert_log", "file_upload_search", "file_recycle_list",
        "file_recycle_status",
        # 写
        "file_create", "file_save", "file_upload", "file_move", "file_copy",
        "file_rename", "file_compress", "file_decompress", "file_chmod",
        "file_chown", "file_batch_chmod", "file_wget", "file_favorite",
        "file_favorite_delete", "file_remark", "file_convert",
        "file_recycle_restore",
        # 高危
        "file_delete", "file_batch_delete", "file_recycle_clear",
    }
    missing = expected - names
    assert not missing, f"缺少工具: {missing}"


# ---- 读工具端到端 ----

@pytest.mark.asyncio
@respx.mock
async def test_file_list_returns_data():
    """file_list 应调 POST /files/search 并返回 data。"""
    respx.post("http://1panel.test/api/v2/files/search").respond(
        json={"code": 200, "message": "", "data": {
            "items": [{"name": "nginx.conf", "isDir": False}],
            "total": 1,
        }}
    )
    result = await mcp.call_tool("file_list", {"path": "/opt/1panel"})
    data = parse_tool_result(result)
    assert data["total"] == 1
    assert data["items"][0]["name"] == "nginx.conf"


@pytest.mark.asyncio
@respx.mock
async def test_file_content_returns_data():
    """file_content 应调 POST /files/content 并返回 data（含 content 字段）。"""
    respx.post("http://1panel.test/api/v2/files/content").respond(
        json={"code": 200, "message": "", "data": {
            "path": "/etc/hostname", "content": "myhost", "isDir": False,
        }}
    )
    result = await mcp.call_tool("file_content", {"path": "/etc/hostname"})
    data = parse_tool_result(result)
    assert data["content"] == "myhost"


@pytest.mark.asyncio
@respx.mock
async def test_file_recycle_list_uses_post():
    """file_recycle_list 应调 POST /files/recycle/search（不是 GET）。"""
    route = respx.post("http://1panel.test/api/v2/files/recycle/search").respond(
        json={"code": 200, "message": "", "data": {"items": [], "total": 0}}
    )
    result = await mcp.call_tool("file_recycle_list", {"page": 1})
    assert route.called
    data = parse_tool_result(result)
    assert data["total"] == 0


@pytest.mark.asyncio
@respx.mock
async def test_file_recycle_status_uses_get():
    """file_recycle_status 应调 GET /files/recycle/status（不是 POST）。"""
    route = respx.get("http://1panel.test/api/v2/files/recycle/status").respond(
        json={"code": 200, "message": "", "data": True}
    )
    result = await mcp.call_tool("file_recycle_status", {})
    assert route.called
    data = parse_tool_result(result)
    assert data is True


# ---- 写工具端到端 + 请求体校验 ----

@pytest.mark.asyncio
@respx.mock
async def test_file_save_posts_correct_body():
    """file_save 应以 path/content 字段调 POST /files/save。"""
    route = respx.post("http://1panel.test/api/v2/files/save").respond(
        json={"code": 200, "message": "", "data": None}
    )
    await mcp.call_tool("file_save", {
        "path": "/tmp/x.txt", "content": "hello",
    })
    assert route.called
    import json as _json
    body = _json.loads(route.calls.last.request.content)
    assert body == {"path": "/tmp/x.txt", "content": "hello"}


@pytest.mark.asyncio
@respx.mock
async def test_file_compress_posts_type_field():
    """file_compress 应把 type 透传到 body。"""
    route = respx.post("http://1panel.test/api/v2/files/compress").respond(
        json={"code": 200, "message": "", "data": None}
    )
    await mcp.call_tool("file_compress", {
        "files": ["/tmp/a"], "dst": "/tmp", "name": "out", "type": "tar.gz",
    })
    assert route.called
    import json as _json
    body = _json.loads(route.calls.last.request.content)
    assert body["type"] == "tar.gz"
    assert body["name"] == "out"


@pytest.mark.asyncio
@respx.mock
async def test_file_recycle_restore_maps_from_underscore():
    """file_recycle_restore 应把 from_ 入参映射为 body 的 from 字段。"""
    route = respx.post("http://1panel.test/api/v2/files/recycle/reduce").respond(
        json={"code": 200, "message": "", "data": None}
    )
    await mcp.call_tool("file_recycle_restore", {
        "from_": "/opt", "r_name": "1234-file",
    })
    assert route.called
    import json as _json
    body = _json.loads(route.calls.last.request.content)
    assert body["from"] == "/opt"
    assert body["rName"] == "1234-file"


@pytest.mark.asyncio
@respx.mock
async def test_file_upload_multipart(tmp_path):
    """file_upload 应以 multipart/form-data 调 POST /files/upload（file+path+overwrite）。"""
    local = tmp_path / "hello.txt"
    local.write_bytes(b"hello upload")
    route = respx.post("http://1panel.test/api/v2/files/upload").respond(
        json={"code": 200, "message": "", "data": None}
    )
    await mcp.call_tool("file_upload", {
        "local_path": str(local), "remote_dir": "/opt/target",
    })
    assert route.called
    body = route.calls.last.request.content
    assert b'name="file"' in body
    assert b"hello upload" in body
    assert b"/opt/target" in body


@pytest.mark.asyncio
async def test_file_upload_missing_local_file_rejected():
    """本地文件不存在时 file_upload 应报错且不发请求。"""
    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/files/upload")
        with pytest.raises(Exception):
            await mcp.call_tool("file_upload", {
                "local_path": "Z:/definitely/not/exists.bin",
                "remote_dir": "/opt/target",
            })
        assert not route.called


# ---- 写工具安全校验：高危 confirm 拦截 ----

@pytest.mark.asyncio
async def test_file_delete_requires_confirm():
    """file_delete 不传 confirm=true 应拒绝（不发起请求）。"""
    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/files/del")
        with pytest.raises(Exception):
            await mcp.call_tool("file_delete", {"path": "/tmp/x", "confirm": False})
        assert not route.called


@pytest.mark.asyncio
async def test_file_batch_delete_requires_confirm():
    """file_batch_delete 不传 confirm=true 应拒绝。"""
    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/files/batch/del")
        with pytest.raises(Exception):
            await mcp.call_tool("file_batch_delete", {"paths": ["/tmp/x"]})
        assert not route.called


@pytest.mark.asyncio
async def test_file_recycle_clear_requires_confirm():
    """file_recycle_clear 不传 confirm=true 应拒绝（清空回收站高危）。"""
    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/files/recycle/clear")
        with pytest.raises(Exception):
            await mcp.call_tool("file_recycle_clear", {"confirm": False})
        assert not route.called


@pytest.mark.asyncio
@respx.mock
async def test_file_delete_with_confirm_calls_api():
    """file_delete 传 confirm=true 应真正调用 API。"""
    route = respx.post("http://1panel.test/api/v2/files/del").respond(
        json={"code": 200, "message": "", "data": None}
    )
    await mcp.call_tool("file_delete", {
        "path": "/tmp/x", "confirm": True,
    })
    assert route.called


# ---- 写工具安全校验：只读模式 ----

@pytest.mark.asyncio
async def test_write_ops_rejected_in_readonly_mode(monkeypatch):
    """只读模式下写操作应被 require_write 拦截（FastMCP 包成 ToolError）。"""
    monkeypatch.setenv("PANEL_READONLY", "true")
    get_settings.cache_clear()
    assert get_settings().panel_readonly is True

    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/files/move")
        with pytest.raises(Exception) as exc_info:
            await mcp.call_tool("file_move", {
                "old_paths": ["/tmp/a"], "new_path": "/tmp/b",
            })
        assert "只读模式" in str(exc_info.value)
        assert not route.called

    # 恢复（autouse fixture 也会清，但同测试内显式 reset 更稳）
    monkeypatch.setenv("PANEL_READONLY", "false")
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_chmod_rejected_in_readonly_mode(monkeypatch):
    """只读模式下 file_chmod（普通写操作）也应被拦截。"""
    monkeypatch.setenv("PANEL_READONLY", "true")
    get_settings.cache_clear()

    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/files/mode")
        with pytest.raises(Exception) as exc_info:
            await mcp.call_tool("file_chmod", {"path": "/tmp/x", "mode": 493})
        assert "只读模式" in str(exc_info.value)
        assert not route.called

    monkeypatch.setenv("PANEL_READONLY", "false")
    get_settings.cache_clear()
