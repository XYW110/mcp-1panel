# Quality Guidelines

> Code quality standards for backend development.

---

## Overview

本仓库的详细实现规范在根目录 `AGENTS.md`（工具模块实现规范，必读），
本文件是质量门禁摘要。核心要求：每个工具对应 openapi.json 真实接口、
读写安全分层、测试 mock 不打真实面板。

---

## Required Patterns

- 工具定义在 `register(mcp)` 闭包内，`@mcp.tool()` **带括号**。
- description 第一行格式（影响 mcphub 向量召回）：
  - 读：`[模块] xxx。读操作。`
  - 写：`⚠️写操作 [模块] xxx。`
  - 高危：`⚠️高危 [模块] xxx。`
- 写操作 handler 第一行 `require_write()`；delete/remove 额外加
  `confirm: bool = False` 参数校验。
- 参数 schema：`Annotated[T, Field(description=...)]`；枚举用
  `Literal`；search 类用 `client.search()`（自动注入必填分页）。
- 实现前用 jq 查 `references/openapi.json` 确认路径/字段/orderBy
  枚举（各模块 orderBy 值不同：container 用驼峰，website 用下划线）。

---

## Forbidden Patterns

- 动态 import / 扫描注册模块（`server.py` 必须显式 import）。
- 工具 path 带 `/api/v2` 前缀、混用 v1 签名。
- 测试打真实 1Panel（必须 respx mock）。
- 工具层吞异常或 `{"error": ...}` 返回值（见 error-handling.md）。

---

## Testing Requirements

- 每个模块配套 `tests/test_tools_<module>.py`，至少包含：
  1. `test_<module>_tools_registered`（list_tools 验证注册）；
  2. ≥1 个读工具端到端（respx mock + call_tool +
     `helpers.parse_tool_result` 解包）；
  3. ≥1 个写工具安全校验（confirm / readonly 拦截）。
- 运行：`.venv/Scripts/python.exe -m pytest tests/ -q`
  （pytest `pythonpath=["src"]` 已保证测仓库源码）。
- **全量回归全绿是提交前置条件**（当前基线 242 passed）。

---

## Code Review Checklist

- [ ] openapi.json 覆盖：该模块接口是否都成了工具？
- [ ] `server.py` `module_registers` 已加本模块？README 模块表更新？
- [ ] 读/写/高危 description 格式正确？
- [ ] 写操作有 `require_write()`，高危有 confirm？
- [ ] 新测试用 respx + parse_tool_result，且全量 pytest 绿？
- [ ] 模块文件头保留了该模块全部工具的读/写/高危清单注释
      （范式：`tools/container.py` 文件头）。
