"""应用商店模块（对应 openapi.json 的 App tag，31 个端点）。

覆盖 1Panel 应用商店全部能力：
1. 应用商店搜索与详情：app_search / app_get_by_key / app_detail_* / app_get_detail
2. 已安装应用管理：app_installed_search / app_installed_list / app_installed_info
3. 应用安装与生命周期：app_install / app_operate / app_upgrade / app_uninstall
4. 应用参数与配置：app_params / app_params_update / app_config_update
5. 应用端口与连接信息：app_port / app_port_change / app_connection_info
6. 升级忽略管理：app_ignore_upgrade / app_ignore_cancel / app_ignored_list
7. 应用商店同步与配置：app_sync_local / app_sync_remote / app_store_config(_update)

实现风格与 container.py 一致：
- 工具名 app_<object>_<action>（app_search / app_install / app_uninstall ...）
- description [应用] 开头，写操作加 ⚠️，高危（uninstall/delete）加 confirm
- search 类接口（/apps/search 与 /apps/installed/search）注意：这两个接口
  的请求 schema（request.AppSearch / request.AppInstalledSearch）**没有
  orderBy/order 字段**，仅 page/pageSize 必填，因此不走 client.search，直接
  用 client.post 自行组装 body。

AppInstalledOperate 的 operate 取值（来自 1Panel backend/constant/app.go）：
  start / stop / restart / delete / sync / backup / update / rebuild / upgrade / reload

接口来源：references/openapi.json 的 /apps/* 与 /core/settings/apps/store/* 路径，
basePath /api/v2。
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Optional

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..client import get_client
from ..safety import require_write


# ---- 枚举类型（来自 openapi.json 的 schema 定义）----

# 应用商店搜索的 type（request.AppSearch.type）
AppType = Literal["website", "database", "tool"]

# 已安装应用生命周期操作（constant.AppOperate）
AppOperate = Literal[
    "start", "stop", "restart", "delete",
    "sync", "backup", "update", "rebuild", "upgrade", "reload",
]

# 容器重启策略（request.AppInstallCreate.restartPolicy）
AppRestartPolicy = Literal["always", "unless-stopped", "no", "on-failure"]

# 升级忽略范围（request.AppIgnoreUpgradeReq.scope）
AppIgnoreScope = Literal["all", "version"]

# 应用商店配置项（dto.AppstoreUpdate.scope）
AppStoreScope = Literal[
    "UninstallDeleteImage", "UpgradeBackup", "UninstallDeleteBackup",
]
AppStoreStatus = Literal["Enable", "Disable"]


def register(mcp: FastMCP) -> None:

    # ---- 应用商店搜索与详情 ----

    @mcp.tool()
    async def app_search(
        name: Annotated[Optional[str], Field(description="应用名模糊匹配，留空返回全部")] = None,
        type: Annotated[
            Optional[AppType],
            Field(description="应用类型过滤：website/database/tool"),
        ] = None,
        tags: Annotated[Optional[list[str]], Field(description="标签过滤列表")] = None,
        recommend: Annotated[bool, Field(description="仅返回推荐应用")] = False,
        resource: Annotated[Optional[str], Field(description="资源类型过滤，一般留空")] = None,
        page: Annotated[int, Field(ge=1, description="页码，从 1 开始")] = 1,
        page_size: Annotated[int, Field(ge=1, le=500, description="每页数量")] = 20,
        show_current_arch: Annotated[bool, Field(description="返回当前架构可用性")] = True,
    ) -> dict:
        """[应用] 搜索应用商店可用应用。读操作。

        1Panel 应用商店分页搜索接口，支持按名称、类型、标签过滤。对应
        POST /apps/search（request.AppSearch）。注意该接口的 schema 没有
        orderBy/order 字段，仅 page/pageSize 必填。

        Args:
            name: 应用名模糊匹配，留空返回全部。
            type: 应用类型过滤：website(网站类) / database(数据库类) / tool(工具类)。
            tags: 按标签过滤的字符串列表。
            recommend: 仅返回推荐应用。
            resource: 资源类型过滤，一般留空。
            page: 页码，从 1 开始。
            page_size: 每页数量，上限 500。
            show_current_arch: 返回结果是否包含当前架构可用性。
        """
        client = await get_client()
        body: dict[str, Any] = {
            "name": name or "",
            "recommend": recommend,
            "page": page,
            "pageSize": page_size,
            "showCurrentArch": show_current_arch,
        }
        if type is not None:
            body["type"] = type
        if tags is not None:
            body["tags"] = tags
        if resource is not None:
            body["resource"] = resource
        return await client.post("/apps/search", body)

    @mcp.tool()
    async def app_get_by_key(
        key: Annotated[str, Field(description="应用 key，如 wordpress / mysql")],
    ) -> dict:
        """[应用] 按 key 查询应用基础信息。读操作。

        返回应用名称、描述、图标、版本列表、标签、是否已安装等。对应
        GET /apps/:key。

        Args:
            key: 应用 key（标识符），如 wordpress、mysql、nginx。
        """
        client = await get_client()
        return await client.get(f"/apps/{key}")

    @mcp.tool()
    async def app_detail_by_id(
        app_id: Annotated[int, Field(description="应用 ID")],
        version: Annotated[str, Field(description="应用版本号")],
        type: Annotated[str, Field(description="应用类型")],
    ) -> dict:
        """[应用] 按 ID+版本+类型查询应用详情（含 docker-compose 模板）。读操作。

        返回应用详情（dockerCompose 模板、镜像、参数定义、架构、内存要求等）。
        对应 GET /apps/detail/:appId/:version/:type。

        Args:
            app_id: 应用 ID。
            version: 应用版本号。
            type: 应用类型。
        """
        client = await get_client()
        return await client.get(f"/apps/detail/{app_id}/{version}/{type}")

    @mcp.tool()
    async def app_detail_by_key(
        app_key: Annotated[str, Field(description="应用 key，如 wordpress")],
        version: Annotated[str, Field(description="应用版本号")],
    ) -> dict:
        """[应用] 按 key+版本查询应用详情（精简版，节点部署用）。读操作。

        返回应用的精简详情，主要用于多节点部署时拉取版本信息。对应
        GET /apps/detail/node/:appKey/:version。

        Args:
            app_key: 应用 key。
            version: 应用版本号。
        """
        client = await get_client()
        return await client.get(f"/apps/detail/node/{app_key}/{version}")

    @mcp.tool()
    async def app_get_detail(
        app_id: Annotated[int, Field(description="应用 ID")],
    ) -> dict:
        """[应用] 按 ID 查询应用详情（含所有版本与参数定义）。读操作。

        返回应用的完整详情（含可用版本、参数 schema 等）。对应
        GET /apps/details/:id。

        Args:
            app_id: 应用 ID。
        """
        client = await get_client()
        return await client.get(f"/apps/details/{app_id}")

    @mcp.tool()
    async def app_check_update() -> dict:
        """[应用] 查询所有已安装应用的可升级版本。读操作。

        返回当前有可用更新的已安装应用列表。对应 GET /apps/checkupdate。
        """
        client = await get_client()
        return await client.get("/apps/checkupdate")

    @mcp.tool()
    async def app_icon(
        key: Annotated[str, Field(description="应用 key 或应用 ID 字符串")],
    ) -> dict:
        """[应用] 获取应用图标。读操作。

        返回应用图标文件。对应 GET /apps/icon/:key。

        Args:
            key: 应用 key 或应用 ID（1Panel 内部按 key 解析）。
        """
        client = await get_client()
        return await client.get(f"/apps/icon/{key}")

    @mcp.tool()
    async def app_services(
        key: Annotated[str, Field(description="应用 key")],
    ) -> dict:
        """[应用] 查询应用关联的 Docker 服务（compose services）。读操作。

        返回该应用 compose 文件中定义的 service 列表。对应
        GET /apps/services/:key。

        Args:
            key: 应用 key。
        """
        client = await get_client()
        return await client.get(f"/apps/services/{key}")

    # ---- 已安装应用查询 ----

    @mcp.tool()
    async def app_installed_search(
        name: Annotated[Optional[str], Field(description="已安装应用名模糊匹配，留空返回全部")] = None,
        type: Annotated[
            Optional[AppType],
            Field(description="应用类型过滤：website/database/tool"),
        ] = None,
        tags: Annotated[Optional[list[str]], Field(description="标签过滤列表")] = None,
        update: Annotated[bool, Field(description="仅返回有可用升级的应用")] = False,
        unused: Annotated[bool, Field(description="仅返回未被使用的应用")] = False,
        all: Annotated[bool, Field(description="返回全部（含未启用）")] = False,
        check_update: Annotated[bool, Field(description="同时检查升级")] = False,
        sync: Annotated[bool, Field(description="触发同步后再返回")] = False,
        page: Annotated[int, Field(ge=1, description="页码，从 1 开始")] = 1,
        page_size: Annotated[int, Field(ge=1, le=500, description="每页数量")] = 20,
    ) -> dict:
        """[应用] 搜索/分页查询已安装的应用。读操作。

        1Panel 已安装应用分页查询接口，支持按名称、类型、是否可升级等过滤。
        对应 POST /apps/installed/search（request.AppInstalledSearch）。注意该
        接口 schema 没有 orderBy/order 字段，仅 page/pageSize 必填。

        Args:
            name: 已安装应用名模糊匹配，留空返回全部。
            type: 应用类型过滤：website/database/tool。
            tags: 标签过滤列表。
            update: 仅返回有可用升级的应用。
            unused: 仅返回未被网站等引用的应用。
            all: 返回全部（含未启用的安装实例）。
            check_update: 同时触发升级检查。
            sync: 先同步再返回结果。
            page: 页码，从 1 开始。
            page_size: 每页数量，上限 500。
        """
        client = await get_client()
        body: dict[str, Any] = {
            "page": page,
            "pageSize": page_size,
            "update": update,
            "unused": unused,
            "all": all,
            "checkUpdate": check_update,
            "sync": sync,
            "name": name or "",
        }
        if type is not None:
            body["type"] = type
        if tags is not None:
            body["tags"] = tags
        return await client.post("/apps/installed/search", body)

    @mcp.tool()
    async def app_installed_list() -> dict:
        """[应用] 列出全部已安装应用（不分页）。读操作。

        返回所有已安装应用实例的列表。对应 GET /apps/installed/list。
        适合需要拿到全量列表做本地过滤的场景；分页场景请用 app_installed_search。
        """
        client = await get_client()
        return await client.get("/apps/installed/list")

    @mcp.tool()
    async def app_installed_info(
        app_install_id: Annotated[int, Field(description="已安装应用实例 ID（appInstallId）")],
    ) -> dict:
        """[应用] 查询已安装应用实例详情。读操作。

        返回某个安装实例的完整信息（容器名、端口、安装路径、状态、版本等）。
        对应 GET /apps/installed/info/:appInstallId。

        Args:
            app_install_id: 已安装应用实例 ID（appInstallId）。
        """
        client = await get_client()
        return await client.get(f"/apps/installed/info/{app_install_id}")

    @mcp.tool()
    async def app_params(
        app_install_id: Annotated[int, Field(description="已安装应用实例 ID（appInstallId）")],
    ) -> dict:
        """[应用] 查询已安装应用的参数与配置（compose 内容）。读操作。

        返回该安装实例的参数定义与当前 docker-compose 配置。对应
        GET /apps/installed/params/:appInstallId。

        Args:
            app_install_id: 已安装应用实例 ID（appInstallId）。
        """
        client = await get_client()
        return await client.get(f"/apps/installed/params/{app_install_id}")

    @mcp.tool()
    async def app_default_config(
        type: Annotated[str, Field(description="应用类型（OperationWithNameAndType.type）")],
        name: Annotated[Optional[str], Field(description="应用名，一般留空")] = None,
    ) -> dict:
        """[应用] 按 type+name 查询应用的默认配置模板。读操作。

        返回应用安装时的默认配置字符串。对应 POST /apps/installed/conf
        （dto.OperationWithNameAndType）。

        Args:
            type: 应用类型，与 app_search 的 type 一致。
            name: 应用名，一般留空由 type 决定。
        """
        client = await get_client()
        body: dict[str, Any] = {"type": type}
        if name is not None:
            body["name"] = name
        return await client.post("/apps/installed/conf", body)

    @mcp.tool()
    async def app_connection_info(
        type: Annotated[str, Field(description="应用类型（如 mysql / redis）")],
        name: Annotated[Optional[str], Field(description="应用名，一般留空")] = None,
    ) -> dict:
        """[应用] 查询应用的连接信息（账号/密码/主机等）。读操作。

        返回应用的数据库连接信息（含密码）。对应 POST /apps/installed/conninfo
        （dto.OperationWithNameAndType，response.DatabaseConn）。

        Args:
            type: 应用类型，如 mysql / redis。
            name: 应用名，一般留空。
        """
        client = await get_client()
        body: dict[str, Any] = {"type": type}
        if name is not None:
            body["name"] = name
        return await client.post("/apps/installed/conninfo", body)

    @mcp.tool()
    async def app_port(
        type: Annotated[str, Field(description="应用类型")],
        name: Annotated[Optional[str], Field(description="应用名，一般留空")] = None,
    ) -> dict:
        """[应用] 查询应用占用的端口。读操作。

        返回应用服务监听的端口号。对应 POST /apps/installed/loadport
        （dto.OperationWithNameAndType）。

        Args:
            type: 应用类型。
            name: 应用名，一般留空。
        """
        client = await get_client()
        body: dict[str, Any] = {"type": type}
        if name is not None:
            body["name"] = name
        return await client.post("/apps/installed/loadport", body)

    @mcp.tool()
    async def app_installed_check(
        key: Annotated[str, Field(description="应用 key")],
        name: Annotated[Optional[str], Field(description="应用名，用于校验同名安装")] = None,
    ) -> dict:
        """[应用] 检查指定应用是否已安装。读操作。

        返回是否已安装及安装实例信息（response.AppInstalledCheck）。
        对应 POST /apps/installed/check（request.AppInstalledInfo）。

        Args:
            key: 应用 key。
            name: 应用名，用于校验是否已存在同名安装。
        """
        client = await get_client()
        body: dict[str, Any] = {"key": key}
        if name is not None:
            body["name"] = name
        return await client.post("/apps/installed/check", body)

    @mcp.tool()
    async def app_update_versions(
        app_install_id: Annotated[int, Field(description="已安装应用实例 ID")],
    ) -> dict:
        """[应用] 查询已安装应用的可升级版本列表。读操作。

        返回该安装实例可选升级到的版本数组（dto.AppVersion）。
        对应 POST /apps/installed/update/versions，body 含 appInstallID。

        Args:
            app_install_id: 已安装应用实例 ID。
        """
        client = await get_client()
        return await client.post(
            "/apps/installed/update/versions", {"appInstallID": app_install_id}
        )

    @mcp.tool()
    async def app_uninstall_check(
        app_install_id: Annotated[int, Field(description="已安装应用实例 ID")],
    ) -> dict:
        """[应用] 卸载前检查应用关联资源（数据库/网站等依赖）。读操作。

        返回删除前需确认的关联资源列表（dto.AppResource）。建议卸载前先调用
        以了解影响范围。对应 GET /apps/installed/delete/check/:appInstallId。

        Args:
            app_install_id: 已安装应用实例 ID。
        """
        client = await get_client()
        return await client.get(f"/apps/installed/delete/check/{app_install_id}")

    @mcp.tool()
    async def app_ignored_list() -> dict:
        """[应用] 列出被忽略升级的应用。读操作。

        返回当前被忽略升级的应用列表。对应 GET /apps/ignored/detail。
        """
        client = await get_client()
        return await client.get("/apps/ignored/detail")

    @mcp.tool()
    async def app_store_config() -> dict:
        """[应用商店] 查询应用商店配置（卸载删镜像/升级备份等开关）。读操作。

        返回应用商店的卸载删镜像、升级备份、卸载删备份等开关状态。
        对应 GET /core/settings/apps/store/config。
        """
        client = await get_client()
        return await client.get("/core/settings/apps/store/config")

    # ---- 应用安装与生命周期（写操作）----

    @mcp.tool()
    async def app_install(
        app_detail_id: Annotated[int, Field(description="应用详情 ID（AppDetail.id，标识具体版本）")],
        params: Annotated[
            dict[str, Any],
            Field(description="应用参数对象，key 由 app_detail_by_id 返回的 params 定义决定"),
        ],
        name: Annotated[
            Optional[str],
            Field(description="自定义安装实例名，留空则用应用默认名"),
        ] = None,
        container_name: Annotated[
            Optional[str],
            Field(description="自定义容器名前缀，留空由 1Panel 生成"),
        ] = None,
        docker_compose: Annotated[
            Optional[str],
            Field(description="自定义 docker-compose 内容；留空则用模板"),
        ] = None,
        advanced: Annotated[bool, Field(description="是否启用高级配置（CPU/内存限制等）")] = False,
        cpu_quota: Annotated[Optional[float], Field(description="CPU 配额（核数），advanced=true 时生效")] = None,
        memory_limit: Annotated[Optional[float], Field(description="内存上限，advanced=true 时生效")] = None,
        memory_unit: Annotated[Optional[str], Field(description="内存单位，如 MB/GB")] = None,
        restart_policy: Annotated[
            AppRestartPolicy, Field(description="容器重启策略，默认 unless-stopped")
        ] = "unless-stopped",
        pull_image: Annotated[bool, Field(description="安装时是否拉取镜像")] = True,
        allow_port: Annotated[bool, Field(description="是否允许 1Panel 自动放行防火墙端口")] = True,
    ) -> dict:
        """⚠️写操作 [应用] 安装应用商店应用。

        根据 AppDetail ID 与参数安装应用，返回安装任务信息。对应
        POST /apps/install（request.AppInstallCreate）。

        使用流程：
        1. app_search 找到应用，拿 app_id
        2. app_get_detail 或 app_detail_by_id 拿 appDetailId 与参数定义
        3. app_install 用 appDetailId + params 提交安装

        Args:
            app_detail_id: 应用详情 ID（标识具体版本的 AppDetail.id）。
            params: 应用参数对象，key 由 AppDetail.params 定义决定。
            name: 自定义安装实例名，留空用默认名。
            container_name: 自定义容器名前缀，留空由 1Panel 生成。
            docker_compose: 自定义 docker-compose 内容，留空用模板。
            advanced: 是否启用高级配置（CPU/内存限制）。
            cpu_quota: CPU 配额（核数），advanced=true 时生效。
            memory_limit: 内存上限，advanced=true 时生效。
            memory_unit: 内存单位（MB/GB）。
            restart_policy: 容器重启策略，默认 unless-stopped。
            pull_image: 安装时是否拉取镜像。
            allow_port: 是否允许 1Panel 自动放行防火墙端口。
        """
        require_write()
        client = await get_client()
        body: dict[str, Any] = {
            "appDetailId": app_detail_id,
            "params": params,
            "advanced": advanced,
            "restartPolicy": restart_policy,
            "pullImage": pull_image,
            "allowPort": allow_port,
        }
        if name is not None:
            body["name"] = name
        if container_name is not None:
            body["containerName"] = container_name
        if docker_compose is not None:
            body["dockerCompose"] = docker_compose
        if cpu_quota is not None:
            body["cpuQuota"] = cpu_quota
        if memory_limit is not None:
            body["memoryLimit"] = memory_limit
        if memory_unit is not None:
            body["memoryUnit"] = memory_unit
        return await client.post("/apps/install", body)

    @mcp.tool()
    async def app_operate(
        install_id: Annotated[int, Field(description="已安装应用实例 ID（installId）")],
        operation: Annotated[
            AppOperate,
            Field(description="操作类型：start/stop/restart/sync/backup/update/rebuild/upgrade/reload/delete"),
        ],
        detail_id: Annotated[
            Optional[int],
            Field(description="目标版本 AppDetail ID，升级(upgrade)时必填"),
        ] = None,
        backup_id: Annotated[Optional[int], Field(description="备份记录 ID，恢复场景用")] = None,
        backup: Annotated[bool, Field(description="升级前是否先备份")] = False,
        pull_image: Annotated[bool, Field(description="操作时是否拉取镜像")] = False,
        force_delete: Annotated[bool, Field(description="delete 时强制删除（忽略依赖检查）")] = False,
        delete_backup: Annotated[bool, Field(description="delete 时同时删除备份")] = False,
        delete_db: Annotated[bool, Field(description="delete 时同时删除关联数据库")] = False,
        confirm: Annotated[
            bool,
            Field(description="delete/upgrade 等高危操作必须传 true 才执行"),
        ] = False,
    ) -> dict:
        """⚠️写操作 [应用] 对已安装应用执行生命周期操作（启停/升级/同步/备份/删除）。

        已安装应用的统一操作入口。对应 POST /apps/installed/op
        （request.AppInstalledOperate）。

        operation 取值（来自 1Panel constant.AppOperate）：
        - start/stop/restart：启动/停止/重启
        - sync：同步应用状态
        - backup：备份应用
        - update/rebuild/reload：参数变更后重建/重载
        - upgrade：升级到新版本（需配合 detail_id）
        - delete：卸载应用（高危，必须传 confirm=true）

        Args:
            install_id: 已安装应用实例 ID（installId）。
            operation: 操作类型，见上方说明。
            detail_id: 目标版本 AppDetail ID，升级(upgrade)时必填。
            backup_id: 备份记录 ID，恢复场景用。
            backup: 升级前是否先备份。
            pull_image: 操作时是否拉取镜像。
            force_delete: delete 时强制删除（忽略依赖检查）。
            delete_backup: delete 时同时删除备份。
            delete_db: delete 时同时删除关联数据库。
            confirm: delete/upgrade 等高危操作必须传 true 才执行。
        """
        require_write()
        if operation in ("delete", "upgrade") and not confirm:
            raise ValueError(
                f"高危操作 {operation} 必须显式传 confirm=true 才能执行。"
            )
        client = await get_client()
        body: dict[str, Any] = {
            "installId": install_id,
            "operate": operation,
            "backup": backup,
            "pullImage": pull_image,
            "forceDelete": force_delete,
            "deleteBackup": delete_backup,
            "deleteDB": delete_db,
        }
        if detail_id is not None:
            body["detailId"] = detail_id
        if backup_id is not None:
            body["backupId"] = backup_id
        return await client.post("/apps/installed/op", body)

    @mcp.tool()
    async def app_upgrade(
        install_id: Annotated[int, Field(description="已安装应用实例 ID（installId）")],
        detail_id: Annotated[int, Field(description="目标版本 AppDetail ID（可通过 app_update_versions 查询）")],
        backup: Annotated[bool, Field(description="升级前是否先备份")] = False,
        pull_image: Annotated[bool, Field(description="是否拉取新版本镜像")] = True,
        confirm: Annotated[bool, Field(description="升级是高危操作，必须传 true")] = False,
    ) -> dict:
        """⚠️写操作 [应用] 升级已安装应用到指定版本。

        app_operate 的升级便捷封装（operation=upgrade）。对应 POST /apps/installed/op
        with operate=upgrade。升级前建议用 app_update_versions 查可用版本拿 detail_id。

        Args:
            install_id: 已安装应用实例 ID。
            detail_id: 目标版本 AppDetail ID。
            backup: 升级前是否先备份。
            pull_image: 是否拉取新版本镜像。
            confirm: 升级是高危操作，必须传 true。
        """
        require_write()
        if not confirm:
            raise ValueError("升级应用是高危操作，必须显式传 confirm=true。")
        client = await get_client()
        return await client.post("/apps/installed/op", {
            "installId": install_id,
            "operate": "upgrade",
            "detailId": detail_id,
            "backup": backup,
            "pullImage": pull_image,
        })

    @mcp.tool()
    async def app_uninstall(
        install_id: Annotated[int, Field(description="已安装应用实例 ID（installId）")],
        force_delete: Annotated[bool, Field(description="强制删除（忽略依赖检查）")] = False,
        delete_backup: Annotated[bool, Field(description="同时删除该应用的备份")] = False,
        delete_db: Annotated[bool, Field(description="同时删除关联数据库")] = False,
        pull_image: Annotated[bool, Field(description="同时删除镜像")] = False,
        confirm: Annotated[bool, Field(description="卸载是高危操作，必须传 true 才执行")] = False,
    ) -> dict:
        """⚠️高危 [应用] 卸载已安装应用。

        app_operate 的卸载便捷封装（operation=delete）。卸载不可恢复，
        建议先调用 app_uninstall_check 了解关联资源影响。对应
        POST /apps/installed/op with operate=delete。

        Args:
            install_id: 已安装应用实例 ID。
            force_delete: 强制删除（忽略依赖检查）。
            delete_backup: 同时删除该应用的备份。
            delete_db: 同时删除关联数据库。
            pull_image: 同时删除镜像。
            confirm: 卸载是高危操作，必须为 true。
        """
        require_write()
        if not confirm:
            raise ValueError("卸载应用是高危操作，必须显式传 confirm=true。")
        client = await get_client()
        return await client.post("/apps/installed/op", {
            "installId": install_id,
            "operate": "delete",
            "forceDelete": force_delete,
            "deleteBackup": delete_backup,
            "deleteDB": delete_db,
            "pullImage": pull_image,
        })

    @mcp.tool()
    async def app_params_update(
        install_id: Annotated[int, Field(description="已安装应用实例 ID（installId）")],
        params: Annotated[dict[str, Any], Field(description="新的参数对象，key 由 app_params 返回的 schema 决定")],
        pull_image: Annotated[bool, Field(description="参数变更后是否重新拉取镜像")] = False,
        advanced: Annotated[bool, Field(description="是否启用高级配置")] = False,
        restart_policy: Annotated[
            Optional[AppRestartPolicy], Field(description="容器重启策略")
        ] = None,
    ) -> dict:
        """⚠️写操作 [应用] 修改已安装应用的参数并重建容器。

        修改应用参数后，1Panel 会重建容器使新参数生效。对应
        POST /apps/installed/params/update（request.AppInstalledUpdate）。

        Args:
            install_id: 已安装应用实例 ID。
            params: 新的参数对象。
            pull_image: 参数变更后是否重新拉取镜像。
            advanced: 是否启用高级配置。
            restart_policy: 容器重启策略，留空保持不变。
        """
        require_write()
        client = await get_client()
        body: dict[str, Any] = {
            "installId": install_id,
            "params": params,
            "pullImage": pull_image,
            "advanced": advanced,
        }
        if restart_policy is not None:
            body["restartPolicy"] = restart_policy
        return await client.post("/apps/installed/params/update", body)

    @mcp.tool()
    async def app_config_update(
        install_id: Annotated[int, Field(description="已安装应用实例 ID（installID）")],
        web_ui: Annotated[Optional[str], Field(description="应用访问入口 URL，留空保持不变")] = None,
    ) -> dict:
        """⚠️写操作 [应用] 更新已安装应用的配置（如访问入口）。

        用于更新应用的 webUI 访问入口等轻量配置。对应
        POST /apps/installed/config/update（request.AppConfigUpdate）。

        Args:
            install_id: 已安装应用实例 ID。
            web_ui: 应用访问入口 URL，留空保持不变。
        """
        require_write()
        client = await get_client()
        body: dict[str, Any] = {"installID": install_id}
        if web_ui is not None:
            body["webUI"] = web_ui
        return await client.post("/apps/installed/config/update", body)

    @mcp.tool()
    async def app_port_change(
        key: Annotated[str, Field(description="应用 key")],
        name: Annotated[str, Field(description="已安装应用实例名")],
        port: Annotated[int, Field(description="新端口号")],
    ) -> dict:
        """⚠️写操作 [应用] 修改应用监听端口。

        修改已安装应用的端口映射。对应 POST /apps/installed/port/change
        （request.PortUpdate）。

        Args:
            key: 应用 key。
            name: 已安装应用实例名。
            port: 新端口号。
        """
        require_write()
        client = await get_client()
        return await client.post("/apps/installed/port/change", {
            "key": key, "name": name, "port": port,
        })

    @mcp.tool()
    async def app_ignore_upgrade(
        app_id: Annotated[int, Field(description="应用 ID（appID）")],
        scope: Annotated[AppIgnoreScope, Field(description="忽略范围：all=全部版本，version=仅当前版本")],
        app_detail_id: Annotated[
            Optional[int],
            Field(description="AppDetail ID，scope=version 时必填"),
        ] = None,
    ) -> dict:
        """⚠️写操作 [应用] 忽略应用升级。

        将应用加入升级忽略列表（全部版本或仅当前版本）。
        对应 POST /apps/installed/ignore（request.AppIgnoreUpgradeReq）。

        Args:
            app_id: 应用 ID。
            scope: 忽略范围：all=忽略全部版本升级，version=仅忽略当前版本。
            app_detail_id: AppDetail ID，scope=version 时必填。
        """
        require_write()
        client = await get_client()
        body: dict[str, Any] = {"appID": app_id, "scope": scope}
        if app_detail_id is not None:
            body["appDetailID"] = app_detail_id
        return await client.post("/apps/installed/ignore", body)

    @mcp.tool()
    async def app_ignore_cancel(
        app_id: Annotated[int, Field(description="应用忽略记录 ID（request.ReqWithID.id）")],
    ) -> dict:
        """⚠️写操作 [应用] 取消忽略应用升级。

        将应用从升级忽略列表移除。对应 POST /apps/ignored/cancel
        （request.ReqWithID，id 为忽略记录 ID）。

        Args:
            app_id: 应用升级忽略记录的 ID。
        """
        require_write()
        client = await get_client()
        return await client.post("/apps/ignored/cancel", {"id": app_id})

    @mcp.tool()
    async def app_installed_sync() -> dict:
        """⚠️写操作 [应用] 同步已安装应用列表状态。

        重新扫描本地 docker，同步已安装应用的实际运行状态。
        对应 POST /apps/installed/sync（无请求体）。
        """
        require_write()
        client = await get_client()
        return await client.post("/apps/installed/sync", {})

    @mcp.tool()
    async def app_sync_local() -> dict:
        """⚠️写操作 [应用商店] 从本地同步应用商店列表。

        读取本地缓存的远程应用商店元数据刷新本地应用列表。
        对应 POST /apps/sync/local（无请求体）。
        """
        require_write()
        client = await get_client()
        return await client.post("/apps/sync/local", {})

    @mcp.tool()
    async def app_sync_remote() -> dict:
        """⚠️写操作 [应用商店] 从远程同步应用商店列表。

        从 1Panel 官方远程仓库拉取最新应用商店元数据。
        对应 POST /apps/sync/remote（无请求体）。
        """
        require_write()
        client = await get_client()
        return await client.post("/apps/sync/remote", {})

    @mcp.tool()
    async def app_store_config_update(
        scope: Annotated[
            AppStoreScope,
            Field(description="配置项：UninstallDeleteImage=卸载删镜像 / UpgradeBackup=升级前备份 / UninstallDeleteBackup=卸载删备份"),
        ],
        status: Annotated[
            AppStoreStatus,
            Field(description="开关状态：Enable=开启 / Disable=关闭"),
        ],
    ) -> dict:
        """⚠️写操作 [应用商店] 更新应用商店配置（卸载删镜像/升级备份等开关）。

        按单项更新应用商店配置。对应 POST /core/settings/apps/store/update
        （dto.AppstoreUpdate）。

        Args:
            scope: 配置项：UninstallDeleteImage（卸载时删镜像） /
                UpgradeBackup（升级前备份） / UninstallDeleteBackup（卸载时删备份）。
            status: 开关状态：Enable / Disable。
        """
        require_write()
        client = await get_client()
        return await client.post("/core/settings/apps/store/update", {
            "scope": scope, "status": status,
        })
