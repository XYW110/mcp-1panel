# 工具模块实现规范（所有 agent 必须遵守）

本文件是并行 agent 开发各 `tools/<module>.py` 的统一规范。已完成的
`src/mcp_1panel/tools/container.py` 是**黄金范式**，照它的风格写。

## 1. 文件结构

每个模块文件 `src/mcp_1panel/tools/<module>.py` 必须：
- 导出 `register(mcp: FastMCP) -> None` 函数
- 函数内部用 `@mcp.tool()`（**必须带括号**，mcp 1.28.1 要求）装饰工具
- 工具函数定义在 `register` 内部（闭包，避免模块级命名污染）

```python
from __future__ import annotations
from typing import Annotated, Literal, Optional
from mcp.server.fastmcp import FastMCP
from pydantic import Field
from ..client import get_client
from ..safety import require_write


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    async def module_action(
        param: Annotated[str, Field(description="参数说明")] = "",
        page: Annotated[int, Field(ge=1)] = 1,
    ) -> dict:
        """[模块名] 一句话功能。读操作/⚠️写操作。

        详细说明。对应 POST/GET /xxx/yyy。

        Args:
            param: 参数语义。
            page: 页码。
        """
        client = await get_client()
        return await client.post("/xxx/yyy", {"param": param})
```

## 2. 工具命名规范

`<module>_<action>` 或 `<module>_<object>_<action>`：
- 读：`container_search` / `website_list` / `database_mysql_list`
- 写：`container_start` / `website_create` / `app_install`
- 批量加对象消歧：`database_mysql_create` / `database_pg_create` / `database_redis_backup`

## 3. description 规范（mcphub 向量搜索核心）

格式：`[模块] 一句话功能。操作类型。` + docstring 详细说明。

- 读操作 description 第一行：`[模块] xxx。读操作。`
- 写操作 description 第一行：`⚠️写操作 [模块] xxx。`
- 高危（delete/remove）：`⚠️高危 [模块] xxx。`
- docstring 补充：对应哪个 API、参数语义、业务注意事项

description 质量直接决定 mcphub Smart Routing 召回率，必须认真写。

## 4. 调用客户端

```python
client = await get_client()           # 全局共享单例
await client.get(path, params={...})  # GET
await client.post(path, body)         # POST（body 是 dict）
await client.search(path, filters={...}, page=1)  # search 类，自动注入分页
```

⚠️ search 的 order_by 默认是 `createdAt`，但**不同模块的可选值不同**：
- container: `name`/`createdAt`/`state`
- website 等: `created_at`/`updated_at`/`name`（下划线）
- 实现前用 jq 查 openapi.json 确认该模块 orderBy 的 enum 值

## 5. 读写安全

- 写操作（create/update/delete/install/restart/operate 等）：handler 第一行 `require_write()`
- 高危操作（delete/del/remove）：额外加 `confirm: bool = False` 参数，不传 true 就 raise ValueError
- 见 `container_remove` 范式

## 6. 参数 schema

- 简单参数用 `Annotated[T, Field(description="...")]`
- 枚举用 `Literal["a", "b", "c"]`
- 复杂入参（多个相关字段）建 Pydantic 模型放 `src/mcp_1panel/models/<module>.py`

## 7. 测试要求

每个模块配套 `tests/test_tools_<module>.py`：
- `test_<module>_tools_registered`：验证工具注册（list_tools）
- 至少 1 个读工具端到端（respx mock + call_tool + parse_tool_result）
- 至少 1 个写工具安全校验（confirm / readonly）
- 用 `from .helpers import parse_tool_result` 解包返回值

测试用 respx mock，**不打真实 1Panel**。运行（在仓库根目录）：
```bash
.venv/Scripts/python.exe -m pytest tests/test_tools_<module>.py -v
```

## 8. 接口来源

权威数据源：`references/openapi.json`（仓库根目录相对路径；Swagger 2.0，basePath /api/v2）。

查接口：
```bash
# 该模块所有路径
jq -r '.paths | to_entries[] | select(.value|to_entries[].value.tags[]? | test("<Tag>")) | "\(.key)\t\(.value|keys|join(","))"' references/openapi.json
# 某接口的请求 schema
jq '.paths["/<path>"].post.parameters' references/openapi.json
# schema 定义（看字段和 enum）
jq '.definitions["<DefinitionName>"]' references/openapi.json
```

## 9. 已知约束（踩坑）

- API 路径前缀 `/api/v2`（client 内部已处理，工具里 path 不带前缀）
- v2 用 MD5 签名，绝不混 v1
- search 接口 page/pageSize/orderBy/order 全必填（client.search 已自动注入）
- orderBy 可选值因模块而异，必须查 openapi.json 确认
- 写操作默认开启（PANEL_READONLY=false），只读模式由 require_write() 拦截

## 10. 完成标准

- [ ] 模块所有接口（按 openapi.json tag 覆盖）都实现成工具
- [ ] server.py 的 register_all 列表已包含本模块（主 agent 统一加）
- [ ] `pytest tests/test_tools_<module>.py` 全绿
- [ ] `pytest tests/` 全量回归全绿（不能破坏其他模块）
