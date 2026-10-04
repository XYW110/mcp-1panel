# Logging Guidelines

> How logging is done in this project.

---

## Overview

本项目**库代码（client/tools/safety）完全不打日志**。这是有意为之：
MCP 工具的结果就是返回给客户端的数据，运行诊断信息由两个渠道承担——

1. 启动入口 `src/mcp_1panel/__main__.py` 用标准库 `logging`
   （logger 名 `"mcp-1panel"`）输出传输层启动信息；
2. 错误一律走 `errors.py` 异常体系（见 error-handling.md），
   异常消息里已带响应体前 200 字符。

---

## Log Levels

仅 `__main__.py` 使用：

- `INFO`：server 启动、监听地址/传输方式。
- `ERROR`：启动期致命错误（配置缺失等）。

---

## What to Log

只在进程生命周期事件（启动/退出）打日志。不要在请求路径上加日志——
每个 MCP 调用都会经过 client，加了就是噪音。

---

## What NOT to Log

- **`PANEL_API_KEY`、签名头、Authorization** 等凭证（异常消息也
  不带——`client.py` 截取响应体时已避免回显请求头）。
- 面板返回的完整 payload（太大，排障走异常消息里的 200 字符摘要）。

---

## Common Mistakes

- 在 `tools/<module>.py` 里加 `print()` / `logging`——违反库代码
  静默约定，MCP stdio 传输下 print 还会污染协议 stdout。
