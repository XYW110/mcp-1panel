"""监控模块（对应 openapi.json 的 Monitor tag，5 个端点）。

覆盖 1Panel 主机监控：CPU/内存/负载/磁盘 IO/网络流量 历史数据查询、
GPU 监控、监控设置读写、清空监控数据。

接口来源（references/openapi.json，basePath /api/v2）：
- POST /hosts/monitor/search        按 param 查历史监控（cpu/memory/load/io/network/all）
- POST /hosts/monitor/gpu/search    查 GPU 监控数据
- GET  /hosts/monitor/setting       读监控设置（默认网卡/IO、采集间隔、保留天数）
- POST /hosts/monitor/setting/update 改监控设置（按 key 单字段更新）
- POST /hosts/monitor/clean         清空全部监控数据（高危）

实现风格与 container.py 一致：
- 工具名 monitor_<object>_<action>
- description [监控] 开头，写操作加 ⚠️，高危加 confirm
- search 类的时间范围/网卡/IO 设备参数见各工具 docstring
"""

from __future__ import annotations

from typing import Annotated, Literal, Optional

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..client import get_client
from ..safety import require_write


# ---- 监控指标维度（dto.MonitorSearch.param 的 enum）----
MonitorParam = Literal["all", "cpu", "memory", "load", "io", "network"]

# ---- 监控设置可改字段（dto.MonitorSettingUpdate.key 的 enum）----
MonitorSettingKey = Literal[
    "MonitorStatus",      # 监控开关，value: "enable"/"disable"
    "MonitorStoreDays",   # 保留天数，value: 数字字符串
    "MonitorInterval",    # 采集间隔（秒），value: 数字字符串
    "DefaultNetwork",     # 默认网卡名，value: 如 "eth0"
    "DefaultIO",          # 默认 IO 设备名，value: 如 "sda"
]


def register(mcp: FastMCP) -> None:

    # ---- 历史监控数据查询（POST /hosts/monitor/search）----
    # 按 param 拆成多个便捷工具，便于 mcphub 向量召回与 LLM 选择。

    async def _fetch_monitor(
        param: str,
        start_time: Optional[str],
        end_time: Optional[str],
        network: Optional[str],
        io: Optional[str],
    ) -> dict:
        """内部封装：调 /hosts/monitor/search。"""
        client = await get_client()
        body: dict = {"param": param}
        if start_time:
            body["startTime"] = start_time
        if end_time:
            body["endTime"] = end_time
        if network:
            body["network"] = network
        if io:
            body["io"] = io
        return await client.post("/hosts/monitor/search", body)

    @mcp.tool()
    async def monitor_cpu(
        start_time: Annotated[Optional[str], Field(description="起始时间，格式 YYYY-MM-DD HH:mm:ss，留空由 1Panel 取默认范围")] = None,
        end_time: Annotated[Optional[str], Field(description="结束时间，格式 YYYY-MM-DD HH:mm:ss")] = None,
    ) -> dict:
        """[监控] 查询 CPU 使用率历史。读操作。

        返回一段时间内 CPU 使用率采样序列（date + value 数组）。
        对应 POST /hosts/monitor/search with param=cpu。

        Args:
            start_time: 起始时间，格式 "YYYY-MM-DD HH:mm:ss"。
            end_time: 结束时间，格式同上。
        """
        return await _fetch_monitor("cpu", start_time, end_time, None, None)

    @mcp.tool()
    async def monitor_memory(
        start_time: Annotated[Optional[str], Field(description="起始时间，格式 YYYY-MM-DD HH:mm:ss")] = None,
        end_time: Annotated[Optional[str], Field(description="结束时间，格式 YYYY-MM-DD HH:mm:ss")] = None,
    ) -> dict:
        """[监控] 查询内存/缓存使用率历史。读操作。

        返回内存、Swap 使用率采样序列。对应
        POST /hosts/monitor/search with param=memory。

        Args:
            start_time: 起始时间，格式 "YYYY-MM-DD HH:mm:ss"。
            end_time: 结束时间，格式同上。
        """
        return await _fetch_monitor("memory", start_time, end_time, None, None)

    @mcp.tool()
    async def monitor_load(
        start_time: Annotated[Optional[str], Field(description="起始时间，格式 YYYY-MM-DD HH:mm:ss")] = None,
        end_time: Annotated[Optional[str], Field(description="结束时间，格式 YYYY-MM-DD HH:mm:ss")] = None,
    ) -> dict:
        """[监控] 查询系统负载（load1/load5/load15）历史。读操作。

        返回系统平均负载采样序列。对应
        POST /hosts/monitor/search with param=load。

        Args:
            start_time: 起始时间，格式 "YYYY-MM-DD HH:mm:ss"。
            end_time: 结束时间，格式同上。
        """
        return await _fetch_monitor("load", start_time, end_time, None, None)

    @mcp.tool()
    async def monitor_io(
        io: Annotated[str, Field(description="块设备名，如 sda、vda；可先用 host_io 查可用设备")],
        start_time: Annotated[Optional[str], Field(description="起始时间，格式 YYYY-MM-DD HH:mm:ss")] = None,
        end_time: Annotated[Optional[str], Field(description="结束时间，格式 YYYY-MM-DD HH:mm:ss")] = None,
    ) -> dict:
        """[监控] 查询磁盘 IO 读写速率历史。读操作。

        返回指定块设备的读/写速率采样序列。对应
        POST /hosts/monitor/search with param=io。

        Args:
            io: 块设备名（如 sda、nvme0n1），必填。
            start_time: 起始时间，格式 "YYYY-MM-DD HH:mm:ss"。
            end_time: 结束时间，格式同上。
        """
        return await _fetch_monitor("io", start_time, end_time, None, io)

    @mcp.tool()
    async def monitor_network(
        network: Annotated[str, Field(description="网卡名，如 eth0、ens33；可先用 host_network 查可用网卡")],
        start_time: Annotated[Optional[str], Field(description="起始时间，格式 YYYY-MM-DD HH:mm:ss")] = None,
        end_time: Annotated[Optional[str], Field(description="结束时间，格式 YYYY-MM-DD HH:mm:ss")] = None,
    ) -> dict:
        """[监控] 查询网卡流量（入/出速率）历史。读操作。

        返回指定网卡的入站/出站流量采样序列。对应
        POST /hosts/monitor/search with param=network。

        Args:
            network: 网卡名（如 eth0），必填。
            start_time: 起始时间，格式 "YYYY-MM-DD HH:mm:ss"。
            end_time: 结束时间，格式同上。
        """
        return await _fetch_monitor("network", start_time, end_time, network, None)

    @mcp.tool()
    async def monitor_search(
        param: Annotated[MonitorParam, Field(description="监控维度：all/cpu/memory/load/io/network")],
        start_time: Annotated[Optional[str], Field(description="起始时间，格式 YYYY-MM-DD HH:mm:ss")] = None,
        end_time: Annotated[Optional[str], Field(description="结束时间，格式 YYYY-MM-DD HH:mm:ss")] = None,
        network: Annotated[Optional[str], Field(description="网卡名，param=network 时必填，如 eth0")] = None,
        io: Annotated[Optional[str], Field(description="块设备名，param=io 时必填，如 sda")] = None,
    ) -> dict:
        """[监控] 通用历史监控数据查询（按 param 维度）。读操作。

        monitor_cpu/memory/load/io/network 的通用版本，适合需要 all 维度
        或动态选择指标的场景。对应 POST /hosts/monitor/search。

        Args:
            param: 监控维度：all（全部）/cpu/memory/load/io/network。
            start_time: 起始时间，格式 "YYYY-MM-DD HH:mm:ss"。
            end_time: 结束时间，格式同上。
            network: 网卡名，param=network 时必填。
            io: 块设备名，param=io 时必填。
        """
        return await _fetch_monitor(param, start_time, end_time, network, io)

    # ---- GPU 监控（POST /hosts/monitor/gpu/search）----

    @mcp.tool()
    async def monitor_gpu(
        start_time: Annotated[Optional[str], Field(description="起始时间，格式 YYYY-MM-DD HH:mm:ss")] = None,
        end_time: Annotated[Optional[str], Field(description="结束时间，格式 YYYY-MM-DD HH:mm:ss")] = None,
        product_name: Annotated[Optional[str], Field(description="GPU 产品名筛选，留空返回默认 GPU")] = None,
    ) -> dict:
        """[监控] 查询 GPU 监控数据（利用率/显存/温度/功耗/进程）。读操作。

        返回 GPU 利用率、显存、温度、功耗及占用进程等时序数据。
        对应 POST /hosts/monitor/gpu/search。仅 GPU 主机可用。

        Args:
            start_time: 起始时间，格式 "YYYY-MM-DD HH:mm:ss"。
            end_time: 结束时间，格式同上。
            product_name: GPU 产品名（多卡时区分），留空取默认。
        """
        client = await get_client()
        body: dict = {}
        if start_time:
            body["startTime"] = start_time
        if end_time:
            body["endTime"] = end_time
        if product_name:
            body["productName"] = product_name
        return await client.post("/hosts/monitor/gpu/search", body)

    # ---- 监控设置（GET /hosts/monitor/setting, POST /hosts/monitor/setting/update）----

    @mcp.tool()
    async def monitor_setting_get() -> dict:
        """[监控] 读取监控设置。读操作。

        返回监控开关、采集间隔、保留天数、默认网卡、默认 IO 设备等配置。
        对应 GET /hosts/monitor/setting。
        """
        client = await get_client()
        return await client.get("/hosts/monitor/setting")

    @mcp.tool()
    async def monitor_setting_update(
        key: Annotated[MonitorSettingKey, Field(description="设置项 key")],
        value: Annotated[str, Field(description="设置项新值（字符串）")],
    ) -> dict:
        """⚠️写操作 [监控] 修改监控设置（单字段）。

        按 key 更新单个监控配置项。对应
        POST /hosts/monitor/setting/update。修改采集间隔/保留天数等。

        Args:
            key: 设置项：MonitorStatus（开关 enable/disable）/
                MonitorStoreDays（保留天数）/ MonitorInterval（采集间隔秒）/
                DefaultNetwork（默认网卡）/ DefaultIO（默认 IO 设备）。
            value: 新值字符串，如 "30"（天）、"5"（秒）、"eth0"、"enable"。
        """
        require_write()
        client = await get_client()
        return await client.post("/hosts/monitor/setting/update", {
            "key": key, "value": value,
        })

    # ---- 清空监控数据（POST /hosts/monitor/clean，高危）----

    @mcp.tool()
    async def monitor_clean(
        confirm: Annotated[bool, Field(description="清空全部监控历史是高危操作，必须传 true")] = False,
    ) -> dict:
        """⚠️高危 [监控] 清空全部监控历史数据。

        不可恢复地删除所有已采集的监控数据（CPU/内存/网络/IO/GPU 等）。
        对应 POST /hosts/monitor/clean。必须显式传 confirm=true。

        Args:
            confirm: 必须为 true 才执行清空。
        """
        require_write()
        if not confirm:
            raise ValueError("清空监控数据是高危操作，必须显式传 confirm=true。")
        client = await get_client()
        return await client.post("/hosts/monitor/clean", {})
