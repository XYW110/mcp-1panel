"""container 模块工具测试（端到端，用 respx mock）。

FastMCP 1.28.1 调用方式：
- list_tools() -> list[Tool]  （只有元数据）
- call_tool(name, args) -> Sequence[ContentBlock] | dict  （实际执行）

测试要点：
1. 工具注册（通过 list_tools 检查名字）
2. 读工具端到端（call_tool → respx mock 1Panel → 返回 data）
3. 写工具的安全校验（confirm / readonly）
"""

from __future__ import annotations

import pytest
import respx

from mcp_1panel.config import get_settings
from mcp_1panel.server import mcp
from .helpers import parse_tool_result


# ---- 注册验证 ----

async def test_container_tools_registered():
    """container 模块的全部工具应被注册到 mcp。

    覆盖原有 14 个 + 新增 39 个（镜像/仓库/网络/卷/Compose/模板/Docker）。
    """
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    expected = {
        # ---- 原有 14 个 ----
        "container_search", "container_operate", "container_start",
        "container_stop", "container_restart", "container_remove",
        "container_inspect", "container_rename", "container_stats",
        "container_log_search", "container_image_list", "container_image_pull",
        "container_image_remove", "container_compose_search",
        # ---- 镜像进阶（6）----
        "container_image_search", "container_image_build", "container_image_load",
        "container_image_push", "container_image_save", "container_image_tag",
        # ---- 镜像仓库（6）----
        "container_repo_list", "container_repo_search", "container_repo_create",
        "container_repo_update", "container_repo_delete", "container_repo_status",
        # ---- 网络（4）----
        "container_network_list", "container_network_search",
        "container_network_create", "container_network_delete",
        # ---- 卷（4）----
        "container_volume_list", "container_volume_search",
        "container_volume_create", "container_volume_delete",
        # ---- Compose 进阶（5）----
        "container_compose_create", "container_compose_operate",
        "container_compose_update", "container_compose_test",
        "container_compose_env",
        # ---- 模板（5）----
        "container_template_list", "container_template_search",
        "container_template_create", "container_template_update",
        "container_template_delete",
        # ---- Docker daemon（9）----
        "container_docker_status", "container_docker_operate",
        "container_daemonjson_get", "container_daemonjson_update",
        "container_prune", "container_commit", "container_upgrade",
        "container_info", "container_limit",
        # ---- 创建与配置更新（2）----
        "container_create", "container_update",
    }
    missing = expected - names
    assert not missing, f"缺少工具: {missing}"


# ---- 读工具端到端 ----

@pytest.mark.asyncio
@respx.mock
async def test_container_search_returns_data():
    """container_search 应调 /containers/search 并返回 data。"""
    respx.post("http://1panel.test/api/v2/containers/search").respond(
        json={"code": 200, "message": "", "data": {"items": [{"name": "nginx"}], "total": 1}}
    )
    result = await mcp.call_tool("container_search", {"page": 1})
    data = parse_tool_result(result)
    assert data["total"] == 1
    assert data["items"][0]["name"] == "nginx"


# ---- 写工具安全校验 ----

@pytest.mark.asyncio
async def test_container_remove_requires_confirm():
    """container_remove 不传 confirm=true 应拒绝（不发起请求）。"""
    with respx.mock:
        # 即使配了路由也不应被命中（confirm 先拒绝）
        route = respx.post("http://1panel.test/api/v2/containers/operate")
        with pytest.raises(Exception):
            await mcp.call_tool("container_remove", {"name": "x", "confirm": False})
        assert not route.called


@pytest.mark.asyncio
async def test_container_remove_with_confirm_calls_api():
    """container_remove 传 confirm=true 应真正调用 API。"""
    with respx.mock as mock:
        mock.post("http://1panel.test/api/v2/containers/operate").respond(
            json={"code": 200, "message": "", "data": None}
        )
        await mcp.call_tool("container_remove", {"name": "nginx", "confirm": True})
        assert mock.calls.last  # 确实发了请求


@pytest.mark.asyncio
async def test_write_ops_rejected_in_readonly_mode(monkeypatch):
    """只读模式下写操作应被拒绝（FastMCP 包装成 ToolError，原始是 PanelReadOnlyError）。"""
    monkeypatch.setenv("PANEL_READONLY", "true")
    get_settings.cache_clear()
    assert get_settings().panel_readonly is True

    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/containers/operate")
        # FastMCP 把 handler 抛的异常包成 ToolError
        with pytest.raises(Exception) as exc_info:
            await mcp.call_tool("container_start", {"name": "x"})
        assert "只读模式" in str(exc_info.value)
        assert not route.called

    # 恢复（autouse fixture 会清理，但同测试内显式 reset 更稳）
    monkeypatch.setenv("PANEL_READONLY", "false")
    get_settings.cache_clear()


@pytest.mark.asyncio
@respx.mock
async def test_container_image_list():
    """container_image_list 应调 GET /containers/image。"""
    respx.get("http://1panel.test/api/v2/containers/image").respond(
        json={"code": 200, "message": "", "data": [{"id": "sha:abc", "tags": ["nginx:latest"]}]}
    )
    result = await mcp.call_tool("container_image_list", {})
    data = parse_tool_result(result)
    # data 是 list 时，FastMCP 逐元素展平，parse_tool_result 返回 list
    if isinstance(data, list):
        assert data[0]["tags"] == ["nginx:latest"]
    else:
        assert data["tags"] == ["nginx:latest"]


# ====================================================================
# 新增工具测试（镜像/仓库/网络/卷/Compose/模板/Docker）
# ====================================================================

# ---- 新增读工具端到端 ----

@pytest.mark.asyncio
@respx.mock
async def test_container_repo_list():
    """container_repo_list 应调 GET /containers/repo。"""
    respx.get("http://1panel.test/api/v2/containers/repo").respond(
        json={"code": 200, "message": "", "data": [
            {"id": 1, "name": "Docker Hub", "downloadUrl": "https://registry-1.docker.io"},
        ]}
    )
    result = await mcp.call_tool("container_repo_list", {})
    data = parse_tool_result(result)
    if isinstance(data, list):
        assert data[0]["name"] == "Docker Hub"
    else:
        assert data["name"] == "Docker Hub"


@pytest.mark.asyncio
@respx.mock
async def test_container_network_search():
    """container_network_search 应调 POST /containers/network/search 且带分页。"""
    route = respx.post("http://1panel.test/api/v2/containers/network/search").respond(
        json={"code": 200, "message": "", "data": {"items": [{"name": "my-net"}], "total": 1}}
    )
    result = await mcp.call_tool("container_network_search", {"info": "my", "page": 1, "page_size": 20})
    data = parse_tool_result(result)
    assert data["total"] == 1
    assert data["items"][0]["name"] == "my-net"
    assert route.called
    # 验证请求体包含 info 和分页字段
    import json as _json
    sent = _json.loads(route.calls.last.request.content)
    assert sent["info"] == "my"
    assert sent["page"] == 1
    assert sent["pageSize"] == 20


@pytest.mark.asyncio
@respx.mock
async def test_container_docker_status():
    """container_docker_status 应调 GET /containers/docker/status。"""
    respx.get("http://1panel.test/api/v2/containers/docker/status").respond(
        json={"code": 200, "message": "", "data": {"isExist": True, "isActive": True}}
    )
    result = await mcp.call_tool("container_docker_status", {})
    data = parse_tool_result(result)
    assert data["isActive"] is True


@pytest.mark.asyncio
@respx.mock
async def test_container_template_list():
    """container_template_list 应调 GET /containers/template。"""
    respx.get("http://1panel.test/api/v2/containers/template").respond(
        json={"code": 200, "message": "", "data": [{"id": 1, "name": "redis-tpl"}]}
    )
    result = await mcp.call_tool("container_template_list", {})
    data = parse_tool_result(result)
    if isinstance(data, list):
        assert data[0]["name"] == "redis-tpl"
    else:
        assert data["name"] == "redis-tpl"


@pytest.mark.asyncio
@respx.mock
async def test_container_daemonjson_get():
    """container_daemonjson_get 应调 GET /containers/daemonjson。"""
    respx.get("http://1panel.test/api/v2/containers/daemonjson").respond(
        json={"code": 200, "message": "", "data": {"data-root": "/var/lib/docker"}}
    )
    result = await mcp.call_tool("container_daemonjson_get", {})
    data = parse_tool_result(result)
    assert data["data-root"] == "/var/lib/docker"


# ---- 新增写工具端到端 ----

@pytest.mark.asyncio
@respx.mock
async def test_container_image_build():
    """container_image_build 应把 from_ 映射为 from 发到 POST /containers/image/build。"""
    import json as _json
    route = respx.post("http://1panel.test/api/v2/containers/image/build").respond(
        json={"code": 200, "message": "", "data": None}
    )
    await mcp.call_tool("container_image_build", {
        "name": "myapp:1.0",
        "from_": "/opt/build/ctx",
        "dockerfile": "Dockerfile",
    })
    assert route.called
    sent = _json.loads(route.calls.last.request.content)
    # Python 保留字 from_ 必须映射成 API 的 from
    assert sent["from"] == "/opt/build/ctx"
    assert sent["name"] == "myapp:1.0"
    assert sent["dockerfile"] == "Dockerfile"


@pytest.mark.asyncio
@respx.mock
async def test_container_repo_create():
    """container_repo_create 应调 POST /containers/repo。"""
    respx.post("http://1panel.test/api/v2/containers/repo").respond(
        json={"code": 200, "message": "", "data": None}
    )
    await mcp.call_tool("container_repo_create", {
        "name": "harbor", "download_url": "https://harbor.local", "auth": True,
        "username": "u", "password": "p",
    })
    # 200 即通过


@pytest.mark.asyncio
@respx.mock
async def test_container_compose_create():
    """container_compose_create 应调 POST /containers/compose。"""
    respx.post("http://1panel.test/api/v2/containers/compose").respond(
        json={"code": 200, "message": "", "data": None}
    )
    await mcp.call_tool("container_compose_create", {
        "name": "web-stack", "source": "edit", "file": "services:\n  web:\n    image: nginx",
    })


@pytest.mark.asyncio
@respx.mock
async def test_container_commit():
    """container_commit 应调 POST /containers/commit。"""
    respx.post("http://1panel.test/api/v2/containers/commit").respond(
        json={"code": 200, "message": "", "data": None}
    )
    await mcp.call_tool("container_commit", {
        "container_id": "abc123", "new_image_name": "myimg:v1",
    })


# ---- 新增高危工具安全校验（confirm）----

@pytest.mark.asyncio
async def test_container_prune_requires_confirm():
    """container_prune 不传 confirm=true 应拒绝（不发起请求）。"""
    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/containers/prune")
        with pytest.raises(Exception):
            await mcp.call_tool("container_prune", {"prune_type": "container", "confirm": False})
        assert not route.called


@pytest.mark.asyncio
@respx.mock
async def test_container_prune_with_confirm_calls_api():
    """container_prune 传 confirm=true 应真正调用 API。"""
    respx.post("http://1panel.test/api/v2/containers/prune").respond(
        json={"code": 200, "message": "", "data": None}
    )
    await mcp.call_tool("container_prune", {"prune_type": "image", "confirm": True})


@pytest.mark.asyncio
async def test_container_network_delete_requires_confirm():
    """container_network_delete 不传 confirm=true 应拒绝。"""
    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/containers/network/del")
        with pytest.raises(Exception):
            await mcp.call_tool("container_network_delete", {"names": ["n1"], "confirm": False})
        assert not route.called


@pytest.mark.asyncio
async def test_container_template_delete_requires_confirm():
    """container_template_delete 不传 confirm=true 应拒绝。"""
    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/containers/template/del")
        with pytest.raises(Exception):
            await mcp.call_tool("container_template_delete", {"names": ["t1"], "confirm": False})
        assert not route.called


@pytest.mark.asyncio
async def test_container_compose_operate_delete_requires_confirm():
    """container_compose_operate 的 delete 操作不传 confirm 应拒绝。"""
    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/containers/compose/operate")
        with pytest.raises(Exception):
            await mcp.call_tool("container_compose_operate", {
                "name": "stack", "operation": "delete", "confirm": False,
            })
        assert not route.called


# ---- 新增写工具的只读模式安全校验 ----

@pytest.mark.asyncio
async def test_new_write_ops_rejected_in_readonly_mode(monkeypatch):
    """只读模式下新增写工具（docker_operate/daemonjson_update）应被拒绝。"""
    monkeypatch.setenv("PANEL_READONLY", "true")
    get_settings.cache_clear()
    assert get_settings().panel_readonly is True

    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/containers/docker/operate")
        with pytest.raises(Exception) as exc_info:
            await mcp.call_tool("container_docker_operate", {"operation": "restart"})
        assert "只读模式" in str(exc_info.value)
        assert not route.called

    monkeypatch.setenv("PANEL_READONLY", "false")
    get_settings.cache_clear()


# ====================================================================
# 容器创建 / 配置更新（container_create / container_update）
# ====================================================================

@pytest.mark.asyncio
@respx.mock
async def test_container_create_maps_fields():
    """container_create 应解析端口/卷/hosts 字符串并映射为 dto.ContainerOperate 字段。"""
    import json as _json
    route = respx.post("http://1panel.test/api/v2/containers").respond(
        json={"code": 200, "message": "", "data": None}
    )
    await mcp.call_tool("container_create", {
        "name": "web", "image": "nginx:1.27",
        "ports": ["127.0.0.1:8080:80/udp", "443:443"],
        "volumes": ["mydata:/app/data", "/opt/x:/x:ro"],
        "env": ["A=1"],
        "network": "bridge",
        "restart_policy": "unless-stopped",
        "extra_hosts": ["db:192.168.1.10"],
    })
    sent = _json.loads(route.calls.last.request.content)
    assert sent["name"] == "web"
    assert sent["image"] == "nginx:1.27"
    assert sent["restartPolicy"] == "unless-stopped"
    assert sent["exposedPorts"] == [
        {"hostIP": "127.0.0.1", "hostPort": "8080", "containerPort": "80", "protocol": "udp"},
        {"hostIP": "", "hostPort": "443", "containerPort": "443", "protocol": "tcp"},
    ]
    assert sent["volumes"] == [
        {"type": "volume", "sourceDir": "mydata", "containerDir": "/app/data", "mode": "rw", "shared": ""},
        {"type": "bind", "sourceDir": "/opt/x", "containerDir": "/x", "mode": "ro", "shared": ""},
    ]
    assert sent["env"] == ["A=1"]
    assert sent["networks"] == [{"network": "bridge", "ipv4": "", "ipv6": ""}]
    assert sent["extraHosts"] == [{"hostname": "db", "ip": "192.168.1.10"}]


@pytest.mark.asyncio
async def test_container_create_invalid_port_rejected():
    """端口格式非法应直接报错且不发请求。"""
    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/containers")
        with pytest.raises(Exception):
            await mcp.call_tool("container_create", {
                "name": "web", "image": "nginx", "ports": ["abc"],
            })
        assert not route.called


@pytest.mark.asyncio
async def test_container_create_rejected_in_readonly_mode(monkeypatch):
    """只读模式下 container_create 应被拒绝。"""
    monkeypatch.setenv("PANEL_READONLY", "true")
    get_settings.cache_clear()
    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/containers")
        with pytest.raises(Exception) as exc_info:
            await mcp.call_tool("container_create", {"name": "web", "image": "nginx"})
        assert "只读模式" in str(exc_info.value)
        assert not route.called
    monkeypatch.setenv("PANEL_READONLY", "false")
    get_settings.cache_clear()


@pytest.mark.asyncio
@respx.mock
async def test_container_update_merges_with_current_config():
    """container_update 应以 /containers/info 为基底打增量：改 env 不丢卷/端口。"""
    import json as _json
    base = {
        "name": "meituan-coupon",
        "image": "dockercom110/meituan-coupon-assistant:latest",
        "env": ["ACCESS_CODE=old", "B=2"],
        "exposedPorts": [
            {"hostIP": "", "hostPort": "3000", "containerPort": "3000", "protocol": "tcp"}
        ],
        "volumes": [
            {"type": "volume", "sourceDir": "meituan-data", "containerDir": "/app/data",
             "mode": "rw", "shared": ""}
        ],
        "restartPolicy": "unless-stopped",
        "networks": [{"network": "bridge", "ipv4": "", "ipv6": ""}],
    }
    respx.post("http://1panel.test/api/v2/containers/info").respond(
        json={"code": 200, "message": "", "data": base}
    )
    update_route = respx.post("http://1panel.test/api/v2/containers/update").respond(
        json={"code": 200, "message": "", "data": None}
    )
    await mcp.call_tool("container_update", {
        "name": "meituan-coupon",
        "env_add": ["B=3", "NEW=1"],
        "env_remove": ["ACCESS_CODE"],
    })
    sent = _json.loads(update_route.calls.last.request.content)
    assert sent["env"] == ["B=3", "NEW=1"]
    # 未显式传入的配置全部沿用
    assert sent["image"] == "dockercom110/meituan-coupon-assistant:latest"
    assert sent["volumes"] == base["volumes"]
    assert sent["exposedPorts"] == base["exposedPorts"]
    assert sent["restartPolicy"] == "unless-stopped"


@pytest.mark.asyncio
@respx.mock
async def test_container_update_replaces_image_and_ports():
    """container_update 支持换镜像与整体替换端口。"""
    import json as _json
    respx.post("http://1panel.test/api/v2/containers/info").respond(
        json={"code": 200, "message": "", "data": {
            "name": "web", "image": "nginx:1.25",
            "exposedPorts": [
                {"hostIP": "", "hostPort": "80", "containerPort": "80", "protocol": "tcp"}
            ],
            "volumes": [], "env": [],
        }}
    )
    update_route = respx.post("http://1panel.test/api/v2/containers/update").respond(
        json={"code": 200, "message": "", "data": None}
    )
    await mcp.call_tool("container_update", {
        "name": "web", "image": "nginx:1.27", "ports": ["8080:80"],
    })
    sent = _json.loads(update_route.calls.last.request.content)
    assert sent["image"] == "nginx:1.27"
    assert sent["exposedPorts"] == [
        {"hostIP": "", "hostPort": "8080", "containerPort": "80", "protocol": "tcp"}
    ]


@pytest.mark.asyncio
async def test_container_update_aborts_when_info_unavailable():
    """/containers/info 异常时应放弃更新（不能用不完整配置重建容器）。"""
    with respx.mock:
        respx.post("http://1panel.test/api/v2/containers/info").respond(
            json={"code": 200, "message": "", "data": None}
        )
        update_route = respx.post("http://1panel.test/api/v2/containers/update")
        with pytest.raises(Exception):
            await mcp.call_tool("container_update", {"name": "ghost", "image": "nginx:2"})
        assert not update_route.called


@pytest.mark.asyncio
async def test_container_update_rejected_in_readonly_mode(monkeypatch):
    """只读模式下 container_update 应被拒绝（连 info 都不发）。"""
    monkeypatch.setenv("PANEL_READONLY", "true")
    get_settings.cache_clear()
    with respx.mock:
        info_route = respx.post("http://1panel.test/api/v2/containers/info")
        with pytest.raises(Exception) as exc_info:
            await mcp.call_tool("container_update", {"name": "web"})
        assert "只读模式" in str(exc_info.value)
        assert not info_route.called
    monkeypatch.setenv("PANEL_READONLY", "false")
    get_settings.cache_clear()
