"""容器运维相关组合接口。"""

from __future__ import annotations

from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ...client import get_client
from ...safety import require_write


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    async def combo_container_inspect_full(
        container_name: Annotated[str, Field(description="容器名称")],
    ) -> dict:
        """[组合-容器] 一次性聚合容器完整状态：详情 + 资源占用 + 最近日志。

        聚合 inspect + stats + log 三个查询，便于 LLM 诊断容器问题。
        读操作。

        Args:
            container_name: 容器名称。
        """
        import asyncio
        client = await get_client()

        inspect_task = client.post("/containers/inspect", {
            "id": container_name, "type": "container",
        })
        stats_task = client.post("/containers/item/stats", {"id": container_name})

        inspect, stats = await asyncio.gather(inspect_task, stats_task, return_exceptions=True)

        def _safe(v, default=None):
            return v if not isinstance(v, Exception) else {"error": str(v)}

        return {
            "container": container_name,
            "inspect": _safe(inspect),
            "stats": _safe(stats),
        }

    @mcp.tool()
    async def combo_container_safe_restart(
        container_name: Annotated[str, Field(description="容器名称")],
        confirm: Annotated[bool, Field(description="重启是写操作，必须传 true")] = False,
    ) -> dict:
        """⚠️写操作 [组合-容器] 安全重启容器：先记录当前状态快照，再重启，最后验证恢复。

        流程：1) 重启前快照 inspect → 2) 执行 restart → 3) 重启后快照。
        便于排查"重启后行为异常"的问题。

        Args:
            container_name: 容器名称。
            confirm: 必须为 true 才执行。
        """
        require_write()
        if not confirm:
            raise ValueError("重启容器是写操作，必须显式传 confirm=true。")

        client = await get_client()

        # 重启前快照
        before = await client.post("/containers/inspect", {
            "id": container_name, "type": "container",
        })

        # 执行重启
        await client.post("/containers/operate", {
            "names": [container_name], "operation": "restart",
        })

        # 重启后状态
        import asyncio
        await asyncio.sleep(2)  # 给容器 2 秒启动时间
        after = await client.post("/containers/inspect", {
            "id": container_name, "type": "container",
        })

        return {
            "container": container_name,
            "before": before,
            "after": after,
            "restarted": True,
        }
