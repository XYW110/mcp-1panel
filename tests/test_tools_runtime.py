"""runtime 模块工具测试（端到端，用 respx mock）。

测试要点：
1. 工具注册（通过 list_tools 检查关键名字）
2. 读工具端到端：runtime_supervisor_process_get（GET 路径参数）、
   runtime_php_config_get（GET 路径参数）、runtime_node_modules（POST body ID）
3. 写工具安全校验：
   - runtime_create 被只读模式拦截
   - runtime_supervisor_process_operate 正常调用 API
   - runtime_php_container_update 发送正确 body

注意：这里使用独立的 FastMCP 实例（只注册 runtime 模块），而非 server.py 的
全局 mcp，避免被其他并行开发模块的临时语法错误拖累（register_all 会导入全部模块）。
runtime 模块与 website 模块工具名不冲突（website 已实现 9 个 runtime/php 工具，
本模块只实现 website 未覆盖的部分）。
"""

from __future__ import annotations

import json

import pytest
import respx
from mcp.server.fastmcp import FastMCP

from mcp_1panel.config import get_settings
from mcp_1panel.tools import runtime as runtime_mod
from .helpers import parse_tool_result


@pytest.fixture
def mcp():
    """独立 FastMCP 实例，只注册 runtime 模块。"""
    server = FastMCP("test-runtime")
    runtime_mod.register(server)
    return server


# ---- 注册验证 ----

async def test_runtime_tools_registered(mcp):
    """runtime 模块的工具应被注册到 mcp。"""
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    expected = {
        # CRUD 增补
        "runtime_create", "runtime_update", "runtime_remark",
        # Node
        "runtime_node_modules", "runtime_node_modules_operate",
        "runtime_node_package_scripts",
        # PHP 配置/容器/FPM/文件
        "runtime_php_config_get", "runtime_php_config_update",
        "runtime_php_container_get", "runtime_php_container_update",
        "runtime_php_fpm_config_get", "runtime_php_fpm_config_update",
        "runtime_php_fpm_status", "runtime_php_file_get",
        "runtime_php_file_update", "runtime_php_extensions_list",
        # Supervisor
        "runtime_supervisor_process_get",
        "runtime_supervisor_process_operate",
        "runtime_supervisor_process_file",
    }
    missing = expected - names
    assert not missing, f"缺少工具: {missing}"


async def test_runtime_no_name_collision_with_website(mcp):
    """runtime 模块不得重复定义 website.py 已有的工具名（否则注册重名报错）。

    website.py 已实现：runtime_search / runtime_detail / runtime_operate /
    runtime_delete / runtime_delete_check / runtime_sync /
    runtime_php_extensions_search / runtime_php_extension_install /
    runtime_php_extension_uninstall。本模块必须避开这些名字。
    """
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    website_owned = {
        "runtime_search", "runtime_detail", "runtime_operate", "runtime_delete",
        "runtime_delete_check", "runtime_sync",
        "runtime_php_extensions_search", "runtime_php_extension_install",
        "runtime_php_extension_uninstall",
    }
    collision = names & website_owned
    assert not collision, f"runtime 模块不得重复定义 website 模块的工具: {collision}"


# ---- 读工具端到端 ----

@pytest.mark.asyncio
@respx.mock
async def test_runtime_supervisor_process_get_uses_path_param(mcp):
    """runtime_supervisor_process_get 应调 GET /runtimes/supervisor/process/{id}。"""
    route = respx.get("http://1panel.test/api/v2/runtimes/supervisor/process/7").respond(
        json={"code": 200, "message": "",
              "data": [{"name": "worker1", "command": "php artisan queue:work"}]}
    )
    result = await mcp.call_tool("runtime_supervisor_process_get", {"runtime_id": 7})
    data = parse_tool_result(result)
    assert route.called
    # 单元素 list 会被 FastMCP 扁平化成 dict
    items = data if isinstance(data, list) else [data]
    assert items[0]["name"] == "worker1"


@pytest.mark.asyncio
@respx.mock
async def test_runtime_php_config_get_uses_path_param(mcp):
    """runtime_php_config_get 应调 GET /runtimes/php/config/{id}。"""
    route = respx.get("http://1panel.test/api/v2/runtimes/php/config/3").respond(
        json={"code": 200, "message": "",
              "data": {"id": 3, "maxExecutionTime": "300", "uploadMaxSize": "50M"}}
    )
    result = await mcp.call_tool("runtime_php_config_get", {"runtime_id": 3})
    data = parse_tool_result(result)
    assert route.called
    assert data["maxExecutionTime"] == "300"
    assert data["uploadMaxSize"] == "50M"


@pytest.mark.asyncio
@respx.mock
async def test_runtime_node_modules_sends_id_body(mcp):
    """runtime_node_modules 应调 POST /runtimes/node/modules，body 带 ID。"""
    route = respx.post("http://1panel.test/api/v2/runtimes/node/modules").respond(
        json={"code": 200, "message": "",
              "data": [{"name": "express", "version": "4.18.0"}]}
    )
    result = await mcp.call_tool("runtime_node_modules", {"runtime_id": 11})
    data = parse_tool_result(result)
    assert route.called
    sent = json.loads(route.calls.last.request.content)
    assert sent == {"ID": 11}
    items = data if isinstance(data, list) else [data]
    assert items[0]["name"] == "express"


@pytest.mark.asyncio
@respx.mock
async def test_runtime_php_extensions_list_uses_path_param(mcp):
    """runtime_php_extensions_list 应调 GET /runtimes/php/{id}/extensions。"""
    route = respx.get("http://1panel.test/api/v2/runtimes/php/5/extensions").respond(
        json={"code": 200, "message": "", "data": [{"name": "redis"}, {"name": "mysqli"}]}
    )
    result = await mcp.call_tool("runtime_php_extensions_list", {"runtime_id": 5})
    data = parse_tool_result(result)
    assert route.called
    items = data if isinstance(data, list) else [data]
    assert items[0]["name"] == "redis"


# ---- 写工具端到端 + 安全校验 ----

@pytest.mark.asyncio
@respx.mock
async def test_runtime_create_calls_api(mcp):
    """runtime_create 应调 POST /runtimes，body 携带核心字段。"""
    route = respx.post("http://1panel.test/api/v2/runtimes").respond(
        json={"code": 200, "message": "", "data": None}
    )
    await mcp.call_tool("runtime_create", {
        "name": "php82", "type": "php", "version": "8.2",
    })
    assert route.called
    sent = json.loads(route.calls.last.request.content)
    assert sent["name"] == "php82"
    assert sent["type"] == "php"
    assert sent["version"] == "8.2"


@pytest.mark.asyncio
async def test_runtime_create_rejected_in_readonly_mode(mcp, monkeypatch):
    """只读模式下写操作（runtime_create）应被拒绝（不发起请求）。"""
    monkeypatch.setenv("PANEL_READONLY", "true")
    get_settings.cache_clear()
    assert get_settings().panel_readonly is True

    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/runtimes")
        with pytest.raises(Exception) as exc_info:
            await mcp.call_tool("runtime_create", {
                "name": "x", "type": "php", "version": "8.2",
            })
        assert "只读模式" in str(exc_info.value)
        assert not route.called

    monkeypatch.setenv("PANEL_READONLY", "false")
    get_settings.cache_clear()


@pytest.mark.asyncio
@respx.mock
async def test_runtime_supervisor_process_operate_sends_body(mcp):
    """runtime_supervisor_process_operate 应调 POST /runtimes/supervisor/process。"""
    route = respx.post("http://1panel.test/api/v2/runtimes/supervisor/process").respond(
        json={"code": 200, "message": "", "data": None}
    )
    await mcp.call_tool("runtime_supervisor_process_operate", {
        "runtime_id": 9, "operate": "start", "name": "worker1",
    })
    assert route.called
    sent = json.loads(route.calls.last.request.content)
    assert sent["id"] == 9
    assert sent["operate"] == "start"
    assert sent["name"] == "worker1"


@pytest.mark.asyncio
@respx.mock
async def test_runtime_php_container_update_sends_correct_body(mcp):
    """runtime_php_container_update 应调 POST /runtimes/php/container/update，
    且 body 用 camelCase（environments/exposedPorts/...）。"""
    route = respx.post(
        "http://1panel.test/api/v2/runtimes/php/container/update"
    ).respond(json={"code": 200, "message": "", "data": None})
    await mcp.call_tool("runtime_php_container_update", {
        "runtime_id": 4,
        "environments": [{"key": "APP_ENV", "value": "prod"}],
        "exposed_ports": [{"containerPort": 9000, "hostPort": 9001, "hostIP": ""}],
    })
    assert route.called
    sent = json.loads(route.calls.last.request.content)
    assert sent["id"] == 4
    # camelCase 校验
    assert sent["environments"] == [{"key": "APP_ENV", "value": "prod"}]
    assert sent["exposedPorts"] == [{"containerPort": 9000, "hostPort": 9001, "hostIP": ""}]


@pytest.mark.asyncio
@respx.mock
async def test_runtime_php_file_update_sends_content(mcp):
    """runtime_php_file_update 应调 POST /runtimes/php/update，覆盖写内容。"""
    route = respx.post("http://1panel.test/api/v2/runtimes/php/update").respond(
        json={"code": 200, "message": "", "data": None}
    )
    await mcp.call_tool("runtime_php_file_update", {
        "runtime_id": 6, "type": "php", "content": "memory_limit = 256M",
    })
    assert route.called
    sent = json.loads(route.calls.last.request.content)
    assert sent == {"id": 6, "type": "php", "content": "memory_limit = 256M"}


@pytest.mark.asyncio
async def test_runtime_remark_rejected_in_readonly_mode(mcp, monkeypatch):
    """只读模式下 runtime_remark（写操作）应被拒绝。"""
    monkeypatch.setenv("PANEL_READONLY", "true")
    get_settings.cache_clear()

    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/runtimes/remark")
        with pytest.raises(Exception):
            await mcp.call_tool("runtime_remark", {"runtime_id": 1, "remark": "x"})
        assert not route.called

    monkeypatch.setenv("PANEL_READONLY", "false")
    get_settings.cache_clear()
