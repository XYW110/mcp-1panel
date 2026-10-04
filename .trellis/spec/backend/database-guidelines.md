# Database Guidelines

> Database patterns and conventions for this project.

---

## Overview

**本项目不使用数据库。** 这是 1Panel REST API 的 MCP 封装：所有数据
读写都通过 `PanelClient`（`src/mcp_1panel/client.py`）调 1Panel
`/api/v2/*` 接口完成，本地无 ORM、无迁移、无持久化状态。

唯一沾边的"存储"语义是 1Panel 面板自身的数据库（MySQL/PostgreSQL/
Redis 管理接口，在 `tools/database.py`），但那些只是转发 API 调用，
本项目不直接连库。

---

## 若未来需要本地状态

（当前不存在此需求，记录约定以防随手引入。）

- 配置一律走 `config.py` 的 pydantic-settings 环境变量（`PANEL_*`），
  不引入本地配置文件或 SQLite。
- 若确需缓存/持久化，先在任务 PRD 里说明必要性，评审后再选型。

---

## Common Mistakes

- 不要在工具函数里缓存 1Panel 响应（面板状态随时会变，MCP 工具必须
  每次实时读）。
- 不要把 1Panel 返回的原始 payload 做有损改写——工具层原样返回
  `data` 字段，字段裁剪/重命名会破坏客户端兼容性。
