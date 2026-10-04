# Directory Structure

> How backend code is organized in this project.

---

## Overview

本项目是手写的 1Panel v2 MCP Server（Python 3.12+，src 布局）。
核心分层只有两层：`client.py`（带 MD5 签名的 1Panel REST 客户端）
和 `tools/<module>.py`（MCP 工具注册模块）。没有 ORM、没有 service 层——
工具函数直接调 client 并原样返回 1Panel 的 data 字段。

**权威 API 数据源是 `references/openapi.json`**（Swagger 2.0，
basePath /api/v2）。新增/修改任何工具前先用 jq 查它确认路径、
参数 schema 和 orderBy 枚举值。

---

## Directory Layout

```
src/mcp_1panel/
├── __main__.py        # CLI 入口：传输方式（http/stdio/sse）、日志初始化
├── server.py          # FastMCP 实例 + register_all()：显式 import 每个模块，
│                      #   module_registers 字典 + PANEL_MODULES/PANEL_TOOLS 白名单裁剪
├── client.py          # PanelClient：签名（MD5）、get/post/post_multipart/search、
│                      #   _unwrap（HTTP 状态 + 业务码校验）、全局单例 get_client()
├── config.py          # pydantic-settings：PANEL_* 环境变量
├── errors.py          # PanelError 异常体系（见 error-handling.md）
├── safety.py          # require_write() / write_op 装饰器（PANEL_READONLY 拦截）
├── pagination.py      # 分页参数处理
├── tools/             # 每个模块一个文件，导出 register(mcp: FastMCP) -> None
│   ├── container.py   # 黄金范式：新模块照它的风格写
│   ├── combos/        # 组合便捷接口（子包，register_all）
│   └── ...
tests/
├── conftest.py        # 环境变量 fixture
├── helpers.py         # parse_tool_result：解包 FastMCP call_tool 的 TextContent
├── test_client_signing.py
├── test_tools_<module>.py   # 与 src/mcp_1panel/tools/<module>.py 一一对应
└── test_combos.py
references/openapi.json      # 1Panel v2 API 权威定义（勿手改）
docs/                        # 运维 runbook 等文档
```

---

## Module Organization

新增模块（如 `tools/foo.py`）的固定步骤：

1. 文件导出 `register(mcp: FastMCP) -> None`；工具函数定义在 `register`
   内部（闭包），用 `@mcp.tool()`（**必须带括号**，mcp 1.28.1 要求）装饰。
2. 在 `server.py` 的 `module_registers` 字典加一行 `"foo": foo.register`
   （显式 import，不做动态扫描——为了 IDE 可跳转和 PANEL_MODULES 校验）。
3. 新建 `tests/test_tools_<module>.py`（见 quality-guidelines.md）。
4. 更新 `README.md` 模块表工具数。
5. 复杂入参（多个相关字段）建 Pydantic 模型放 `src/mcp_1panel/models/<module>.py`。

---

## Naming Conventions

- 工具名：`<module>_<action>` 或 `<module>_<object>_<action>`
  （读：`container_search`；写：`website_create`；批量消歧：
  `database_mysql_create` / `database_pg_create`）。
- 模块文件名与 `module_registers` key、`tests/test_tools_<module>.py`
  三者严格同名对应。
- 工具 path 参数一律不带 `/api/v2` 前缀（client 内部处理）。

---

## Examples

- 黄金范式：`src/mcp_1panel/tools/container.py`（文件头有模块内全部工具的
  读/写/高危清单注释，register 内闭包定义工具）。
- multipart 上传：`src/mcp_1panel/tools/file.py` 的 `file_upload`
  （client 侧配套 `post_multipart`）。
- 注册与白名单裁剪：`src/mcp_1panel/server.py` 的 `register_all`。
