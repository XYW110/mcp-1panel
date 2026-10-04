# Error Handling

> How errors are handled in this project.

---

## Overview

异常体系集中在 `src/mcp_1panel/errors.py`，全部继承 `PanelError`。
**分层规则：client 层负责把 HTTP/业务错误翻译成类型化异常；工具层
不捕获、不包装，直接让异常沿 MCP 协议传给客户端**（FastMCP 会把
未捕获异常转成 tool error 返回）。

---

## Error Types

`src/mcp_1panel/errors.py`（全部继承 `PanelError(Exception)`）：

| 异常 | 触发点 | 语义 |
|---|---|---|
| `PanelConfigError` | `client.py` 初始化 | endpoint/api_key 缺失等配置错误 |
| `PanelAuthError` | `client.py::_unwrap` | HTTP 401/403 或业务码鉴权失败 |
| `PanelAPIError` | `client.py::_unwrap` | 1Panel 业务码非 200（含 code/message） |
| `PanelTransportError` | `client.py` | httpx 网络错误、5xx、非 JSON 响应 |
| `PanelReadOnlyError` | `safety.py::require_write` | PANEL_READONLY=true 时拒绝写操作 |

---

## Error Handling Patterns

- **client 层**（唯一做翻译的地方）：`httpx.RequestError` →
  `PanelTransportError`（`raise ... from e` 保留链）；HTTP 5xx →
  `PanelTransportError`；4xx/业务码 → `PanelAuthError` /
  `PanelAPIError`。错误消息带响应体前 200 字符便于排障。
- **工具层**：参数校验失败直接 `raise ValueError(...)`（如
  `file_upload` 的"本地文件不存在"、`container.py` 的解析失败、
  高危操作 confirm 未传），不自定义新异常类。
- **安全层**：`require_write()` 抛 `PanelReadOnlyError`；高危工具
  （delete/remove）必须加 `confirm: bool = False` 参数，未传 true
  就 raise（范式：`container_remove`）。
- 新增异常类型前先确认 `errors.py` 里没有语义匹配的——**不要在
  模块文件里散落定义异常类**。

---

## Common Mistakes

- 工具层 `try/except Exception` 吞异常或转成返回值
  `{"error": ...}`——错误必须以异常形式传播，客户端靠它区分成功/失败。
- 丢失异常链（裸 `raise PanelXxx(...)` 不带 `from e`）。
- 用 print 而非异常报告错误（本项目库代码不打日志，见
  logging-guidelines.md）。
