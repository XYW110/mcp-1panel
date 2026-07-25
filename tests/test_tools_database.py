"""database 模块工具测试（端到端，用 respx mock）。

测试要点（对齐 AGENTS.md 第 7 节 + container 测试范式）：
1. 工具注册（list_tools 验证 42 个 database_* 工具齐全）
2. 读工具端到端（call_tool → respx mock 1Panel → 返回 data）
3. 写工具安全校验（confirm / readonly / require_write）
"""

from __future__ import annotations

import pytest
import respx

from mcp_1panel.config import get_settings
from mcp_1panel.server import mcp
from .helpers import parse_tool_result


# ---- 注册验证 ----

async def test_database_tools_registered():
    """database 模块的全部 42 个工具应被注册到 mcp。

    覆盖通用（Database/Database Common）+ MySQL + PostgreSQL + Redis 四组。
    """
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    expected = {
        # 通用（Database / Database Common）
        "database_list", "database_get", "database_db_list",
        "database_db_items", "database_info", "database_status",
        "database_conf", "database_conf_update",
        "database_create", "database_check", "database_update",
        "database_delete", "database_delete_check",
        # MySQL（Database Mysql）
        "database_mysql_list", "database_mysql_create",
        "database_mysql_delete", "database_mysql_delete_check",
        "database_mysql_password", "database_mysql_privileges",
        "database_mysql_bind", "database_mysql_load", "database_mysql_remote",
        "database_mysql_variables", "database_mysql_variables_update",
        "database_mysql_description", "database_mysql_format_options",
        # PostgreSQL（Database PostgreSQL）
        "database_pg_list", "database_pg_create",
        "database_pg_delete", "database_pg_delete_check",
        "database_pg_password", "database_pg_privileges",
        "database_pg_bind", "database_pg_load", "database_pg_description",
        # Redis（Database Redis）
        "database_redis_status", "database_redis_conf",
        "database_redis_conf_update", "database_redis_password",
        "database_redis_persistence_conf", "database_redis_persistence_update",
        "database_redis_install_cli",
    }
    missing = expected - names
    assert not missing, f"缺少工具: {missing}"
    # 顺带检查没有越界的额外 database_* 工具（防止命名漂移）
    extras = {n for n in names if n.startswith("database_")} - expected
    assert not extras, f"出现未声明的 database_* 工具: {extras}"


# ---- 读工具端到端 ----

@pytest.mark.asyncio
@respx.mock
async def test_database_mysql_list_returns_data():
    """database_mysql_list 应调 POST /databases/search 并返回 data。

    校验请求体含必填分页参数 + database/info 过滤字段。
    """
    respx.post("http://1panel.test/api/v2/databases/search").respond(
        json={"code": 200, "message": "", "data": {"items": [{"name": "wp"}], "total": 1}}
    )
    result = await mcp.call_tool(
        "database_mysql_list",
        {"database": "mysql", "info": "wp", "page": 1, "page_size": 20},
    )
    data = parse_tool_result(result)
    assert data["total"] == 1
    assert data["items"][0]["name"] == "wp"
    # 校验请求体形态（分页 + 过滤字段齐全）
    body = respx.calls.last.request.content.decode()
    for key in ("page", "pageSize", "orderBy", "order", "database", "info"):
        assert key in body, f"请求体缺少 {key}: {body}"


@pytest.mark.asyncio
@respx.mock
async def test_database_pg_list_returns_data():
    """database_pg_list 应调 POST /databases/pg/search 并返回 data。"""
    respx.post("http://1panel.test/api/v2/databases/pg/search").respond(
        json={"code": 200, "message": "", "data": {"items": [{"name": "appdb"}], "total": 1}}
    )
    result = await mcp.call_tool("database_pg_list", {"database": "postgresql"})
    data = parse_tool_result(result)
    assert data["total"] == 1
    assert data["items"][0]["name"] == "appdb"
    # 路径校验
    assert respx.calls.last.request.url.path == "/api/v2/databases/pg/search"


@pytest.mark.asyncio
@respx.mock
async def test_database_redis_status_returns_data():
    """database_redis_status 应调 POST /databases/redis/status 并返回 data。"""
    respx.post("http://1panel.test/api/v2/databases/redis/status").respond(
        json={"code": 200, "message": "", "data": {"connected_clients": "5", "uptime": "1000"}}
    )
    result = await mcp.call_tool("database_redis_status", {"name": "redis", "type": "redis"})
    data = parse_tool_result(result)
    assert data["connected_clients"] == "5"


@pytest.mark.asyncio
@respx.mock
async def test_database_db_list_get_endpoint():
    """database_db_list 应调 GET /databases/db/list/:type（路径参数）。"""
    respx.get("http://1panel.test/api/v2/databases/db/list/mysql").respond(
        json={"code": 200, "message": "", "data": [{"id": 1, "version": "8.0"}]}
    )
    result = await mcp.call_tool("database_db_list", {"type": "mysql"})
    data = parse_tool_result(result)
    assert respx.calls.last.request.method == "GET"
    assert respx.calls.last.request.url.path == "/api/v2/databases/db/list/mysql"
    if isinstance(data, list):
        assert data[0]["version"] == "8.0"
    else:
        assert data["version"] == "8.0"


@pytest.mark.asyncio
@respx.mock
async def test_database_get_by_name():
    """database_get 应调 GET /databases/db/:name。"""
    respx.get("http://1panel.test/api/v2/databases/db/myinst").respond(
        json={"code": 200, "message": "", "data": {"name": "myinst", "version": "16", "port": 5432}}
    )
    result = await mcp.call_tool("database_get", {"name": "myinst"})
    data = parse_tool_result(result)
    assert data["port"] == 5432
    assert respx.calls.last.request.url.path == "/api/v2/databases/db/myinst"


# ---- 写工具端到端（含 from_ 别名映射校验）----

@pytest.mark.asyncio
@respx.mock
async def test_database_create_maps_from_underscore_to_from():
    """database_create 的 from_ 参数应映射到请求体的 'from' 键（1Panel 要求）。"""
    respx.post("http://1panel.test/api/v2/databases/db").respond(
        json={"code": 200, "message": "", "data": None}
    )
    await mcp.call_tool("database_create", {
        "name": "mydb", "type": "mysql", "username": "root", "version": "8.0",
        "from_": "remote", "address": "10.0.0.1", "port": 3306, "password": "secret",
    })
    body = respx.calls.last.request.content.decode()
    assert '"from":"remote"' in body, f"from_ 未映射为 from 键: {body}"
    assert "from_" not in body, f"请求体不应出现 from_: {body}"


# ---- 写工具安全校验（confirm）----

@pytest.mark.asyncio
async def test_database_mysql_delete_requires_confirm():
    """database_mysql_delete 不传 confirm=true 应被拒绝（不发起请求）。"""
    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/databases/del")
        with pytest.raises(Exception):
            await mcp.call_tool(
                "database_mysql_delete",
                {"id": 1, "database": "mysql", "type": "mysql", "confirm": False},
            )
        assert not route.called


@pytest.mark.asyncio
@respx.mock
async def test_database_mysql_delete_with_confirm_calls_api():
    """database_mysql_delete 传 confirm=true 应真正调用 API。"""
    respx.post("http://1panel.test/api/v2/databases/del").respond(
        json={"code": 200, "message": "", "data": None}
    )
    await mcp.call_tool(
        "database_mysql_delete",
        {"id": 1, "database": "mysql", "type": "mysql", "confirm": True},
    )
    assert respx.calls.last  # 确实发了请求
    body = respx.calls.last.request.content.decode()
    assert '"deleteBackup":false' in body
    assert '"forceDelete":false' in body


@pytest.mark.asyncio
async def test_database_pg_delete_requires_confirm():
    """database_pg_delete 不传 confirm=true 应被拒绝（不发起请求）。"""
    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/databases/pg/del")
        with pytest.raises(Exception):
            await mcp.call_tool(
                "database_pg_delete",
                {"id": 1, "database": "postgresql", "type": "postgresql", "confirm": False},
            )
        assert not route.called


@pytest.mark.asyncio
async def test_database_delete_requires_confirm():
    """database_delete（通用实例解绑）不传 confirm=true 应被拒绝。"""
    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/databases/db/del")
        with pytest.raises(Exception):
            await mcp.call_tool("database_delete", {"id": 1, "confirm": False})
        assert not route.called


# ---- 写工具安全校验（只读模式 require_write）----

@pytest.mark.asyncio
async def test_write_ops_rejected_in_readonly_mode(monkeypatch):
    """只读模式下写操作应被 require_write() 拦截（FastMCP 包成 ToolError）。"""
    monkeypatch.setenv("PANEL_READONLY", "true")
    get_settings.cache_clear()
    assert get_settings().panel_readonly is True

    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/databases/redis/conf/update")
        with pytest.raises(Exception) as exc_info:
            await mcp.call_tool("database_redis_conf_update", {
                "database": "redis", "db_type": "redis", "maxmemory": "2gb",
            })
        assert "只读模式" in str(exc_info.value)
        assert not route.called

    # 恢复只读状态（autouse fixture 也会清，这里显式 reset 更稳）
    monkeypatch.setenv("PANEL_READONLY", "false")
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_install_cli_rejected_in_readonly_mode(monkeypatch):
    """database_redis_install_cli 是写操作，只读模式应被拒。"""
    monkeypatch.setenv("PANEL_READONLY", "true")
    get_settings.cache_clear()

    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/databases/redis/install/cli")
        with pytest.raises(Exception) as exc_info:
            await mcp.call_tool("database_redis_install_cli", {})
        assert "只读模式" in str(exc_info.value)
        assert not route.called

    monkeypatch.setenv("PANEL_READONLY", "false")
    get_settings.cache_clear()
