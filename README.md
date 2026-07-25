# mcp-1panel

> 全功能 1Panel MCP Server（Python 手写实现），对接 1Panel v2 REST API，通过 streamable-http 暴露，配合 [mcphub](https://github.com/samanhappy/mcpphub) 聚合使用。

[![Python](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/)
[![MCP](https://img.shields.io/badge/MCP-1.28-green.svg)](https://modelcontextprotocol.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## 特性

- **全功能覆盖**：手写实现 **490+ 个 MCP 工具**，覆盖 1Panel openapi.json 的核心运维场景
- **模块化分组**：工具按 `<模块>_<动作>` 命名（`container_search`/`website_create`/`database_mysql_list`），便于 mcphub Smart Routing 向量搜索召回
- **streamable-http 传输**：MCP 官方新标准，容器化部署友好，service 名直连
- **读写安全分层**：读操作无限制；写操作受 `PANEL_READONLY` 控制；高危操作（delete/remove）强制 `confirm` 参数
- **mcphub 集成**：开箱即用的 docker-compose（mcphub + onepanel-mcp + postgres），启用 pgvector 向量搜索

## 模块覆盖

| 模块 | 工具数 | 说明 |
|---|---|---|
| website | 92 | 网站/域名/SSL/HTTPS/Nginx/Acme/CA/DNS/PHP |
| system | 52 | 面板设置/快照/升级/SSL/密码/MFA/SSH |
| database | 42 | MySQL/PostgreSQL/Redis 库管理与权限 |
| container | 14+ | 容器/镜像/网络/卷/Compose（持续补齐中） |
| file | 36 | 文件浏览/编辑/压缩/权限/回收站 |
| app | 33 | 应用商店/安装/升级/参数 |
| ai | 33 | Ollama 模型/Agent/账户/渠道 |
| runtime | 28 | PHP/Node/Java/Go/Python/.NET 运行时 |
| backup | 25 | 备份账号(S3/OSS/MinIO...)/备份/恢复 |
| cronjob | 16 | 计划任务 CRUD/执行记录 |
| firewall | 15 | ufw 规则/端口/IP/转发 |
| openresty | 10 | OpenResty/Nginx 配置/模块 |
| dashboard | 12 | 概览/资源/进程 Top |
| monitor | 10 | CPU/内存/IO/网络/GPU 监控历史 |
| security | 27 | Clam 病毒扫描/Fail2ban/FTP |
| host | 43 | 进程/SSH/磁盘/日志/命令片段 |

## 快速开始

### 方式一：docker-compose（推荐，含 mcphub）

```bash
# 1. 克隆并配置
cp .env.example .env
# 编辑 .env，填入 1Panel 面板地址和 API Key

# 2. 启动全部服务
docker compose up -d --build

# 3. 访问 mcphub dashboard
# 浏览器打开 http://localhost:3000
```

`docker-compose.yml` 包含三个服务：
- **mcphub**（端口 3000）：MCP 网关 + dashboard + smart routing
- **onepanel-mcp**（端口 8000，仅容器内网）：本 MCP server
- **postgres**（pgvector）：mcphub smart routing 向量搜索依赖

### 方式二：本地运行（开发调试）

```bash
# 安装依赖
make install  # 或 uv sync --extra dev

# 配置环境变量
export PANEL_ENDPOINT="http://192.168.1.2:39579"
export PANEL_API_KEY="your-api-key"

# 启动（streamable-http）
python -m mcp_1panel --transport http --host 0.0.0.0 --port 8000

# 或 stdio 模式（Cursor 直连）
python -m mcp_1panel --transport stdio
```

## 客户端配置

### mcphub

`mcp_settings.json`：
```json
{
  "mcpServers": {
    "onepanel": {
      "type": "streamable-http",
      "url": "http://onepanel-mcp:8000/mcp"
    }
  }
}
```

### Cursor / Windsurf / Claude Desktop

直连本 MCP（绕过 mcphub）：
```json
{
  "mcpServers": {
    "1panel": {
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

## 环境变量

| 变量 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `PANEL_ENDPOINT` | ✅ | - | 1Panel 面板地址（如 `http://192.168.1.2:39579`） |
| `PANEL_API_KEY` | ✅ | - | 面板「设置 → API 接口」的 API Key |
| `PANEL_TIMEOUT` | | `30` | 请求超时秒数 |
| `PANEL_READONLY` | | `false` | 只读模式，拒绝所有写操作 |
| `MCP_TRANSPORT` | | `http` | 传输方式：`http`/`stdio`/`sse` |
| `MCP_HOST` | | `0.0.0.0` | HTTP 监听地址（容器内必须 0.0.0.0） |
| `MCP_PORT` | | `8000` | HTTP 监听端口 |
| `LOG_LEVEL` | | `INFO` | 日志级别 |

### 获取 1Panel API Key

1. 登录 1Panel 管理面板
2. 进入「面板设置」→「API 接口」
3. 开启 API 接口
4. 创建并复制 API Key
5. IP 白名单添加客户端 IP（测试可设 `0.0.0.0/0`）

## 工具命名与安全

### 命名规范

工具名统一 `<模块>_<动作>`：
- 读：`container_search` / `website_list` / `database_mysql_list`
- 写：`container_start` / `website_create` / `app_install`
- 高危：`container_remove` / `website_delete`

### description 规范（mcphub 召回核心）

mcphub Smart Routing 是 pgvector 向量语义搜索，索引 `name + description + parameters`。description 质量直接决定召回率：

```
[模块] 一句话功能。读操作/⚠️写操作/⚠️高危。关键参数语义。
```

### 安全分层

| 层级 | 标记 | 行为 |
|---|---|---|
| 读操作 | description 含「读操作」 | 无限制 |
| 写操作 | description 含「⚠️写操作」 | 受 `PANEL_READONLY` 控制，只读模式拒绝 |
| 高危操作 | description 含「⚠️高危」 | 强制 `confirm: bool = true` 参数 |

## 开发

### 项目结构

```
mcp-1panel/
├── src/mcp_1panel/
│   ├── client.py          # 签名 HTTP 客户端（核心，MD5 签名）
│   ├── server.py          # FastMCP 实例与模块注册
│   ├── config.py          # 环境变量配置
│   ├── pagination.py      # 分页参数模型
│   ├── safety.py          # 读写安全分层
│   ├── errors.py          # 统一异常类型
│   └── tools/             # 业务模块（每个文件导出 register(mcp)）
│       ├── container.py / website.py / database.py ...
│       └── combos/        # 组合便捷接口（扩展点）
├── tests/                 # pytest + respx mock + FastMCP 端到端
├── references/openapi.json # 1Panel v2 API 权威数据源
├── docker-compose.yml     # mcphub + onepanel-mcp + postgres
└── Dockerfile             # 多阶段构建
```

### 新增工具

参考黄金范式 `src/mcp_1panel/tools/container.py`。一个工具约 15-25 行：

```python
@mcp.tool()
async def module_action(
    param: Annotated[str, Field(description="参数说明")],
) -> dict:
    """[模块] 一句话功能。读操作。

    详细说明，对应 POST/GET /xxx/yyy。

    Args:
        param: 参数语义。
    """
    client = await get_client()
    return await client.post("/xxx/yyy", {"param": param})
```

### 测试

```bash
make test          # 全量测试
make test-cov      # 带覆盖率
```

测试用 `respx` mock httpx，不打真实 1Panel；用 FastMCP in-memory Client 端到端验证。

## 签名算法

1Panel v2 API 用 MD5 签名（见 `client.py`）：

```
Token = md5("1panel" + API_KEY + UnixTimestamp).hexdigest()
Header: 1Panel-Token = Token, 1Panel-Timestamp = 时间戳
URL: {endpoint}/api/v2{path}
```

关键点：
- 时间戳每请求重算（签名只在那一秒有效）
- 统一用 Python `hashlib.md5`（避免 shell md5 跨平台差异）
- v2 用 MD5 签名，绝不混 v1 明文 key

## 已知约束（踩坑）

- **search 接口分页必填**：`page/pageSize/orderBy/order` 全部必填，缺 `orderBy` 返回 400。`client.search()` 已自动注入默认值
- **orderBy 可选值因模块而异**：container 用 `name/createdAt/state`（驼峰），website 用 `created_at/updated_at`（下划线），实现时必须查 openapi.json 确认
- **反代真实后端**：`POST /websites/proxies` body `{"id": site_id}` → `data[].proxyPass`（不要用 `GET /websites/{id}` 的 `proxy` 字段，那是创建快照）
- **生效域名**：`GET /websites/domains/{websiteId}`（不要用 `GET /websites/{id}` 的 `name` 字段）

## License

MIT
