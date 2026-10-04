"""容器管理模块（对应 openapi.json 的 Container / Container Image / Container Network /
Container Volume / Container Compose 等 tag，约 60 个端点）。

这是全功能 MCP 的**实现范式模板**。后续模块照此风格写：
1. 工具名：<module>_<action>（container_search / container_start / ...）
2. description：结构化，[模块] 开头，写操作加 ⚠️，便于 mcphub 向量搜索召回
3. 入参用 Annotated[T, Field(description=...)]，复杂入参用 models/<module>.py 的 Pydantic 模型
4. handler 用 `await get_client()` 拿共享客户端，调 .search() / .post() / .get()
5. 写操作开头调 require_write()，高危操作加 confirm 参数
6. docstring 的 Args 段补充参数语义（FastMCP 会解析进 inputSchema）

接口来源：references/openapi.json 的 /containers/* 路径，basePath /api/v2。
"""

from __future__ import annotations

import re
from typing import Annotated, Literal, Optional

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..client import get_client
from ..safety import require_write


# ---- 分页查询 ----

ContainerState = Literal[
    "all", "created", "running", "paused",
    "restarting", "removing", "exited", "dead",
]
ContainerOrderBy = Literal["name", "createdAt", "state"]

# 端口号或端口范围（如 80 / 3000-3005）
_PORT_RE = re.compile(r"^\d+(-\d+)?$")


def register(mcp: FastMCP) -> None:

    # ---- 字符串参数 → dto 结构的解析器（create/update 共用）----

    def _parse_port(spec: str) -> dict:
        """'127.0.0.1:8080:80/udp' / '8080:80' / '80' → PortHelper 结构。"""
        s = spec.strip()
        if not s:
            raise ValueError("端口映射不能为空字符串")
        protocol = "tcp"
        if "/" in s:
            s, proto = s.rsplit("/", 1)
            protocol = proto.lower()
            if protocol not in ("tcp", "udp", "sctp"):
                raise ValueError(f"端口协议非法（支持 tcp/udp/sctp）: {spec}")
        parts = s.split(":")
        if len(parts) == 1:
            host_ip, host_port, container_port = "", "", parts[0]
        elif len(parts) == 2:
            host_ip, host_port, container_port = "", parts[0], parts[1]
        elif len(parts) == 3:
            host_ip, host_port, container_port = parts
        else:
            raise ValueError(
                f"端口映射格式非法: {spec}，应为 [hostIP:]hostPort:containerPort[/protocol]"
            )
        for p in (host_port, container_port):
            if not _PORT_RE.match(p):
                raise ValueError(f"端口号非法（应为数字或范围）: {spec}")
        return {
            "hostIP": host_ip, "hostPort": host_port,
            "containerPort": container_port, "protocol": protocol,
        }

    def _parse_volume(spec: str) -> dict:
        """'meituan-data:/app/data' / '/opt/x:/app/y:ro' → VolumeHelper 结构。"""
        s = spec.strip()
        if not s:
            raise ValueError("卷挂载不能为空字符串")
        parts = s.split(":")
        if len(parts) == 2:
            source, container_dir, mode = parts[0], parts[1], "rw"
        elif len(parts) == 3:
            source, container_dir, mode = parts
        else:
            raise ValueError(f"卷挂载格式非法: {spec}，应为 源:容器路径[:rw|ro]")
        return {
            "type": "bind" if source.startswith("/") else "volume",
            "sourceDir": source, "containerDir": container_dir,
            "mode": mode or "rw", "shared": "",
        }

    def _parse_extra_host(spec: str) -> dict:
        """'hostname:192.168.1.1' → ExtraHost 结构。"""
        host, sep, ip = spec.strip().partition(":")
        if not sep or not host or not ip:
            raise ValueError(f"extraHosts 格式非法: {spec}，应为 主机名:IP")
        return {"hostname": host, "ip": ip}

    @mcp.tool()
    async def container_search(
        name: Annotated[Optional[str], Field(description="容器名模糊匹配，留空返回全部")] = None,
        state: Annotated[ContainerState, Field(description="按状态过滤，默认 all")] = "all",
        page: Annotated[int, Field(ge=1, description="页码")] = 1,
        page_size: Annotated[int, Field(ge=1, le=500, description="每页数量")] = 100,
        order_by: Annotated[ContainerOrderBy, Field(description="排序字段")] = "createdAt",
        order: Annotated[Literal["ascending", "descending"], Field(description="排序方向")] = "descending",
    ) -> dict:
        """[容器] 列出或搜索 Docker 容器。读操作。

        1Panel 的容器分页查询接口，支持按名称、状态过滤。对应
        POST /containers/search。返回分页容器列表（含名称、状态、镜像、端口等）。

        Args:
            name: 容器名模糊匹配，留空返回全部。
            state: 按运行状态过滤，常用 running/exited，all 表示不过滤。
            page: 页码，从 1 开始。
            page_size: 每页数量，上限 500。
            order_by: 排序字段：name/createdAt/state。
            order: 排序方向：ascending/descending。
        """
        client = await get_client()
        body = {
            "page": page,
            "pageSize": page_size,
            "orderBy": order_by,
            "order": order,
            "state": state,
            "name": name or "",
            "filters": "",
            "excludeAppStore": False,
        }
        return await client.post("/containers/search", body)

    @mcp.tool()
    async def container_operate(
        names: Annotated[list[str], Field(description="容器名称列表，支持批量操作")],
        operation: Annotated[
            Literal["start", "stop", "restart", "kill", "pause", "unpause", "remove"],
            Field(description="操作类型"),
        ],
        confirm: Annotated[bool, Field(description="高危操作二次确认，必须传 true 才执行")] = False,
    ) -> dict:
        """⚠️写操作 [容器] 对容器执行生命周期操作（启动/停止/重启/暂停/删除）。

        批量操作容器。对应 POST /containers/operate。
        kill 和 remove 为高危操作，必须显式传 confirm=true。

        Args:
            names: 容器名称列表，1Panel 按名称（而非 ID）操作。
            operation: start 启动 / stop 停止 / restart 重启 / kill 强制停止 /
                pause 暂停 / unpause 恢复 / remove 删除。
            confirm: kill 和 remove 必须传 true，否则拒绝执行。
        """
        require_write()
        if operation in ("kill", "remove") and not confirm:
            raise ValueError(
                f"高危操作 {operation} 必须显式传 confirm=true 才能执行。"
            )
        client = await get_client()
        return await client.post("/containers/operate", {
            "names": names,
            "operation": operation,
        })

    @mcp.tool()
    async def container_start(
        name: Annotated[str, Field(description="容器名称")],
    ) -> dict:
        """⚠️写操作 [容器] 启动容器。

        container_operate 的便捷封装，单个容器启动。对应 POST /containers/operate
        with operation=start。

        Args:
            name: 容器名称。
        """
        require_write()
        client = await get_client()
        return await client.post("/containers/operate", {
            "names": [name], "operation": "start",
        })

    @mcp.tool()
    async def container_stop(
        name: Annotated[str, Field(description="容器名称")],
    ) -> dict:
        """⚠️写操作 [容器] 停止容器。

        单个容器停止。对应 POST /containers/operate with operation=stop。

        Args:
            name: 容器名称。
        """
        require_write()
        client = await get_client()
        return await client.post("/containers/operate", {
            "names": [name], "operation": "stop",
        })

    @mcp.tool()
    async def container_restart(
        name: Annotated[str, Field(description="容器名称")],
    ) -> dict:
        """⚠️写操作 [容器] 重启容器。

        单个容器重启。对应 POST /containers/operate with operation=restart。

        Args:
            name: 容器名称。
        """
        require_write()
        client = await get_client()
        return await client.post("/containers/operate", {
            "names": [name], "operation": "restart",
        })

    @mcp.tool()
    async def container_remove(
        name: Annotated[str, Field(description="容器名称")],
        confirm: Annotated[bool, Field(description="删除是高危操作，必须传 true")] = False,
    ) -> dict:
        """⚠️高危 [容器] 删除容器。

        删除指定容器，不可恢复。对应 POST /containers/operate with operation=remove。
        必须显式传 confirm=true 才执行。

        Args:
            name: 容器名称。
            confirm: 必须为 true 才执行删除。
        """
        require_write()
        if not confirm:
            raise ValueError("删除容器是高危操作，必须显式传 confirm=true。")
        client = await get_client()
        return await client.post("/containers/operate", {
            "names": [name], "operation": "remove",
        })

    @mcp.tool()
    async def container_inspect(
        container_id: Annotated[str, Field(description="容器 ID")],
        detail: Annotated[Optional[str], Field(description="额外详情类型，可空")] = None,
    ) -> dict:
        """[容器] 查看容器详细信息（docker inspect 等价）。

        返回容器的完整 inspect JSON（网络、挂载、环境变量、启动配置等）。
        对应 POST /containers/inspect with type=container。

        Args:
            container_id: 容器 ID。
            detail: 额外详情类型，一般留空。
        """
        client = await get_client()
        return await client.post("/containers/inspect", {
            "id": container_id,
            "type": "container",
            "detail": detail or "",
        })

    @mcp.tool()
    async def container_rename(
        name: Annotated[str, Field(description="当前容器名")],
        new_name: Annotated[str, Field(description="新容器名")],
    ) -> dict:
        """⚠️写操作 [容器] 重命名容器。

        修改容器名称。对应 POST /containers/rename。

        Args:
            name: 当前容器名。
            new_name: 新容器名。
        """
        require_write()
        client = await get_client()
        return await client.post("/containers/rename", {
            "name": name, "newName": new_name,
        })

    @mcp.tool()
    async def container_stats(
        container_id: Annotated[str, Field(description="容器 ID")],
    ) -> dict:
        """[容器] 获取容器资源使用统计（CPU/内存/网络 IO）。

        对应 POST /containers/item/stats。

        Args:
            container_id: 容器 ID。
        """
        client = await get_client()
        return await client.post("/containers/item/stats", {"id": container_id})

    @mcp.tool()
    async def container_log_search(
        container_id: Annotated[str, Field(description="容器 ID")],
        page: Annotated[int, Field(ge=1)] = 1,
        page_size: Annotated[int, Field(ge=1, le=500)] = 100,
    ) -> dict:
        """[容器] 查询容器操作日志。

        分页返回该容器的操作记录。对应 GET /containers/search/log。

        Args:
            container_id: 容器 ID。
            page: 页码。
            page_size: 每页数量。
        """
        client = await get_client()
        return await client.get("/containers/search/log", params={
            "id": container_id, "page": page, "pageSize": page_size,
        })

    # ---- 容器镜像管理 ----

    @mcp.tool()
    async def container_image_list() -> dict:
        """[镜像] 列出本地 Docker 镜像。读操作。

        返回所有本地镜像及其 tag、大小、创建时间。对应 GET /containers/image。
        """
        client = await get_client()
        return await client.get("/containers/image")

    @mcp.tool()
    async def container_image_pull(
        repo: Annotated[str, Field(description="镜像名，如 nginx:latest 或 docker.io/library/nginx:latest")],
    ) -> dict:
        """⚠️写操作 [镜像] 拉取镜像。

        从仓库拉取镜像到本地。对应 POST /containers/image/pull。

        Args:
            repo: 完整镜像名（含 tag）。
        """
        require_write()
        client = await get_client()
        return await client.post("/containers/image/pull", {"repoName": repo})

    @mcp.tool()
    async def container_image_remove(
        image_id: Annotated[str, Field(description="镜像 ID")],
        confirm: Annotated[bool, Field(description="删除是高危操作，必须传 true")] = False,
    ) -> dict:
        """⚠️高危 [镜像] 删除本地镜像。

        删除指定镜像，被容器引用的镜像无法删除。对应 POST /containers/image/remove。
        必须显式传 confirm=true。

        Args:
            image_id: 镜像 ID。
            confirm: 必须为 true。
        """
        require_write()
        if not confirm:
            raise ValueError("删除镜像是高危操作，必须显式传 confirm=true。")
        client = await get_client()
        return await client.post("/containers/image/remove", {"imageID": image_id})

    # ---- Compose 编排 ----

    @mcp.tool()
    async def container_compose_search(
        page: Annotated[int, Field(ge=1)] = 1,
        page_size: Annotated[int, Field(ge=1, le=500)] = 100,
    ) -> dict:
        """[编排] 列出 docker-compose 编排。读操作。

        分页返回所有 compose 编排。对应 POST /containers/compose/search。

        Args:
            page: 页码。
            page_size: 每页数量。
        """
        client = await get_client()
        return await client.search("/containers/compose/search", page=page, page_size=page_size)

    # ---- 镜像进阶操作 ----

    @mcp.tool()
    async def container_image_search(
        name: Annotated[Optional[str], Field(description="镜像名/标签模糊匹配，留空返回全部")] = None,
        page: Annotated[int, Field(ge=1, description="页码")] = 1,
        page_size: Annotated[int, Field(ge=1, le=500, description="每页数量")] = 100,
        order_by: Annotated[Literal["size", "tags", "createdAt", "isUsed"], Field(description="排序字段")] = "createdAt",
        order: Annotated[Literal["null", "ascending", "descending"], Field(description="排序方向，null 表示不排序")] = "descending",
    ) -> dict:
        """[镜像] 分页搜索本地镜像（含使用状态/大小排序）。读操作。

        对应 POST /containers/image/search，返回分页的本地镜像列表（含是否被容器
        引用、大小、创建时间等），可按 size/tags/createdAt/isUsed 排序。

        Args:
            name: 镜像名/标签模糊匹配，留空返回全部。
            page: 页码，从 1 开始。
            page_size: 每页数量，上限 500。
            order_by: 排序字段：size/tags/createdAt/isUsed。
            order: 排序方向：null/ascending/descending。
        """
        client = await get_client()
        body = {
            "name": name or "",
            "page": page,
            "pageSize": page_size,
            "orderBy": order_by,
            "order": order,
        }
        return await client.post("/containers/image/search", body)

    @mcp.tool()
    async def container_image_build(
        name: Annotated[str, Field(description="构建产物镜像名，如 myapp:latest")],
        from_: Annotated[str, Field(description="构建来源，本地路径如 /opt/1panel/docker/compose/test，alias `from`")],
        dockerfile: Annotated[str, Field(description="Dockerfile 名（相对 from 的文件名）")],
        tags: Annotated[Optional[list[str]], Field(description="额外 tag 列表")] = None,
        args: Annotated[Optional[list[str]], Field(description="构建参数键值对列表，如 ['HTTP_PROXY=...']")] = None,
    ) -> dict:
        """⚠️写操作 [镜像] 从 Dockerfile 构建镜像。

        对应 POST /containers/image/build。任务异步执行，返回 taskID。

        Args:
            name: 构建产物的镜像名（含 tag）。
            from_: 构建上下文路径（构建目录的绝对路径）。
            dockerfile: Dockerfile 文件名（相对 from）。
            tags: 额外 tag 列表（可选）。
            args: 构建参数（可选）。
        """
        require_write()
        client = await get_client()
        return await client.post("/containers/image/build", {
            "name": name, "from": from_, "dockerfile": dockerfile,
            "tags": tags or [], "args": args or [],
        })

    @mcp.tool()
    async def container_image_load(
        paths: Annotated[list[str], Field(description="待导入的镜像 tar 包路径列表")],
    ) -> dict:
        """⚠️写操作 [镜像] 从 tar 包导入镜像（docker load）。

        对应 POST /containers/image/load。

        Args:
            paths: tar 文件绝对路径列表。
        """
        require_write()
        client = await get_client()
        return await client.post("/containers/image/load", {"paths": paths})

    @mcp.tool()
    async def container_image_push(
        name: Annotated[str, Field(description="本地镜像名（含 tag）")],
        repo_id: Annotated[int, Field(description="目标镜像仓库 ID（见 container_repo_list）")],
        tag_name: Annotated[str, Field(description="推送后的目标 tag")],
    ) -> dict:
        """⚠️写操作 [镜像] 推送镜像到镜像仓库（docker push）。

        对应 POST /containers/image/push。需先在 1Panel 配置镜像仓库（容器-仓库）。

        Args:
            name: 本地镜像名（含 tag）。
            repo_id: 目标镜像仓库 ID。
            tag_name: 推送后的 tag 名。
        """
        require_write()
        client = await get_client()
        return await client.post("/containers/image/push", {
            "name": name, "repoID": repo_id, "tagName": tag_name,
        })

    @mcp.tool()
    async def container_image_save(
        name: Annotated[str, Field(description="待导出的镜像名（含 tag）")],
        tag_name: Annotated[str, Field(description="镜像 tag")],
        path: Annotated[str, Field(description="导出 tar 文件的保存路径")],
    ) -> dict:
        """⚠️写操作 [镜像] 导出镜像为 tar 包（docker save）。

        对应 POST /containers/image/save。

        Args:
            name: 待导出的镜像名（含 tag）。
            tag_name: 镜像 tag。
            path: tar 文件保存路径。
        """
        require_write()
        client = await get_client()
        return await client.post("/containers/image/save", {
            "name": name, "tagName": tag_name, "path": path,
        })

    @mcp.tool()
    async def container_image_tag(
        source_id: Annotated[str, Field(description="源镜像 ID")],
        tags: Annotated[list[str], Field(description="目标 tag 列表，如 ['myrepo/app:v1', 'myrepo/app:latest']")],
    ) -> dict:
        """⚠️写操作 [镜像] 给镜像打新 tag（docker tag）。

        对应 POST /containers/image/tag。批量给同一源镜像打多个 tag。

        Args:
            source_id: 源镜像 ID。
            tags: 目标 tag 列表。
        """
        require_write()
        client = await get_client()
        return await client.post("/containers/image/tag", {
            "sourceID": source_id, "tags": tags,
        })

    # ---- 镜像仓库（Image Repo）管理 ----

    @mcp.tool()
    async def container_repo_list() -> dict:
        """[仓库] 列出已配置的镜像仓库。读操作。

        对应 GET /containers/repo。返回所有镜像仓库（Docker Hub / 私有 registry 等），
        仅含 id/name/downloadUrl（不含密码）。

        Returns:
            镜像仓库列表。
        """
        client = await get_client()
        return await client.get("/containers/repo")

    @mcp.tool()
    async def container_repo_search(
        info: Annotated[Optional[str], Field(description="仓库名模糊匹配，留空返回全部")] = None,
        page: Annotated[int, Field(ge=1, description="页码")] = 1,
        page_size: Annotated[int, Field(ge=1, le=500, description="每页数量")] = 100,
    ) -> dict:
        """[仓库] 分页搜索镜像仓库。读操作。

        对应 POST /containers/repo/search。

        Args:
            info: 仓库名模糊匹配，留空返回全部。
            page: 页码。
            page_size: 每页数量。
        """
        client = await get_client()
        return await client.search(
            "/containers/repo/search",
            filters={"info": info or ""},
            page=page, page_size=page_size,
        )

    @mcp.tool()
    async def container_repo_create(
        name: Annotated[str, Field(description="仓库名（唯一）")],
        download_url: Annotated[str, Field(description="仓库下载地址，如 https://registry-1.docker.io")],
        protocol: Annotated[str, Field(description="协议，如 https")] = "https",
        auth: Annotated[bool, Field(description="是否需要鉴权")] = False,
        username: Annotated[Optional[str], Field(description="鉴权用户名")] = None,
        password: Annotated[Optional[str], Field(description="鉴权密码")] = None,
    ) -> dict:
        """⚠️写操作 [仓库] 新增镜像仓库配置。

        对应 POST /containers/repo。新增后可用于 image pull/push。

        Args:
            name: 仓库名。
            download_url: 仓库下载地址。
            protocol: 协议（https/http）。
            auth: 是否启用鉴权。
            username: 鉴权用户名（auth=true 时必填）。
            password: 鉴权密码（auth=true 时必填）。
        """
        require_write()
        client = await get_client()
        body: dict = {
            "name": name, "downloadUrl": download_url, "protocol": protocol,
            "auth": auth, "username": username or "", "password": password or "",
        }
        return await client.post("/containers/repo", body)

    @mcp.tool()
    async def container_repo_update(
        repo_id: Annotated[int, Field(description="仓库 ID")],
        name: Annotated[Optional[str], Field(description="仓库名")] = None,
        download_url: Annotated[Optional[str], Field(description="仓库下载地址")] = None,
        protocol: Annotated[Optional[str], Field(description="协议")] = None,
        auth: Annotated[Optional[bool], Field(description="是否启用鉴权")] = None,
        username: Annotated[Optional[str], Field(description="鉴权用户名")] = None,
        password: Annotated[Optional[str], Field(description="鉴权密码")] = None,
    ) -> dict:
        """⚠️写操作 [仓库] 更新镜像仓库配置。

        对应 POST /containers/repo/update。

        Args:
            repo_id: 仓库 ID。
            name: 仓库名（可空表示不改）。
            download_url: 仓库下载地址（可空）。
            protocol: 协议（可空）。
            auth: 是否启用鉴权（可空）。
            username: 鉴权用户名（可空）。
            password: 鉴权密码（可空）。
        """
        require_write()
        client = await get_client()
        body: dict = {"id": repo_id}
        if name is not None:
            body["name"] = name
        if download_url is not None:
            body["downloadUrl"] = download_url
        if protocol is not None:
            body["protocol"] = protocol
        if auth is not None:
            body["auth"] = auth
        if username is not None:
            body["username"] = username
        if password is not None:
            body["password"] = password
        return await client.post("/containers/repo/update", body)

    @mcp.tool()
    async def container_repo_delete(
        repo_id: Annotated[int, Field(description="仓库 ID")],
        confirm: Annotated[bool, Field(description="删除是高危操作，必须传 true")] = False,
    ) -> dict:
        """⚠️高危 [仓库] 删除镜像仓库配置。

        对应 POST /containers/repo/del。必须显式传 confirm=true。仅删除 1Panel
        中的仓库配置，不影响已拉取的本地镜像。

        Args:
            repo_id: 仓库 ID。
            confirm: 必须为 true 才执行。
        """
        require_write()
        if not confirm:
            raise ValueError("删除镜像是高危操作，必须显式传 confirm=true。")
        client = await get_client()
        return await client.post("/containers/repo/del", {"id": repo_id})

    @mcp.tool()
    async def container_repo_status(
        repo_id: Annotated[int, Field(description="仓库 ID")],
    ) -> dict:
        """[仓库] 检测镜像仓库连通性。读操作。

        对应 POST /containers/repo/status。返回仓库是否可达。

        Args:
            repo_id: 仓库 ID。
        """
        client = await get_client()
        return await client.post("/containers/repo/status", {"id": repo_id})

    # ---- 容器网络（Network）管理 ----

    @mcp.tool()
    async def container_network_list() -> dict:
        """[网络] 列出所有 Docker 网络（用于选择/参考）。读操作。

        对应 GET /containers/network。返回 {option: name} 列表（精简选项，
        便于下拉框）。如需完整网络详情请用 docker inspect。

        Returns:
            网络选项列表。
        """
        client = await get_client()
        return await client.get("/containers/network")

    @mcp.tool()
    async def container_network_search(
        info: Annotated[Optional[str], Field(description="网络名模糊匹配，留空返回全部")] = None,
        page: Annotated[int, Field(ge=1, description="页码")] = 1,
        page_size: Annotated[int, Field(ge=1, le=500, description="每页数量")] = 100,
    ) -> dict:
        """[网络] 分页搜索容器网络。读操作。

        对应 POST /containers/network/search。返回分页的网络详情（驱动、子网、网关等）。

        Args:
            info: 网络名模糊匹配，留空返回全部。
            page: 页码。
            page_size: 每页数量。
        """
        client = await get_client()
        return await client.search(
            "/containers/network/search",
            filters={"info": info or ""},
            page=page, page_size=page_size,
        )

    @mcp.tool()
    async def container_network_create(
        name: Annotated[str, Field(description="网络名")],
        driver: Annotated[str, Field(description="网络驱动，如 bridge / macvlan")] = "bridge",
        subnet: Annotated[Optional[str], Field(description="IPv4 子网 CIDR，如 172.20.0.0/16")] = None,
        gateway: Annotated[Optional[str], Field(description="IPv4 网关")] = None,
        ip_range: Annotated[Optional[str], Field(description="IPv4 地址范围 CIDR")] = None,
        ipv4: Annotated[bool, Field(description="是否启用 IPv4")] = True,
        ipv6: Annotated[bool, Field(description="是否启用 IPv6")] = False,
        subnet_v6: Annotated[Optional[str], Field(description="IPv6 子网 CIDR")] = None,
        gateway_v6: Annotated[Optional[str], Field(description="IPv6 网关")] = None,
        ip_range_v6: Annotated[Optional[str], Field(description="IPv6 地址范围 CIDR")] = None,
        labels: Annotated[Optional[list[str]], Field(description="标签列表，如 ['key=value']")] = None,
        options: Annotated[Optional[list[str]], Field(description="驱动选项列表，如 ['parent=eth0']")] = None,
    ) -> dict:
        """⚠️写操作 [网络] 创建 Docker 网络（docker network create）。

        对应 POST /containers/network。创建自定义网络供容器互联。

        Args:
            name: 网络名。
            driver: 网络驱动，bridge/host/macvlan/overlay。
            subnet: IPv4 子网 CIDR。
            gateway: IPv4 网关。
            ip_range: IPv4 地址范围。
            ipv4: 启用 IPv4。
            ipv6: 启用 IPv6。
            subnet_v6: IPv6 子网 CIDR。
            gateway_v6: IPv6 网关。
            ip_range_v6: IPv6 地址范围。
            labels: 标签列表。
            options: 驱动选项列表。
        """
        require_write()
        client = await get_client()
        body: dict = {"name": name, "driver": driver, "ipv4": ipv4, "ipv6": ipv6}
        if subnet is not None:
            body["subnet"] = subnet
        if gateway is not None:
            body["gateway"] = gateway
        if ip_range is not None:
            body["ipRange"] = ip_range
        if subnet_v6 is not None:
            body["subnetV6"] = subnet_v6
        if gateway_v6 is not None:
            body["gatewayV6"] = gateway_v6
        if ip_range_v6 is not None:
            body["ipRangeV6"] = ip_range_v6
        if labels is not None:
            body["labels"] = labels
        if options is not None:
            body["options"] = options
        return await client.post("/containers/network", body)

    @mcp.tool()
    async def container_network_delete(
        names: Annotated[list[str], Field(description="网络名列表，支持批量删除")],
        force: Annotated[bool, Field(description="是否强制删除")] = False,
        confirm: Annotated[bool, Field(description="删除是高危操作，必须传 true")] = False,
    ) -> dict:
        """⚠️高危 [网络] 删除 Docker 网络（docker network rm）。

        对应 POST /containers/network/del。被容器引用的网络需先断开或 force=true。

        Args:
            names: 网络名列表。
            force: 是否强制删除。
            confirm: 必须为 true 才执行。
        """
        require_write()
        if not confirm:
            raise ValueError("删除网络是高危操作，必须显式传 confirm=true。")
        client = await get_client()
        return await client.post("/containers/network/del", {
            "names": names, "force": force,
        })

    # ---- 容器存储卷（Volume）管理 ----

    @mcp.tool()
    async def container_volume_list() -> dict:
        """[存储卷] 列出所有 Docker 存储卷（用于选择/参考）。读操作。

        对应 GET /containers/volume。返回 {option: name} 精简选项。

        Returns:
            存储卷选项列表。
        """
        client = await get_client()
        return await client.get("/containers/volume")

    @mcp.tool()
    async def container_volume_search(
        info: Annotated[Optional[str], Field(description="卷名模糊匹配，留空返回全部")] = None,
        page: Annotated[int, Field(ge=1, description="页码")] = 1,
        page_size: Annotated[int, Field(ge=1, le=500, description="每页数量")] = 100,
    ) -> dict:
        """[存储卷] 分页搜索存储卷。读操作。

        对应 POST /containers/volume/search。返回分页卷详情（驱动、挂载点、大小）。

        Args:
            info: 卷名模糊匹配，留空返回全部。
            page: 页码。
            page_size: 每页数量。
        """
        client = await get_client()
        return await client.search(
            "/containers/volume/search",
            filters={"info": info or ""},
            page=page, page_size=page_size,
        )

    @mcp.tool()
    async def container_volume_create(
        name: Annotated[str, Field(description="卷名")],
        driver: Annotated[str, Field(description="卷驱动，默认 local")] = "local",
        labels: Annotated[Optional[list[str]], Field(description="标签列表，如 ['key=value']")] = None,
        options: Annotated[Optional[list[str]], Field(description="驱动选项列表，如 ['type=nfs']")] = None,
    ) -> dict:
        """⚠️写操作 [存储卷] 创建 Docker 存储卷（docker volume create）。

        对应 POST /containers/volume。

        Args:
            name: 卷名。
            driver: 卷驱动，默认 local。
            labels: 标签列表。
            options: 驱动选项列表。
        """
        require_write()
        client = await get_client()
        body: dict = {"name": name, "driver": driver}
        if labels is not None:
            body["labels"] = labels
        if options is not None:
            body["options"] = options
        return await client.post("/containers/volume", body)

    @mcp.tool()
    async def container_volume_delete(
        names: Annotated[list[str], Field(description="卷名列表，支持批量删除")],
        force: Annotated[bool, Field(description="是否强制删除")] = False,
        confirm: Annotated[bool, Field(description="删除是高危操作，必须传 true")] = False,
    ) -> dict:
        """⚠️高危 [存储卷] 删除 Docker 存储卷（docker volume rm）。

        对应 POST /containers/volume/del。被容器引用的卷需先断开或 force=true。

        Args:
            names: 卷名列表。
            force: 是否强制删除。
            confirm: 必须为 true 才执行。
        """
        require_write()
        if not confirm:
            raise ValueError("删除存储卷是高危操作，必须显式传 confirm=true。")
        client = await get_client()
        return await client.post("/containers/volume/del", {
            "names": names, "force": force,
        })

    # ---- Compose 编排进阶操作 ----

    @mcp.tool()
    async def container_compose_create(
        name: Annotated[str, Field(description="编排名（唯一）")],
        source: Annotated[Literal["edit", "path", "template"], Field(description="编排来源：edit 直接编辑 yaml / path 指定文件路径 / template 用模板 ID")] = "edit",
        file: Annotated[Optional[str], Field(description="source=edit 时的 docker-compose.yaml 内容")] = None,
        path: Annotated[Optional[str], Field(description="source=path 时的 compose 文件目录绝对路径")] = None,
        template: Annotated[Optional[int], Field(description="source=template 时的模板 ID")] = None,
        env: Annotated[Optional[str], Field(description="环境变量内容，KEY=VALUE 多行")] = None,
        force_pull: Annotated[bool, Field(description="启动时是否强制重新拉取镜像")] = False,
    ) -> dict:
        """⚠️写操作 [编排] 创建并启动 docker-compose 编排。

        对应 POST /containers/compose。根据 source 取不同的参数：
        - edit：直接提供 file（compose yaml 文本）
        - path：提供宿主机上已存在的 compose 目录 path
        - template：提供 1Panel 模板 ID template

        Args:
            name: 编排名（唯一）。
            source: 编排来源。
            file: source=edit 时的 compose yaml 文本。
            path: source=path 时的目录绝对路径。
            template: source=template 时的模板 ID。
            env: 环境变量（多行 KEY=VALUE）。
            force_pull: 启动时强制重新拉取镜像。
        """
        require_write()
        client = await get_client()
        body: dict = {"name": name, "from": source, "forcePull": force_pull}
        if file is not None:
            body["file"] = file
        if path is not None:
            body["path"] = path
        if template is not None:
            body["template"] = template
        if env is not None:
            body["env"] = env
        return await client.post("/containers/compose", body)

    @mcp.tool()
    async def container_compose_operate(
        name: Annotated[str, Field(description="编排名")],
        operation: Annotated[
            Literal["up", "start", "restart", "stop", "down", "delete"],
            Field(description="操作类型"),
        ],
        path: Annotated[Optional[str], Field(description="compose 文件目录绝对路径")] = None,
        with_file: Annotated[bool, Field(description="delete 时是否同时删除 compose 文件")] = False,
        force: Annotated[bool, Field(description="down/delete 时是否强制")] = False,
        confirm: Annotated[bool, Field(description="delete 是高危操作，必须传 true")] = False,
    ) -> dict:
        """⚠️写操作 [编排] 对 docker-compose 编排执行生命周期操作。

        对应 POST /containers/compose/operate。up/start/restart/stop/down 为常规操作，
        delete 会删除编排及其容器，必须 confirm=true。

        Args:
            name: 编排名。
            operation: up 启动 / start 启动 / restart 重启 / stop 停止 /
                down 停止并删除容器 / delete 删除编排。
            path: compose 文件目录绝对路径。
            with_file: delete 时是否同时删除 compose 文件。
            force: down/delete 时是否强制。
            confirm: delete 操作必须为 true。
        """
        require_write()
        if operation == "delete" and not confirm:
            raise ValueError("delete 编排是高危操作，必须显式传 confirm=true。")
        client = await get_client()
        body: dict = {"name": name, "operation": operation, "withFile": with_file, "force": force}
        if path is not None:
            body["path"] = path
        return await client.post("/containers/compose/operate", body)

    @mcp.tool()
    async def container_compose_update(
        name: Annotated[str, Field(description="编排名")],
        path: Annotated[str, Field(description="compose 文件目录绝对路径")],
        content: Annotated[str, Field(description="新的 compose yaml 文本")],
        env: Annotated[Optional[str], Field(description="环境变量，KEY=VALUE 多行")] = None,
        force_pull: Annotated[bool, Field(description="更新后是否强制重新拉取镜像")] = False,
    ) -> dict:
        """⚠️写操作 [编排] 更新 compose 编排内容并重启。

        对应 POST /containers/compose/update。修改 compose yaml 后重新部署。

        Args:
            name: 编排名。
            path: compose 文件目录绝对路径。
            content: 新的 compose yaml 文本。
            env: 环境变量。
            force_pull: 是否强制重新拉取镜像。
        """
        require_write()
        client = await get_client()
        body: dict = {"name": name, "path": path, "content": content, "forcePull": force_pull}
        if env is not None:
            body["env"] = env
        return await client.post("/containers/compose/update", body)

    @mcp.tool()
    async def container_compose_test(
        name: Annotated[str, Field(description="编排名（仅用于标识）")],
        source: Annotated[Literal["edit", "path", "template"], Field(description="编排来源")] = "edit",
        file: Annotated[Optional[str], Field(description="source=edit 时的 compose yaml 文本")] = None,
        path: Annotated[Optional[str], Field(description="source=path 时的目录绝对路径")] = None,
        template: Annotated[Optional[int], Field(description="source=template 时的模板 ID")] = None,
        env: Annotated[Optional[str], Field(description="环境变量")] = None,
        force_pull: Annotated[bool, Field(description="是否强制拉取镜像")] = False,
    ) -> dict:
        """[编排] 校验 compose 配置（不真正部署）。读操作。

        对应 POST /containers/compose/test。校验 compose yaml 语法与环境变量，
        返回错误信息（如有）。

        Args:
            name: 编排名（仅标识）。
            source: 编排来源。
            file: source=edit 时的 yaml 文本。
            path: source=path 时的目录绝对路径。
            template: source=template 时的模板 ID。
            env: 环境变量。
            force_pull: 是否强制拉取镜像。
        """
        client = await get_client()
        body: dict = {"name": name, "from": source, "forcePull": force_pull}
        if file is not None:
            body["file"] = file
        if path is not None:
            body["path"] = path
        if template is not None:
            body["template"] = template
        if env is not None:
            body["env"] = env
        return await client.post("/containers/compose/test", body)

    @mcp.tool()
    async def container_compose_env(
        path: Annotated[str, Field(description="compose 目录或 .env 文件路径")],
    ) -> dict:
        """[编排] 加载 compose 环境变量。读操作。

        对应 POST /containers/compose/env。解析指定路径下的 .env，返回键值对。

        Args:
            path: compose 目录或 .env 文件路径。
        """
        client = await get_client()
        return await client.post("/containers/compose/env", {"path": path})

    # ---- Compose 模板（Compose-template）管理 ----

    @mcp.tool()
    async def container_template_list() -> dict:
        """[模板] 列出所有 compose 模板。读操作。

        对应 GET /containers/template。返回模板列表（id/name/content/description）。

        Returns:
            compose 模板列表。
        """
        client = await get_client()
        return await client.get("/containers/template")

    @mcp.tool()
    async def container_template_search(
        info: Annotated[Optional[str], Field(description="模板名/描述模糊匹配，留空返回全部")] = None,
        page: Annotated[int, Field(ge=1, description="页码")] = 1,
        page_size: Annotated[int, Field(ge=1, le=500, description="每页数量")] = 100,
    ) -> dict:
        """[模板] 分页搜索 compose 模板。读操作。

        对应 POST /containers/template/search。

        Args:
            info: 模板名/描述模糊匹配，留空返回全部。
            page: 页码。
            page_size: 每页数量。
        """
        client = await get_client()
        return await client.search(
            "/containers/template/search",
            filters={"info": info or ""},
            page=page, page_size=page_size,
        )

    @mcp.tool()
    async def container_template_create(
        name: Annotated[str, Field(description="模板名（唯一）")],
        content: Annotated[Optional[str], Field(description="compose yaml 文本")] = None,
        description: Annotated[Optional[str], Field(description="模板描述")] = None,
    ) -> dict:
        """⚠️写操作 [模板] 创建 compose 模板。

        对应 POST /containers/template。模板可被 container_compose_create 复用。

        Args:
            name: 模板名。
            content: compose yaml 文本。
            description: 模板描述。
        """
        require_write()
        client = await get_client()
        body: dict = {"name": name}
        if content is not None:
            body["content"] = content
        if description is not None:
            body["description"] = description
        return await client.post("/containers/template", body)

    @mcp.tool()
    async def container_template_update(
        template_id: Annotated[int, Field(description="模板 ID")],
        content: Annotated[Optional[str], Field(description="compose yaml 文本")] = None,
        description: Annotated[Optional[str], Field(description="模板描述")] = None,
    ) -> dict:
        """⚠️写操作 [模板] 更新 compose 模板。

        对应 POST /containers/template/update。

        Args:
            template_id: 模板 ID。
            content: compose yaml 文本。
            description: 模板描述。
        """
        require_write()
        client = await get_client()
        body: dict = {"id": template_id}
        if content is not None:
            body["content"] = content
        if description is not None:
            body["description"] = description
        return await client.post("/containers/template/update", body)

    @mcp.tool()
    async def container_template_delete(
        names: Annotated[list[str], Field(description="模板名列表，支持批量删除")],
        force: Annotated[bool, Field(description="是否强制删除")] = False,
        confirm: Annotated[bool, Field(description="删除是高危操作，必须传 true")] = False,
    ) -> dict:
        """⚠️高危 [模板] 删除 compose 模板。

        对应 POST /containers/template/del。注意入参为模板名（不是 ID）。

        Args:
            names: 模板名列表。
            force: 是否强制删除。
            confirm: 必须为 true 才执行。
        """
        require_write()
        if not confirm:
            raise ValueError("删除模板是高危操作，必须显式传 confirm=true。")
        client = await get_client()
        return await client.post("/containers/template/del", {
            "names": names, "force": force,
        })

    # ---- Docker daemon 管理 ----

    @mcp.tool()
    async def container_docker_status() -> dict:
        """[Docker] 查询 Docker 服务状态。读操作。

        对应 GET /containers/docker/status。返回 Docker 是否安装/运行。

        Returns:
            Docker 服务状态（是否安装、是否运行、版本等）。
        """
        client = await get_client()
        return await client.get("/containers/docker/status")

    @mcp.tool()
    async def container_docker_operate(
        operation: Annotated[
            Literal["start", "restart", "stop"],
            Field(description="操作类型：启动/重启/停止 Docker 服务"),
        ],
    ) -> dict:
        """⚠️写操作 [Docker] 启动/重启/停止 Docker 服务。

        对应 POST /containers/docker/operate。停止 Docker 会停掉所有容器，
        谨慎使用。

        Args:
            operation: start 启动 / restart 重启 / stop 停止 Docker 守护进程。
        """
        require_write()
        client = await get_client()
        return await client.post("/containers/docker/operate", {"operation": operation})

    @mcp.tool()
    async def container_daemonjson_get() -> dict:
        """[Docker] 读取 docker daemon.json 配置（结构化）。读操作。

        对应 GET /containers/daemonjson。返回 1Panel 维护的结构化 daemon 配置。

        Returns:
            结构化的 daemon 配置。
        """
        client = await get_client()
        return await client.get("/containers/daemonjson")

    @mcp.tool()
    async def container_daemonjson_update(
        key: Annotated[str, Field(description="配置项 key，如 registry-mirrors / data-root / log-opts 等")],
        value: Annotated[str, Field(description="配置项 value，JSON 字符串或字符串")],
    ) -> dict:
        """⚠️写操作 [Docker] 更新 daemon.json 单项配置。

        对应 POST /containers/daemonjson/update。修改后需手动重启 Docker 生效。
        value 一般是 JSON 字符串（如数组、对象序列化后）。

        Args:
            key: 配置项 key。
            value: 配置项 value（字符串或 JSON 字符串）。
        """
        require_write()
        client = await get_client()
        return await client.post("/containers/daemonjson/update", {
            "key": key, "value": value,
        })

    @mcp.tool()
    async def container_prune(
        prune_type: Annotated[
            Literal["container", "image", "volume", "network", "buildcache"],
            Field(description="清理对象类型"),
        ],
        with_tag_all: Annotated[bool, Field(description="image 类型时是否清理所有未被引用镜像（含已 tag）")] = False,
        confirm: Annotated[bool, Field(description="清理是高危操作，必须传 true")] = False,
    ) -> dict:
        """⚠️高危 [Docker] 清理未使用的容器/镜像/卷/网络/构建缓存（docker prune）。

        对应 POST /containers/prune。回收磁盘空间，但会删除所有未引用资源，
        不可恢复，必须 confirm=true。

        Args:
            prune_type: container 容器 / image 镜像 / volume 卷 / network 网络 /
                buildcache 构建缓存。
            with_tag_all: image 类型时是否清理所有未引用镜像（含已 tag 的）。
            confirm: 必须为 true 才执行。
        """
        require_write()
        if not confirm:
            raise ValueError("清理资源（prune）是高危操作，必须显式传 confirm=true。")
        client = await get_client()
        return await client.post("/containers/prune", {
            "pruneType": prune_type, "withTagAll": with_tag_all,
        })

    @mcp.tool()
    async def container_commit(
        container_id: Annotated[str, Field(description="源容器 ID")],
        new_image_name: Annotated[Optional[str], Field(description="提交后的镜像名")] = None,
        author: Annotated[Optional[str], Field(description="作者")] = None,
        comment: Annotated[Optional[str], Field(description="提交说明")] = None,
        pause: Annotated[bool, Field(description="提交时是否暂停容器（默认 true）")] = True,
    ) -> dict:
        """⚠️写操作 [容器] 把容器变更提交为新镜像（docker commit）。

        对应 POST /containers/commit。一般用于保存临时调试改动，
        生产环境建议用 Dockerfile 重建。

        Args:
            container_id: 源容器 ID。
            new_image_name: 提交后的镜像名（含 tag）。
            author: 作者。
            comment: 提交说明。
            pause: 提交时是否暂停容器，默认 true。
        """
        require_write()
        client = await get_client()
        body: dict = {"containerID": container_id, "pause": pause}
        if new_image_name is not None:
            body["newImageName"] = new_image_name
        if author is not None:
            body["author"] = author
        if comment is not None:
            body["comment"] = comment
        return await client.post("/containers/commit", body)

    @mcp.tool()
    async def container_upgrade(
        names: Annotated[list[str], Field(description="容器名列表，支持批量升级")],
        image: Annotated[str, Field(description="目标镜像名（含 tag）")],
        force_pull: Annotated[bool, Field(description="是否强制重新拉取镜像")] = False,
    ) -> dict:
        """⚠️写操作 [容器] 升级容器到新镜像版本。

        对应 POST /containers/upgrade。用新镜像重建容器，保留原配置（卷、网络等）。

        Args:
            names: 容器名列表。
            image: 目标镜像名（含 tag）。
            force_pull: 是否强制重新拉取镜像。
        """
        require_write()
        client = await get_client()
        return await client.post("/containers/upgrade", {
            "names": names, "image": image, "forcePull": force_pull,
        })

    @mcp.tool()
    async def container_info(
        name: Annotated[str, Field(description="容器名")],
    ) -> dict:
        """[容器] 加载容器概要信息（1Panel 视图）。读操作。

        对应 POST /containers/info。返回容器名、镜像、端口映射、卷、环境变量等
        结构化信息（与 docker inspect 互补，更贴合 1Panel 展示）。

        Args:
            name: 容器名。
        """
        client = await get_client()
        return await client.post("/containers/info", {"name": name})

    # ---- 容器创建与配置更新（改配置重建）----

    @mcp.tool()
    async def container_create(
        name: Annotated[str, Field(description="容器名（唯一）")],
        image: Annotated[str, Field(description="镜像名（含 tag）")],
        ports: Annotated[Optional[list[str]], Field(description="端口映射列表，格式 [hostIP:]hostPort:containerPort[/protocol]，如 ['8080:80','127.0.0.1:53:53/udp']")] = None,
        volumes: Annotated[Optional[list[str]], Field(description="挂载列表，格式 源:容器路径[:rw|ro]，源为卷名（volume）或绝对路径（bind），如 ['mydata:/app/data','/opt/x:/x:ro']")] = None,
        env: Annotated[Optional[list[str]], Field(description="环境变量列表，KEY=VALUE 格式")] = None,
        network: Annotated[Optional[str], Field(description="接入的 Docker 网络名，留空用默认 bridge")] = None,
        restart_policy: Annotated[Literal["no", "always", "unless-stopped", "on-failure"], Field(description="重启策略")] = "no",
        hostname: Annotated[Optional[str], Field(description="容器主机名")] = None,
        working_dir: Annotated[Optional[str], Field(description="工作目录")] = None,
        user: Annotated[Optional[str], Field(description="运行用户")] = None,
        cmd: Annotated[Optional[list[str]], Field(description="覆盖容器启动命令（argv 列表）")] = None,
        entrypoint: Annotated[Optional[list[str]], Field(description="覆盖入口点")] = None,
        labels: Annotated[Optional[list[str]], Field(description="标签列表，key=value")] = None,
        extra_hosts: Annotated[Optional[list[str]], Field(description="额外 hosts，格式 主机名:IP")] = None,
        privileged: Annotated[bool, Field(description="特权模式")] = False,
        auto_remove: Annotated[bool, Field(description="退出后自动删除（--rm）")] = False,
        publish_all_ports: Annotated[bool, Field(description="暴露镜像声明的全部端口（-P）")] = False,
        tty: Annotated[bool, Field(description="分配 TTY")] = False,
        open_stdin: Annotated[bool, Field(description="保持 STDIN 打开（-i）")] = False,
        force_pull: Annotated[bool, Field(description="创建前强制重新拉取镜像")] = False,
        memory: Annotated[float, Field(ge=0, description="内存上限，字节（0=不限）")] = 0,
        nano_cpus: Annotated[float, Field(ge=0, description="CPU 配额，1 核=1e9（0=不限）")] = 0,
    ) -> dict:
        """⚠️写操作 [容器] 创建并启动一个新容器。

        对应 POST /containers（dto.ContainerOperate）。本地无该镜像且
        force_pull=false 时会创建失败，可先 container_image_pull 或开 force_pull=true。
        创建后用 container_search 确认状态、container_log_search 看启动日志。

        Args:
            name: 容器名（唯一）。
            image: 镜像名（含 tag）。
            ports: 端口映射，[hostIP:]hostPort:containerPort[/protocol]。
            volumes: 挂载，源:容器路径[:rw|ro]，源为卷名（volume）或绝对路径（bind）。
            env: 环境变量 KEY=VALUE 列表。
            network: 网络名，留空使用默认 bridge。
            restart_policy: no / always / unless-stopped / on-failure。
            hostname: 容器主机名。
            working_dir: 工作目录。
            user: 运行用户。
            cmd: 启动命令覆盖。
            entrypoint: 入口点覆盖。
            labels: 标签 key=value 列表。
            extra_hosts: 额外 hosts（主机名:IP）。
            privileged: 特权模式。
            auto_remove: 退出自动删除。
            publish_all_ports: 暴露镜像声明的全部端口。
            tty: 分配 TTY。
            open_stdin: 保持 STDIN 打开。
            force_pull: 创建前强制拉取镜像。
            memory: 内存上限（字节），0 不限。
            nano_cpus: CPU 配额（1 核 = 1e9），0 不限。
        """
        require_write()
        body: dict = {
            "name": name, "image": image,
            "exposedPorts": [_parse_port(p) for p in (ports or [])],
            "volumes": [_parse_volume(v) for v in (volumes or [])],
            "env": list(env or []),
            "labels": list(labels or []),
            "restartPolicy": restart_policy,
            "privileged": privileged,
            "autoRemove": auto_remove,
            "publishAllPorts": publish_all_ports,
            "tty": tty,
            "openStdin": open_stdin,
            "forcePull": force_pull,
            "taskID": "",
        }
        if network:
            body["networks"] = [{"network": network, "ipv4": "", "ipv6": ""}]
        if extra_hosts:
            body["extraHosts"] = [_parse_extra_host(h) for h in extra_hosts]
        if hostname:
            body["hostname"] = hostname
        if working_dir:
            body["workingDir"] = working_dir
        if user:
            body["user"] = user
        if cmd:
            body["cmd"] = list(cmd)
        if entrypoint:
            body["entrypoint"] = list(entrypoint)
        if memory:
            body["memory"] = memory
        if nano_cpus:
            body["nanoCPUs"] = nano_cpus
        client = await get_client()
        return await client.post("/containers", body)

    @mcp.tool()
    async def container_update(
        name: Annotated[str, Field(description="要更新的容器名")],
        image: Annotated[Optional[str], Field(description="改成的新镜像（含 tag），留空沿用当前")] = None,
        env_add: Annotated[Optional[list[str]], Field(description="追加/覆盖的环境变量 KEY=VALUE，同名覆盖旧值")] = None,
        env_remove: Annotated[Optional[list[str]], Field(description="要删除的环境变量 KEY 列表")] = None,
        ports: Annotated[Optional[list[str]], Field(description="端口映射整体替换（格式同 container_create），留空沿用当前")] = None,
        volumes: Annotated[Optional[list[str]], Field(description="挂载整体替换（格式同 container_create），留空沿用当前")] = None,
        network: Annotated[Optional[str], Field(description="改成的新网络名，留空沿用当前")] = None,
        restart_policy: Annotated[Optional[Literal["no", "always", "unless-stopped", "on-failure"]], Field(description="重启策略，留空沿用当前")] = None,
        force_pull: Annotated[Optional[bool], Field(description="更新时是否强制重新拉取镜像")] = None,
    ) -> dict:
        """⚠️写操作 [容器] 修改容器配置并重建（等价改配置后的 docker rm -f + run）。

        对应 POST /containers/update。**会删除旧容器并按新配置重建**（短暂停机，
        卷数据不受影响）。工具自动先读当前配置（POST /containers/info）作为基底，
        只叠加显式传入的增量字段——未传的端口/卷/网络/环境变量等全部沿用，
        避免漏传丢配置。典型用途：给运行中的容器增删环境变量、改重启策略、
        换网络；只换镜像发版请用语义更轻的 container_upgrade。

        Args:
            name: 容器名。
            image: 新镜像（含 tag），留空不改。
            env_add: 追加/覆盖的环境变量 KEY=VALUE。
            env_remove: 删除的环境变量 KEY 列表。
            ports: 端口映射整体替换，留空沿用当前。
            volumes: 挂载整体替换，留空沿用当前。
            network: 新网络名，留空沿用当前。
            restart_policy: 重启策略，留空沿用当前。
            force_pull: 是否强制重新拉取镜像。
        """
        require_write()
        client = await get_client()
        info = await client.post("/containers/info", {"name": name})
        if not isinstance(info, dict) or not info.get("name") or not info.get("image"):
            raise ValueError(
                f"无法加载容器 {name} 的当前配置（/containers/info 返回异常），"
                "已取消更新，以免用不完整配置重建容器。"
            )
        body: dict = dict(info)  # 当前配置作基底，未显式传入的字段全部沿用
        if image:
            body["image"] = image
        if env_add or env_remove:
            merged: dict[str, str] = {}
            for kv in body.get("env") or []:
                if isinstance(kv, str) and "=" in kv:
                    k, v = kv.split("=", 1)
                    merged[k] = v
            for k in env_remove or []:
                merged.pop(k, None)
            for kv in env_add or []:
                if "=" not in kv:
                    raise ValueError(f"env_add 必须是 KEY=VALUE 格式: {kv}")
                k, v = kv.split("=", 1)
                merged[k] = v
            body["env"] = [f"{k}={v}" for k, v in merged.items()]
        if ports is not None:
            body["exposedPorts"] = [_parse_port(p) for p in ports]
        if volumes is not None:
            body["volumes"] = [_parse_volume(v) for v in volumes]
        if network:
            current = {
                n.get("network"): n
                for n in body.get("networks") or [] if isinstance(n, dict)
            }
            prev = current.get(network, {})
            body["networks"] = [{
                "network": network,
                "ipv4": prev.get("ipv4") or "",
                "ipv6": prev.get("ipv6") or "",
            }]
        if restart_policy:
            body["restartPolicy"] = restart_policy
        if force_pull is not None:
            body["forcePull"] = force_pull
        return await client.post("/containers/update", body)

    @mcp.tool()
    async def container_limit() -> dict:
        """[容器] 查询容器限制（数量/资源上限）。读操作。

        对应 GET /containers/limit。

        Returns:
            容器相关限制配置。
        """
        client = await get_client()
        return await client.get("/containers/limit")
