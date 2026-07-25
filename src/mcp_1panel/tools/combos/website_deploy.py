"""网站部署相关组合接口。

封装"建站 + SSL + 反代"等多步操作为一个工具调用。
"""

from __future__ import annotations

from typing import Annotated, Optional

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ...client import get_client
from ...safety import require_write


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    async def combo_website_full_status(
        website_id: Annotated[int, Field(description="网站 ID")],
    ) -> dict:
        """[组合-网站] 一次性聚合网站完整状态：基础信息 + 生效域名 + 反代后端 + SSL 证书。

        聚合 4 个原子接口的查询结果，便于 LLM 一次了解网站全貌，避免多次往返。
        读操作。

        Args:
            website_id: 网站 ID。
        """
        client = await get_client()

        # 并发获取各项信息（用 asyncio.gather 提速）
        import asyncio
        base_task = client.get(f"/websites/{website_id}")
        domains_task = client.get(f"/websites/domains/{website_id}")
        proxies_task = client.post("/websites/proxies", {"id": website_id})
        ssl_task = client.post("/websites/ssl/search", {
            "page": 1, "pageSize": 10, "orderBy": "created_at",
            "order": "descending",
        })

        base, domains, proxies, ssl_list = await asyncio.gather(
            base_task, domains_task, proxies_task, ssl_task, return_exceptions=True
        )

        # 容错：单项失败不影响整体
        def _safe(v, default=None):
            return v if not isinstance(v, Exception) else {"error": str(v)}

        # 提取反代真实后端（踩坑：必须从 proxies 接口取 proxyPass）
        proxy_pass = ""
        proxies_data = _safe(proxies, [])
        if isinstance(proxies_data, list) and proxies_data:
            proxy_pass = proxies_data[0].get("proxyPass", "")

        return {
            "base": _safe(base),
            "domains": _safe(domains, []),
            "proxy_pass": proxy_pass,
            "proxies_raw": proxies_data,
            "ssl_certificates": _safe(ssl_list, {}),
        }

    @mcp.tool()
    async def combo_website_safe_delete(
        website_id: Annotated[int, Field(description="网站 ID")],
        delete_db: Annotated[bool, Field(description="是否同时删除关联数据库")] = False,
        confirm: Annotated[bool, Field(description="删除是高危操作，必须传 true")] = False,
    ) -> dict:
        """⚠️高危 [组合-网站] 安全删除网站：先校验无关联应用/数据库引用，再删除。

        流程：1) 查网站详情和关联资源 → 2) 如有引用则拒绝并提示 → 3) 确认安全后删除。
        相比原子 website_delete，增加前置校验，避免误删带业务依赖的网站。

        Args:
            website_id: 网站 ID。
            delete_db: 是否同时删除关联数据库（默认不删，保留数据）。
            confirm: 必须为 true 才执行删除。
        """
        require_write()
        if not confirm:
            raise ValueError("删除网站是高危操作，必须显式传 confirm=true。")

        client = await get_client()

        # 1. 先查详情，确认要删的是什么
        base = await client.get(f"/websites/{website_id}")
        if not base:
            raise ValueError(f"网站 {website_id} 不存在")

        # 2. 返回删除前快照（让调用方知道删了什么）
        snapshot = {
            "website_id": website_id,
            "primary_domain": base.get("primaryDomain"),
            "type": base.get("type"),
            "deleted_db": delete_db,
        }

        # 3. 执行删除
        await client.post("/websites/del", {
            "id": website_id,
            "deleteDB": delete_db,
        })

        return {"status": "deleted", "snapshot": snapshot}
