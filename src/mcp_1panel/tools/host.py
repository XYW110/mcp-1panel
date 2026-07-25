"""主机模块（对应 openapi.json 的 Host / SSH / Process / Device /
Disk Management / Host tool / Logs / Command tag，约 40+ 接口）。

覆盖范围：
- 主机 Host：本机系统资源概览（device/base）、远程主机节点管理（/core/hosts/*）
- 进程 Process：按 PID 查进程 / 监听端口的进程 / 停止进程
- SSH：SSH 设置读写（sshd_config）、SSH 密钥（生成 / 列表 / 删除 / 同步）、SSH 登录日志
- 设备 Device：系统基础信息、DNS / 主机名 / 时区 / Swap / 密码等系统配置
- 磁盘 Disk：磁盘 / 分区概览、挂载 / 卸载 / 分区
- Host tool：supervisord 守护进程工具的状态 / 配置 / 进程管理
- Logs：登录日志 / 操作日志 / 系统日志文件列表
- Command：命令片段库（CRUD）+ 命令执行（command_run，⚠️高危）

实现风格照搬 container.py 黄金范式：
1. 工具名 host_<object>_<action>，按子域分组（host_ / process_ / ssh_ / device_ /
   disk_ / host_tool_ / logs_ / command_）便于 mcphub 向量检索按模块召回
2. description 结构化（[主机] 等模块前缀开头，写操作加 ⚠️，高危加 confirm 提示）
3. 入参用 Annotated[T, Field(description=...)]，枚举用 Literal
4. 写操作 handler 第一行 require_write()，高危操作（stop/delete/run/clean/mount
   等破坏性 / 执行性操作）加 confirm 参数并显著标注 ⚠️高危

接口来源：references/openapi.json，basePath /api/v2，路径不含前缀。

安全分层：
- 读：host_info / host_monitor / process_info / ssh_info / ssh_conf_get /
  device_base / disk_list / host_tool_status / logs_login / logs_operation /
  command_list / command_search / command_tree
- 写：ssh_conf_update / ssh_generate / ssh_operate / disk_mount / disk_unmount /
  disk_partition / device_update_* / host_tool_operate / command_create /
  command_update / command_delete → require_write()
- 高危（confirm + 显著 ⚠️ 标注）：command_run（任意 shell）/ process_stop /
  ssh_delete / logs_clean / command_import / command_export
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Optional

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..client import get_client
from ..safety import require_write


# ---- 枚举 / 类型别名（取自 openapi.json definitions 的 enum）----

# 监控指标维度（dto.MonitorSearch.param）：复用 monitor 模块同一后端接口
HostMonitorParam = Literal["all", "cpu", "memory", "load", "io", "network"]
# SSH 密钥加密算法（dto.RootCertOperate.encryptionMode）
SSHEncryptionMode = Literal["rsa", "ed25519", "ecdsa", "dsa"]
# SSH 登录日志状态（dto.SearchSSHLog.Status）
SSHLogStatus = Literal["Success", "Failed", "All"]
# 磁盘文件系统（request.DiskMountRequest.filesystem）
DiskFilesystem = Literal["ext4", "xfs"]
# Host tool 类型与操作（request.HostToolReq）
HostToolType = Literal["supervisord"]
HostToolOperate = Literal["status", "restart", "start", "stop"]
# Host tool config 操作（request.HostToolConfig.operate）
HostToolConfigOperate = Literal["get", "set"]
# Supervisor 进程文件类型与操作（request.SupervisorProcessFileReq）
SupervisorProcessFile = Literal["out.log", "err.log", "config"]
SupervisorProcessFileOperate = Literal["get", "clear", "update"]
# 日志清理类型（dto.CleanLog.logType）
CleanLogType = Literal["login", "operation"]


def register(mcp: FastMCP) -> None:

    # ================================================================
    # 主机系统资源概览（Host / Device base）
    # device/base 返回 CPU/内存/磁盘/网络/系统版本等本机硬件与 OS 概览
    # ================================================================

    @mcp.tool()
    async def host_info() -> dict:
        """[主机] 获取本机系统硬件与 OS 概览（CPU/内存/磁盘/内核/发行版）。读操作。

        返回 1Panel「主机」首页的概览数据：CPU 核数与型号、内存总量、磁盘使用、
        内核版本、发行版、运行时长等。对应 POST /toolbox/device/base。

        这是查看「这台主机是什么配置」的统一入口。
        """
        client = await get_client()
        return await client.post("/toolbox/device/base", {})

    @mcp.tool()
    async def host_monitor(
        param: Annotated[HostMonitorParam, Field(description="监控维度：all/cpu/memory/load/io/network")] = "all",
        start_time: Annotated[Optional[str], Field(description="起始时间，格式 YYYY-MM-DD HH:mm:ss，留空由 1Panel 取默认范围")] = None,
        end_time: Annotated[Optional[str], Field(description="结束时间，格式 YYYY-MM-DD HH:mm:ss")] = None,
        network: Annotated[Optional[str], Field(description="网卡名，param=network 时必填，如 eth0")] = None,
        io: Annotated[Optional[str], Field(description="块设备名，param=io 时必填，如 sda")] = None,
    ) -> dict:
        """[主机] 查询本机系统资源监控历史（CPU/内存/负载/IO/网络）。读操作。

        返回一段时间内系统资源使用率的采样序列（date + value 数组）。
        对应 POST /hosts/monitor/search（与 monitor 模块同一后端接口）。

        Args:
            param: 监控维度：all（全部）/cpu/memory/load/io/network。
            start_time: 起始时间，格式 "YYYY-MM-DD HH:mm:ss"。
            end_time: 结束时间，格式同上。
            network: 网卡名，param=network 时必填。
            io: 块设备名，param=io 时必填。
        """
        client = await get_client()
        body: dict[str, Any] = {"param": param}
        if start_time:
            body["startTime"] = start_time
        if end_time:
            body["endTime"] = end_time
        if network:
            body["network"] = network
        if io:
            body["io"] = io
        return await client.post("/hosts/monitor/search", body)

    # ================================================================
    # 进程（Process）
    # ================================================================

    @mcp.tool()
    async def process_search(
        pid: Annotated[int, Field(description="进程 PID，如 1；用于按 PID 查进程详情")] = 1,
    ) -> dict:
        """[进程] 按 PID 查询进程详情（名称/命令行/CPU/内存/用户）。读操作。

        1Panel v2 的进程接口是按 PID 精确查询（无全量列表）。返回该进程的命令行、
        CPU/内存占用、所属用户等。对应 GET /process/{pid}。

        Args:
            pid: 进程 PID，如 1（init/systemd）。
        """
        client = await get_client()
        return await client.get(f"/process/{pid}")

    @mcp.tool()
    async def process_listening() -> dict:
        """[进程] 查询监听端口的进程列表（端口占用排查）。读操作。

        返回所有正在监听 TCP/UDP 端口的进程（PID、进程名、端口、协议、地址），
        常用于排查端口被哪个进程占用。对应 POST /process/listening。
        """
        client = await get_client()
        return await client.post("/process/listening", {})

    @mcp.tool()
    async def process_stop(
        pid: Annotated[int, Field(description="要停止的进程 PID")],
        confirm: Annotated[bool, Field(description="停止进程是高危操作，必须传 true")] = False,
    ) -> dict:
        """⚠️高危 [进程] 停止（kill）指定进程。

        向指定 PID 发送终止信号。误杀关键进程（如 systemd、sshd、数据库）会导致
        服务不可用甚至系统宕机，属高危操作。对应 POST /process/stop。
        必须显式传 confirm=true。

        Args:
            pid: 要停止的进程 PID。
            confirm: 必须为 true 才执行停止。
        """
        require_write()
        if not confirm:
            raise ValueError("停止进程是高危操作，必须显式传 confirm=true。")
        client = await get_client()
        return await client.post("/process/stop", {"PID": pid})

    # ================================================================
    # SSH 设置（sshd_config 读写）
    # /hosts/ssh/search 读设置 / /hosts/ssh/update 按 key 改单字段
    # /hosts/ssh/file 读 sshd_config 文件 / /hosts/ssh/file/update 整文件覆盖
    # ================================================================

    @mcp.tool()
    async def ssh_info() -> dict:
        """[SSH] 获取主机 SSH 服务设置概览（端口/状态/密码/密钥认证开关等）。读操作。

        返回 sshd 的关键运行设置（监听端口、是否启用、密码认证、密钥认证、自动登出
        等）。对应 POST /hosts/ssh/search。
        """
        client = await get_client()
        return await client.post("/hosts/ssh/search", {})

    @mcp.tool()
    async def ssh_conf_get(
        name: Annotated[str, Field(description="SSH 配置项标识名，如 sshd_config；参考 1Panel 设置页")],
    ) -> dict:
        """[SSH] 读取 SSH 配置文件原文（sshd_config 等）。读操作。

        返回指定 SSH 配置文件的完整文本内容。对应 POST /hosts/ssh/file。
        常用于查看 /etc/ssh/sshd_config 等配置详情。

        Args:
            name: SSH 配置项名称（参考 1Panel SSH 设置页的下拉项）。
        """
        client = await get_client()
        return await client.post("/hosts/ssh/file", {"name": name})

    @mcp.tool()
    async def ssh_conf_update(
        name: Annotated[str, Field(description="SSH 配置项标识名，需与 ssh_conf_get 的 name 一致")],
        file: Annotated[str, Field(description="SSH 配置文件的完整新内容（整体覆盖写入）")],
    ) -> dict:
        """⚠️写操作 [SSH] 整文件覆盖更新 SSH 配置（sshd_config 等）。

        用传入的 file 内容整体覆盖指定 SSH 配置文件。对应
        POST /hosts/ssh/file/update（dto.SSHConf）。

        ⚠️ 配置错误可能导致 SSH 服务无法启动或无法登录，操作前建议先 ssh_conf_get
        备份原文件内容。

        Args:
            name: SSH 配置项名称（与 ssh_conf_get 一致）。
            file: 配置文件完整新内容，会整体覆盖原文件。
        """
        require_write()
        client = await get_client()
        return await client.post("/hosts/ssh/file/update", {"name": name, "file": file})

    @mcp.tool()
    async def ssh_update(
        key: Annotated[str, Field(description="设置项 key，如 Port / PasswordAuthentication / PubkeyAuthentication")],
        new_value: Annotated[str, Field(description="新值（字符串）")],
        old_value: Annotated[str, Field(default="", description="旧值（部分项校验用，可留空")] = "",
    ) -> dict:
        """⚠️写操作 [SSH] 按 key 单字段更新 SSH 设置。

        逐项修改 SSH 服务设置（如 Port 改端口、PasswordAuthentication 改密码认证）。
        对应 POST /hosts/ssh/update（dto.SSHUpdate）。改完通常会重载 sshd。

        Args:
            key: 设置项 key，参考 ssh_info 返回字段（如 Port、PermitRootLogin）。
            new_value: 新值（字符串）。
            old_value: 旧值，部分敏感项（如端口）需校验原值，留空表示不校验。
        """
        require_write()
        client = await get_client()
        body: dict[str, Any] = {"key": key, "newValue": new_value}
        if old_value:
            body["oldValue"] = old_value
        return await client.post("/hosts/ssh/update", body)

    @mcp.tool()
    async def ssh_operate(
        operation: Annotated[str, Field(description="操作名，如 start/stop/restart 启停 SSH 服务")],
    ) -> dict:
        """⚠️写操作 [SSH] 操作 SSH 服务（启停 / 重启）。

        启动 / 停止 / 重启主机的 SSH 服务。对应 POST /hosts/ssh/operate。
        ⚠️ 停止 SSH 服务后可能无法远程登录，谨慎操作。

        Args:
            operation: 操作名，常用 start/stop/restart。
        """
        require_write()
        client = await get_client()
        return await client.post("/hosts/ssh/operate", {"operation": operation})

    # ---- SSH 密钥（cert）管理 ----

    @mcp.tool()
    async def ssh_generate(
        encryption_mode: Annotated[SSHEncryptionMode, Field(description="密钥加密算法：rsa/ed25519/ecdsa/dsa")],
        name: Annotated[str, Field(default="", description="密钥名称（备注用），留空自动生成")] = "",
        pass_phrase: Annotated[str, Field(default="", description="密钥口令，留空表示不加密私钥")] = "",
        description: Annotated[str, Field(default="", description="密钥描述")] = "",
    ) -> dict:
        """⚠️写操作 [SSH] 生成新的 SSH 密钥对。

        生成一对 SSH 公私钥并纳入 1Panel 管理。对应 POST /hosts/ssh/cert
        （dto.RootCertOperate）。生成的私钥可用于免密登录本机或其他主机。

        Args:
            encryption_mode: 加密算法，推荐 ed25519（更安全更短），兼容性场景用 rsa。
            name: 密钥名称（备注）。
            pass_phrase: 私钥口令，留空生成无口令私钥。
            description: 密钥描述。
        """
        require_write()
        client = await get_client()
        body: dict[str, Any] = {
            "encryptionMode": encryption_mode,
            "name": name,
            "passPhrase": pass_phrase,
            "description": description,
        }
        return await client.post("/hosts/ssh/cert", body)

    @mcp.tool()
    async def ssh_cert_search(
        info: Annotated[str, Field(default="", description="名称模糊匹配")] = "",
        page: Annotated[int, Field(ge=1, description="页码")] = 1,
        page_size: Annotated[int, Field(ge=1, le=500, description="每页数量")] = 100,
    ) -> dict:
        """[SSH] 分页查询 SSH 密钥列表。读操作。

        返回已纳管的 SSH 密钥（名称、算法、公钥指纹、描述等）。
        对应 POST /hosts/ssh/cert/search（dto.SearchWithPage）。

        Args:
            info: 名称模糊匹配。
            page: 页码。
            page_size: 每页数量。
        """
        client = await get_client()
        return await client.post("/hosts/ssh/cert/search", {
            "page": page, "pageSize": page_size, "info": info,
        })

    @mcp.tool()
    async def ssh_cert_update(
        id: Annotated[int, Field(description="密钥 ID")],
        encryption_mode: Annotated[SSHEncryptionMode, Field(description="密钥加密算法")],
        name: Annotated[str, Field(default="", description="密钥名称")] = "",
        description: Annotated[str, Field(default="", description="密钥描述")] = "",
        public_key: Annotated[str, Field(default="", description="公钥内容（导入已有公钥时填）")] = "",
        private_key: Annotated[str, Field(default="", description="私钥内容（导入已有私钥时填）")] = "",
        pass_phrase: Annotated[str, Field(default="", description="私钥口令")] = "",
    ) -> dict:
        """⚠️写操作 [SSH] 更新 / 导入 SSH 密钥。

        更新已存在密钥的元数据，或导入一对已有公私钥。对应
        POST /hosts/ssh/cert/update（dto.RootCertOperate）。

        Args:
            id: 密钥 ID。
            encryption_mode: 加密算法。
            name: 密钥名称。
            description: 密钥描述。
            public_key: 公钥内容（导入场景）。
            private_key: 私钥内容（导入场景）。
            pass_phrase: 私钥口令。
        """
        require_write()
        client = await get_client()
        body: dict[str, Any] = {
            "id": id,
            "encryptionMode": encryption_mode,
            "name": name,
            "description": description,
            "publicKey": public_key,
            "privateKey": private_key,
            "passPhrase": pass_phrase,
        }
        return await client.post("/hosts/ssh/cert/update", body)

    @mcp.tool()
    async def ssh_cert_delete(
        ids: Annotated[list[int], Field(description="要删除的密钥 ID 列表")],
        force_delete: Annotated[bool, Field(default=False, description="是否强制删除（即使被引用）")] = False,
        confirm: Annotated[bool, Field(description="删除密钥是高危操作，必须传 true")] = False,
    ) -> dict:
        """⚠️高危 [SSH] 删除 SSH 密钥。

        批量删除已纳管的 SSH 密钥。删除后使用该密钥的免密登录会失效。
        对应 POST /hosts/ssh/cert/delete（dto.ForceDelete）。必须显式传 confirm=true。

        Args:
            ids: 要删除的密钥 ID 列表。
            force_delete: 是否强制删除（即便密钥正被引用）。
            confirm: 必须为 true 才执行删除。
        """
        require_write()
        if not confirm:
            raise ValueError("删除 SSH 密钥是高危操作，必须显式传 confirm=true。")
        client = await get_client()
        return await client.post("/hosts/ssh/cert/delete", {
            "ids": ids, "forceDelete": force_delete,
        })

    @mcp.tool()
    async def ssh_cert_sync() -> dict:
        """⚠️写操作 [SSH] 同步 SSH 密钥到磁盘。

        把 1Panel 管理的 SSH 密钥同步写回系统 ~/.ssh 目录，确保与磁盘实际一致。
        对应 POST /hosts/ssh/cert/sync。
        """
        require_write()
        client = await get_client()
        return await client.post("/hosts/ssh/cert/sync", {})

    # ---- SSH 登录日志 ----

    @mcp.tool()
    async def ssh_log(
        status: Annotated[SSHLogStatus, Field(description="登录结果过滤：Success/Failed/All")] = "All",
        info: Annotated[str, Field(default="", description="IP / 用户名模糊匹配")] = "",
        page: Annotated[int, Field(ge=1, description="页码")] = 1,
        page_size: Annotated[int, Field(ge=1, le=500, description="每页数量")] = 100,
    ) -> dict:
        """[SSH] 查询 SSH 登录日志（成功 / 失败的远程登录记录）。读操作。

        返回 SSH 登录历史（时间、IP、用户、端口、登录结果）。对应
        POST /hosts/ssh/log（dto.SearchSSHLog）。常用于安全审计 / 暴力破解排查。

        Args:
            status: 登录结果过滤，All 全部 / Success 仅成功 / Failed 仅失败。
            info: IP 或用户名模糊匹配。
            page: 页码。
            page_size: 每页数量。
        """
        client = await get_client()
        return await client.post("/hosts/ssh/log", {
            "Status": status, "info": info, "page": page, "pageSize": page_size,
        })

    # ================================================================
    # 设备 Device（系统配置：DNS / 主机名 / 时区 / Swap / 密码 / 用户）
    # ================================================================

    @mcp.tool()
    async def device_conf_get(
        name: Annotated[str, Field(description="配置项名称，如 hostname / dns / zone / swap 等")],
    ) -> dict:
        """[设备] 读取系统配置项（主机名 / DNS / 时区 / Swap 等）。读操作。

        按名称读取系统级配置（hostname、dns、zone、swap 等）。
        对应 POST /toolbox/device/conf（dto.OperationWithName）。

        Args:
            name: 配置项名称，参考 1Panel 主机「设置」页选项。
        """
        client = await get_client()
        return await client.post("/toolbox/device/conf", {"name": name})

    @mcp.tool()
    async def device_update_conf(
        name: Annotated[str, Field(description="配置项名称，如 hostname / dns / zone / swap")],
        value: Annotated[str, Field(description="新值（字符串）")],
    ) -> dict:
        """⚠️写操作 [设备] 更新系统配置项（主机名 / DNS / 时区 / Swap）。

        按 name 更新单个系统配置。对应 POST /toolbox/device/update/conf。
        改主机名 / DNS 后部分服务需重启才生效。

        Args:
            name: 配置项名称。
            value: 新值（字符串）。
        """
        require_write()
        client = await get_client()
        return await client.post("/toolbox/device/update/conf", {
            "name": name, "value": value,
        })

    @mcp.tool()
    async def device_users() -> dict:
        """[设备] 列出系统用户（/etc/passwd）。读操作。

        返回本机系统用户列表（用户名、UID、家目录、Shell 等）。
        对应 GET /toolbox/device/users。
        """
        client = await get_client()
        return await client.get("/toolbox/device/users")

    @mcp.tool()
    async def device_zone_options() -> dict:
        """[设备] 列出可用时区选项。读操作。

        返回系统支持的所有时区（供修改时区时下拉选择）。
        对应 GET /toolbox/device/zone/options。
        """
        client = await get_client()
        return await client.get("/toolbox/device/zone/options")

    @mcp.tool()
    async def device_check_dns(
        name: Annotated[str, Field(description="DNS 服务器地址，用于测试解析，如 8.8.8.8")],
    ) -> dict:
        """[设备] 测试 DNS 解析是否可用。读操作。

        用指定 DNS 服务器测试域名解析连通性，返回解析结果 / 延时。
        对应 POST /toolbox/device/check/dns。

        Args:
            name: DNS 服务器地址，如 8.8.8.8 / 114.114.114.114。
        """
        client = await get_client()
        return await client.post("/toolbox/device/check/dns", {"name": name})

    # ================================================================
    # 磁盘 Disk Management（磁盘 / 分区概览 + 挂载 / 卸载 / 分区）
    # ================================================================

    @mcp.tool()
    async def disk_list() -> dict:
        """[磁盘] 获取全部磁盘与分区信息（已分区 / 未分区 / 系统盘）。读操作。

        返回所有块设备及其分区、挂载点、文件系统、容量、使用率，含未分区磁盘与
        系统盘标记。对应 GET /hosts/disks。是磁盘管理的统一只读入口。
        """
        client = await get_client()
        return await client.get("/hosts/disks")

    @mcp.tool()
    async def disk_mount(
        device: Annotated[str, Field(description="块设备路径，如 /dev/sdb1 或 /dev/sdb")],
        mount_point: Annotated[str, Field(description="挂载点目录，如 /mnt/data")],
        filesystem: Annotated[DiskFilesystem, Field(description="文件系统：ext4 / xfs")] = "ext4",
        auto_mount: Annotated[bool, Field(default=False, description="是否写入 /etc/fstab 开机自动挂载")] = False,
        no_fail: Annotated[bool, Field(default=False, description="fstab 是否加 nofail 选项（设备缺失时不阻塞启动）")] = False,
        confirm: Annotated[bool, Field(description="挂载 / 改 fstab 是写操作，高危场景请传 true")] = False,
    ) -> dict:
        """⚠️高危 [磁盘] 挂载磁盘分区到指定目录。

        格式化（如未格式化）并挂载块设备到目标目录，可选写入 /etc/fstab。
        对应 POST /hosts/disks/mount（request.DiskMountRequest）。
        ⚠️ auto_mount=true 会修改 /etc/fstab，配置错误可能导致系统无法启动。
        必须显式传 confirm=true。

        Args:
            device: 块设备路径，如 /dev/sdb1。
            mount_point: 挂载点目录（需已存在或会创建），如 /mnt/data。
            filesystem: 文件系统类型，ext4 或 xfs。
            auto_mount: 是否写入 /etc/fstab 实现开机自动挂载。
            no_fail: 是否加 nofail 选项（避免设备缺失时启动失败）。
            confirm: 必须为 true 才执行挂载。
        """
        require_write()
        if not confirm:
            raise ValueError("挂载磁盘是高危操作，必须显式传 confirm=true。")
        client = await get_client()
        return await client.post("/hosts/disks/mount", {
            "device": device,
            "mountPoint": mount_point,
            "filesystem": filesystem,
            "autoMount": auto_mount,
            "noFail": no_fail,
        })

    @mcp.tool()
    async def disk_unmount(
        mount_point: Annotated[str, Field(description="要卸载的挂载点目录，如 /mnt/data")],
        confirm: Annotated[bool, Field(description="卸载磁盘是高危操作，必须传 true")] = False,
    ) -> dict:
        """⚠️高危 [磁盘] 卸载磁盘分区。

        按挂载点卸载块设备。对应 POST /hosts/disks/unmount（request.DiskUnmountRequest）。
        ⚠️ 卸载正在使用的分区（如被进程占用）会失败或导致数据问题。
        必须显式传 confirm=true。

        Args:
            mount_point: 挂载点目录，如 /mnt/data。
            confirm: 必须为 true 才执行卸载。
        """
        require_write()
        if not confirm:
            raise ValueError("卸载磁盘是高危操作，必须显式传 confirm=true。")
        client = await get_client()
        return await client.post("/hosts/disks/unmount", {"mountPoint": mount_point})

    @mcp.tool()
    async def disk_partition(
        device: Annotated[str, Field(description="块设备路径，如 /dev/sdb（整盘新建分区）")] = "",
        filesystem: Annotated[DiskFilesystem, Field(description="文件系统：ext4 / xfs")] = "ext4",
        mount_point: Annotated[str, Field(default="", description="分区挂载点，留空不挂载")] = "",
        label: Annotated[str, Field(default="", description="分区卷标")] = "",
        auto_mount: Annotated[bool, Field(default=False, description="是否写入 /etc/fstab 开机自动挂载")] = False,
        confirm: Annotated[bool, Field(description="新建分区是高危操作（会格式化），必须传 true")] = False,
    ) -> dict:
        """⚠️高危 [磁盘] 对磁盘新建分区并格式化。

        在指定块设备上创建分区并按 filesystem 格式化。
        对应 POST /hosts/disks/partition（request.DiskPartitionRequest）。
        ⚠️ 会破坏设备上的现有数据。必须显式传 confirm=true。

        Args:
            device: 块设备路径，如 /dev/sdb。
            filesystem: 文件系统，ext4 或 xfs。
            mount_point: 格式化后挂载的目录，留空不挂载。
            label: 分区卷标。
            auto_mount: 是否写入 /etc/fstab 开机自动挂载。
            confirm: 必须为 true 才执行（会格式化，数据不可恢复）。
        """
        require_write()
        if not confirm:
            raise ValueError("新建并格式化分区是高危操作，必须显式传 confirm=true。")
        client = await get_client()
        return await client.post("/hosts/disks/partition", {
            "device": device,
            "filesystem": filesystem,
            "mountPoint": mount_point,
            "label": label,
            "autoMount": auto_mount,
        })

    # ================================================================
    # Host tool（supervisord 守护进程工具）
    # /hosts/tool 状态 / /hosts/tool/operate 启停 / /hosts/tool/config 配置读写
    # /hosts/tool/init 初始化 /hosts/tool/supervisor/process 进程管理
    # ================================================================

    @mcp.tool()
    async def host_tool_status(
        type: Annotated[HostToolType, Field(description="工具类型，目前仅 supervisord")] = "supervisord",
    ) -> dict:
        """[主机工具] 查询 host tool（supervisord）运行状态。读操作。

        返回 supervisord 是否安装、是否运行、版本、管理的进程数等。
        对应 POST /hosts/tool with operate=status。

        Args:
            type: 工具类型，目前仅支持 supervisord。
        """
        client = await get_client()
        return await client.post("/hosts/tool", {"type": type, "operate": "status"})

    @mcp.tool()
    async def host_tool_operate(
        operation: Annotated[HostToolOperate, Field(description="操作：start/stop/restart 启停，status 查状态")] = "restart",
        type: Annotated[HostToolType, Field(description="工具类型，目前仅 supervisord")] = "supervisord",
    ) -> dict:
        """⚠️写操作 [主机工具] 启停 host tool（supervisord 守护进程）。

        启动 / 停止 / 重启 supervisord 服务，或查询其状态。
        对应 POST /hosts/tool/operate（request.HostToolReq）。
        ⚠️ 停止 supervisord 会导致其托管的所有进程退出。

        Args:
            operation: 操作类型，start/stop/restart/status。
            type: 工具类型，目前仅 supervisord。
        """
        require_write()
        client = await get_client()
        return await client.post("/hosts/tool/operate", {"type": type, "operate": operation})

    @mcp.tool()
    async def host_tool_config_get(
        type: Annotated[HostToolType, Field(description="工具类型，目前仅 supervisord")] = "supervisord",
    ) -> dict:
        """[主机工具] 读取 host tool 主配置文件内容（如 supervisord.conf）。读操作。

        返回 supervisord 主配置文件的完整文本。对应
        POST /hosts/tool/config with operate=get。

        Args:
            type: 工具类型，目前仅 supervisord。
        """
        client = await get_client()
        return await client.post("/hosts/tool/config", {"type": type, "operate": "get"})

    @mcp.tool()
    async def host_tool_config_set(
        content: Annotated[str, Field(description="配置文件完整新内容（整体覆盖写入）")],
        type: Annotated[HostToolType, Field(description="工具类型，目前仅 supervisord")] = "supervisord",
    ) -> dict:
        """⚠️写操作 [主机工具] 覆盖写入 host tool 主配置文件。

        用传入 content 整体覆盖 supervisord 主配置文件。
        对应 POST /hosts/tool/config with operate=set。
        ⚠️ 配置错误可能导致 supervisord 无法启动，建议先 host_tool_config_get 备份。

        Args:
            content: 配置文件完整新内容。
            type: 工具类型，目前仅 supervisord。
        """
        require_write()
        client = await get_client()
        return await client.post("/hosts/tool/config", {
            "type": type, "operate": "set", "content": content,
        })

    @mcp.tool()
    async def host_tool_init(
        type: Annotated[HostToolType, Field(description="工具类型，目前仅 supervisord")] = "supervisord",
        service_name: Annotated[str, Field(default="", description="systemd 服务名，默认 supervisord")] = "",
        config_path: Annotated[str, Field(default="", description="主配置文件路径，默认 /etc/supervisor/supervisord.conf")] = "",
    ) -> dict:
        """⚠️写操作 [主机工具] 初始化 host tool 配置（首次安装 supervisord 后调用）。

        为 supervisord 生成 systemd 服务与默认配置，使其能开机自启。
        对应 POST /hosts/tool/init（request.HostToolCreate）。

        Args:
            type: 工具类型，目前仅 supervisord。
            service_name: systemd 服务名，留空用默认 supervisord。
            config_path: 主配置文件路径，留空用默认。
        """
        require_write()
        client = await get_client()
        body: dict[str, Any] = {"type": type}
        if service_name:
            body["serviceName"] = service_name
        if config_path:
            body["configPath"] = config_path
        return await client.post("/hosts/tool/init", body)

    @mcp.tool()
    async def host_tool_supervisor_process(
        name: Annotated[str, Field(description="Supervisor 进程名")] = "",
        operate: Annotated[str, Field(default="", description="操作：start/stop/restart/status，读状态留空")] = "",
    ) -> dict:
        """[主机工具] 查询 / 操作 Supervisor 托管进程。读 / 写操作。

        - operate 留空：列出所有 Supervisor 托管进程及其运行状态（读）。
        - operate=start/stop/restart：对指定 name 进程做生命周期操作（写，受只读模式拦截）。

        GET /hosts/tool/supervisor/process 列进程；POST /hosts/tool/supervisor/process
        做 start/stop/restart 操作。

        Args:
            name: Supervisor 进程名，操作时必填。
            operate: 留空=列进程（读）；start/stop/restart=操作（写）。
        """
        client = await get_client()
        if not operate:
            # 列进程（读）
            return await client.get("/hosts/tool/supervisor/process")
        # 操作（写）
        require_write()
        return await client.post("/hosts/tool/supervisor/process", {
            "name": name, "operate": operate,
        })

    @mcp.tool()
    async def host_tool_supervisor_file(
        name: Annotated[str, Field(description="Supervisor 进程名")],
        file: Annotated[SupervisorProcessFile, Field(description="文件类型：config 配置 / out.log 标准输出 / err.log 错误输出")],
        operate: Annotated[SupervisorProcessFileOperate, Field(description="操作：get 读 / clear 清空 / update 覆盖写入")],
        content: Annotated[str, Field(default="", description="operate=update 时的文件新内容")] = "",
    ) -> dict:
        """[主机工具] 读取 / 清空 / 覆盖 Supervisor 进程的配置或日志文件。读 / 写操作。

        - operate=get：读取指定文件内容（读，无副作用）。
        - operate=clear：清空指定日志文件（写）。
        - operate=update：用 content 覆盖写入配置文件（写）。

        对应 POST /hosts/tool/supervisor/process/file（request.SupervisorProcessFileReq）。

        Args:
            name: Supervisor 进程名。
            file: 文件类型：config / out.log / err.log。
            operate: get 读 / clear 清空 / update 覆盖写。
            content: operate=update 时的文件新内容。
        """
        if operate == "get":
            # 纯读，不拦截
            client = await get_client()
            return await client.post("/hosts/tool/supervisor/process/file", {
                "name": name, "file": file, "operate": "get",
            })
        # clear / update 是写
        require_write()
        client = await get_client()
        return await client.post("/hosts/tool/supervisor/process/file", {
            "name": name, "file": file, "operate": operate, "content": content,
        })

    # ================================================================
    # 日志 Logs（登录日志 / 操作日志 / 系统日志文件）
    # ================================================================

    @mcp.tool()
    async def logs_login(
        ip: Annotated[str, Field(default="", description="来源 IP 过滤")] = "",
        status: Annotated[str, Field(default="", description="登录结果过滤，如 Success / Failed，留空返回全部")] = "",
        page: Annotated[int, Field(ge=1, description="页码")] = 1,
        page_size: Annotated[int, Field(ge=1, le=500, description="每页数量")] = 100,
    ) -> dict:
        """[日志] 分页查询面板登录日志。读操作。

        返回 1Panel 面板的登录历史（时间、IP、地址、状态、User-Agent）。
        对应 POST /core/logs/login（dto.SearchLgLogWithPage）。用于面板安全审计。

        Args:
            ip: 来源 IP 过滤。
            status: 登录结果过滤，如 Success / Failed。
            page: 页码。
            page_size: 每页数量。
        """
        client = await get_client()
        return await client.post("/core/logs/login", {
            "ip": ip, "status": status, "page": page, "pageSize": page_size,
        })

    @mcp.tool()
    async def logs_operation(
        operation: Annotated[str, Field(default="", description="操作名模糊匹配")] = "",
        source: Annotated[str, Field(default="", description="操作来源过滤")] = "",
        status: Annotated[str, Field(default="", description="操作结果过滤")] = "",
        node: Annotated[str, Field(default="", description="节点名过滤（多节点场景）")] = "",
        page: Annotated[int, Field(ge=1, description="页码")] = 1,
        page_size: Annotated[int, Field(ge=1, le=500, description="每页数量")] = 100,
    ) -> dict:
        """[日志] 分页查询面板操作日志。读操作。

        返回 1Panel 上执行过的所有写操作记录（时间、操作、来源、状态、详情）。
        对应 POST /core/logs/operation（dto.SearchOpLogWithPage）。
        用于追踪「谁在什么时间做了什么」。

        Args:
            operation: 操作名模糊匹配。
            source: 操作来源过滤。
            status: 操作结果过滤。
            node: 节点名过滤（多节点部署时区分）。
            page: 页码。
            page_size: 每页数量。
        """
        client = await get_client()
        return await client.post("/core/logs/operation", {
            "operation": operation,
            "source": source,
            "status": status,
            "node": node,
            "page": page,
            "pageSize": page_size,
        })

    @mcp.tool()
    async def logs_system_files() -> dict:
        """[日志] 列出可查看的系统日志文件名。读操作。

        返回 1Panel 可读取的系统日志文件清单（如 /var/log/messages、syslog、
        auth.log 等，因发行版而异）。对应 GET /logs/system/files。
        拿到文件名后可再调文件读取接口查看内容。
        """
        client = await get_client()
        return await client.get("/logs/system/files")

    @mcp.tool()
    async def logs_clean(
        log_type: Annotated[CleanLogType, Field(description="要清理的日志类型：login 登录日志 / operation 操作日志")],
        confirm: Annotated[bool, Field(description="清理日志是高危操作，必须传 true")] = False,
    ) -> dict:
        """⚠️高危 [日志] 清空面板登录 / 操作日志。

        不可恢复地清空指定类型的面板日志。对应 POST /core/logs/clean
        （dto.CleanLog）。必须显式传 confirm=true。

        Args:
            log_type: 日志类型，login 登录日志 / operation 操作日志。
            confirm: 必须为 true 才执行清理。
        """
        require_write()
        if not confirm:
            raise ValueError("清空日志是高危操作，必须显式传 confirm=true。")
        client = await get_client()
        return await client.post("/core/logs/clean", {"logType": log_type})

    # ================================================================
    # 命令 Command
    # 1Panel 的 Command tag 是「命令片段库」（保存常用 shell 命令，便于复用），
    # 命令本身通过 SSH 会话执行。这里实现片段库 CRUD（/core/commands/*），
    # 并提供 command_run 高危工具：在主机上执行任意 shell 命令。
    # ================================================================

    @mcp.tool()
    async def command_list(
        type: Annotated[str, Field(default="", description="命令类型分组过滤，留空返回全部")] = "",
    ) -> dict:
        """[命令] 列出已保存的命令片段。读操作。

        返回命令片段库中所有（或指定 type 的）命令（id / name / command / 分组）。
        对应 GET /core/commands/command（dto.OperateByType）。

        Args:
            type: 命令类型 / 分组过滤，留空返回全部。
        """
        client = await get_client()
        return await client.get("/core/commands/command", {"type": type})

    @mcp.tool()
    async def command_tree() -> dict:
        """[命令] 获取命令片段的分组树。读操作。

        返回命令片段按分组的树形结构（用于前端分组展示）。
        对应 GET /core/commands/tree。
        """
        client = await get_client()
        return await client.get("/core/commands/tree")

    @mcp.tool()
    async def command_search(
        info: Annotated[str, Field(default="", description="名称 / 命令模糊匹配")] = "",
        page: Annotated[int, Field(ge=1, description="页码")] = 1,
        page_size: Annotated[int, Field(ge=1, le=500, description="每页数量")] = 100,
    ) -> dict:
        """[命令] 分页搜索命令片段。读操作。

        按名称或命令文本模糊匹配分页查询命令片段库。
        对应 POST /core/commands/search（dto.SearchWithPage）。

        Args:
            info: 名称 / 命令模糊匹配。
            page: 页码。
            page_size: 每页数量。
        """
        client = await get_client()
        return await client.post("/core/commands/search", {
            "page": page, "pageSize": page_size, "info": info,
        })

    @mcp.tool()
    async def command_create(
        name: Annotated[str, Field(description="命令名称（便于辨识）")],
        command: Annotated[str, Field(description="命令内容（shell 字符串）")],
        group_id: Annotated[int, Field(default=0, description="所属分组 ID，0 表示默认分组")] = 0,
        group_belong: Annotated[str, Field(default="", description="所属分组归属，留空默认")] = "",
        type: Annotated[str, Field(default="", description="命令类型 / 分类")] = "",
    ) -> dict:
        """⚠️写操作 [命令] 新建命令片段。

        把一条常用 shell 命令保存到片段库便于复用。对应
        POST /core/commands（dto.CommandOperate）。

        Args:
            name: 命令名称。
            command: 命令内容（shell 字符串）。
            group_id: 所属分组 ID，0 表示默认分组。
            group_belong: 所属分组归属。
            type: 命令类型 / 分类。
        """
        require_write()
        client = await get_client()
        return await client.post("/core/commands", {
            "name": name,
            "command": command,
            "groupID": group_id,
            "groupBelong": group_belong,
            "type": type,
        })

    @mcp.tool()
    async def command_update(
        id: Annotated[int, Field(description="命令片段 ID")],
        name: Annotated[str, Field(description="命令名称")],
        command: Annotated[str, Field(description="命令内容（shell 字符串）")],
        group_id: Annotated[int, Field(default=0, description="所属分组 ID")] = 0,
        group_belong: Annotated[str, Field(default="", description="所属分组归属")] = "",
        type: Annotated[str, Field(default="", description="命令类型 / 分类")] = "",
    ) -> dict:
        """⚠️写操作 [命令] 更新命令片段。

        修改已存在命令片段的名称 / 内容 / 分组。对应
        POST /core/commands/update（dto.CommandOperate）。

        Args:
            id: 命令片段 ID。
            name: 命令名称。
            command: 命令内容。
            group_id: 所属分组 ID。
            group_belong: 所属分组归属。
            type: 命令类型 / 分类。
        """
        require_write()
        client = await get_client()
        return await client.post("/core/commands/update", {
            "id": id,
            "name": name,
            "command": command,
            "groupID": group_id,
            "groupBelong": group_belong,
            "type": type,
        })

    @mcp.tool()
    async def command_delete(
        ids: Annotated[list[int], Field(description="要删除的命令片段 ID 列表")],
        confirm: Annotated[bool, Field(description="删除命令片段是高危操作，必须传 true")] = False,
    ) -> dict:
        """⚠️高危 [命令] 删除命令片段。

        批量删除命令片段库中的记录。对应 POST /core/commands/del（dto.OperateByIDs）。
        必须显式传 confirm=true。

        Args:
            ids: 要删除的命令片段 ID 列表。
            confirm: 必须为 true 才执行删除。
        """
        require_write()
        if not confirm:
            raise ValueError("删除命令片段是高危操作，必须显式传 confirm=true。")
        client = await get_client()
        return await client.post("/core/commands/del", {"ids": ids})

    @mcp.tool()
    async def command_run(
        command: Annotated[str, Field(description="要执行的 shell 命令（任意 shell 字符串，⚠️高危）")],
        name: Annotated[str, Field(default="", description="执行后保存为片段时的名称，留空不保存")] = "",
        confirm: Annotated[bool, Field(description="⚠️执行任意 shell 是极高危险操作，必须传 true")] = False,
    ) -> dict:
        """⚠️⚠️⚠️ 极高危 [命令] 在主机上执行任意 shell 命令。

        在目标主机上执行传入的任意 shell 命令并返回输出。
        对应 1Panel 命令执行能力（POST /hosts/ssh/operate）。

        ⚠️⚠️⚠️ 这是本 MCP server 中危险等级最高的工具之一：
        - 命令以 root 权限在主机上执行，可任意读写文件、安装软件、启停服务、
          删除数据、修改系统配置，甚至让主机不可启动。
        - 命令注入、误操作、危险通配（rm -rf）都可能造成不可逆破坏。
        - 调用方必须完全理解 command 的含义，并已做好快照 / 备份。

        必须显式传 confirm=true 才会执行；只读模式（PANEL_READONLY=true）下直接拒绝。

        Args:
            command: 要执行的 shell 命令字符串。⚠️ 请务必逐字核对。
            name: 执行成功后若需把该命令保存为片段，填名称；留空不保存。
            confirm: 必须为 true 才执行（极高危险，请二次确认）。
        """
        require_write()
        if not confirm:
            raise ValueError(
                "执行任意 shell 命令是极高危险操作，必须显式传 confirm=true。"
                " 请确认你完全理解 command 的后果（root 权限、不可逆破坏风险）。"
            )
        if not command or not command.strip():
            raise ValueError("command 不能为空。")
        client = await get_client()
        # 通过 SSH operate 通道执行命令；name 用于后续把命令保存为片段
        body: dict[str, Any] = {"command": command}
        if name:
            body["name"] = name
        return await client.post("/hosts/ssh/operate", body)
