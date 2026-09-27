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

    采用显式 import + register 字典，而非动态扫描，原因：
    1. 静态可读，新增模块时一眼能看到要加哪行
    2. 避免 import 顺序 / 循环依赖的动态坑
    3. 支持 PANEL_MODULES 按模块裁剪：全量 543 个工具的 schema 约 24 万 token，
       客户端可只启用所需模块；未注册的模块既不出现在 tools/list，也无法被调用
    """
    # 延迟 import 避免模块加载时副作用
    from .config import get_settings
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

    # 显式注册顺序：按模块语义分组，读多写少的常用模块在前（dict 保持插入序）
    module_registers: dict[str, Callable[[FastMCP], None]] = {
        # 监控与系统
        "dashboard": dashboard.register,
        "monitor": monitor.register,
        "system": system.register,
        # 容器与应用
        "container": container.register,
        "app": app.register,
        "openresty": openresty.register,
        # 网站 + 运行时（website 含部分 runtime，runtime 补齐其余）
        "website": website.register,
        "runtime": runtime.register,
        # 数据库与文件
        "database": database.register,
        "file": file.register,
        # 备份恢复
        "backup": backup.register,
        # 安全（防火墙、Clam、Fail2ban、FTP）
        "firewall": firewall.register,
        "security": security.register,
        # 主机运维
        "host": host.register,
        "cronjob": cronjob.register,
        # AI
        "ai": ai.register,
        # 杂项（脚本库、任务日志、菜单设置）
        "misc": misc.register,
        # 组合便捷接口（聚合原子工具，封装业务流程）
        "combos": combos.register_all,
    }

    enabled = {
        m.strip() for m in get_settings().panel_modules.split(",") if m.strip()
    }
    if enabled:
        unknown = enabled - module_registers.keys()
        if unknown:
            raise ValueError(
                f"PANEL_MODULES 含未知模块: {sorted(unknown)}；可选: {sorted(module_registers)}"
            )
        module_registers = {
            k: v for k, v in module_registers.items() if k in enabled
        }

    for reg in module_registers.values():
        reg(server)


# 默认注册（兼容 `from mcp_1panel.server import mcp` 直接用）
register_all(mcp)
