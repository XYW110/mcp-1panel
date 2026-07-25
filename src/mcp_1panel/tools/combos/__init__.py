"""组合便捷接口（combos）。

聚合多个原子工具，封装常见业务流程，让 LLM 一次调用完成多步操作。
每个组合工具的 description 必须写清业务流程，便于 mcphub 向量召回。

命名：`combo_<业务场景>`，与原子工具的 `<模块>_<动作>` 区分。

示例：
- combo_website_quick_deploy: 一键建站（创建网站 + 申请 SSL + 配置反代）
- combo_app_safe_restart: 安全重启应用（停止 + 备份 + 启动）
- combo_container_update_image: 更新容器镜像（拉取 + 重建 + 验证）

新增组合接口时在此包内新建文件，并在 register 中注册。
"""

from __future__ import annotations

from collections.abc import Callable

from mcp.server.fastmcp import FastMCP


def register_all(server: FastMCP) -> None:
    """注册所有组合接口。"""
    from . import website_deploy, container_ops

    registers: list[Callable[[FastMCP], None]] = [
        website_deploy.register,
        container_ops.register,
    ]
    for reg in registers:
        reg(server)
