# 整理未提交改动与工作流基建入库

## Goal

将工作区 11 个脏路径（7 改 + 4 未跟踪）按功能流整理成干净的提交历史，
提交前通过全量测试质量门禁，整理后工作区恢复干净状态。

## Requirements

### A. 代码改动（两条独立功能流，分开提交）

1. **容器管理增强**：`src/mcp_1panel/tools/container.py` 新增
   `container_create` / `container_update`（改配置重建）工具与
   `_parse_port` / `_parse_volume` / `_parse_extra_host` 解析辅助，
   配套 `tests/test_tools_container.py`。
2. **文件上传与 list 修正**：`src/mcp_1panel/client.py` 新增
   `post_multipart`（multipart/form-data 签名请求）；`file.py` 新增
   `file_upload` 工具、修正 `file_list` 的 `expand` 默认值与 `dir_only`
   参数（1Panel v2 实测行为）；配套 `tests/test_tools_file.py`。

### B. 文档与配置

3. `README.md`：同步 546 工具数、模块表、PANEL_MODULES/PANEL_TOOLS 说明
   （追认已提交的两个白名单 feature）。
4. `pyproject.toml`：pytest `pythonpath = ["src"]`，保证测仓库源码而非
   已安装副本。

### C. 工作流基建（未跟踪，入库前安检）

5. `.gitattributes`：journal merge=union 策略。
6. `.trellis/`：Trellis 工作流（spec 骨架、scripts、任务工件）。
7. `.zcode/`：ZCode 平台集成（hooks/skills/agents/commands）。
8. `docs/runbook-pure-1panel-release.md`：纯 1Panel MCP 发版 runbook。

## Acceptance Criteria

- [ ] `pytest tests/` 全量全绿（提交前质量门禁）
- [ ] 代码改动按功能流分成独立 commit（container / file / 测试配置 / docs）
- [ ] 基建目录入库前检查无敏感信息、无本机绝对路径
- [ ] 提交信息沿用仓库惯例（`feat:`/`fix:`/`docs:`/`chore:`，中文摘要）
- [ ] 整理后 `git status` 干净（除新增的任务工件）

## Notes

- bootstrap 任务（00-bootstrap-guidelines）的 spec 填充与归档不属于本任务，
  在该任务下单独进行。
- 本任务为轻量任务，PRD-only。
