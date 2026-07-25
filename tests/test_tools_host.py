"""host 模块工具测试（端到端，用 respx mock）。

FastMCP 1.28.1 调用方式：
- list_tools() -> list[Tool]  （只有元数据）
- call_tool(name, args) -> Sequence[ContentBlock] | dict  （实际执行）

测试要点：
1. 工具注册（通过 list_tools 检查名字）
2. 读工具端到端（call_tool → respx mock 1Panel → 返回 data）
3. 写工具的安全校验：
   - confirm（高危操作 command_run / process_stop / logs_clean 等）
   - readonly（PANEL_READONLY=true 拦截所有写操作）
"""

from __future__ import annotations

import pytest
import respx

from mcp_1panel.config import get_settings
from mcp_1panel.server import mcp
from .helpers import parse_tool_result


# ---- 注册验证 ----

async def test_host_tools_registered():
    """host 模块的工具应被注册到 mcp（覆盖各子域的关键工具）。"""
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    # 按子域分组验证关键工具，确保各 tag 都被覆盖
    expected = {
        # Host
        "host_info", "host_monitor",
        # Process
        "process_search", "process_listening", "process_stop",
        # SSH
        "ssh_info", "ssh_conf_get", "ssh_conf_update", "ssh_generate",
        "ssh_update", "ssh_operate", "ssh_cert_search", "ssh_cert_delete",
        # Device
        "device_conf_get", "device_update_conf", "device_users",
        # Disk
        "disk_list", "disk_mount", "disk_unmount", "disk_partition",
        # Host tool
        "host_tool_status", "host_tool_operate", "host_tool_config_get",
        "host_tool_supervisor_process",
        # Logs
        "logs_login", "logs_operation", "logs_system_files", "logs_clean",
        # Command
        "command_list", "command_search", "command_tree", "command_create",
        "command_update", "command_delete", "command_run",
    }
    missing = expected - names
    assert not missing, f"缺少 host 模块工具: {missing}"


# ---- 读工具端到端 ----

@pytest.mark.asyncio
@respx.mock
async def test_host_info_calls_device_base():
    """host_info 应调 POST /toolbox/device/base 并返回 data。"""
    respx.post("http://1panel.test/api/v2/toolbox/device/base").respond(
        json={"code": 200, "message": "", "data": {"cpuCores": 4, "os": "Ubuntu 22.04"}}
    )
    result = await mcp.call_tool("host_info", {})
    data = parse_tool_result(result)
    assert data["cpuCores"] == 4
    assert data["os"] == "Ubuntu 22.04"


@pytest.mark.asyncio
@respx.mock
async def test_disk_list_calls_get_disks():
    """disk_list 应调 GET /hosts/disks 并返回 data。"""
    respx.get("http://1panel.test/api/v2/hosts/disks").respond(
        json={"code": 200, "message": "",
              "data": {"totalDisks": 2, "totalCapacity": 1073741824,
                       "disks": [], "systemDisks": [], "unpartitionedDisks": []}}
    )
    result = await mcp.call_tool("disk_list", {})
    data = parse_tool_result(result)
    assert data["totalDisks"] == 2


@pytest.mark.asyncio
@respx.mock
async def test_logs_operation_passes_filters():
    """logs_operation 应把过滤参数透传到 POST /core/logs/operation。"""
    route = respx.post("http://1panel.test/api/v2/core/logs/operation").respond(
        json={"code": 200, "message": "", "data": {"items": [], "total": 0}}
    )
    await mcp.call_tool("logs_operation", {
        "operation": "create", "status": "Success", "page": 2, "page_size": 10,
    })
    assert route.called
    import json as _json
    body = _json.loads(route.calls.last.request.content.decode())
    assert body["operation"] == "create"
    assert body["status"] == "Success"
    assert body["page"] == 2
    assert body["pageSize"] == 10


@pytest.mark.asyncio
@respx.mock
async def test_process_search_uses_pid_in_path():
    """process_search 应把 pid 拼进路径 GET /process/{pid}。"""
    route = respx.get("http://1panel.test/api/v2/process/1234").respond(
        json={"code": 200, "message": "", "data": {"pid": 1234, "name": "sshd"}}
    )
    result = await mcp.call_tool("process_search", {"pid": 1234})
    assert route.called
    data = parse_tool_result(result)
    assert data["name"] == "sshd"


# ---- 写工具安全校验：confirm（高危）----

@pytest.mark.asyncio
async def test_command_run_requires_confirm():
    """command_run 不传 confirm=true 必须拒绝，且不发请求。"""
    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/hosts/ssh/operate")
        with pytest.raises(Exception) as exc_info:
            await mcp.call_tool(
                "command_run",
                {"command": "rm -rf /tmp/x", "confirm": False},
            )
        # 提示信息应明确点出 confirm
        assert "confirm=true" in str(exc_info.value)
        assert not route.called


@pytest.mark.asyncio
async def test_command_run_rejects_empty_command():
    """command_run 即使传了 confirm=true，空命令也应拒绝。"""
    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/hosts/ssh/operate")
        with pytest.raises(Exception):
            await mcp.call_tool(
                "command_run",
                {"command": "   ", "confirm": True},
            )
        assert not route.called


@pytest.mark.asyncio
@respx.mock
async def test_command_run_with_confirm_calls_api():
    """command_run 传 confirm=true 应真正调用 /hosts/ssh/operate。"""
    route = respx.post("http://1panel.test/api/v2/hosts/ssh/operate").respond(
        json={"code": 200, "message": "", "data": {"output": "ok"}}
    )
    await mcp.call_tool(
        "command_run",
        {"command": "uptime", "confirm": True},
    )
    assert route.called
    import json as _json
    body = _json.loads(route.calls.last.request.content.decode())
    assert body["command"] == "uptime"


@pytest.mark.asyncio
async def test_process_stop_requires_confirm():
    """process_stop 不传 confirm=true 应拒绝。"""
    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/process/stop")
        with pytest.raises(Exception) as exc_info:
            await mcp.call_tool("process_stop", {"pid": 9999, "confirm": False})
        assert "confirm=true" in str(exc_info.value)
        assert not route.called


@pytest.mark.asyncio
async def test_logs_clean_requires_confirm():
    """logs_clean 不传 confirm=true 应拒绝。"""
    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/core/logs/clean")
        with pytest.raises(Exception) as exc_info:
            await mcp.call_tool(
                "logs_clean",
                {"log_type": "operation", "confirm": False},
            )
        assert "confirm=true" in str(exc_info.value)
        assert not route.called


@pytest.mark.asyncio
async def test_disk_mount_requires_confirm():
    """disk_mount 不传 confirm=true 应拒绝。"""
    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/hosts/disks/mount")
        with pytest.raises(Exception) as exc_info:
            await mcp.call_tool(
                "disk_mount",
                {"device": "/dev/sdb1", "mount_point": "/mnt/data", "confirm": False},
            )
        assert "confirm=true" in str(exc_info.value)
        assert not route.called


# ---- 写工具安全校验：readonly ----

@pytest.mark.asyncio
async def test_write_ops_rejected_in_readonly_mode(monkeypatch):
    """只读模式下写操作（ssh_conf_update）应被拒绝。"""
    monkeypatch.setenv("PANEL_READONLY", "true")
    get_settings.cache_clear()
    assert get_settings().panel_readonly is True

    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/hosts/ssh/file/update")
        with pytest.raises(Exception) as exc_info:
            await mcp.call_tool(
                "ssh_conf_update",
                {"name": "sshd_config", "file": "Port 22"},
            )
        assert "只读模式" in str(exc_info.value)
        assert not route.called

    # 恢复（autouse fixture 会清理，同测试内显式 reset 更稳）
    monkeypatch.setenv("PANEL_READONLY", "false")
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_command_run_rejected_in_readonly_mode(monkeypatch):
    """只读模式下即使 confirm=true，command_run 也应被只读拦截优先拒绝。"""
    monkeypatch.setenv("PANEL_READONLY", "true")
    get_settings.cache_clear()

    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/hosts/ssh/operate")
        with pytest.raises(Exception) as exc_info:
            await mcp.call_tool(
                "command_run",
                {"command": "uptime", "confirm": True},
            )
        # require_write() 优先于 confirm 校验
        assert "只读模式" in str(exc_info.value)
        assert not route.called

    monkeypatch.setenv("PANEL_READONLY", "false")
    get_settings.cache_clear()


# ---- 写工具端到端（confirm 通过后真正调 API）----

@pytest.mark.asyncio
@respx.mock
async def test_ssh_generate_calls_cert_endpoint():
    """ssh_generate 应调 POST /hosts/ssh/cert 并透传 encryptionMode。"""
    route = respx.post("http://1panel.test/api/v2/hosts/ssh/cert").respond(
        json={"code": 200, "message": "", "data": {"id": 1, "name": "k1"}}
    )
    await mcp.call_tool(
        "ssh_generate",
        {"encryption_mode": "ed25519", "name": "k1"},
    )
    assert route.called
    import json as _json
    body = _json.loads(route.calls.last.request.content.decode())
    assert body["encryptionMode"] == "ed25519"
    assert body["name"] == "k1"


@pytest.mark.asyncio
@respx.mock
async def test_process_stop_with_confirm_calls_api():
    """process_stop 传 confirm=true 应真正调 POST /process/stop。"""
    route = respx.post("http://1panel.test/api/v2/process/stop").respond(
        json={"code": 200, "message": "", "data": None}
    )
    await mcp.call_tool("process_stop", {"pid": 9999, "confirm": True})
    assert route.called
    import json as _json
    body = _json.loads(route.calls.last.request.content.decode())
    assert body["PID"] == 9999
