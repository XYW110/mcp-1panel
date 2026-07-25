"""FastMCP server 实例与模块组装。

每个 tools/<module>.py 导出一个 register(mcp) 函数，把本模块的工具注册到 mcp 实例。
server.py 负责创建 mcp 并遍历注册所有模块。

工具命名规范：<module>_<action>（如 container_search / website_create），
description 用结构化模板便于 mcphub Smart Routing 向量搜索召回。
"""

from __future__ import annotations

import os
from collections.abc import Callable

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

# host/port/transport 从环境变量读，初始化时传给 FastMCP（run() 不接受这些参数）
_host = os.getenv("MCP_HOST", "0.0.0.0")
_port = int(os.getenv("MCP_PORT", "8000"))

# 容器化部署需要放行任意 host（DNS rebinding protection 默认只允许 localhost）
_allowed_hosts = [f"{_host}:*"] if _host not in ("127.0.0.1", "localhost") else None
_transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=False,  # 容器内禁用，否则拦截非 localhost 请求
    allowed_hosts=_allowed_hosts or ["*:*"],
    allowed_origins=["*"],
) if _host not in ("127.0.0.1", "localhost") else None

# 创建 server 实例（无 auth —— mcphub 统一处理鉴权）
mcp: FastMCP = FastMCP(
    "1Panel",
    host=_host,
    port=_port,
    transport_security=_transport_security,
    # instructions 会作为 system prompt 注入，帮助 LLM 理解工具集
    instructions=(
        "1Panel 全功能运维 MCP server。覆盖容器、网站、应用、数据库、文件、"
        "防火墙、主机、计划任务、备份、监控等全部模块。工具名以模块前缀分组"
        "（container_/website_/app_/database_/file_/firewall_/host_/cronjob_/"
        "backup_/monitor_/system_ 等），写操作 description 含 ⚠️ 标记。"
        "分页查询接口的 page/pageSize/orderBy/order 参数必填。"
    ),
)


def register_all(server: FastMCP) -> None:
    """遍历注册所有业务模块的工具。

    采用显式 import + register 列表，而非动态扫描，原因：
    1. 静态可读，新增模块时一眼能看到要加哪行
    2. 避免 import 顺序 / 循环依赖的动态坑
    3. 便于按需注释某模块做调试
    """
    # 延迟 import 避免模块加载时副作用
    from .tools import (
        ai,
        app,
        backup,
        container,
        cronjob,
        dashboard,
        database,
        file,
        firewall,
        host,
        misc,
        monitor,
        openresty,
        runtime,
        security,
        system,
        website,
    )
    from .tools import combos

    # 显式注册顺序：按模块语义分组，读多写少的常用模块在前
    registers: list[Callable[[FastMCP], None]] = [
        # 监控与系统
        dashboard.register,
        monitor.register,
        system.register,
        # 容器与应用
        container.register,
        app.register,
        openresty.register,
        # 网站 + 运行时（website 含部分 runtime，runtime 补齐其余）
        website.register,
        runtime.register,
        # 数据库与文件
        database.register,
        file.register,
        # 备份恢复
        backup.register,
        # 安全（防火墙、Clam、Fail2ban、FTP）
        firewall.register,
        security.register,
        # 主机运维
        host.register,
        cronjob.register,
        # AI
        ai.register,
        # 杂项（脚本库、任务日志、菜单设置）
        misc.register,
        # 组合便捷接口（聚合原子工具，封装业务流程）
        combos.register_all,
    ]
    for reg in registers:
        reg(server)


# 默认注册（兼容 `from mcp_1panel.server import mcp` 直接用）
register_all(mcp)
