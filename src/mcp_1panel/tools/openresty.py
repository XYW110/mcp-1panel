"""OpenResty（nginx）模块（对应 openapi.json 的 OpenResty tag + PHP Extensions tag）。

照 container.py 黄金范式风格：
1. 工具名：openresty_<action> / php_extensions_<action>
2. description：[OpenResty] 开头，写操作加 ⚠️，影响全局的高危操作加 confirm
3. 入参用 Annotated[T, Field(description=...)]
4. handler 用 `await get_client()` 拿共享客户端，调 .get() / .post()
5. 写操作开头调 require_write()

接口来源：references/openapi.json（AGENTS.md 指定权威数据源），basePath /api/v2。

⚠️ 关于服务生命周期（start/stop/restart）：
openapi.json 的 OpenResty tag 下**没有** start/stop/restart 端点。1Panel 的
OpenResty 是按配置驱动运行的：reload 通过"更新配置"实现，启停由 1Panel 进程托管，
不暴露独立的 start/stop/restart API。本模块严格只实现 openapi.json 里真实存在的
10 个 OpenResty + 4 个 PHP Extensions 接口，不编造不存在的端点。

OpenResty 接口清单（10 个）：
- GET  /openresty              加载 nginx.conf 内容（openresty_config_get）
- GET  /openresty/status       OpenResty 运行状态指标（openresty_status）
- GET  /openresty/https        默认 HTTPS 开关状态（openresty_https_status）
- GET  /openresty/modules      OpenResty 构建配置/模块列表（openresty_base）
- POST /openresty/scope        按 scope 加载 nginx 配置段（openresty_scope）
- POST /openresty/file         上传文件方式更新 nginx 配置（openresty_config_update）
- POST /openresty/update       按 scope 更新 nginx 配置参数（openresty_scope_update）
- POST /openresty/build        构建 OpenResty（openresty_build，高危及全站，需 confirm）
- POST /openresty/https        启停默认 HTTPS（openresty_https_update）
- POST /openresty/modules/update 更新/新增/删除编译模块（openresty_module_update，构建级）

PHP Extensions 接口清单（4 个）：
- POST /runtimes/php/extensions/search   分页查询 PHP 扩展（php_extensions_search）
- POST /runtimes/php/extensions          新建 PHP 扩展（php_extensions_create）
- POST /runtimes/php/extensions/update   更新 PHP 扩展（php_extensions_update）
- POST /runtimes/php/extensions/del      删除 PHP 扩展（php_extensions_delete，需 confirm）
"""

from __future__ import annotations

from typing import Annotated, Literal, Optional

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..client import get_client
from ..safety import require_write


# ---- 枚举（来自 openapi.json definitions） ----

# dto.NginxKey —— nginx 配置段标识，scope / openresty_scope / openresty_scope_update 共用
NginxScope = Literal[
    "index",        # 首页/根 location 配置
    "limit-conn",   # 并发连接限制
    "ssl",          # SSL/TLS 配置
    "cache",        # 缓存配置
    "http-per",     # HTTP 性能参数
    "proxy-cache",  # 反向代理缓存
]
# request.NginxDefaultHTTPSUpdate.operate —— 默认 HTTPS 开关
HttpsOperate = Literal["enable", "disable"]
# request.NginxModuleUpdate.operate —— 模块增/改/删
ModuleOperate = Literal["create", "update", "delete"]
# request.NginxConfigUpdate.operate —— scope 配置增/改/删
ScopeConfigOperate = Literal["add", "update", "delete"]


def register(mcp: FastMCP) -> None:

    # ---- 读：OpenResty 运行状态 / 配置 / 构建 ----

    @mcp.tool()
    async def openresty_status() -> dict:
        """[OpenResty] 获取 OpenResty（nginx）运行状态指标。读操作。

        返回 nginx stub_status 风格的实时指标：active/handled/accepts/requests/
        reading/writing/waiting。对应 GET /openresty/status。

        Returns:
            dict，字段含 active(活跃连接数)、accepts(总连接)、handled(已处理)、
            requests(总请求)、reading(读)、writing(写)、waiting(等待长连接)。
        """
        client = await get_client()
        return await client.get("/openresty/status")

    @mcp.tool()
    async def openresty_base() -> dict:
        """[OpenResty] 获取 OpenResty 构建配置与已编译模块列表。读操作。

        返回 OpenResty 的镜像源（mirror）和当前编译进去的模块列表（含每个模块的
        name/enable/packages/params/script）。对应 GET /openresty/modules。

        用于在执行 openresty_build 或 openresty_module_update 之前查看现有配置。

        Returns:
            dict，字段 mirror(镜像源) 与 modules(模块列表)。
        """
        client = await get_client()
        return await client.get("/openresty/modules")

    @mcp.tool()
    async def openresty_config_get() -> dict:
        """[OpenResty] 加载 OpenResty（nginx）主配置文件内容。读操作。

        返回 nginx.conf 的完整文本内容，用于审阅/修改。对应 GET /openresty。
        返回的 content 字段为 nginx 配置字符串，修改后可用 openresty_config_update 回写。

        Returns:
            dict，字段 content 为 nginx.conf 文本内容。
        """
        client = await get_client()
        return await client.get("/openresty")

    @mcp.tool()
    async def openresty_https_status() -> dict:
        """[OpenResty] 获取默认 HTTPS（443）开关状态。读操作。

        返回 1Panel 默认 HTTPS 站点的启用状态，以及 sslRejectHandshake（HTTPS 未匹配
        时是否拒绝握手，拒绝可避免证书泄露域名）。对应 GET /openresty/https。

        Returns:
            dict，字段 https(是否启用默认 HTTPS)、sslRejectHandshake(是否拒绝未匹配 SNI 的握手)。
        """
        client = await get_client()
        return await client.get("/openresty/https")

    @mcp.tool()
    async def openresty_scope(
        scope: Annotated[NginxScope, Field(description="配置段标识：index/limit-conn/ssl/cache/http-per/proxy-cache")],
        website_id: Annotated[Optional[int], Field(description="网站 ID，加载某网站的配置段时传入；不传则查全局默认段")] = None,
    ) -> list:
        """[OpenResty] 按 scope 加载 nginx 配置段（结构化参数）。读操作。

        1Panel 把 nginx 配置按 scope 分段管理，此接口返回某 scope 下的参数项
        （NginxParam 列表，含 name 与 params）。对应 POST /openresty/scope。

        通常先调此接口拿到现有参数，再用 openresty_scope_update 增改删。

        Args:
            scope: 配置段标识。index 首页、limit-conn 并发限制、ssl SSL、
                cache 缓存、http-per HTTP 性能、proxy-cache 反代缓存。
            website_id: 网站 ID，查某网站的该 scope 时传入；省略查全局默认。

        Returns:
            list[NginxParam]，每项含 name（参数名）与 params（参数取值列表）。
        """
        client = await get_client()
        body: dict = {"scope": scope}
        if website_id is not None:
            body["websiteId"] = website_id
        return await client.post("/openresty/scope", body)

    # ---- 写：OpenResty 配置更新 ----

    @mcp.tool()
    async def openresty_config_update(
        content: Annotated[str, Field(description="nginx.conf 的完整文本内容（替换式写入）")],
        backup: Annotated[bool, Field(description="是否在更新前备份当前配置，建议 true")] = True,
    ) -> dict:
        """⚠️写操作 [OpenResty] 更新 OpenResty（nginx）主配置文件内容。

        以整体覆盖方式写入 nginx.conf 内容（先用 openresty_config_get 读出当前内容
        再修改回写）。对应 POST /openresty/file。1Panel 会在写入后自动 reload nginx，
        配置语法错误可能导致 OpenResty 无法启动，请先在本地校验。

        Args:
            content: nginx.conf 完整文本（替换式，非增量）。
            backup: 是否先备份原配置，建议 true。
        """
        require_write()
        client = await get_client()
        return await client.post("/openresty/file", {
            "content": content,
            "backup": backup,
        })

    @mcp.tool()
    async def openresty_scope_update(
        operate: Annotated[ScopeConfigOperate, Field(description="操作类型：add 新增 / update 修改 / delete 删除")],
        scope: Annotated[NginxScope, Field(description="目标配置段：index/limit-conn/ssl/cache/http-per/proxy-cache")],
        website_id: Annotated[Optional[int], Field(description="网站 ID，改某网站的该 scope 时传入；省略改全局默认段")] = None,
        params: Annotated[Optional[dict], Field(description="该 scope 的参数项（结构由各 scope 决定，通常来自 openresty_scope 返回的结构改后回传）")] = None,
    ) -> dict:
        """⚠️写操作 [OpenResty] 按 scope 增改删 nginx 配置参数。

        对某 scope 的参数项做增/改/删，1Panel 会重新渲染该段 nginx 配置并 reload。
        对应 POST /openresty/update。建议先用 openresty_scope 读出该 scope 现有参数，
        再据此构造 params 调用本接口。

        Args:
            operate: add 新增 / update 修改 / delete 删除。
            scope: 目标配置段。
            website_id: 网站 ID，操作某网站的该 scope 时传入。
            params: 参数项内容，结构随 scope 不同（一般来自 openresty_scope 返回改写）。
        """
        require_write()
        client = await get_client()
        body: dict = {"operate": operate, "scope": scope}
        if website_id is not None:
            body["websiteId"] = website_id
        if params is not None:
            body["params"] = params
        return await client.post("/openresty/update", body)

    @mcp.tool()
    async def openresty_https_update(
        operate: Annotated[HttpsOperate, Field(description="enable 启用默认 HTTPS / disable 关闭")],
        ssl_reject_handshake: Annotated[bool, Field(description="未匹配 SNI 时是否拒绝握手（拒绝可防证书泄露域名），启用 HTTPS 时建议 true")] = False,
    ) -> dict:
        """⚠️写操作 [OpenResty] 启停默认 HTTPS（443 端口）站点。

        操作 1Panel 默认 HTTPS 站点的启用/关闭，影响所有未单独配置 HTTPS 的请求走向。
        对应 POST /openresty/https。关闭默认 HTTPS 后，未匹配到网站的 HTTPS 请求将被
        重置，可能影响证书申请/续签流程。

        Args:
            operate: enable 启用 / disable 关闭默认 HTTPS。
            ssl_reject_handshake: 未匹配 SNI 时是否拒绝握手。
        """
        require_write()
        client = await get_client()
        return await client.post("/openresty/https", {
            "operate": operate,
            "sslRejectHandshake": ssl_reject_handshake,
        })

    # ---- 写：构建级高危操作（影响全站） ----

    @mcp.tool()
    async def openresty_module_update(
        name: Annotated[str, Field(description="模块名称")],
        operate: Annotated[ModuleOperate, Field(description="操作类型：create 新增 / update 修改 / delete 删除模块")],
        enable: Annotated[bool, Field(description="模块是否启用")] = False,
        packages: Annotated[Optional[str], Field(description="模块依赖的系统包（空格分隔），create/update 时填")] = None,
        params: Annotated[Optional[str], Field(description="编译参数（传给 ./configure），create/update 时填")] = None,
        script: Annotated[Optional[str], Field(description="自定义构建脚本内容，create/update 时填")] = None,
    ) -> dict:
        """⚠️写操作 [OpenResty] 新增/修改/删除 OpenResty 编译模块。

        管理需要重新编译进 OpenResty 的第三方模块（如 lua、brotli 等）。对应
        POST /openresty/modules/update。模块变更不会立即生效，需随后调用
        openresty_build 重新构建 OpenResty。

        Args:
            name: 模块名。
            operate: create 新增 / update 修改 / delete 删除。
            enable: 是否启用。
            packages: 依赖系统包（空格分隔）。
            params: 编译参数。
            script: 自定义构建脚本。
        """
        require_write()
        client = await get_client()
        body: dict = {
            "name": name,
            "operate": operate,
            "enable": enable,
        }
        if packages is not None:
            body["packages"] = packages
        if params is not None:
            body["params"] = params
        if script is not None:
            body["script"] = script
        return await client.post("/openresty/modules/update", body)

    @mcp.tool()
    async def openresty_build(
        mirror: Annotated[str, Field(description="构建用镜像源地址（可从 openresty_base 获取当前值）")],
        task_id: Annotated[str, Field(description="构建任务唯一 ID（用于异步跟踪构建进度，建议用 UUID）")],
        confirm: Annotated[bool, Field(description="重新构建 OpenResty 会中断所有网站服务，必须传 true 才执行")] = False,
    ) -> dict:
        """⚠️高危 [OpenResty] 重新构建 OpenResty（按当前模块配置编译镜像）。

        会依据当前已配置的模块列表（见 openresty_base）重新编译 OpenResty 镜像，
        并替换运行中的实例。构建期间所有依赖 OpenResty 的网站会中断服务，且构建
        失败可能导致 OpenResty 无法启动。对应 POST /openresty/build。

        必须显式传 confirm=true 才执行。建议先 openresty_base 查看配置，准备好
        唯一 task_id 后再调用。

        Args:
            mirror: 镜像源地址。
            task_id: 构建任务 ID（异步跟踪用）。
            confirm: 必须为 true 才执行（构建影响全站）。
        """
        require_write()
        if not confirm:
            raise ValueError(
                "重新构建 OpenResty 是高危操作（会中断所有网站服务），"
                "必须显式传 confirm=true 才能执行。"
            )
        client = await get_client()
        return await client.post("/openresty/build", {
            "mirror": mirror,
            "taskID": task_id,
        })

    # ---- PHP Extensions（PHP 运行时扩展管理） ----

    @mcp.tool()
    async def php_extensions_search(
        page: Annotated[int, Field(ge=1, description="页码")] = 1,
        page_size: Annotated[int, Field(ge=1, le=500, description="每页数量")] = 100,
        all: Annotated[bool, Field(description="true 时忽略分页返回全部扩展")] = False,
    ) -> dict:
        """[PHP扩展] 分页查询 PHP 运行时已安装的扩展列表。读操作。

        返回 1Panel 管理的 PHP 运行时扩展分页结果。对应
        POST /runtimes/php/extensions/search。

        Args:
            page: 页码，从 1 开始。
            page_size: 每页数量，上限 500。
            all: true 时忽略分页返回全部。
        """
        client = await get_client()
        return await client.post("/runtimes/php/extensions/search", {
            "page": page,
            "pageSize": page_size,
            "all": all,
        })

    @mcp.tool()
    async def php_extensions_create(
        name: Annotated[str, Field(description="扩展名称（PHP 运行时标识）")],
        extensions: Annotated[str, Field(description="扩展内容/配置，按 1Panel 约定的字符串格式")],
    ) -> dict:
        """⚠️写操作 [PHP扩展] 新建 PHP 扩展。

        给指定 PHP 运行时新增扩展配置。对应 POST /runtimes/php/extensions。

        Args:
            name: 扩展/运行时名称。
            extensions: 扩展内容字符串。
        """
        require_write()
        client = await get_client()
        return await client.post("/runtimes/php/extensions", {
            "name": name,
            "extensions": extensions,
        })

    @mcp.tool()
    async def php_extensions_update(
        id: Annotated[int, Field(description="扩展 ID")],
        extensions: Annotated[str, Field(description="更新后的扩展内容字符串")],
    ) -> dict:
        """⚠️写操作 [PHP扩展] 更新已有 PHP 扩展。

        按扩展 ID 修改其内容。对应 POST /runtimes/php/extensions/update。

        Args:
            id: 扩展 ID。
            extensions: 更新后的扩展内容字符串。
        """
        require_write()
        client = await get_client()
        return await client.post("/runtimes/php/extensions/update", {
            "id": id,
            "extensions": extensions,
        })

    @mcp.tool()
    async def php_extensions_delete(
        id: Annotated[int, Field(description="要删除的扩展 ID")],
        confirm: Annotated[bool, Field(description="删除扩展不可恢复，必须传 true 才执行")] = False,
    ) -> dict:
        """⚠️高危 [PHP扩展] 删除 PHP 扩展。

        按扩展 ID 删除，不可恢复。对应 POST /runtimes/php/extensions/del。
        删除被运行中 PHP 网站依赖的扩展会导致网站报错，请先确认无依赖。
        必须显式传 confirm=true。

        Args:
            id: 要删除的扩展 ID。
            confirm: 必须为 true 才执行。
        """
        require_write()
        if not confirm:
            raise ValueError("删除 PHP 扩展是高危操作，必须显式传 confirm=true。")
        client = await get_client()
        return await client.post("/runtimes/php/extensions/del", {"id": id})
