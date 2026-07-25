"""杂项小 tag 模块（对应 openapi.json 的 ScriptLibrary / TaskLog / Menu Setting tag，共 8 接口）。

这几个 tag 接口数量少、彼此无业务关联，统一收在本文件。覆盖范围：

- ScriptLibrary（脚本库，5 接口）：分页查询 / 新增 / 更新 / 删除 / 从远程同步官方脚本
  对应路径 /core/script、/core/script/search、/core/script/update、/core/script/del、/core/script/sync
- TaskLog（任务日志，2 接口）：分页查询异步任务记录 / 查询正在执行的任务数
  对应路径 /logs/tasks/search、/logs/tasks/executing/count
- Menu Setting（菜单设置，1 接口）：把面板菜单恢复到默认
  对应路径 /core/settings/menu/default

实现风格照搬 container.py 黄金范式：
1. 工具名 <tag>_<action>，便于 mcphub 向量检索按模块召回
2. description 结构化（[模块] 开头，写操作加 ⚠️，高危加 confirm）
3. 入参用 Annotated[T, Field(description=...)]
4. 写操作 handler 第一行 require_write()，高危操作（delete）加 confirm

注意（踩坑）：
- ScriptLibrary 的 search 接口请求体（dto.SearchPageWithGroup）只接受
  page/pageSize/groupID/info 四个字段，**没有 orderBy/order**。所以不能用
  client.search()（它会注入 orderBy/order 导致后端报错），必须直接构造 body
  调 client.post()。
- TaskLog 的 search 接口同理（dto.SearchTaskLogReq 只有 page/pageSize/status/type）。
- /logs/tasks/executing/count 是 GET 返回裸整数，用 client.get() 即可。

接口来源：references/openapi.json，basePath /api/v2，路径不含前缀。
"""

from __future__ import annotations

from typing import Annotated, Optional

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..client import get_client
from ..safety import require_write


def register(mcp: FastMCP) -> None:

    # ==================== ScriptLibrary（脚本库）====================

    @mcp.tool()
    async def script_library_search(
        info: Annotated[str, Field(description="脚本名称模糊匹配，留空返回全部")] = "",
        group_id: Annotated[int, Field(description="分组 ID，0 表示不限分组")] = 0,
        page: Annotated[int, Field(ge=1, description="页码，从 1 开始")] = 1,
        page_size: Annotated[int, Field(ge=1, le=500, description="每页数量")] = 100,
    ) -> dict:
        """[脚本库] 分页查询 1Panel 脚本库脚本。读操作。

        返回脚本库中已收录的脚本列表（含名称、描述、分组、内容等）。对应
        POST /core/script/search，请求体为 dto.SearchPageWithGroup。

        Args:
            info: 脚本名称 / 描述模糊匹配关键字，留空返回全部。
            group_id: 分组 ID，0 表示不限分组。
            page: 页码，从 1 开始。
            page_size: 每页数量，上限 500。
        """
        client = await get_client()
        body = {
            "page": page,
            "pageSize": page_size,
            "groupID": group_id,
            "info": info,
        }
        return await client.post("/core/script/search", body)

    @mcp.tool()
    async def script_library_create(
        name: Annotated[str, Field(description="脚本名称")],
        script: Annotated[str, Field(description="脚本内容（shell 等可执行文本）")],
        description: Annotated[str, Field(description="脚本描述说明")] = "",
        groups: Annotated[str, Field(description="所属分组 ID，多个用逗号分隔；无分组传空串")] = "",
        is_interactive: Annotated[
            bool,
            Field(description="是否为交互式脚本（执行时需要用户输入）"),
        ] = False,
    ) -> dict:
        """⚠️写操作 [脚本库] 新增自定义脚本。

        向脚本库添加一条自定义脚本，可在面板「工具箱 / 快速部署 / 脚本」中使用。
        对应 POST /core/script，请求体为 dto.ScriptOperate。

        Args:
            name: 脚本名称。
            script: 脚本内容。
            description: 脚本描述。
            groups: 所属分组 ID（逗号分隔的字符串），无分组传空串。
            is_interactive: 是否交互式脚本。
        """
        require_write()
        client = await get_client()
        return await client.post("/core/script", {
            "name": name,
            "script": script,
            "description": description,
            "groups": groups,
            "isInteractive": is_interactive,
        })

    @mcp.tool()
    async def script_library_update(
        script_id: Annotated[int, Field(description="要更新的脚本 ID")],
        name: Annotated[str, Field(description="脚本名称")],
        script: Annotated[str, Field(description="脚本内容（shell 等可执行文本）")],
        description: Annotated[str, Field(description="脚本描述说明")] = "",
        groups: Annotated[str, Field(description="所属分组 ID，多个用逗号分隔；无分组传空串")] = "",
        is_interactive: Annotated[
            bool,
            Field(description="是否为交互式脚本（执行时需要用户输入）"),
        ] = False,
    ) -> dict:
        """⚠️写操作 [脚本库] 更新已有脚本。

        修改脚本库中某条脚本的内容 / 名称 / 描述 / 分组 / 交互属性。
        对应 POST /core/script/update，请求体为 dto.ScriptOperate（需带 id）。

        Args:
            script_id: 要更新的脚本 ID。
            name: 脚本名称。
            script: 脚本内容。
            description: 脚本描述。
            groups: 所属分组 ID（逗号分隔的字符串），无分组传空串。
            is_interactive: 是否交互式脚本。
        """
        require_write()
        client = await get_client()
        return await client.post("/core/script/update", {
            "id": script_id,
            "name": name,
            "script": script,
            "description": description,
            "groups": groups,
            "isInteractive": is_interactive,
        })

    @mcp.tool()
    async def script_library_delete(
        ids: Annotated[list[int], Field(description="要删除的脚本 ID 列表，支持批量")],
        confirm: Annotated[
            bool,
            Field(description="删除是高危操作，必须显式传 true 才执行"),
        ] = False,
    ) -> dict:
        """⚠️高危 [脚本库] 删除脚本（支持批量）。

        从脚本库删除指定脚本，不可恢复。对应 POST /core/script/del，
        请求体为 dto.OperateByIDs。必须显式传 confirm=true。

        Args:
            ids: 要删除的脚本 ID 列表，支持批量。
            confirm: 必须为 true 才执行删除。
        """
        require_write()
        if not confirm:
            raise ValueError("删除脚本是高危操作，必须显式传 confirm=true。")
        client = await get_client()
        return await client.post("/core/script/del", {"ids": ids})

    @mcp.tool()
    async def script_library_sync(
        task_id: Annotated[
            str,
            Field(description="同步任务 ID（由前端先创建任务拿到，传给后端执行）"),
        ],
    ) -> dict:
        """⚠️写操作 [脚本库] 从官方远程仓库同步脚本。

        触发从 1Panel 官方脚本仓库拉取 / 更新内置脚本（覆盖更新已有同名脚本）。
        对应 POST /core/script/sync，请求体为 dto.OperateByTaskID。

        Args:
            task_id: 同步任务 ID。1Panel 的同步是异步任务，需要先有 taskID 再触发执行。
        """
        require_write()
        client = await get_client()
        return await client.post("/core/script/sync", {"taskID": task_id})

    # ==================== TaskLog（任务日志）====================

    @mcp.tool()
    async def task_log_search(
        status: Annotated[
            Optional[str],
            Field(
                description=(
                    "按任务状态过滤，留空返回全部。1Panel 常见值如 "
                    "Success / Failed / Pending / Running 等（具体以面板为准）"
                ),
            ),
        ] = None,
        type: Annotated[
            Optional[str],
            Field(
                description=(
                    "按任务类型过滤，留空返回全部。如备份、快照、同步等任务类型字符串"
                ),
            ),
        ] = None,
        page: Annotated[int, Field(ge=1, description="页码，从 1 开始")] = 1,
        page_size: Annotated[int, Field(ge=1, le=500, description="每页数量")] = 100,
    ) -> dict:
        """[任务日志] 分页查询异步任务执行记录。读操作。

        返回面板后台异步任务（备份、快照、网站申请证书、脚本同步等）的执行历史，
        包含状态、耗时、错误信息等。对应 POST /logs/tasks/search，
        请求体为 dto.SearchTaskLogReq。

        Args:
            status: 按任务状态过滤，留空返回全部。
            type: 按任务类型过滤，留空返回全部。
            page: 页码，从 1 开始。
            page_size: 每页数量，上限 500。
        """
        client = await get_client()
        body = {
            "page": page,
            "pageSize": page_size,
            "status": status or "",
            "type": type or "",
        }
        return await client.post("/logs/tasks/search", body)

    @mcp.tool()
    async def task_log_executing_count() -> dict:
        """[任务日志] 查询当前正在执行的后台任务数。读操作。

        返回 1Panel 后台正在跑的异步任务数量。常用于轮询是否还有任务在跑、
        决定是否可以执行依赖前置任务完成的后续操作。
        对应 GET /logs/tasks/executing/count（后端返回裸整数，这里包成
        {"count": <int>} 以保持工具返回值统一为 dict）。

        Returns:
            {"count": <正在执行的任务数>}
        """
        client = await get_client()
        data = await client.get("/logs/tasks/executing/count")
        # 后端返回裸整数，统一包成 dict（与本模块其他工具一致）
        count = data if isinstance(data, int) else int(data or 0)
        return {"count": count}

    # ==================== Menu Setting（菜单设置）====================

    @mcp.tool()
    async def menu_setting_reset_default() -> dict:
        """⚠️写操作 [菜单设置] 把面板左侧导航菜单恢复为默认状态。

        将 1Panel 高级功能菜单的显示 / 隐藏配置重置为出厂默认。
        对应 POST /core/settings/menu/default。注意：本接口只重置菜单显隐，
        不影响其他系统设置。
        """
        require_write()
        client = await get_client()
        return await client.post("/core/settings/menu/default")
