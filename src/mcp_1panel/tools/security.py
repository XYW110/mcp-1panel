"""安全工具箱模块（对应 openapi.json 的 Clam / Fail2ban / FTP 三个 tag，共 27 个端点）。

覆盖 1Panel "工具箱" 下的三类安全功能：
- Clam：ClamAV 病毒扫描（扫描规则、扫描记录、配置文件、服务状态）
- Fail2ban：SSH 暴力破解防护（封禁/白名单 IP、jail 配置）
- FTP：FTP 账号管理（增删改查、同步、操作日志）

风格照 container.py（黄金范式）：
1. 工具名：<module>_<object>_<action>（clam_rule_search / fail2ban_conf_update / ...）
2. description：[模块] 开头，写操作加 ⚠️，高危（delete）加 confirm 参数，便于 mcphub 召回
3. 入参用 Annotated[T, Field(description=...)]，枚举用 Literal
4. handler 用 `await get_client()` 拿共享客户端，调 .search() / .post() / .get()
5. 写操作开头调 require_write()，delete 额外加 confirm 参数

接口来源：references/openapi.json 的 /toolbox/clam|fail2ban|ftp/* 路径，basePath /api/v2。
"""

from __future__ import annotations

from typing import Annotated, Literal, Optional

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..client import get_client
from ..safety import require_write


# ---- 枚举（来自 openapi.json 的 schema enum，避免运行时传错值）----

# Clam 扫描规则排序字段（dto.SearchClamWithPage.orderBy）
ClamRuleOrderBy = Literal["name", "status", "createdAt"]
# Clam 扫描规则排序方向（dto.SearchClamWithPage.order 含 "null"，工具层不暴露）
ClamSortOrder = Literal["ascending", "descending"]
# Fail2ban IP 状态（dto.Fail2BanSearch.status / dto.Fail2BanSet.operate）
Fail2banIpStatus = Literal["banned", "ignore"]
# Fail2ban 配置项 key（dto.Fail2BanUpdate.key）
Fail2banConfKey = Literal[
    "port", "bantime", "findtime", "maxretry", "banaction", "logpath",
]


def register(mcp: FastMCP) -> None:

    # ================================================================
    # Clam（ClamAV 病毒扫描）—— 12 个端点
    # ================================================================

    # ---- 服务状态 / 配置文件（读）----

    @mcp.tool()
    async def clam_status() -> dict:
        """[Clam] 查询 ClamAV 服务状态（是否安装/运行、版本、病毒库版本）。读操作。

        返回 ClamBaseInfo：isExist 是否已安装、isActive 是否在运行、version 引擎版本、
        freshIsExist/freshIsActive/freshVersion 为 freshclam 病毒库更新器状态。
        对应 POST /toolbox/clam/base。

        依赖宿主机已安装 ClamAV（1Panel 不内置），未安装时 isExist=false。
        """
        client = await get_client()
        return await client.post("/toolbox/clam/base", {})

    @mcp.tool()
    async def clam_setting_get(
        name: Annotated[str, Field(description="配置文件名，如 clamd.conf / freshclam.conf")],
        tail: Annotated[str, Field(description="读取方式/尾部行数等附加参数，一般留空")] = "",
    ) -> dict:
        """[Clam] 读取 ClamAV 配置文件内容。读操作。

        返回指定 ClamAV 配置文件的文本内容（如 clamd.conf、freshclam.conf）。
        对应 POST /toolbox/clam/file/search，schema dto.ClamFileReq。

        Args:
            name: 配置文件名。
            tail: 附加参数，通常留空。
        """
        client = await get_client()
        return await client.post("/toolbox/clam/file/search", {
            "name": name, "tail": tail,
        })

    @mcp.tool()
    async def clam_scan_search(
        clam_id: Annotated[int, Field(description="扫描规则 ID（clam_rule_search 返回的 id）")],
        page: Annotated[int, Field(ge=1, description="页码")] = 1,
        page_size: Annotated[int, Field(ge=1, le=500, description="每页数量")] = 20,
        status: Annotated[str, Field(description="按扫描结果状态过滤，留空返回全部")] = "",
        start_time: Annotated[str, Field(description="起始时间，如 2024-01-01 00:00:00，留空不过滤")] = "",
        end_time: Annotated[str, Field(description="结束时间，留空不过滤")] = "",
    ) -> dict:
        """[Clam] 分页查询某扫描规则的病毒扫描记录。读操作。

        返回该规则历次扫描的报告（扫描时间、发现威胁数、状态等）。
        对应 POST /toolbox/clam/record/search，schema dto.ClamLogSearch。
        注意此接口无 orderBy/order，仅 page/pageSize 必填。

        Args:
            clam_id: 扫描规则 ID。
            page: 页码。
            page_size: 每页数量。
            status: 按扫描状态过滤。
            start_time: 起始时间字符串。
            end_time: 结束时间字符串。
        """
        client = await get_client()
        body: dict = {"page": page, "pageSize": page_size, "clamID": clam_id}
        if status:
            body["status"] = status
        if start_time:
            body["startTime"] = start_time
        if end_time:
            body["endTime"] = end_time
        return await client.post("/toolbox/clam/record/search", body)

    @mcp.tool()
    async def clam_rule_search(
        info: Annotated[str, Field(description="规则名/路径模糊匹配，留空返回全部")] = "",
        page: Annotated[int, Field(ge=1, description="页码")] = 1,
        page_size: Annotated[int, Field(ge=1, le=500, description="每页数量")] = 100,
        order_by: Annotated[ClamRuleOrderBy, Field(description="排序字段：name/status/createdAt")] = "createdAt",
        order: Annotated[ClamSortOrder, Field(description="排序方向")] = "descending",
    ) -> dict:
        """[Clam] 分页查询病毒扫描规则列表。读操作。

        返回所有扫描规则（名称、扫描路径、感染处理策略、告警配置、状态等）。
        对应 POST /toolbox/clam/search，schema dto.SearchClamWithPage。

        Args:
            info: 名称/路径模糊匹配。
            page: 页码。
            page_size: 每页数量。
            order_by: 排序字段。
            order: 排序方向。
        """
        client = await get_client()
        return await client.search(
            "/toolbox/clam/search",
            filters={"info": info or ""},
            page=page, page_size=page_size, order_by=order_by, order=order,
        )

    # ---- 扫描执行 / 记录清理（写）----

    @mcp.tool()
    async def clam_scan_run(
        clam_id: Annotated[int, Field(description="要执行扫描的规则 ID")],
    ) -> dict:
        """⚠️写操作 [Clam] 立即触发一次病毒扫描。

        对指定规则立即执行 ClamAV 扫描（异步任务，扫描完成后记录写入扫描记录）。
        对应 POST /toolbox/clam/handle，schema dto.OperateByID。

        Args:
            clam_id: 扫描规则 ID。
        """
        require_write()
        client = await get_client()
        return await client.post("/toolbox/clam/handle", {"id": clam_id})

    @mcp.tool()
    async def clam_scan_record_clean(
        clam_id: Annotated[int, Field(description="要清空扫描记录的规则 ID")],
    ) -> dict:
        """⚠️写操作 [Clam] 清空指定规则的病毒扫描记录。

        删除该规则的所有历史扫描报告（不影响规则本身）。不可恢复。
        对应 POST /toolbox/clam/record/clean，schema dto.OperateByID。

        Args:
            clam_id: 扫描规则 ID。
        """
        require_write()
        client = await get_client()
        return await client.post("/toolbox/clam/record/clean", {"id": clam_id})

    # ---- 配置文件写入（写）----

    @mcp.tool()
    async def clam_setting_update(
        name: Annotated[str, Field(description="配置文件名，如 clamd.conf / freshclam.conf")],
        file: Annotated[str, Field(description="完整的配置文件新内容")],
    ) -> dict:
        """⚠️写操作 [Clam] 更新 ClamAV 配置文件内容。

        覆盖写入指定配置文件（clamd.conf / freshclam.conf 等）。
        误改配置可能导致 ClamAV 无法启动，修改前建议先用 clam_setting_get 备份原内容。
        对应 POST /toolbox/clam/file/update，schema dto.UpdateByNameAndFile。

        Args:
            name: 配置文件名。
            file: 完整的新文件内容。
        """
        require_write()
        client = await get_client()
        return await client.post("/toolbox/clam/file/update", {
            "name": name, "file": file,
        })

    # ---- 扫描规则增删改（写 / 高危）----

    @mcp.tool()
    async def clam_rule_create(
        name: Annotated[str, Field(description="规则名称")],
        path: Annotated[str, Field(description="要扫描的目录绝对路径")],
        spec: Annotated[str, Field(description="cron 调度表达式，如 '0 3 * * *'（每天 3 点）；留空表示仅手动扫描")] = "",
        infected_dir: Annotated[str, Field(description="感染文件隔离目录绝对路径")] = "",
        infected_strategy: Annotated[str, Field(description="发现感染文件的处理策略，如 move/copy/delete/none")] = "none",
        alert_count: Annotated[int, Field(ge=0, description="触发告警的最小感染文件数，0 表示不告警")] = 0,
        alert_method: Annotated[str, Field(description="告警方式，留空表示不告警")] = "",
        alert_title: Annotated[str, Field(description="告警标题")] = "",
        description: Annotated[str, Field(description="规则描述")] = "",
        timeout: Annotated[int, Field(ge=0, description="单次扫描超时秒数，0 表示不限制")] = 0,
        status: Annotated[str, Field(description="启用状态，启用传 enable")] = "enable",
    ) -> dict:
        """⚠️写操作 [Clam] 创建病毒扫描规则。

        新建一条 ClamAV 扫描规则（含扫描路径、调度、感染处理、告警）。
        对应 POST /toolbox/clam，schema dto.ClamCreate。

        Args:
            name: 规则名称。
            path: 要扫描的目录。
            spec: cron 表达式，留空仅手动扫描。
            infected_dir: 感染文件隔离目录。
            infected_strategy: 感染处理策略（move/copy/delete/none）。
            alert_count: 告警阈值。
            alert_method: 告警方式。
            alert_title: 告警标题。
            description: 规则描述。
            timeout: 扫描超时秒数。
            status: 启用状态。
        """
        require_write()
        client = await get_client()
        return await client.post("/toolbox/clam", {
            "name": name, "path": path, "spec": spec,
            "infectedDir": infected_dir, "infectedStrategy": infected_strategy,
            "alertCount": alert_count, "alertMethod": alert_method,
            "alertTitle": alert_title, "description": description,
            "timeout": timeout, "status": status,
        })

    @mcp.tool()
    async def clam_rule_update(
        rule_id: Annotated[int, Field(description="规则 ID")],
        name: Annotated[str, Field(description="规则名称")],
        path: Annotated[str, Field(description="要扫描的目录绝对路径")],
        spec: Annotated[str, Field(description="cron 调度表达式，留空表示仅手动扫描")] = "",
        infected_dir: Annotated[str, Field(description="感染文件隔离目录绝对路径")] = "",
        infected_strategy: Annotated[str, Field(description="发现感染文件的处理策略")] = "none",
        alert_count: Annotated[int, Field(ge=0, description="告警阈值")] = 0,
        alert_method: Annotated[str, Field(description="告警方式")] = "",
        alert_title: Annotated[str, Field(description="告警标题")] = "",
        description: Annotated[str, Field(description="规则描述")] = "",
        timeout: Annotated[int, Field(ge=0, description="扫描超时秒数")] = 0,
    ) -> dict:
        """⚠️写操作 [Clam] 更新病毒扫描规则。

        修改已存在的扫描规则（id 之外的参数同 clam_rule_create）。
        对应 POST /toolbox/clam/update，schema dto.ClamUpdate。

        Args:
            rule_id: 规则 ID。
            name/path/spec/...: 同 clam_rule_create。
        """
        require_write()
        client = await get_client()
        return await client.post("/toolbox/clam/update", {
            "id": rule_id, "name": name, "path": path, "spec": spec,
            "infectedDir": infected_dir, "infectedStrategy": infected_strategy,
            "alertCount": alert_count, "alertMethod": alert_method,
            "alertTitle": alert_title, "description": description,
            "timeout": timeout,
        })

    @mcp.tool()
    async def clam_rule_status_update(
        rule_id: Annotated[int, Field(description="规则 ID")],
        status: Annotated[Literal["enable", "disable"], Field(description="目标状态：enable 启用 / disable 停用")],
    ) -> dict:
        """⚠️写操作 [Clam] 启用/停用扫描规则。

        切换扫描规则的启用状态（停用后不再按 cron 自动扫描，但可手动扫描）。
        对应 POST /toolbox/clam/status/update，schema dto.ClamUpdateStatus。

        Args:
            rule_id: 规则 ID。
            status: enable 启用 / disable 停用。
        """
        require_write()
        client = await get_client()
        return await client.post("/toolbox/clam/status/update", {
            "id": rule_id, "status": status,
        })

    @mcp.tool()
    async def clam_rule_delete(
        ids: Annotated[list[int], Field(description="要删除的规则 ID 列表，支持批量")],
        remove_infected: Annotated[bool, Field(description="是否同时删除隔离目录下的感染文件")] = False,
        confirm: Annotated[bool, Field(description="删除是高危操作，必须传 true")] = False,
    ) -> dict:
        """⚠️高危 [Clam] 删除病毒扫描规则。

        删除指定扫描规则（可批量）。不可恢复。
        对应 POST /toolbox/clam/del，schema dto.ClamDelete。
        必须显式传 confirm=true 才执行。

        Args:
            ids: 规则 ID 列表。
            remove_infected: 是否顺带删除隔离的感染文件。
            confirm: 必须为 true 才执行删除。
        """
        require_write()
        if not confirm:
            raise ValueError("删除扫描规则是高危操作，必须显式传 confirm=true。")
        client = await get_client()
        return await client.post("/toolbox/clam/del", {
            "ids": ids, "removeInfected": remove_infected,
        })

    @mcp.tool()
    async def clam_operate(
        operation: Annotated[Literal["freshclam"], Field(description="操作类型，目前支持 freshclam（更新病毒库）")],
    ) -> dict:
        """⚠️写操作 [Clam] 执行 ClamAV 服务级操作（如更新病毒库）。

        对应 POST /toolbox/clam/operate，schema dto.Operate。
        常用 operation=freshclam 触发病毒库更新。

        Args:
            operation: 操作名，freshclam 更新病毒库。
        """
        require_write()
        client = await get_client()
        return await client.post("/toolbox/clam/operate", {"operation": operation})

    # ================================================================
    # Fail2ban（SSH 暴力破解防护）—— 7 个端点
    # ================================================================

    # ---- 状态 / 配置读取（读）----

    @mcp.tool()
    async def fail2ban_status() -> dict:
        """[Fail2ban] 查询 Fail2ban 服务状态（是否安装/运行）。读操作。

        返回 isExist 是否安装、isActive 是否在运行等基础信息。
        对应 GET /toolbox/fail2ban/base。

        依赖宿主机已安装 fail2ban 服务。
        """
        client = await get_client()
        return await client.get("/toolbox/fail2ban/base")

    @mcp.tool()
    async def fail2ban_conf_get() -> dict:
        """[Fail2ban] 读取 sshd jail 配置（jail.conf / jail.local）。读操作。

        返回 fail2ban 的 sshd 监狱配置项（port、bantime、findtime、maxretry、
        banaction、logpath 等）。对应 GET /toolbox/fail2ban/load/conf。
        """
        client = await get_client()
        return await client.get("/toolbox/fail2ban/load/conf")

    @mcp.tool()
    async def fail2ban_ssh_search(
        status: Annotated[Fail2banIpStatus, Field(description="查询 banned（已封禁 IP）或 ignore（白名单 IP）")],
    ) -> dict:
        """[Fail2ban] 查询 SSH 封禁记录（已封禁 IP 列表或白名单）。读操作。

        按状态返回 IP 列表：status=banned 返回当前被封禁的 IP（含封禁时间、
        封禁原因等），status=ignore 返回白名单 IP。对应 POST /toolbox/fail2ban/search，
        schema dto.Fail2BanSearch。

        Args:
            status: banned 已封禁 / ignore 白名单。
        """
        client = await get_client()
        return await client.post("/toolbox/fail2ban/search", {"status": status})

    # ---- 配置写入（写）----

    @mcp.tool()
    async def fail2ban_conf_update(
        key: Annotated[Fail2banConfKey, Field(description="配置项 key：port/bantime/findtime/maxretry/banaction/logpath")],
        value: Annotated[str, Field(description="配置项新值")],
    ) -> dict:
        """⚠️写操作 [Fail2ban] 修改 sshd jail 单项配置。

        修改 fail2ban sshd 监狱的某个配置项（如 maxretry=5、bantime=1h）。
        对应 POST /toolbox/fail2ban/update，schema dto.Fail2BanUpdate。

        Args:
            key: 配置项 key。
            value: 新值（字符串形式，如 "5"、"1h"、"/var/log/auth.log"）。
        """
        require_write()
        client = await get_client()
        return await client.post("/toolbox/fail2ban/update", {"key": key, "value": value})

    @mcp.tool()
    async def fail2ban_conf_update_byconf(
        file: Annotated[str, Field(description="完整的 jail 配置文件内容")],
    ) -> dict:
        """⚠️写操作 [Fail2ban] 用整份配置文件内容覆盖更新 sshd jail 配置。

        直接写入完整的 jail 配置文件（比单项修改更强力，但误改风险更高）。
        建议先用 fail2ban_conf_get 取出当前内容再改。对应 POST /toolbox/fail2ban/update/byconf，
        schema dto.UpdateByFile。

        Args:
            file: 完整的配置文件内容。
        """
        require_write()
        client = await get_client()
        return await client.post("/toolbox/fail2ban/update/byconf", {"file": file})

    # ---- IP 封禁 / 服务操作（写）----

    @mcp.tool()
    async def fail2ban_ssh_operate(
        operate: Annotated[Fail2banIpStatus, Field(description="banned 封禁这些 IP / ignore 加入白名单")],
        ips: Annotated[list[str], Field(description="IP 地址列表")] = [],
    ) -> dict:
        """⚠️写操作 [Fail2ban] 封禁 IP 或加入白名单。

        手动封禁 IP（operate=banned）或将 IP 加入白名单（operate=ignore）。
        对应 POST /toolbox/fail2ban/operate/sshd，schema dto.Fail2BanSet。

        Args:
            operate: banned 封禁 / ignore 白名单。
            ips: IP 地址列表。
        """
        require_write()
        client = await get_client()
        return await client.post("/toolbox/fail2ban/operate/sshd", {
            "operate": operate, "ips": ips,
        })

    @mcp.tool()
    async def fail2ban_operate(
        operation: Annotated[Literal["start", "stop", "restart"], Field(description="服务操作：start/stop/restart")],
    ) -> dict:
        """⚠️写操作 [Fail2ban] 控制 Fail2ban 服务（启动/停止/重启）。

        对应 POST /toolbox/fail2ban/operate，schema dto.Operate。
        服务未安装时调用会失败。

        Args:
            operation: start 启动 / stop 停止 / restart 重启。
        """
        require_write()
        client = await get_client()
        return await client.post("/toolbox/fail2ban/operate", {"operation": operation})

    # ================================================================
    # FTP 账号管理 —— 8 个端点
    # ================================================================

    # ---- 列表 / 状态 / 日志（读）----

    @mcp.tool()
    async def ftp_status() -> dict:
        """[FTP] 查询 FTP 服务状态（是否安装/运行）。读操作。

        返回 isExist 是否安装、isActive 是否在运行等基础信息。
        对应 GET /toolbox/ftp/base。
        """
        client = await get_client()
        return await client.get("/toolbox/ftp/base")

    @mcp.tool()
    async def ftp_search(
        info: Annotated[str, Field(description="用户名模糊匹配，留空返回全部")] = "",
        page: Annotated[int, Field(ge=1, description="页码")] = 1,
        page_size: Annotated[int, Field(ge=1, le=500, description="每页数量")] = 100,
    ) -> dict:
        """[FTP] 分页查询 FTP 账号列表。读操作。

        返回所有 FTP 账号（用户名、家目录、状态、描述等）。
        对应 POST /toolbox/ftp/search，schema dto.SearchWithPage。
        注意此接口无 orderBy/order，仅 page/pageSize 必填。

        Args:
            info: 用户名模糊匹配。
            page: 页码。
            page_size: 每页数量。
        """
        client = await get_client()
        return await client.post("/toolbox/ftp/search", {
            "info": info or "", "page": page, "pageSize": page_size,
        })

    @mcp.tool()
    async def ftp_log_search(
        page: Annotated[int, Field(ge=1, description="页码")] = 1,
        page_size: Annotated[int, Field(ge=1, le=500, description="每页数量")] = 100,
        user: Annotated[str, Field(description="按 FTP 用户名过滤，留空返回全部")] = "",
        operation: Annotated[str, Field(description="按操作类型过滤，留空返回全部")] = "",
    ) -> dict:
        """[FTP] 分页查询 FTP 操作日志。读操作。

        返回 FTP 账号的操作记录（登录、上传、下载等）。对应 POST /toolbox/ftp/log/search，
        schema dto.FtpLogSearch。

        Args:
            page: 页码。
            page_size: 每页数量。
            user: 按用户名过滤。
            operation: 按操作类型过滤。
        """
        client = await get_client()
        body: dict = {"page": page, "pageSize": page_size}
        if user:
            body["user"] = user
        if operation:
            body["operation"] = operation
        return await client.post("/toolbox/ftp/log/search", body)

    # ---- 增删改 / 同步（写 / 高危）----

    @mcp.tool()
    async def ftp_create(
        user: Annotated[str, Field(description="FTP 用户名")],
        password: Annotated[str, Field(description="FTP 登录密码")],
        path: Annotated[str, Field(description="FTP 家目录绝对路径")],
        description: Annotated[str, Field(description="账号描述")] = "",
    ) -> dict:
        """⚠️写操作 [FTP] 创建 FTP 账号。

        新建一个 FTP 账号（含用户名、密码、家目录）。对应 POST /toolbox/ftp，
        schema dto.FtpCreate。

        Args:
            user: 用户名。
            password: 密码。
            path: 家目录绝对路径。
            description: 账号描述。
        """
        require_write()
        client = await get_client()
        return await client.post("/toolbox/ftp", {
            "user": user, "password": password, "path": path,
            "description": description,
        })

    @mcp.tool()
    async def ftp_update(
        ftp_id: Annotated[int, Field(description="FTP 账号 ID")],
        password: Annotated[str, Field(description="FTP 登录密码（如不修改也需传入当前密码）")],
        path: Annotated[str, Field(description="FTP 家目录绝对路径")],
        description: Annotated[str, Field(description="账号描述")] = "",
        status: Annotated[str, Field(description="启用状态，如 enable/disable")] = "",
    ) -> dict:
        """⚠️写操作 [FTP] 修改 FTP 账号。

        更新 FTP 账号的密码、家目录、描述、状态等。对应 POST /toolbox/ftp/update，
        schema dto.FtpUpdate。

        Args:
            ftp_id: 账号 ID。
            password: 密码（API 要求必传）。
            path: 家目录绝对路径。
            description: 账号描述。
            status: 启用状态。
        """
        require_write()
        client = await get_client()
        return await client.post("/toolbox/ftp/update", {
            "id": ftp_id, "password": password, "path": path,
            "description": description, "status": status,
        })

    @mcp.tool()
    async def ftp_delete(
        ids: Annotated[list[int], Field(description="要删除的 FTP 账号 ID 列表，支持批量")],
        confirm: Annotated[bool, Field(description="删除是高危操作，必须传 true")] = False,
    ) -> dict:
        """⚠️高危 [FTP] 删除 FTP 账号。

        删除指定 FTP 账号（可批量）。不可恢复。对应 POST /toolbox/ftp/del，
        schema dto.BatchDeleteReq。必须显式传 confirm=true 才执行。

        Args:
            ids: 账号 ID 列表。
            confirm: 必须为 true 才执行删除。
        """
        require_write()
        if not confirm:
            raise ValueError("删除 FTP 账号是高危操作，必须显式传 confirm=true。")
        client = await get_client()
        return await client.post("/toolbox/ftp/del", {"ids": ids})

    @mcp.tool()
    async def ftp_operate(
        operation: Annotated[Literal["start", "stop", "restart"], Field(description="服务操作：start/stop/restart")],
    ) -> dict:
        """⚠️写操作 [FTP] 控制 FTP 服务（启动/停止/重启）。

        对应 POST /toolbox/ftp/operate，schema dto.Operate。

        Args:
            operation: start 启动 / stop 停止 / restart 重启。
        """
        require_write()
        client = await get_client()
        return await client.post("/toolbox/ftp/operate", {"operation": operation})

    @mcp.tool()
    async def ftp_sync(
        ids: Annotated[list[int], Field(description="要同步的 FTP 账号 ID 列表")],
    ) -> dict:
        """⚠️写操作 [FTP] 同步 FTP 账号（重建本地配置）。

        当 FTP 后端配置与数据库不一致时，按 ID 重新同步账号配置。
        对应 POST /toolbox/ftp/sync，schema dto.BatchDeleteReq。

        Args:
            ids: 要同步的账号 ID 列表。
        """
        require_write()
        client = await get_client()
        return await client.post("/toolbox/ftp/sync", {"ids": ids})
