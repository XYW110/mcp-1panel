"""计划任务模块（对应 openapi.json 的 Cronjob tag，16 个端点）。

照 container.py 黄金范式风格：
1. 工具名：cronjob_<action>
2. description：[计划任务] 开头，写操作加 ⚠️，高危加 confirm
3. 入参用 Annotated[T, Field(description=...)]
4. handler 用 `await get_client()` 拿共享客户端，调 .post() / .get() / .search()
5. 写操作开头调 require_write()，删除类加 confirm 参数

接口来源：references/openapi.json 的 /cronjobs/* 路径，basePath /api/v2。

注意：1Panel 计划任务类型（type）常见取值：
- shell         Shell 脚本（command 存脚本内容，或 scriptMode=select 选已有脚本）
- container     容器内执行命令
- website       网站备份（website=网站名，exclusionRules=排除规则）
- app           应用备份（appID=应用 ID）
- database      数据库备份（dbType=mysql/...，dbName=库名）
- directory     目录备份（sourceDir=源目录，isDir=true）
- snapshot      系统快照（snapshotRule=快照规则）
- url           请求 URL（url=地址，args=参数）
- cutWebsiteLog 切割网站日志（website=网站名）
具体取值由调用方按业务填入，本模块不强校验。
"""

from __future__ import annotations

from typing import Annotated, Literal, Optional

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..client import get_client
from ..safety import require_write


# ---- 排序枚举（dto.PageCronjob.orderBy） ----
CronjobOrderBy = Literal["name", "status", "createdAt"]
CronjobOrder = Literal["ascending", "descending", "null"]
# 执行记录查询的状态过滤（dto.SearchRecord.status，free string，此处给常用值）
CronjobRecordStatus = Literal["all", "Success", "Failed", "Waiting", "Running"]


def register(mcp: FastMCP) -> None:

    # ---- 查询 / 详情 ----

    @mcp.tool()
    async def cronjob_search(
        info: Annotated[str, Field(description="名称/描述模糊匹配，留空返回全部")] = "",
        group_ids: Annotated[Optional[list[int]], Field(description="按分组 ID 过滤，可多选")] = None,
        page: Annotated[int, Field(ge=1, description="页码")] = 1,
        page_size: Annotated[int, Field(ge=1, le=500, description="每页数量")] = 100,
        order_by: Annotated[CronjobOrderBy, Field(description="排序字段：name/status/createdAt")] = "createdAt",
        order: Annotated[CronjobOrder, Field(description="排序方向")] = "descending",
    ) -> dict:
        """[计划任务] 列出或搜索计划任务（Cronjob）。读操作。

        1Panel 的计划任务分页查询接口，支持按名称、分组过滤。对应
        POST /cronjobs/search。返回分页任务列表（含名称、类型、cron 表达式、状态等）。

        Args:
            info: 名称/描述模糊匹配，留空返回全部。
            group_ids: 按分组 ID 过滤，可多选，留空不过滤。
            page: 页码，从 1 开始。
            page_size: 每页数量，上限 500。
            order_by: 排序字段：name/status/createdAt。
            order: 排序方向：ascending/descending/null。
        """
        client = await get_client()
        body = {
            "page": page,
            "pageSize": page_size,
            "orderBy": order_by,
            "order": order,
            "info": info or "",
            "groupIDs": group_ids or [],
        }
        return await client.post("/cronjobs/search", body)

    @mcp.tool()
    async def cronjob_detail(
        id: Annotated[int, Field(description="计划任务 ID")],
    ) -> dict:
        """[计划任务] 查看计划任务详情。读操作。

        返回单个计划任务的完整配置（类型、cron 表达式、脚本内容、备份目标、
        重试/超时/告警设置等）。对应 POST /cronjobs/load/info。

        Args:
            id: 计划任务 ID。
        """
        client = await get_client()
        return await client.post("/cronjobs/load/info", {"id": id})

    @mcp.tool()
    async def cronjob_records(
        cronjob_id: Annotated[int, Field(description="计划任务 ID")],
        page: Annotated[int, Field(ge=1, description="页码")] = 1,
        page_size: Annotated[int, Field(ge=1, le=500, description="每页数量")] = 20,
        status: Annotated[CronjobRecordStatus, Field(description="按执行状态过滤，all 不过滤")] = "all",
        start_time: Annotated[Optional[str], Field(description="起始时间，格式 YYYY-MM-DD HH:mm:ss")] = None,
        end_time: Annotated[Optional[str], Field(description="结束时间，格式 YYYY-MM-DD HH:mm:ss")] = None,
    ) -> dict:
        """[计划任务] 查询计划任务的执行记录。读操作。

        分页返回某任务的历次执行记录（开始/结束时间、状态、耗时、记录 ID）。
        对应 POST /cronjobs/search/records。

        Args:
            cronjob_id: 计划任务 ID。
            page: 页码，从 1 开始。
            page_size: 每页数量，上限 500。
            status: 按执行状态过滤，all 表示不过滤；常用 Success/Failed。
            start_time: 起始时间，格式 YYYY-MM-DD HH:mm:ss，可空。
            end_time: 结束时间，格式 YYYY-MM-DD HH:mm:ss，可空。
        """
        client = await get_client()
        body: dict = {
            "page": page,
            "pageSize": page_size,
            "cronjobID": cronjob_id,
            "status": status,
            "startTime": start_time or "",
            "endTime": end_time or "",
        }
        return await client.post("/cronjobs/search/records", body)

    @mcp.tool()
    async def cronjob_record_log(
        record_id: Annotated[int, Field(description="执行记录 ID")],
    ) -> dict:
        """[计划任务] 查看某次执行记录的详细日志。读操作。

        返回单条执行记录的输出日志（stdout/stderr），用于排查执行失败原因。
        对应 POST /cronjobs/records/log。

        Args:
            record_id: 执行记录 ID（来自 cronjob_records 的结果）。
        """
        client = await get_client()
        return await client.post("/cronjobs/records/log", {"id": record_id})

    @mcp.tool()
    async def cronjob_next_run(
        spec: Annotated[str, Field(description="cron 表达式，5 段或 6 段式，如 '0 3 * * *'")],
    ) -> dict:
        """[计划任务] 预览 cron 表达式最近几次执行时间。读操作。

        根据给定 cron 表达式计算未来若干次触发时间（1Panel 默认返回 5 次预览），
        常用于创建/更新前校验表达式是否符合预期。对应 POST /cronjobs/next。

        Args:
            spec: cron 表达式，标准 5 段式（分 时 日 月 周）或 6 段式。
        """
        client = await get_client()
        return await client.post("/cronjobs/next", {"spec": spec})

    @mcp.tool()
    async def cronjob_script_options() -> dict:
        """[计划任务] 列出可用的 Shell 脚本选项。读操作。

        创建/更新 Shell 类型任务时，scriptMode=select 需要从已有脚本中选一个，
        本接口返回可选脚本列表。对应 GET /cronjobs/script/options。
        """
        client = await get_client()
        return await client.get("/cronjobs/script/options")

    # ---- 创建 / 更新 / 删除 ----

    @mcp.tool()
    async def cronjob_create(
        name: Annotated[str, Field(description="任务名称")],
        type: Annotated[str, Field(description="任务类型：shell/container/website/app/database/directory/snapshot/url/cutWebsiteLog")],
        spec: Annotated[str, Field(description="cron 表达式，5/6 段式，如 '0 3 * * *'")],
        spec_custom: Annotated[bool, Field(description="是否自定义 cron 表达式（true 时 spec 必填）")] = False,
        script: Annotated[str, Field(description="脚本内容（shell 类型时填，scriptMode=input 模式）")] = "",
        script_mode: Annotated[str, Field(description="脚本输入方式：input 自定义 / select 选择已有")] = "input",
        script_id: Annotated[int, Field(description="已有脚本 ID（scriptMode=select 时填）", ge=0)] = 0,
        command: Annotated[str, Field(description="执行命令（shell/container 类型时填）")] = "",
        container_name: Annotated[str, Field(description="容器名（container 类型时填）")] = "",
        user: Annotated[str, Field(description="执行用户，默认 root")] = "",
        executor: Annotated[str, Field(description="执行器，默认 bash")] = "",
        website: Annotated[str, Field(description="网站名（website/cutWebsiteLog 类型时填）")] = "",
        app_id: Annotated[str, Field(description="应用 ID（app 类型时填）")] = "",
        db_type: Annotated[str, Field(description="数据库类型：mysql/postgresql 等（database 类型时填）")] = "",
        db_name: Annotated[str, Field(description="数据库名（database 类型时填，all 表示全部）")] = "",
        source_dir: Annotated[str, Field(description="源目录（directory 类型时填）")] = "",
        is_dir: Annotated[bool, Field(description="源是否为目录（directory 类型，true=目录 false=文件）")] = True,
        exclusion_rules: Annotated[str, Field(description="备份排除规则（website/directory 类型时填）")] = "",
        retain_copies: Annotated[int, Field(description="保留副本数，最少 1", ge=1)] = 7,
        url: Annotated[str, Field(description="目标 URL（url 类型时填）")] = "",
        args: Annotated[str, Field(description="请求参数（url 类型时填）")] = "",
        retry_times: Annotated[int, Field(description="失败重试次数，0 表示不重试", ge=0)] = 0,
        timeout: Annotated[int, Field(description="超时秒数，0 表示不限制（建议 >=1）", ge=1)] = 3600,
        ignore_err: Annotated[bool, Field(description="是否忽略错误继续")] = False,
        group_id: Annotated[int, Field(description="分组 ID，默认 0（无分组）", ge=0)] = 0,
        alert_count: Annotated[int, Field(description="失败告警阈值次数", ge=0)] = 0,
        alert_title: Annotated[str, Field(description="告警标题")] = "",
        alert_method: Annotated[str, Field(description="告警方式")] = "",
        download_account_id: Annotated[int, Field(description="远程备份账号 ID（备份到对象存储时填）", ge=0)] = 0,
        source_account_ids: Annotated[str, Field(description="源备份账号 ID（多选，逗号分隔）")] = "",
        secret: Annotated[str, Field(description="加密密钥（远程备份加密时填）")] = "",
    ) -> dict:
        """⚠️写操作 [计划任务] 创建计划任务。

        创建一个新的定时任务。不同 type 需要不同字段组合：shell 需 script/command，
        website 需 website 名，database 需 dbType/dbName，directory 需 sourceDir，
        url 需 url/args 等。对应 POST /cronjobs。

        Args:
            name: 任务名称。
            type: 任务类型，见模块文档的取值列表。
            spec: cron 表达式，如 '0 3 * * *'。
            spec_custom: 是否自定义 cron（true 时 spec 必填）。
            script: 脚本内容（shell + scriptMode=input 时填）。
            script_mode: 脚本输入方式：input 自定义 / select 选择已有。
            script_id: 已有脚本 ID（scriptMode=select 时填）。
            command: 执行命令（shell/container 时填）。
            container_name: 容器名（container 时填）。
            user: 执行用户，默认 root。
            executor: 执行器，默认 bash。
            website: 网站名（website/cutWebsiteLog 时填）。
            app_id: 应用 ID（app 时填）。
            db_type: 数据库类型（database 时填）。
            db_name: 数据库名（database 时填）。
            source_dir: 源目录（directory 时填）。
            is_dir: 源是否目录（directory 时）。
            exclusion_rules: 备份排除规则。
            retain_copies: 保留副本数，最少 1。
            url: 目标 URL（url 时填）。
            args: 请求参数（url 时填）。
            retry_times: 失败重试次数，0 不重试。
            timeout: 超时秒数。
            ignore_err: 是否忽略错误继续。
            group_id: 分组 ID，0 表示无分组。
            alert_count: 失败告警阈值。
            alert_title: 告警标题。
            alert_method: 告警方式。
            download_account_id: 远程备份账号 ID。
            source_account_ids: 源备份账号 ID（逗号分隔）。
            secret: 加密密钥（远程备份加密）。
        """
        require_write()
        client = await get_client()
        body = {
            "name": name,
            "type": type,
            "spec": spec,
            "specCustom": spec_custom,
            "script": script,
            "scriptMode": script_mode,
            "scriptID": script_id,
            "command": command,
            "containerName": container_name,
            "user": user,
            "executor": executor,
            "website": website,
            "appID": app_id,
            "dbType": db_type,
            "dbName": db_name,
            "sourceDir": source_dir,
            "isDir": is_dir,
            "exclusionRules": exclusion_rules,
            "retainCopies": retain_copies,
            "url": url,
            "args": args,
            "retryTimes": retry_times,
            "timeout": timeout,
            "ignoreErr": ignore_err,
            "groupID": group_id,
            "alertCount": alert_count,
            "alertTitle": alert_title,
            "alertMethod": alert_method,
            "downloadAccountID": download_account_id,
            "sourceAccountIDs": source_account_ids,
            "secret": secret,
        }
        return await client.post("/cronjobs", body)

    @mcp.tool()
    async def cronjob_update(
        id: Annotated[int, Field(description="计划任务 ID")],
        name: Annotated[str, Field(description="任务名称")],
        type: Annotated[str, Field(description="任务类型：shell/container/website/app/database/directory/snapshot/url/cutWebsiteLog")],
        spec: Annotated[str, Field(description="cron 表达式，5/6 段式，如 '0 3 * * *'")],
        spec_custom: Annotated[bool, Field(description="是否自定义 cron 表达式")] = False,
        script: Annotated[str, Field(description="脚本内容（shell + scriptMode=input 时填）")] = "",
        script_mode: Annotated[str, Field(description="脚本输入方式：input/select")] = "input",
        script_id: Annotated[int, Field(description="已有脚本 ID（scriptMode=select 时填）", ge=0)] = 0,
        command: Annotated[str, Field(description="执行命令")] = "",
        container_name: Annotated[str, Field(description="容器名")] = "",
        user: Annotated[str, Field(description="执行用户")] = "",
        executor: Annotated[str, Field(description="执行器")] = "",
        website: Annotated[str, Field(description="网站名")] = "",
        app_id: Annotated[str, Field(description="应用 ID")] = "",
        db_type: Annotated[str, Field(description="数据库类型")] = "",
        db_name: Annotated[str, Field(description="数据库名")] = "",
        source_dir: Annotated[str, Field(description="源目录")] = "",
        is_dir: Annotated[bool, Field(description="源是否目录")] = True,
        exclusion_rules: Annotated[str, Field(description="备份排除规则")] = "",
        retain_copies: Annotated[int, Field(description="保留副本数，最少 1", ge=1)] = 7,
        url: Annotated[str, Field(description="目标 URL")] = "",
        args: Annotated[str, Field(description="请求参数")] = "",
        retry_times: Annotated[int, Field(description="失败重试次数", ge=0)] = 0,
        timeout: Annotated[int, Field(description="超时秒数", ge=1)] = 3600,
        ignore_err: Annotated[bool, Field(description="是否忽略错误继续")] = False,
        group_id: Annotated[int, Field(description="分组 ID", ge=0)] = 0,
        alert_count: Annotated[int, Field(description="失败告警阈值", ge=0)] = 0,
        alert_title: Annotated[str, Field(description="告警标题")] = "",
        alert_method: Annotated[str, Field(description="告警方式")] = "",
        download_account_id: Annotated[int, Field(description="远程备份账号 ID", ge=0)] = 0,
        source_account_ids: Annotated[str, Field(description="源备份账号 ID，逗号分隔")] = "",
        secret: Annotated[str, Field(description="加密密钥")] = "",
    ) -> dict:
        """⚠️写操作 [计划任务] 更新计划任务。

        修改已有任务的配置，字段语义与 cronjob_create 一致，必须带上 id。
        对应 POST /cronjobs/update。

        Args:
            id: 计划任务 ID（必填）。
            其余参数：见 cronjob_create 的说明。
        """
        require_write()
        client = await get_client()
        body = {
            "id": id,
            "name": name,
            "type": type,
            "spec": spec,
            "specCustom": spec_custom,
            "script": script,
            "scriptMode": script_mode,
            "scriptID": script_id,
            "command": command,
            "containerName": container_name,
            "user": user,
            "executor": executor,
            "website": website,
            "appID": app_id,
            "dbType": db_type,
            "dbName": db_name,
            "sourceDir": source_dir,
            "isDir": is_dir,
            "exclusionRules": exclusion_rules,
            "retainCopies": retain_copies,
            "url": url,
            "args": args,
            "retryTimes": retry_times,
            "timeout": timeout,
            "ignoreErr": ignore_err,
            "groupID": group_id,
            "alertCount": alert_count,
            "alertTitle": alert_title,
            "alertMethod": alert_method,
            "downloadAccountID": download_account_id,
            "sourceAccountIDs": source_account_ids,
            "secret": secret,
        }
        return await client.post("/cronjobs/update", body)

    @mcp.tool()
    async def cronjob_delete(
        ids: Annotated[list[int], Field(description="要删除的计划任务 ID 列表，支持批量")],
        confirm: Annotated[bool, Field(description="删除是高危操作，必须传 true")] = False,
        clean_data: Annotated[bool, Field(description="是否清理本地备份数据")] = False,
        clean_remote_data: Annotated[bool, Field(description="是否清理远程备份数据")] = False,
    ) -> dict:
        """⚠️高危 [计划任务] 删除计划任务。

        批量删除任务，可同时清理其产生的备份文件。不可恢复，必须显式传
        confirm=true。对应 POST /cronjobs/del。

        Args:
            ids: 要删除的任务 ID 列表，支持批量。
            confirm: 必须为 true 才执行删除。
            clean_data: 是否同时删除本地备份文件。
            clean_remote_data: 是否同时删除远程备份文件。
        """
        require_write()
        if not confirm:
            raise ValueError("删除计划任务是高危操作，必须显式传 confirm=true。")
        client = await get_client()
        return await client.post("/cronjobs/del", {
            "ids": ids,
            "cleanData": clean_data,
            "cleanRemoteData": clean_remote_data,
        })

    @mcp.tool()
    async def cronjob_group_update(
        id: Annotated[int, Field(description="计划任务 ID")],
        group_id: Annotated[int, Field(description="目标分组 ID，0 表示无分组")],
    ) -> dict:
        """⚠️写操作 [计划任务] 修改任务所属分组。

        把任务移动到指定分组。对应 POST /cronjobs/group/update。

        Args:
            id: 计划任务 ID。
            group_id: 目标分组 ID，0 表示无分组。
        """
        require_write()
        client = await get_client()
        return await client.post("/cronjobs/group/update", {
            "id": id, "groupID": group_id,
        })

    # ---- 执行控制 ----

    @mcp.tool()
    async def cronjob_run(
        id: Annotated[int, Field(description="计划任务 ID")],
    ) -> dict:
        """⚠️写操作 [计划任务] 手动执行一次任务。

        立即触发一次任务执行（不影响原 cron 调度），返回执行记录 ID 等。
        对应 POST /cronjobs/handle。

        Args:
            id: 计划任务 ID。
        """
        require_write()
        client = await get_client()
        return await client.post("/cronjobs/handle", {"id": id})

    @mcp.tool()
    async def cronjob_stop(
        id: Annotated[int, Field(description="计划任务 ID")],
    ) -> dict:
        """⚠️写操作 [计划任务] 终止正在运行的任务执行。

        停止某任务当前正在进行的执行（仅对正在运行的记录有效）。
        对应 POST /cronjobs/stop。

        Args:
            id: 计划任务 ID。
        """
        require_write()
        client = await get_client()
        return await client.post("/cronjobs/stop", {"id": id})

    @mcp.tool()
    async def cronjob_status(
        id: Annotated[int, Field(description="计划任务 ID")],
        enable: Annotated[bool, Field(description="true=启用任务，false=禁用任务")] = True,
    ) -> dict:
        """⚠️写操作 [计划任务] 启用/禁用任务。

        切换任务的启停状态（禁用后 cron 不再触发，但保留配置）。对应
        POST /cronjobs/status。

        Args:
            id: 计划任务 ID。
            enable: true=启用，false=禁用。
        """
        require_write()
        client = await get_client()
        return await client.post("/cronjobs/status", {
            "id": id,
            "status": "enable" if enable else "disable",
        })

    # ---- 记录清理 ----

    @mcp.tool()
    async def cronjob_records_clean(
        cronjob_id: Annotated[int, Field(description="计划任务 ID")],
        confirm: Annotated[bool, Field(description="清理是不可逆操作，必须传 true")] = False,
        is_delete: Annotated[bool, Field(description="是否为删除任务触发的清理（内部标记，一般 false）")] = False,
        clean_data: Annotated[bool, Field(description="是否清理本地备份数据")] = False,
        clean_remote_data: Annotated[bool, Field(description="是否清理远程备份数据")] = False,
    ) -> dict:
        """⚠️高危 [计划任务] 清理任务的历史执行记录及备份数据。

        删除指定任务的所有历史执行记录，可选同时清理备份文件。不可恢复，
        必须显式传 confirm=true。对应 POST /cronjobs/records/clean。

        Args:
            cronjob_id: 计划任务 ID。
            confirm: 必须为 true 才执行清理。
            is_delete: 是否为删除任务触发的清理，一般传 false。
            clean_data: 是否同时清理本地备份文件。
            clean_remote_data: 是否同时清理远程备份文件。
        """
        require_write()
        if not confirm:
            raise ValueError("清理执行记录是高危操作，必须显式传 confirm=true。")
        client = await get_client()
        return await client.post("/cronjobs/records/clean", {
            "cronjobID": cronjob_id,
            "isDelete": is_delete,
            "cleanData": clean_data,
            "cleanRemoteData": clean_remote_data,
        })

    # ---- 导入 / 导出 ----

    @mcp.tool()
    async def cronjob_export(
        ids: Annotated[list[int], Field(description="要导出的任务 ID 列表")],
    ) -> dict:
        """[计划任务] 导出计划任务配置（可跨实例迁移）。读操作。

        导出选中任务的配置 JSON（不包含执行记录与备份文件），用于在另一个
        1Panel 实例上导入。对应 POST /cronjobs/export。

        Args:
            ids: 要导出的任务 ID 列表。
        """
        client = await get_client()
        return await client.post("/cronjobs/export", {"ids": ids})

    @mcp.tool()
    async def cronjob_import(
        cronjobs: Annotated[str, Field(description="由 cronjob_export 导出的 JSON 字符串，包含任务配置数组")],
    ) -> dict:
        """⚠️写操作 [计划任务] 导入计划任务配置。

        将 cronjob_export 导出的配置导入当前 1Panel 实例（创建新任务，不覆盖
        已有任务）。对应 POST /cronjobs/import。

        Args:
            cronjobs: 导出的任务配置 JSON 字符串（即 export 返回的 cronjobs 数组）。
        """
        require_write()
        client = await get_client()
        return await client.post("/cronjobs/import", {"cronjobs": cronjobs})
