"""仪表盘模块（对应 openapi.json 的 Dashboard tag，12 个端点）。

照 container.py 黄金范式风格写：
1. 工具名：dashboard_<action>（dashboard_base / dashboard_current / dashboard_os ...）
2. description：结构化，[仪表盘] 开头，写操作加 ⚠️，便于 mcphub 向量搜索召回
3. 入参用 Annotated[T, Field(description=...)]
4. handler 用 `await get_client()` 拿共享客户端，调 .get() / .post()
5. 写操作（restart / launcher 调整 / 快捷入口变更）开头调 require_write()，
   高危操作（重启系统）额外加 confirm 参数

接口来源：references/openapi.json 的 /dashboard/* 路径，basePath /api/v2。
该模块绝大部分是只读的系统概览/资源监控查询；写操作只有系统重启、
应用快捷入口开关、首页快捷入口调整三处。
"""

from __future__ import annotations

from typing import Annotated, Literal, Optional

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..client import get_client
from ..safety import require_write

# ---- 约束枚举 ----

# /dashboard/base/:ioOption/:netOption 与 /dashboard/current/:ioOption/:netOption
# 的路径参数：ioOption 控制磁盘 IO 统计的设备范围，netOption 控制网络 IO 的网卡范围。
# 1Panel 接受设备名（如 eth0）或以下汇总值；all/default 均返回全部设备的聚合数据。
DashboardDeviceOption = Literal["all", "default"]

# /dashboard/system/restart/:operation 的合法操作（来自 1Panel 源码 Restart 函数 switch）：
# - system：重启整个操作系统（高危，调用 reboot）
# - 1panel-agent：仅重启 1panel-agent 服务
# - 1panel：重启 1panel-core + agent
SystemRestartOperation = Literal["system", "1panel-agent", "1panel"]


def register(mcp: FastMCP) -> None:

    # ---- 系统概览（只读） ----

    @mcp.tool()
    async def dashboard_base(
        io_option: Annotated[DashboardDeviceOption, Field(description="磁盘 IO 统计范围，all 或 default 均聚合全部设备；也可传具体设备名如 eth0")] = "all",
        net_option: Annotated[DashboardDeviceOption, Field(description="网络 IO 统计范围，all 或 default 均聚合全部网卡；也可传具体网卡名")] = "all",
    ) -> dict:
        """[仪表盘] 获取系统基础概览（OS/CPU/内存/磁盘/网站数等）。读操作。

        1Panel 首页主概览数据，包含操作系统、内核、CPU 型号与核心数、当前资源
        使用快照、已安装的网站/数据库/应用/计划任务数量、快捷入口等。
        对应 GET /dashboard/base/{ioOption}/{netOption}。

        Args:
            io_option: 磁盘 IO 统计范围，all/default 聚合全部块设备。
            net_option: 网络 IO 统计范围，all/default 聚合全部网卡。
        """
        client = await get_client()
        return await client.get(f"/dashboard/base/{io_option}/{net_option}")

    @mcp.tool()
    async def dashboard_os() -> dict:
        """[仪表盘] 获取操作系统基础信息。读操作。

        返回 OS、发行版、平台、内核版本与架构、磁盘总大小等静态信息，
        不含实时资源使用。对应 GET /dashboard/base/os。
        """
        client = await get_client()
        return await client.get("/dashboard/base/os")

    @mcp.tool()
    async def dashboard_current(
        io_option: Annotated[DashboardDeviceOption, Field(description="磁盘 IO 统计范围，all 或 default 聚合全部设备；也可传具体设备名")] = "all",
        net_option: Annotated[DashboardDeviceOption, Field(description="网络 IO 统计范围，all 或 default 聚合全部网卡；也可传具体网卡名")] = "all",
    ) -> dict:
        """[仪表盘] 获取当前实时资源快照（CPU/内存/IO/网络/负载）。读操作。

        返回最近一次采样的 CPU/内存/Swap 使用率、磁盘 IO 读写量、
        网络收发字节数、系统负载（1/5/15 分钟）、进程数与 Top 进程等。
        对应 GET /dashboard/current/{ioOption}/{netOption}。

        Args:
            io_option: 磁盘 IO 统计范围。
            net_option: 网络 IO 统计范围。
        """
        client = await get_client()
        return await client.get(f"/dashboard/current/{io_option}/{net_option}")

    @mcp.tool()
    async def dashboard_current_node() -> dict:
        """[仪表盘] 获取当前节点的资源快照。读操作。

        用于多节点（agent）场景，返回当前节点的 CPU/内存/负载/网络/磁盘使用。
        单机部署等价于 dashboard_current 的节点视角。对应 GET /dashboard/current/node。
        """
        client = await get_client()
        return await client.get("/dashboard/current/node")

    @mcp.tool()
    async def dashboard_top_cpu() -> dict:
        """[仪表盘] 获取 CPU 占用最高的进程列表。读操作。

        返回当前 CPU 使用率排序靠前的进程（名称、PID、占用百分比、命令行、用户）。
        对应 GET /dashboard/current/top/cpu。
        """
        client = await get_client()
        return await client.get("/dashboard/current/top/cpu")

    @mcp.tool()
    async def dashboard_top_mem() -> dict:
        """[仪表盘] 获取内存占用最高的进程列表。读操作。

        返回当前内存使用量排序靠前的进程（名称、PID、占用内存、命令行、用户）。
        对应 GET /dashboard/current/top/mem。
        """
        client = await get_client()
        return await client.get("/dashboard/current/top/mem")

    # ---- 应用快捷入口（launcher，首页应用磁贴） ----

    @mcp.tool()
    async def dashboard_app_launcher() -> dict:
        """[仪表盘] 获取首页应用快捷入口（launcher 磁贴）。读操作。

        返回已显示在首页的应用磁贴列表（名称、图标、跳转路由等）。
        对应 GET /dashboard/app/launcher。
        """
        client = await get_client()
        return await client.get("/dashboard/app/launcher")

    @mcp.tool()
    async def dashboard_app_launcher_option(
        filter: Annotated[Optional[str], Field(description="按名称过滤应用快捷入口，留空返回全部可选项")] = None,
    ) -> dict:
        """[仪表盘] 获取首页应用快捷入口的可选项。读操作。

        返回所有可作为 launcher 磁贴的应用及其当前显示状态（isShow），
        供首页编辑界面选择。对应 POST /dashboard/app/launcher/option。

        Args:
            filter: 名称过滤关键词，留空返回全部。
        """
        client = await get_client()
        return await client.post("/dashboard/app/launcher/option", {
            "filter": filter or "",
        })

    @mcp.tool()
    async def dashboard_app_launcher_show(
        key: Annotated[str, Field(description="应用 key，如 openresty / n8n / uptime-kuma")],
        value: Annotated[str, Field(description="是否显示，'true' 显示 / 'false' 隐藏")],
    ) -> dict:
        """⚠️写操作 [仪表盘] 设置某个应用快捷入口在首页是否显示。

        调整首页 launcher 磁贴的显隐。对应 POST /dashboard/app/launcher/show。

        Args:
            key: 应用 key。
            value: 'true' 显示该磁贴，'false' 隐藏。
        """
        require_write()
        client = await get_client()
        return await client.post("/dashboard/app/launcher/show", {
            "key": key,
            "value": value,
        })

    # ---- 快捷入口（quick jump，顶部导航快捷） ----

    @mcp.tool()
    async def dashboard_quick_option() -> dict:
        """[仪表盘] 获取顶部快捷入口的可选项。读操作。

        返回所有可作为顶部快捷入口（quick jump）的条目及其当前显示状态。
        对应 GET /dashboard/quick/option。
        """
        client = await get_client()
        return await client.get("/dashboard/quick/option")

    @mcp.tool()
    async def dashboard_quick_change(
        quicks: Annotated[list[dict], Field(description="快捷入口条目数组，每项含 id / name / router / isShow 等字段（dto.QuickJump 结构）")],
    ) -> dict:
        """⚠️写操作 [仪表盘] 批量更新顶部快捷入口。

        全量覆盖顶部快捷入口列表（顺序、显隐、别名等）。对应 POST /dashboard/quick/change。
        每项为 dto.QuickJump 结构：id（条目 ID）/ name / alias / title / detail /
        recommend / isShow（是否显示）/ router（跳转路由）。

        Args:
            quicks: 快捷入口条目数组，全量提交。
        """
        require_write()
        client = await get_client()
        return await client.post("/dashboard/quick/change", {"quicks": quicks})

    # ---- 系统重启（高危） ----

    @mcp.tool()
    async def dashboard_system_restart(
        operation: Annotated[SystemRestartOperation, Field(description="重启目标：system 重启操作系统 / 1panel-agent 重启 agent / 1panel 重启 core+agent")],
        confirm: Annotated[bool, Field(description="高危操作二次确认，必须传 true 才执行")] = False,
    ) -> dict:
        """⚠️高危 [仪表盘] 重启系统或 1Panel 服务。

        高危操作，会直接影响服务器可用性。对应 POST /dashboard/system/restart/{operation}。
        必须显式传 confirm=true。

        Args:
            operation: 重启目标。
                system：重启整个操作系统（执行 reboot，会断开所有连接）；
                1panel-agent：仅重启 1panel-agent 服务；
                1panel：重启 1panel-core 与 agent。
            confirm: 必须为 true 才执行。
        """
        require_write()
        if not confirm:
            raise ValueError(
                f"重启操作（{operation}）是高危操作，必须显式传 confirm=true。"
                " system 会重启整台服务器。"
            )
        client = await get_client()
        return await client.post(f"/dashboard/system/restart/{operation}")
