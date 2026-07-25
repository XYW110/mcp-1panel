"""AI 模块（对应 openapi.json 的 AI tag，共 33 个端点）。

覆盖 1Panel 的 AI 能力：
1. Ollama 模型管理：列出/拉取/删除/重建/同步已安装模型、关闭模型连接
2. GPU/XPU 监控：查询 GPU 负载状态
3. Ollama 域名绑定：绑定/查询 Ollama 对外访问域名
4. AI Agent 管理：创建/列出/删除 Agent、更新模型配置、重置 token、查询供应商
5. Agent 账户：列出/创建/更新/删除/验证供应商 API key 账户
6. Agent 浏览器/其它配置：读取/更新
7. Agent 渠道：Discord/Telegram/飞书 渠道配置读写 + 配对审批

接口来源：references/openapi.json 的 /ai/* 路径，basePath /api/v2。
安全分层：读操作直接放行；写操作（pull/create/update/delete/close/reset/approve...）
开头调 require_write()；删除类高危操作额外加 confirm 参数。
"""

from __future__ import annotations

from typing import Annotated, Literal, Optional

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..client import get_client
from ..safety import require_write


def register(mcp: FastMCP) -> None:

    # ================================================================
    # Ollama 模型管理
    # ================================================================

    @mcp.tool()
    async def ai_model_list(
        info: Annotated[Optional[str], Field(description="模型名/标签模糊匹配，留空返回全部")] = None,
        page: Annotated[int, Field(ge=1, description="页码")] = 1,
        page_size: Annotated[int, Field(ge=1, le=500, description="每页数量")] = 100,
    ) -> dict:
        """[AI] 列出已安装的 Ollama 模型。读操作。

        分页返回 1Panel 当前已安装/拉取过的 Ollama 模型。对应
        POST /ai/ollama/model/load。返回项含模型名、大小、修改时间等。

        Args:
            info: 模型名/标签模糊匹配，留空返回全部。
            page: 页码，从 1 开始。
            page_size: 每页数量，上限 500。
        """
        client = await get_client()
        return await client.post("/ai/ollama/model/load", {
            "info": info or "",
            "page": page,
            "pageSize": page_size,
        })

    @mcp.tool()
    async def ai_model_search(
        info: Annotated[Optional[str], Field(description="模型名模糊匹配，留空返回可拉取的全部")] = None,
        page: Annotated[int, Field(ge=1, description="页码")] = 1,
        page_size: Annotated[int, Field(ge=1, le=500, description="每页数量")] = 100,
    ) -> dict:
        """[AI] 搜索可拉取的 Ollama 模型。读操作。

        分页返回 Ollama 官方仓库可拉取的模型列表（不含已安装）。对应
        POST /ai/ollama/model/search。

        Args:
            info: 模型名模糊匹配，留空返回全部可拉取模型。
            page: 页码，从 1 开始。
            page_size: 每页数量，上限 500。
        """
        client = await get_client()
        return await client.post("/ai/ollama/model/search", {
            "info": info or "",
            "page": page,
            "pageSize": page_size,
        })

    @mcp.tool()
    async def ai_model_pull(
        name: Annotated[str, Field(description="Ollama 模型名，如 llama3.2 或 qwen2.5:7b")],
    ) -> dict:
        """⚠️写操作 [AI] 拉取 Ollama 模型。

        从 Ollama 仓库拉取模型到本地。对应 POST /ai/ollama/model。
        拉取是耗时异步任务，1Panel 会返回 taskID，模型出现在 ai_model_list 中即拉取完成。

        Args:
            name: 模型名（含 tag）。
        """
        require_write()
        client = await get_client()
        return await client.post("/ai/ollama/model", {"name": name})

    @mcp.tool()
    async def ai_model_recreate(
        name: Annotated[str, Field(description="上次拉取失败的 Ollama 模型名")],
    ) -> dict:
        """⚠️写操作 [AI] 重试拉取 Ollama 模型。

        对上次拉取失败的模型重试。对应 POST /ai/ollama/model/recreate。

        Args:
            name: 模型名。
        """
        require_write()
        client = await get_client()
        return await client.post("/ai/ollama/model/recreate", {"name": name})

    @mcp.tool()
    async def ai_model_delete(
        model_ids: Annotated[list[int], Field(description="要删除的 Ollama 模型 ID 列表（来自 ai_model_list）")],
        force: Annotated[bool, Field(description="是否强制删除（忽略引用）")] = False,
        confirm: Annotated[bool, Field(description="删除是高危操作，必须传 true 才执行")] = False,
    ) -> dict:
        """⚠️高危 [AI] 删除已安装的 Ollama 模型。

        按 ID 批量删除模型，释放磁盘空间。对应 POST /ai/ollama/model/del。
        删除不可恢复，必须显式传 confirm=true。

        Args:
            model_ids: 模型 ID 列表，来自 ai_model_list 返回的 id 字段。
            force: 是否强制删除（忽略正在被引用的模型）。
            confirm: 必须为 true 才执行删除。
        """
        require_write()
        if not confirm:
            raise ValueError("删除 Ollama 模型是高危操作，必须显式传 confirm=true。")
        client = await get_client()
        return await client.post("/ai/ollama/model/del", {
            "ids": model_ids,
            "forceDelete": force,
        })

    @mcp.tool()
    async def ai_model_sync() -> list:
        """[AI] 同步 Ollama 模型列表。读操作。

        从本地 Ollama 重新读取已安装的模型清单，回填到 1Panel 数据库，
        用于校准模型状态。对应 POST /ai/ollama/model/sync。
        返回当前同步后发现的模型列表（id + name）。
        """
        client = await get_client()
        return await client.post("/ai/ollama/model/sync")

    @mcp.tool()
    async def ai_model_close(
        name: Annotated[str, Field(description="Ollama 模型名")],
    ) -> dict:
        """⚠️写操作 [AI] 关闭 Ollama 模型连接。

        释放某个正在运行的 Ollama 模型占用的内存/GPU 资源（不删除模型文件）。
        对应 POST /ai/ollama/close。

        Args:
            name: 模型名。
        """
        require_write()
        client = await get_client()
        return await client.post("/ai/ollama/close", {"name": name})

    # ================================================================
    # GPU 监控
    # ================================================================

    @mcp.tool()
    async def ai_gpu_status() -> dict:
        """[AI] 查询 GPU/XPU 负载状态。读操作。

        返回主机上的 GPU（NVIDIA）或 XPU（Intel）显存、利用率、温度等信息，
        用于判断 AI 模型能否在该节点运行。对应 GET /ai/gpu/load。
        无 GPU 时返回空。
        """
        client = await get_client()
        return await client.get("/ai/gpu/load")

    # ================================================================
    # Ollama 域名绑定
    # ================================================================

    @mcp.tool()
    async def ai_domain_get(
        app_install_id: Annotated[int, Field(description="Ollama 应用安装 ID")],
    ) -> dict:
        """[AI] 查询 Ollama 对外访问域名。读操作。

        返回某个已安装 Ollama 应用绑定的外部访问域名（含 SSL 证书、白名单 IP）。
        对应 POST /ai/domain/get。

        Args:
            app_install_id: Ollama 应用安装 ID。
        """
        client = await get_client()
        return await client.post("/ai/domain/get", {"appInstallID": app_install_id})

    @mcp.tool()
    async def ai_domain_bind(
        app_install_id: Annotated[int, Field(description="Ollama 应用安装 ID")],
        domain: Annotated[str, Field(description="要绑定的域名")],
        ip_list: Annotated[Optional[str], Field(description="域名访问白名单 IP，逗号分隔，留空不限制")] = None,
        ssl_id: Annotated[Optional[int], Field(description="已有 SSL 证书 ID，不传则不启用 HTTPS")] = None,
        website_id: Annotated[Optional[int], Field(description="已存在网站 ID（绑定已有反代网站），不传则新建")] = None,
    ) -> dict:
        """⚠️写操作 [AI] 绑定 Ollama 对外访问域名。

        为 Ollama 应用绑定域名（并可选配 SSL），生成可通过外网访问的 Ollama API 端点。
        对应 POST /ai/domain/bind。

        Args:
            app_install_id: Ollama 应用安装 ID。
            domain: 要绑定的域名。
            ip_list: 访问白名单 IP（逗号分隔），留空不限制。
            ssl_id: 已有 SSL 证书 ID，启用 HTTPS 时传入。
            website_id: 已有反代网站 ID，复用现有网站时传入。
        """
        require_write()
        client = await get_client()
        body: dict = {
            "appInstallID": app_install_id,
            "domain": domain,
            "ipList": ip_list or "",
        }
        if ssl_id is not None:
            body["sslID"] = ssl_id
        if website_id is not None:
            body["websiteID"] = website_id
        return await client.post("/ai/domain/bind", body)

    # ================================================================
    # AI Agent 管理（1Panel 内置 Agent 编排应用）
    # ================================================================

    @mcp.tool()
    async def ai_agent_list(
        info: Annotated[Optional[str], Field(description="Agent 名模糊匹配，留空返回全部")] = None,
        page: Annotated[int, Field(ge=1, description="页码")] = 1,
        page_size: Annotated[int, Field(ge=1, le=500, description="每页数量")] = 100,
    ) -> dict:
        """[AI] 列出已安装的 AI Agent。读操作。

        分页返回 1Panel 部署的 AI Agent（如 Dify/FastGPT 类编排应用容器）。
        对应 POST /ai/agents/search。

        Args:
            info: Agent 名模糊匹配，留空返回全部。
            page: 页码，从 1 开始。
            page_size: 每页数量，上限 500。
        """
        client = await get_client()
        return await client.post("/ai/agents/search", {
            "info": info or "",
            "page": page,
            "pageSize": page_size,
        })

    @mcp.tool()
    async def ai_agent_providers() -> list:
        """[AI] 查询支持的 AI 模型供应商。读操作。

        返回 1Panel 预置的模型供应商列表（OpenAI、Anthropic、Ollama 等），
        含供应商标识、显示名、可选模型列表。对应 GET /ai/agents/providers。
        创建 Agent/账户时 provider/model 参数从此处取合法值。
        """
        client = await get_client()
        return await client.get("/ai/agents/providers")

    @mcp.tool()
    async def ai_agent_create(
        name: Annotated[str, Field(description="Agent 名称")],
        app_version: Annotated[str, Field(description="Agent 应用版本（来自 ai_agent_providers 返回的 appVersion）")],
        web_ui_port: Annotated[int, Field(ge=1, le=65535, description="Web UI 监听端口")],
        provider: Annotated[Optional[str], Field(description="模型供应商标识")] = None,
        model: Annotated[Optional[str], Field(description="模型名")] = None,
        api_type: Annotated[Optional[str], Field(description="API 类型，如 openai/anthropic")] = None,
        base_url: Annotated[Optional[str], Field(description="自定义 API BaseURL，留空用供应商默认")] = None,
        api_key: Annotated[Optional[str], Field(description="供应商 API Key")] = None,
        account_id: Annotated[Optional[int], Field(description="已绑定的账户 ID，与 api_key 二选一")] = None,
        token: Annotated[Optional[str], Field(description="供应商 token（部分应用用）")] = None,
        container_name: Annotated[Optional[str], Field(description="容器名，留空自动生成")] = None,
        advanced: Annotated[bool, Field(description="是否使用高级（自定义 compose）配置")] = False,
        edit_compose: Annotated[bool, Field(description="advanced=true 时是否编辑 compose")] = False,
        docker_compose: Annotated[Optional[str], Field(description="自定义 docker-compose 内容")] = None,
        cpu_quota: Annotated[Optional[float], Field(description="CPU 限额（核数）")] = None,
        memory_limit: Annotated[Optional[float], Field(description="内存限额")] = None,
        memory_unit: Annotated[Optional[str], Field(description="内存单位，如 MB/GB")] = None,
        pull_image: Annotated[bool, Field(description="是否预先拉取镜像")] = True,
        allow_port: Annotated[bool, Field(description="是否放行端口到防火墙")] = False,
        bridge_port: Annotated[Optional[int], Field(description="Bridge 端口")] = None,
        context_window: Annotated[Optional[int], Field(description="上下文窗口大小")] = None,
        max_tokens: Annotated[Optional[int], Field(description="最大 token 数")] = None,
        restart_policy: Annotated[Optional[str], Field(description="重启策略，如 always/on-failure")] = None,
        specify_ip: Annotated[Optional[str], Field(description="指定容器 IP")] = None,
        agent_type: Annotated[Optional[str], Field(description="Agent 类型标识")] = None,
        task_id: Annotated[Optional[str], Field(description="追踪用 taskID，一般留空")] = None,
    ) -> dict:
        """⚠️写操作 [AI] 创建 AI Agent。

        部署一个 AI Agent 容器（编排应用）。对应 POST /ai/agents。
        name/app_version/web_ui_port 必填，其余按所选应用类型选填。
        模型凭据可用 api_key + base_url 直接传，或用 account_id 引用已建账户。

        Args:
            name: Agent 名称。
            app_version: Agent 应用版本。
            web_ui_port: Web UI 端口。
            provider: 模型供应商标识。
            model: 模型名。
            api_type: API 类型。
            base_url: 自定义 API BaseURL。
            api_key: 供应商 API Key。
            account_id: 已绑定账户 ID。
            token: 供应商 token。
            container_name: 容器名。
            advanced: 是否启用高级配置。
            edit_compose: 是否编辑 compose。
            docker_compose: 自定义 compose 内容。
            cpu_quota: CPU 限额。
            memory_limit: 内存限额。
            memory_unit: 内存单位。
            pull_image: 是否预拉镜像。
            allow_port: 是否放行防火墙端口。
            bridge_port: Bridge 端口。
            context_window: 上下文窗口。
            max_tokens: 最大 token 数。
            restart_policy: 重启策略。
            specify_ip: 指定容器 IP。
            agent_type: Agent 类型。
            task_id: 追踪 taskID。
        """
        require_write()
        client = await get_client()
        body: dict = {
            "name": name,
            "appVersion": app_version,
            "webUIPort": web_ui_port,
            "advanced": advanced,
            "editCompose": edit_compose,
            "pullImage": pull_image,
            "allowPort": allow_port,
        }
        # 仅把非空的可选字段塞进去，避免覆盖 1Panel 默认值
        optional_fields = {
            "provider": provider, "model": model, "apiType": api_type,
            "baseURL": base_url, "apiKey": api_key, "accountId": account_id,
            "token": token, "containerName": container_name,
            "dockerCompose": docker_compose, "cpuQuota": cpu_quota,
            "memoryLimit": memory_limit, "memoryUnit": memory_unit,
            "bridgePort": bridge_port, "contextWindow": context_window,
            "maxTokens": max_tokens, "restartPolicy": restart_policy,
            "specifyIP": specify_ip, "agentType": agent_type,
            "taskID": task_id,
        }
        for k, v in optional_fields.items():
            if v is not None:
                body[k] = v
        return await client.post("/ai/agents", body)

    @mcp.tool()
    async def ai_agent_delete(
        agent_id: Annotated[int, Field(description="Agent ID")],
        force: Annotated[bool, Field(description="是否强制删除（忽略运行中的容器）")] = False,
        confirm: Annotated[bool, Field(description="删除是高危操作，必须传 true")] = False,
    ) -> dict:
        """⚠️高危 [AI] 删除 AI Agent。

        删除指定 Agent（含其容器、配置）。对应 POST /ai/agents/delete。
        不可恢复，必须显式传 confirm=true。

        Args:
            agent_id: Agent ID。
            force: 是否强制删除。
            confirm: 必须为 true。
        """
        require_write()
        if not confirm:
            raise ValueError("删除 AI Agent 是高危操作，必须显式传 confirm=true。")
        client = await get_client()
        return await client.post("/ai/agents/delete", {
            "id": agent_id,
            "forceDelete": force,
        })

    @mcp.tool()
    async def ai_agent_model_update(
        agent_id: Annotated[int, Field(description="Agent ID")],
        account_id: Annotated[int, Field(description="账户 ID（已绑定供应商账号）")],
        model: Annotated[str, Field(description="新模型名")],
    ) -> dict:
        """⚠️写操作 [AI] 更新 Agent 的模型配置。

        把指定 Agent 切换到另一个模型/账户组合。对应 POST /ai/agents/model/update。

        Args:
            agent_id: Agent ID。
            account_id: 账户 ID。
            model: 新模型名。
        """
        require_write()
        client = await get_client()
        return await client.post("/ai/agents/model/update", {
            "agentId": agent_id,
            "accountId": account_id,
            "model": model,
        })

    @mcp.tool()
    async def ai_agent_token_reset(
        agent_id: Annotated[int, Field(description="Agent ID")],
    ) -> dict:
        """⚠️写操作 [AI] 重置 Agent 访问 token。

        重新生成 Agent 的访问 token（旧 token 立即失效，需更新所有客户端）。
        对应 POST /ai/agents/token/reset。

        Args:
            agent_id: Agent ID。
        """
        require_write()
        client = await get_client()
        return await client.post("/ai/agents/token/reset", {"id": agent_id})

    # ================================================================
    # Agent 账户管理（供应商 API Key 凭据池）
    # ================================================================

    @mcp.tool()
    async def ai_account_list(
        name: Annotated[Optional[str], Field(description="账户名模糊匹配")] = None,
        provider: Annotated[Optional[str], Field(description="供应商标识过滤")] = None,
        page: Annotated[int, Field(ge=1, description="页码")] = 1,
        page_size: Annotated[int, Field(ge=1, le=500, description="每页数量")] = 100,
    ) -> dict:
        """[AI] 列出供应商 API Key 账户。读操作。

        分页返回 1Panel 已保存的模型供应商账户（API Key 凭据池），
        用于给 Agent 共享凭据。对应 POST /ai/agents/accounts/search。

        Args:
            name: 账户名模糊匹配。
            provider: 供应商标识过滤。
            page: 页码。
            page_size: 每页数量。
        """
        client = await get_client()
        body: dict = {"page": page, "pageSize": page_size}
        if name:
            body["name"] = name
        if provider:
            body["provider"] = provider
        return await client.post("/ai/agents/accounts/search", body)

    @mcp.tool()
    async def ai_account_create(
        name: Annotated[str, Field(description="账户名")],
        provider: Annotated[str, Field(description="供应商标识（来自 ai_agent_providers）")],
        api_key: Annotated[str, Field(description="供应商 API Key")],
        model: Annotated[Optional[str], Field(description="默认模型名")] = None,
        api_type: Annotated[Optional[str], Field(description="API 类型")] = None,
        base_url: Annotated[Optional[str], Field(description="自定义 BaseURL")] = None,
        context_window: Annotated[Optional[int], Field(description="上下文窗口大小")] = None,
        max_tokens: Annotated[Optional[int], Field(description="最大 token 数")] = None,
        remark: Annotated[Optional[str], Field(description="备注")] = None,
        remember_api_key: Annotated[bool, Field(description="是否记住 API Key（不记住则用完即删）")] = True,
    ) -> dict:
        """⚠️写操作 [AI] 新增供应商 API Key 账户。

        在凭据池中添加一个供应商账户。对应 POST /ai/agents/accounts。

        Args:
            name: 账户名。
            provider: 供应商标识。
            api_key: 供应商 API Key。
            model: 默认模型名。
            api_type: API 类型。
            base_url: 自定义 BaseURL。
            context_window: 上下文窗口。
            max_tokens: 最大 token 数。
            remark: 备注。
            remember_api_key: 是否持久保存 API Key。
        """
        require_write()
        client = await get_client()
        body: dict = {
            "name": name,
            "provider": provider,
            "apiKey": api_key,
            "rememberApiKey": remember_api_key,
        }
        optional_fields = {
            "model": model, "apiType": api_type, "baseURL": base_url,
            "contextWindow": context_window, "maxTokens": max_tokens,
            "remark": remark,
        }
        for k, v in optional_fields.items():
            if v is not None:
                body[k] = v
        return await client.post("/ai/agents/accounts", body)

    @mcp.tool()
    async def ai_account_update(
        account_id: Annotated[int, Field(description="账户 ID")],
        name: Annotated[str, Field(description="账户名")],
        api_key: Annotated[str, Field(description="供应商 API Key")],
        model: Annotated[Optional[str], Field(description="默认模型名")] = None,
        api_type: Annotated[Optional[str], Field(description="API 类型")] = None,
        base_url: Annotated[Optional[str], Field(description="自定义 BaseURL")] = None,
        context_window: Annotated[Optional[int], Field(description="上下文窗口大小")] = None,
        max_tokens: Annotated[Optional[int], Field(description="最大 token 数")] = None,
        remark: Annotated[Optional[str], Field(description="备注")] = None,
        remember_api_key: Annotated[bool, Field(description="是否记住 API Key")] = True,
        sync_agents: Annotated[bool, Field(description="是否同步更新引用此账户的 Agent")] = False,
    ) -> dict:
        """⚠️写操作 [AI] 更新供应商 API Key 账户。

        修改账户信息。对应 POST /ai/agents/accounts/update。
        sync_agents=true 可把新配置同步到所有引用此账户的 Agent。

        Args:
            account_id: 账户 ID。
            name: 账户名。
            api_key: 供应商 API Key。
            model: 默认模型名。
            api_type: API 类型。
            base_url: 自定义 BaseURL。
            context_window: 上下文窗口。
            max_tokens: 最大 token 数。
            remark: 备注。
            remember_api_key: 是否持久保存 API Key。
            sync_agents: 是否同步更新关联 Agent。
        """
        require_write()
        client = await get_client()
        body: dict = {
            "id": account_id,
            "name": name,
            "apiKey": api_key,
            "rememberApiKey": remember_api_key,
            "syncAgents": sync_agents,
        }
        optional_fields = {
            "model": model, "apiType": api_type, "baseURL": base_url,
            "contextWindow": context_window, "maxTokens": max_tokens,
            "remark": remark,
        }
        for k, v in optional_fields.items():
            if v is not None:
                body[k] = v
        return await client.post("/ai/agents/accounts/update", body)

    @mcp.tool()
    async def ai_account_delete(
        account_id: Annotated[int, Field(description="账户 ID")],
        confirm: Annotated[bool, Field(description="删除是高危操作，必须传 true")] = False,
    ) -> dict:
        """⚠️高危 [AI] 删除供应商 API Key 账户。

        从凭据池删除账户。对应 POST /ai/agents/accounts/delete。
        被 Agent 引用的账户需先解除引用，否则用 force 或先删 Agent。
        必须显式传 confirm=true。

        Args:
            account_id: 账户 ID。
            confirm: 必须为 true。
        """
        require_write()
        if not confirm:
            raise ValueError("删除账户是高危操作，必须显式传 confirm=true。")
        client = await get_client()
        return await client.post("/ai/agents/accounts/delete", {"id": account_id})

    @mcp.tool()
    async def ai_account_verify(
        provider: Annotated[str, Field(description="供应商标识")],
        api_key: Annotated[str, Field(description="待校验的 API Key")],
        base_url: Annotated[Optional[str], Field(description="自定义 BaseURL（用自定义端点时传）")] = None,
    ) -> dict:
        """[AI] 校验供应商 API Key 是否可用。读操作。

        不入库，仅向供应商发起探测请求验证凭据有效。对应
        POST /ai/agents/accounts/verify。

        Args:
            provider: 供应商标识。
            api_key: 待校验的 API Key。
            base_url: 自定义 BaseURL。
        """
        client = await get_client()
        body: dict = {"provider": provider, "apiKey": api_key}
        if base_url:
            body["baseURL"] = base_url
        return await client.post("/ai/agents/accounts/verify", body)

    # ================================================================
    # Agent 浏览器 / 其它配置
    # ================================================================

    @mcp.tool()
    async def ai_agent_browser_get(
        agent_id: Annotated[int, Field(description="Agent ID")],
    ) -> dict:
        """[AI] 查询 Agent 浏览器配置。读操作。

        返回指定 Agent 的浏览器自动化配置（是否启用、headless、默认 profile）。
        对应 POST /ai/agents/browser/get。

        Args:
            agent_id: Agent ID。
        """
        client = await get_client()
        return await client.post("/ai/agents/browser/get", {"agentId": agent_id})

    @mcp.tool()
    async def ai_agent_browser_update(
        agent_id: Annotated[int, Field(description="Agent ID")],
        default_profile: Annotated[str, Field(description="默认浏览器 profile 名")],
        enabled: Annotated[bool, Field(description="是否启用浏览器")] = False,
        headless: Annotated[bool, Field(description="是否无头模式")] = True,
        no_sandbox: Annotated[bool, Field(description="是否禁用 sandbox（容器内常需）")] = False,
    ) -> dict:
        """⚠️写操作 [AI] 更新 Agent 浏览器配置。

        配置 Agent 的浏览器自动化能力。对应 POST /ai/agents/browser/update。

        Args:
            agent_id: Agent ID。
            default_profile: 默认 profile 名。
            enabled: 是否启用浏览器。
            headless: 是否无头模式。
            no_sandbox: 是否禁用 sandbox。
        """
        require_write()
        client = await get_client()
        return await client.post("/ai/agents/browser/update", {
            "agentId": agent_id,
            "defaultProfile": default_profile,
            "enabled": enabled,
            "headless": headless,
            "noSandbox": no_sandbox,
        })

    @mcp.tool()
    async def ai_agent_other_get(
        agent_id: Annotated[int, Field(description="Agent ID")],
    ) -> dict:
        """[AI] 查询 Agent 其它配置。读操作。

        返回指定 Agent 的其它配置（如时区）。对应 POST /ai/agents/other/get。

        Args:
            agent_id: Agent ID。
        """
        client = await get_client()
        return await client.post("/ai/agents/other/get", {"agentId": agent_id})

    @mcp.tool()
    async def ai_agent_other_update(
        agent_id: Annotated[int, Field(description="Agent ID")],
        user_timezone: Annotated[str, Field(description="用户时区，如 Asia/Shanghai")],
    ) -> dict:
        """⚠️写操作 [AI] 更新 Agent 其它配置。

        更新 Agent 的时区等杂项配置。对应 POST /ai/agents/other/update。

        Args:
            agent_id: Agent ID。
            user_timezone: 用户时区（IANA 时区名）。
        """
        require_write()
        client = await get_client()
        return await client.post("/ai/agents/other/update", {
            "agentId": agent_id,
            "userTimezone": user_timezone,
        })

    # ================================================================
    # Agent 渠道配置（Discord / Telegram / 飞书）
    # ================================================================

    @mcp.tool()
    async def ai_agent_discord_get(
        agent_id: Annotated[int, Field(description="Agent ID")],
    ) -> dict:
        """[AI] 查询 Agent Discord 渠道配置。读操作。

        对应 POST /ai/agents/channel/discord/get。

        Args:
            agent_id: Agent ID。
        """
        client = await get_client()
        return await client.post("/ai/agents/channel/discord/get", {"agentId": agent_id})

    @mcp.tool()
    async def ai_agent_discord_update(
        agent_id: Annotated[int, Field(description="Agent ID")],
        token: Annotated[str, Field(description="Discord Bot Token")],
        dm_policy: Annotated[str, Field(description="私聊策略，如 open/allowlist/disabled")],
        group_policy: Annotated[Literal["open", "allowlist", "disabled"], Field(description="群聊策略")] = "disabled",
        enabled: Annotated[bool, Field(description="是否启用")] = False,
        proxy: Annotated[Optional[str], Field(description="代理地址")] = None,
    ) -> dict:
        """⚠️写操作 [AI] 更新 Agent Discord 渠道配置。

        对应 POST /ai/agents/channel/discord/update。

        Args:
            agent_id: Agent ID。
            token: Discord Bot Token。
            dm_policy: 私聊策略。
            group_policy: 群聊策略：open/allowlist/disabled。
            enabled: 是否启用。
            proxy: 代理地址。
        """
        require_write()
        client = await get_client()
        body: dict = {
            "agentId": agent_id,
            "token": token,
            "dmPolicy": dm_policy,
            "groupPolicy": group_policy,
            "enabled": enabled,
        }
        if proxy:
            body["proxy"] = proxy
        return await client.post("/ai/agents/channel/discord/update", body)

    @mcp.tool()
    async def ai_agent_telegram_get(
        agent_id: Annotated[int, Field(description="Agent ID")],
    ) -> dict:
        """[AI] 查询 Agent Telegram 渠道配置。读操作。

        对应 POST /ai/agents/channel/telegram/get。

        Args:
            agent_id: Agent ID。
        """
        client = await get_client()
        return await client.post("/ai/agents/channel/telegram/get", {"agentId": agent_id})

    @mcp.tool()
    async def ai_agent_telegram_update(
        agent_id: Annotated[int, Field(description="Agent ID")],
        bot_token: Annotated[str, Field(description="Telegram Bot Token")],
        dm_policy: Annotated[str, Field(description="私聊策略，如 open/allowlist/disabled")],
        enabled: Annotated[bool, Field(description="是否启用")] = False,
        proxy: Annotated[Optional[str], Field(description="代理地址")] = None,
    ) -> dict:
        """⚠️写操作 [AI] 更新 Agent Telegram 渠道配置。

        对应 POST /ai/agents/channel/telegram/update。

        Args:
            agent_id: Agent ID。
            bot_token: Telegram Bot Token。
            dm_policy: 私聊策略。
            enabled: 是否启用。
            proxy: 代理地址。
        """
        require_write()
        client = await get_client()
        body: dict = {
            "agentId": agent_id,
            "botToken": bot_token,
            "dmPolicy": dm_policy,
            "enabled": enabled,
        }
        if proxy:
            body["proxy"] = proxy
        return await client.post("/ai/agents/channel/telegram/update", body)

    @mcp.tool()
    async def ai_agent_feishu_get(
        agent_id: Annotated[int, Field(description="Agent ID")],
    ) -> dict:
        """[AI] 查询 Agent 飞书渠道配置。读操作。

        对应 POST /ai/agents/channel/feishu/get。

        Args:
            agent_id: Agent ID。
        """
        client = await get_client()
        return await client.post("/ai/agents/channel/feishu/get", {"agentId": agent_id})

    @mcp.tool()
    async def ai_agent_feishu_update(
        agent_id: Annotated[int, Field(description="Agent ID")],
        app_id: Annotated[str, Field(description="飞书应用 App ID")],
        app_secret: Annotated[str, Field(description="飞书应用 App Secret")],
        bot_name: Annotated[str, Field(description="飞书机器人名")],
        dm_policy: Annotated[str, Field(description="私聊策略，如 open/allowlist/disabled")],
        enabled: Annotated[bool, Field(description="是否启用")] = False,
    ) -> dict:
        """⚠️写操作 [AI] 更新 Agent 飞书渠道配置。

        对应 POST /ai/agents/channel/feishu/update。

        Args:
            agent_id: Agent ID。
            app_id: 飞书 App ID。
            app_secret: 飞书 App Secret。
            bot_name: 机器人名。
            dm_policy: 私聊策略。
            enabled: 是否启用。
        """
        require_write()
        client = await get_client()
        return await client.post("/ai/agents/channel/feishu/update", {
            "agentId": agent_id,
            "appId": app_id,
            "appSecret": app_secret,
            "botName": bot_name,
            "dmPolicy": dm_policy,
            "enabled": enabled,
        })

    @mcp.tool()
    async def ai_agent_feishu_pairing_approve(
        agent_id: Annotated[int, Field(description="Agent ID")],
        pairing_code: Annotated[str, Field(description="飞书配对码（用户在飞书端发起获取）")],
    ) -> dict:
        """⚠️写操作 [AI] 批准飞书渠道配对。

        完成飞书机器人与本 Agent 的配对绑定。对应
        POST /ai/agents/channel/feishu/approve。

        Args:
            agent_id: Agent ID。
            pairing_code: 配对码。
        """
        require_write()
        client = await get_client()
        return await client.post("/ai/agents/channel/feishu/approve", {
            "agentId": agent_id,
            "pairingCode": pairing_code,
        })

    @mcp.tool()
    async def ai_agent_channel_pairing_approve(
        agent_id: Annotated[int, Field(description="Agent ID")],
        pairing_code: Annotated[str, Field(description="配对码")],
        channel_type: Annotated[Literal["feishu", "telegram", "discord"], Field(description="渠道类型")],
    ) -> dict:
        """⚠️写操作 [AI] 批准渠道配对（通用）。

        通用的渠道配对审批入口，支持飞书/Telegram/Discord。对应
        POST /ai/agents/channel/pairing/approve。

        Args:
            agent_id: Agent ID。
            pairing_code: 配对码。
            channel_type: 渠道类型：feishu/telegram/discord。
        """
        require_write()
        client = await get_client()
        return await client.post("/ai/agents/channel/pairing/approve", {
            "agentId": agent_id,
            "pairingCode": pairing_code,
            "type": channel_type,
        })
