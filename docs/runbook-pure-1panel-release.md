# 纯 1Panel MCP 发版 Runbook（meituan-coupon）

> 目标：GitHub Actions 出镜像后，**全部用 mcp-1panel MCP 工具**完成服务器侧发版，
> Lighthouse MCP `execute_command` 只留兜底。管理对象：
> 容器 `meituan-coupon`（镜像 `dockercom110/meituan-coupon-assistant:latest`，
> 端口 3000，卷 `meituan-data:/app/data`，`--restart unless-stopped`）。

## 0. 前置条件

- ZCode 会话的 `mcp-1panel` MCP 已连接。当前白名单（config.json `PANEL_TOOLS`）：
  `container_search, container_operate, container_log_search, container_upgrade,
  container_inspect, container_info, container_image_pull, container_create,
  container_update, dashboard_base, dashboard_current, file_*`
  - **改白名单 / 改代码后必须重启 ZCode 会话才生效**（MCP server 启动时裁剪一次）。
  - 工具没出现 ≠ 没实现，先查白名单，再查安装副本是否同步（见 §5）。
- `PANEL_READONLY` 保持默认 false（写操作需要）。
- `host` 模块（`host_command_run`，任意 shell，⚠️高危）**默认不启用**。
  临时开启：`PANEL_MODULES` 追加 `host`、`PANEL_TOOLS` 追加 `host_command_run`，
  重启会话用完即撤。日常兜底执行通道用 Lighthouse MCP。

## 1. 标准发版（只换镜像，env 不变）

```
① container_image_pull  repo="dockercom110/meituan-coupon-assistant:latest"
② container_upgrade     names=["meituan-coupon"]
                        image="dockercom110/meituan-coupon-assistant:latest"
                        force_pull=true
③ 验证（见 §3）
```

- ①可省略：②带 `force_pull=true` 时升级前会拉新镜像。分两步做的好处是
  拉取失败（网络/registry 问题）提前暴露，不占用重建窗口。
- `container_upgrade` 用新镜像重建容器并**保留原 env/卷/网络/重启策略**，
  等价 `docker rm -f + docker run` 但由 1Panel 原子处理，更安全。
- 发版窗口内容器有秒级停机；卷数据不受影响。

## 2. 改环境变量的重建（如新增一个 env）

```
container_update  name="meituan-coupon"  env_add=["NEW_KEY=value"]
```

- 工具内部先 `POST /containers/info` 读取当前完整配置作基底，只叠加显式传入的
  增量：未传的端口/卷/网络/env **全部自动沿用**，不会漏传丢配置。
- 删变量用 `env_remove=["KEY"]`；换镜像/端口/卷/网络也可用它（ports/volumes
  是"整体替换"语义，请先 `container_info` 确认当前值再传）。
- 同样会删旧容器重建（短暂停机）。只换镜像不要用它，走 §1 的 upgrade。
- ⚠️ 密钥类 env 值（ACCESS_CODE / MT_TOKEN_KEY / ADMIN_CODE 等）不得写进
  仓库、测试、文档、对话记录。查看现有 env 用 `container_info`（只读）。

## 3. 冒烟验证（纯 1Panel 路径）

1. `container_search name="meituan-coupon"` → `state=running`、`imageName` 为新镜像。
2. `container_info name="meituan-coupon"` → 端口 `3000:3000/tcp`、
   卷 `meituan-data:/app/data`、`restartPolicy=unless-stopped` 与预期一致。
3. `container_log_search container_id=<search 返回的 containerID>` →
   启动日志无异常堆栈。
4. HTTP 冒烟（1Panel 工具覆盖不到 HTTP 请求，二选一）：
   - Lighthouse MCP `execute_command`：`curl -fsS -o /dev/null -w '%{http_code}' http://127.0.0.1:3000/`（兜底通道）；
   - 或 browser-use 直接打开 `http://111.229.147.203:3000/` 肉眼确认。

## 4. 回滚

```
container_upgrade  names=["meituan-coupon"]
                   image="dockercom110/meituan-coupon-assistant:<旧tag或digest>"
                   force_pull=false
```

- `latest` 被新镜像覆盖后回滚必须用固定版本 tag 或 digest。
- 旧镜像升级后不会自动删除；磁盘紧张时 `container_prune prune_type="image"
  confirm=true`（⚠️高危，会清所有未被引用镜像）。

## 5. MCP server 本体的同步机制（改仓库代码后怎么生效）

- 运行时安装方式：**pip 安装的 wheel**（曾来自 GitHub Release
  `v0.1.2-fork.1`），落在 `PYTHONUSERBASE=D:\PythonEnv\pip\user_base` 的
  site-packages。仓库 ≠ 自动生效，必须重装。
- 本地同步（开发迭代）：
  ```
  PYTHONUSERBASE=D:\PythonEnv\pip\user_base python -m pip install --user \
      --force-reinstall --no-deps D:\Work\Project\ToolProject\mcp-1panel
  ```
- 验证：对比 `src/mcp_1panel` 与安装副本 `mcp_1panel` 的文件 md5。
  注意行尾：仓库工作区可能是 CRLF、wheel 可能是 LF，**逐字节比 md5 前先
  `tr -d '\r'`**，否则全是假差异（本项目已踩过一次）。
- 正式发布：打 tag `vX.Y.Z-fork.N` 推送 → CI 构建 wheel 并发 GitHub Release
  → 任何机器 `pip install` 该 Release 即为官方同步路径。
- 测试永远跑仓库源码（pyproject 已配 `pythonpath=["src"]`），与安装副本无关：
  `python -m pytest tests/`。

## 6. 相关踩坑索引（详见 1panel-ops skill，不重复）

签名每秒重算 / MSYS 路径转换 / files/search 的 expand 与 dir 陷阱 /
1Panel 业务码 401 判定 —— 见 `C:\Users\I\.agents\skills\1panel-ops\SKILL.md`。
