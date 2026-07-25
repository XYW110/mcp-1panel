"""网站模块（对应 openapi.json 的 Website / Website Domain / Website SSL /
Website HTTPS / Website Nginx / Website Acme / Website CA / Website DNS /
Website PHP 等 tag，80+ 接口）。

实现风格对齐黄金范式 container.py：
1. 工具名：<object>_<action>（website_search / website_create / ...）
2. description：结构化，[模块] 开头，写操作加 ⚠️，便于 mcphub 向量搜索召回
3. 入参用 Annotated[T, Field(description=...)]，复杂 body 在 handler 里拼 dict
4. handler 用 `await get_client()` 拿共享客户端，调 .search() / .post() / .get()
5. 写操作开头调 require_write()，高危操作加 confirm 参数

⚠️ 踩坑提醒（已内化到工具实现）：
- 获取反代真实后端用 POST /websites/proxies body {"id": site_id} → data[].proxyPass
  （GET /websites/{id} 的 proxy 字段是创建快照，可能过期）
- 获取生效域名用 GET /websites/domains/{websiteId}
  （不能用 GET /websites/{id} 的 name 字段，那只是网站名）
- 分页 orderBy：website 系列混用驼峰与下划线（search 接受 createdAt 与 created_at 等
  多个值），每个 search 接口的 enum 不同，已按 openapi.json 精确指定。

接口来源：references/openapi.json 的 /websites/* 与 /runtimes/* 路径，basePath /api/v2。
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Optional

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..client import get_client
from ..safety import require_write


# ---- 枚举（按 openapi.json 精确指定，避免传错 orderBy/order 触发 400）----

# /websites/search 的 orderBy enum：混用驼峰与下划线
WebsiteOrderBy = Literal[
    "primary_domain", "type", "status", "createdAt",
    "expire_date", "created_at", "favorite",
]
# /websites/ssl/search 的 orderBy enum（纯下划线）
WebsiteSSLOrderBy = Literal["created_at", "expire_date"]

WebsiteType = Literal["runtime", "static", "proxy", "PHP", "external"]
WebsiteOpType = Literal["start", "stop", "restart"]
SSLCertType = Literal["existed", "auto", "manual"]
SSLUploadType = Literal["paste", "local"]
AcmeType = Literal["letsencrypt", "zerossl", "buypass", "google", "custom"]
KeyType = Literal["P256", "P384", "2048", "3072", "4096", "8192"]
HttpConfig = Literal["HTTPSOnly", "HTTPAlso", "HTTPToHTTPS"]
NginxScope = Literal[
    "index", "limit-conn", "ssl", "cache", "http-per", "proxy-cache",
]


def register(mcp: FastMCP) -> None:

    # ====================================================================
    # Website 主体 CRUD
    # ====================================================================

    @mcp.tool()
    async def website_search(
        name: Annotated[Optional[str], Field(description="网站名/主域名模糊匹配，留空返回全部")] = None,
        type: Annotated[Optional[str], Field(description="按类型过滤：runtime/static/proxy 等")] = None,
        website_group_id: Annotated[Optional[int], Field(description="按网站分组 ID 过滤")] = None,
        page: Annotated[int, Field(ge=1, description="页码，从 1 开始")] = 1,
        page_size: Annotated[int, Field(ge=1, le=500, description="每页数量")] = 100,
        order_by: Annotated[WebsiteOrderBy, Field(description="排序字段")] = "createdAt",
        order: Annotated[Literal["ascending", "descending", "null"], Field(description="排序方向")] = "descending",
    ) -> dict:
        """[网站] 分页搜索网站列表。读操作。

        1Panel 网站分页查询接口，支持按名称、类型、分组过滤。对应
        POST /websites/search。返回分页网站列表（含主域名、类型、状态、协议等）。

        注意：返回的 name/primaryDomain 是网站名/主域名快照，**生效域名请用
        website_domains_list**（GET /websites/domains/{websiteId}）。

        Args:
            name: 网站名/主域名模糊匹配。
            type: 按类型过滤（runtime/static/proxy）。
            website_group_id: 按分组 ID 过滤。
            page: 页码，从 1 开始。
            page_size: 每页数量，上限 500。
            order_by: 排序字段，可选 primary_domain/type/status/createdAt/
                expire_date/created_at/favorite。
            order: 排序方向。
        """
        client = await get_client()
        body: dict[str, Any] = {
            "page": page,
            "pageSize": page_size,
            "orderBy": order_by,
            "order": order,
        }
        if name is not None:
            body["name"] = name
        if type is not None:
            body["type"] = type
        if website_group_id is not None:
            body["websiteGroupId"] = website_group_id
        return await client.post("/websites/search", body)

    @mcp.tool()
    async def website_list() -> dict:
        """[网站] 列出全部网站（简表，用于下拉选项）。读操作。

        返回所有网站的简表（id/主域名/类型等，不含详情）。对应 GET /websites/list。
        比 website_search 更轻量，但无分页/过滤。
        """
        client = await get_client()
        return await client.get("/websites/list")

    @mcp.tool()
    async def website_options() -> dict:
        """[网站] 列出网站名选项（id/alias/primaryDomain）。读操作。

        返回所有网站的 id/alias/primaryDomain 三元组，用于表单选择。
        对应 POST /websites/options（无 body）。
        """
        client = await get_client()
        return await client.post("/websites/options", {})

    @mcp.tool()
    async def website_detail(
        website_id: Annotated[int, Field(description="网站 ID")],
    ) -> dict:
        """[网站] 获取网站详情。读操作。

        返回单个网站的完整配置（主域名、类型、协议、代理、SSL、运行时等）。
        对应 GET /websites/{id}。

        ⚠️ 注意：
        - 返回的 domains/proxy 是**创建时的快照**，可能过期。
        - 获取当前生效的绑定域名请用 website_domains_list。
        - 获取反代真实后端请用 website_proxies_get。

        Args:
            website_id: 网站 ID。
        """
        client = await get_client()
        return await client.get(f"/websites/{website_id}")

    @mcp.tool()
    async def website_create(
        alias: Annotated[str, Field(description="网站别名/显示名")],
        type: Annotated[str, Field(description="网站类型：runtime/static/proxy 等")],
        web_site_group_id: Annotated[int, Field(description="网站分组 ID，默认分组传 1")],
        domains: Annotated[list[str], Field(description="绑定主域名列表，如 ['example.com']")] = None,
        port: Annotated[int, Field(description="监听端口，默认 80")] = 80,
        primary_domain: Annotated[Optional[str], Field(description="主域名（部分类型必填）")] = None,
        remark: Annotated[str, Field(description="备注")] = "",
        proxy: Annotated[Optional[str], Field(description="反代目标地址（proxy 类型用），如 http://127.0.0.1:8080")] = None,
        proxy_type: Annotated[Optional[str], Field(description="反代类型：http/tcp/udp")] = None,
        runtime_id: Annotated[Optional[int], Field(description="运行时 ID（runtime/PHP 类型用）")] = None,
        app_type: Annotated[Optional[Literal["new", "installed"]], Field(description="应用安装方式")] = None,
        app_install_id: Annotated[Optional[int], Field(description="已安装应用 ID（appType=installed 时用）")] = None,
        web_site_ssl_id: Annotated[Optional[int], Field(description="已有 SSL ID（创建即启用 HTTPS 时用）")] = None,
        enable_ssl: Annotated[bool, Field(description="是否在创建时启用 SSL")] = False,
        other_domains: Annotated[Optional[str], Field(description="其他域名，逗号分隔")] = None,
        ip_v6: Annotated[bool, Field(description="是否监听 IPv6")] = False,
    ) -> dict:
        """⚠️写操作 [网站] 创建网站。

        创建一个新网站（静态/运行时/反代等）。对应 POST /websites。
        根据 type 不同，需提供不同字段：proxy 类型需 proxy+proxyType，
        runtime/PHP 类型需 runtime_id。

        Args:
            alias: 网站别名。
            type: 网站类型。
            web_site_group_id: 分组 ID。
            domains: 绑定域名列表（每项可含端口，如 example.com:8080）。
            port: 监听端口。
            primary_domain: 主域名。
            remark: 备注。
            proxy: 反代目标（proxy 类型必填）。
            proxy_type: 反代类型。
            runtime_id: 运行时 ID。
            app_type: 应用安装方式。
            app_install_id: 已安装应用 ID。
            web_site_ssl_id: 已有 SSL ID。
            enable_ssl: 创建时启用 SSL。
            other_domains: 其他域名。
            ip_v6: 监听 IPv6。
        """
        require_write()
        client = await get_client()
        body: dict[str, Any] = {
            "alias": alias,
            "type": type,
            "webSiteGroupID": web_site_group_id,
            "port": port,
            "remark": remark,
            "IPV6": ip_v6,
            "enableSSL": enable_ssl,
        }
        if primary_domain is not None:
            body["primaryDomain"] = primary_domain
        if other_domains is not None:
            body["otherDomains"] = other_domains
        if domains:
            body["domains"] = [{"domain": d} for d in domains]
        if proxy is not None:
            body["proxy"] = proxy
        if proxy_type is not None:
            body["proxyType"] = proxy_type
        if runtime_id is not None:
            body["runtimeID"] = runtime_id
        if app_type is not None:
            body["appType"] = app_type
        if app_install_id is not None:
            body["appInstallID"] = app_install_id
        if web_site_ssl_id is not None:
            body["websiteSSLID"] = web_site_ssl_id
        return await client.post("/websites", body)

    @mcp.tool()
    async def website_update(
        website_id: Annotated[int, Field(description="网站 ID")],
        primary_domain: Annotated[str, Field(description="主域名")],
        remark: Annotated[str, Field(description="备注")] = "",
        expire_date: Annotated[str, Field(description="过期日期，如 2025-12-31")] = "",
        web_site_group_id: Annotated[Optional[int], Field(description="网站分组 ID")] = None,
        favorite: Annotated[Optional[bool], Field(description="是否收藏")] = None,
        ip_v6: Annotated[Optional[bool], Field(description="是否监听 IPv6")] = None,
    ) -> dict:
        """⚠️写操作 [网站] 更新网站基础信息（主域名/备注/分组/过期/收藏）。

        修改网站的基础元信息。对应 POST /websites/update。

        Args:
            website_id: 网站 ID。
            primary_domain: 主域名（必填）。
            remark: 备注。
            expire_date: 过期日期，留空表示不过期。
            web_site_group_id: 调整到的分组 ID。
            favorite: 是否收藏。
            ip_v6: 是否监听 IPv6。
        """
        require_write()
        client = await get_client()
        body: dict[str, Any] = {
            "id": website_id,
            "primaryDomain": primary_domain,
            "remark": remark,
            "expireDate": expire_date,
        }
        if web_site_group_id is not None:
            body["webSiteGroupID"] = web_site_group_id
        if favorite is not None:
            body["favorite"] = favorite
        if ip_v6 is not None:
            body["IPV6"] = ip_v6
        return await client.post("/websites/update", body)

    @mcp.tool()
    async def website_delete(
        website_id: Annotated[int, Field(description="网站 ID")],
        delete_app: Annotated[bool, Field(description="是否同时删除关联应用")] = False,
        delete_db: Annotated[bool, Field(description="是否同时删除关联数据库")] = False,
        delete_backup: Annotated[bool, Field(description="是否同时删除备份")] = False,
        force_delete: Annotated[bool, Field(description="是否强制删除（即使有残留资源）")] = False,
        confirm: Annotated[bool, Field(description="删除是高危操作，必须传 true")] = False,
    ) -> dict:
        """⚠️高危 [网站] 删除网站。

        删除指定网站，可选择级联删除关联应用/数据库/备份。对应 POST /websites/del。
        必须显式传 confirm=true 才执行。

        Args:
            website_id: 网站 ID。
            delete_app: 同时删除关联的应用安装。
            delete_db: 同时删除关联的数据库。
            delete_backup: 同时删除网站备份。
            force_delete: 强制删除（即使存在残留资源也继续）。
            confirm: 必须为 true 才执行删除。
        """
        require_write()
        if not confirm:
            raise ValueError("删除网站是高危操作，必须显式传 confirm=true。")
        client = await get_client()
        return await client.post("/websites/del", {
            "id": website_id,
            "deleteApp": delete_app,
            "deleteDB": delete_db,
            "deleteBackup": delete_backup,
            "forceDelete": force_delete,
        })

    @mcp.tool()
    async def website_operate(
        website_id: Annotated[int, Field(description="网站 ID")],
        operate: Annotated[WebsiteOpType, Field(description="操作类型：start/stop/restart")],
    ) -> dict:
        """⚠️写操作 [网站] 启动/停止/重启网站。

        控制网站的运行状态（对应 nginx 站点的 enable/disable）。
        对应 POST /websites/operate。

        Args:
            website_id: 网站 ID。
            operate: start 启动 / stop 停止 / restart 重启。
        """
        require_write()
        client = await get_client()
        return await client.post("/websites/operate", {
            "id": website_id, "operate": operate,
        })

    @mcp.tool()
    async def website_batch_operate(
        website_ids: Annotated[list[int], Field(description="网站 ID 列表")],
        operate: Annotated[WebsiteOpType, Field(description="操作类型：start/stop/restart")],
        task_id: Annotated[str, Field(description="任务 ID（用于进度跟踪，可为空串）")] = "",
    ) -> dict:
        """⚠️写操作 [网站] 批量启动/停止/重启网站。

        对多个网站执行相同操作。对应 POST /websites/batch/operate。

        Args:
            website_ids: 网站 ID 列表。
            operate: start/stop/restart。
            task_id: 批量任务跟踪 ID。
        """
        require_write()
        client = await get_client()
        return await client.post("/websites/batch/operate", {
            "ids": website_ids, "operate": operate, "taskID": task_id,
        })

    @mcp.tool()
    async def website_batch_set_group(
        website_ids: Annotated[list[int], Field(description="网站 ID 列表")],
        group_id: Annotated[int, Field(description="目标分组 ID")],
    ) -> dict:
        """⚠️写操作 [网站] 批量调整网站分组。

        把多个网站移动到指定分组。对应 POST /websites/batch/group。

        Args:
            website_ids: 网站 ID 列表。
            group_id: 目标分组 ID。
        """
        require_write()
        client = await get_client()
        return await client.post("/websites/batch/group", {
            "ids": website_ids, "groupID": group_id,
        })

    @mcp.tool()
    async def website_batch_set_https(
        website_ids: Annotated[list[int], Field(description="网站 ID 列表")],
        type: Annotated[SSLCertType, Field(description="证书来源：existed 已有/auto 自动申请/manual 手填")],
        task_id: Annotated[str, Field(description="任务 ID，用于进度跟踪")] = "",
        website_ssl_id: Annotated[Optional[int], Field(description="已有 SSL ID（type=existed 时用）")] = None,
        http_config: Annotated[Optional[HttpConfig], Field(description="HTTP 配置：HTTPSOnly/HTTPAlso/HTTPToHTTPS")] = None,
        algorithm: Annotated[Optional[str], Field(description="SSL 算法")] = None,
        certificate: Annotated[Optional[str], Field(description="证书内容（type=manual 时用）")] = None,
        private_key: Annotated[Optional[str], Field(description="私钥内容（type=manual 时用）")] = None,
        ssl_protocol: Annotated[Optional[list[str]], Field(description="SSL 协议版本列表")] = None,
        https_ports: Annotated[Optional[list[int]], Field(description="HTTPS 端口列表")] = None,
        hsts: Annotated[bool, Field(description="是否启用 HSTS")] = False,
        http3: Annotated[bool, Field(description="是否启用 HTTP/3")] = False,
    ) -> dict:
        """⚠️写操作 [网站] 批量为网站设置 HTTPS。

        一次性给多个网站配置 HTTPS（用已有证书/自动申请/手填证书）。
        对应 POST /websites/batch/https。

        Args:
            website_ids: 网站 ID 列表。
            type: 证书来源。
            task_id: 批量任务跟踪 ID。
            website_ssl_id: 已有 SSL ID（type=existed 必填）。
            http_config: HTTP 处理策略。
            algorithm: SSL 算法（type=auto 时用）。
            certificate: 证书 PEM（type=manual 时用）。
            private_key: 私钥 PEM（type=manual 时用）。
            ssl_protocol: 启用的 SSL 协议。
            https_ports: HTTPS 端口。
            hsts: 启用 HSTS。
            http3: 启用 HTTP/3。
        """
        require_write()
        client = await get_client()
        body: dict[str, Any] = {
            "ids": website_ids,
            "taskID": task_id,
            "type": type,
            "hsts": hsts,
            "http3": http3,
        }
        if website_ssl_id is not None:
            body["websiteSSLId"] = website_ssl_id
        if http_config is not None:
            body["httpConfig"] = http_config
        if algorithm is not None:
            body["algorithm"] = algorithm
        if certificate is not None:
            body["certificate"] = certificate
        if private_key is not None:
            body["privateKey"] = private_key
        if ssl_protocol is not None:
            body["SSLProtocol"] = ssl_protocol
        if https_ports is not None:
            body["httpsPorts"] = https_ports
        return await client.post("/websites/batch/https", body)

    @mcp.tool()
    async def website_log(
        website_id: Annotated[int, Field(description="网站 ID")],
        log_type: Annotated[Literal["access", "error", "runtime"], Field(description="日志类型：access 访问/error 错误/runtime 运行时")],
        operate: Annotated[Literal["get", "clear"], Field(description="操作：get 查看/clear 清空")] = "get",
        page: Annotated[int, Field(ge=1, description="页码")] = 1,
        page_size: Annotated[int, Field(ge=1, le=500, description="每页数量")] = 100,
    ) -> dict:
        """[网站] 查询/清空网站日志。读操作/⚠️写操作（operate=clear 为写）。

        查看或清空网站访问/错误日志。对应 POST /websites/log。
        operate=get 为读，operate=clear 为写（清空日志）。

        Args:
            website_id: 网站 ID。
            log_type: 日志类型。
            operate: get 查看 / clear 清空。
            page: 页码。
            page_size: 每页数量。
        """
        client = await get_client()
        if operate == "clear":
            require_write()
        return await client.post("/websites/log", {
            "id": website_id,
            "logType": log_type,
            "operate": operate,
            "page": page,
            "pageSize": page_size,
        })

    @mcp.tool()
    async def website_resource(
        website_id: Annotated[int, Field(description="网站 ID")],
    ) -> dict:
        """[网站] 查看网站资源占用（CPU/内存/磁盘）。读操作。

        返回网站容器/进程的资源使用情况。对应 GET /websites/resource/{id}。

        Args:
            website_id: 网站 ID。
        """
        client = await get_client()
        return await client.get(f"/websites/resource/{website_id}")

    @mcp.tool()
    async def website_dir(
        website_id: Annotated[int, Field(description="网站 ID")],
    ) -> dict:
        """[网站] 查看网站目录配置。读操作。

        返回网站的运行目录、默认文档等。对应 POST /websites/dir。

        Args:
            website_id: 网站 ID。
        """
        client = await get_client()
        return await client.post("/websites/dir", {"id": website_id})

    @mcp.tool()
    async def website_dir_update(
        website_id: Annotated[int, Field(description="网站 ID")],
        site_dir: Annotated[str, Field(description="网站运行目录，相对网站根目录的路径")],
    ) -> dict:
        """⚠️写操作 [网站] 修改网站运行目录。

        修改网站的运行目录（如指向 public）。对应 POST /websites/dir/update。

        Args:
            website_id: 网站 ID。
            site_dir: 运行目录（相对站点根目录）。
        """
        require_write()
        client = await get_client()
        return await client.post("/websites/dir/update", {
            "id": website_id, "siteDir": site_dir,
        })

    @mcp.tool()
    async def website_dir_permission_update(
        website_id: Annotated[int, Field(description="网站 ID")],
        user: Annotated[str, Field(description="属主用户名，如 www")] = "www",
        group: Annotated[str, Field(description="属组名，如 www")] = "www",
    ) -> dict:
        """⚠️写操作 [网站] 修改网站目录权限（属主/属组）。

        chown 网站目录的所有者。对应 POST /websites/dir/permission。

        Args:
            website_id: 网站 ID。
            user: 属主用户。
            group: 属组。
        """
        require_write()
        client = await get_client()
        return await client.post("/websites/dir/permission", {
            "id": website_id, "user": user, "group": group,
        })

    # ====================================================================
    # Website Domain（绑定域名，含生效域名踩坑点）
    # ====================================================================

    @mcp.tool()
    async def website_domains_list(
        website_id: Annotated[int, Field(description="网站 ID")],
    ) -> dict:
        """[网站] 查看网站生效的绑定域名列表。读操作。

        ⚠️ 这是获取网站**当前生效域名**的正确接口（GET /websites/domains/{websiteId}）。
        不要用 GET /websites/{id} 的 name 字段（那只是网站名/主域名快照）。

        Args:
            website_id: 网站 ID。
        """
        client = await get_client()
        return await client.get(f"/websites/domains/{website_id}")

    @mcp.tool()
    async def website_domains_create(
        website_id: Annotated[int, Field(description="网站 ID")],
        domains: Annotated[list[str], Field(description="要绑定的域名列表，如 ['a.com','b.com:8080']")],
        port: Annotated[int, Field(description="端口，默认 80")] = 80,
        ssl: Annotated[bool, Field(description="是否启用 SSL（一般配合 HTTPS 接口用）")] = False,
    ) -> dict:
        """⚠️写操作 [网站] 为网站绑定域名。

        给指定网站追加绑定域名。对应 POST /websites/domains。

        Args:
            website_id: 网站 ID。
            domains: 域名列表。
            port: 监听端口。
            ssl: 是否启用 SSL。
        """
        require_write()
        client = await get_client()
        return await client.post("/websites/domains", {
            "websiteID": website_id,
            "domains": [{"domain": d, "port": port, "ssl": ssl} for d in domains],
        })

    @mcp.tool()
    async def website_domains_update(
        domain_id: Annotated[int, Field(description="域名记录 ID（注意是域名 ID 不是网站 ID）")],
        ssl: Annotated[bool, Field(description="是否对该域名启用 SSL")] = False,
    ) -> dict:
        """⚠️写操作 [网站] 修改绑定域名配置（SSL 开关）。

        修改某个绑定域名记录的 SSL 开关。对应 POST /websites/domains/update。

        Args:
            domain_id: 域名记录 ID（website_domains_list 返回项的 id）。
            ssl: 是否启用 SSL。
        """
        require_write()
        client = await get_client()
        return await client.post("/websites/domains/update", {
            "id": domain_id, "ssl": ssl,
        })

    @mcp.tool()
    async def website_domains_delete(
        domain_id: Annotated[int, Field(description="域名记录 ID")],
    ) -> dict:
        """⚠️写操作 [网站] 解绑域名。

        从网站移除一条绑定域名记录。对应 POST /websites/domains/del。

        Args:
            domain_id: 域名记录 ID。
        """
        require_write()
        client = await get_client()
        return await client.post("/websites/domains/del", {"id": domain_id})

    # ====================================================================
    # Website Proxy（反向代理，含真实后端踩坑点）
    # ====================================================================

    @mcp.tool()
    async def website_proxies_get(
        website_id: Annotated[int, Field(description="网站 ID")],
    ) -> dict:
        """[网站] 查看反代配置列表（含真实后端地址）。读操作。

        ⚠️ 这是获取反代**真实后端**的正确接口（POST /websites/proxies body
        {"id": site_id}），返回 data[].proxyPass 为真实后端地址。
        不要用 GET /websites/{id} 的 proxy 字段（那是创建快照，可能过期）。

        Args:
            website_id: 网站 ID。
        """
        client = await get_client()
        return await client.post("/websites/proxies", {"id": website_id})

    @mcp.tool()
    async def website_proxies_create(
        website_id: Annotated[int, Field(description="网站 ID")],
        name: Annotated[str, Field(description="反代规则名")],
        proxy_pass: Annotated[str, Field(description="后端地址，如 http://127.0.0.1:8080")],
        match: Annotated[str, Field(description="匹配路径，如 / 或 /api/")] = "/",
        proxy_host: Annotated[str, Field(description="转发给后端时的 Host 头")] = "$host",
        modifier: Annotated[str, Field(description="路径修饰符：= 或 ^~ 或留空")] = "",
        enable: Annotated[bool, Field(description="是否启用该规则")] = True,
        cache: Annotated[bool, Field(description="是否启用代理缓存")] = False,
        cors: Annotated[bool, Field(description="是否启用 CORS")] = False,
        sni: Annotated[bool, Field(description="后端为 HTTPS 时是否启用 SNI")] = False,
    ) -> dict:
        """⚠️写操作 [网站] 添加反代规则。

        为网站新增一条反向代理规则。对应 POST /websites/proxies/update
        （1Panel 的增/改都走 update 接口，operate=create 表示新增）。

        Args:
            website_id: 网站 ID。
            name: 规则名。
            proxy_pass: 后端地址。
            match: 匹配路径。
            proxy_host: 转发 Host 头。
            modifier: 路径修饰符。
            enable: 启用开关。
            cache: 代理缓存。
            cors: CORS。
            sni: SNI（HTTPS 后端用）。
        """
        require_write()
        client = await get_client()
        body: dict[str, Any] = {
            "id": website_id,
            "operate": "create",
            "name": name,
            "match": match,
            "proxyPass": proxy_pass,
            "proxyHost": proxy_host,
            "modifier": modifier,
            "enable": enable,
            "cache": cache,
            "cors": cors,
            "sni": sni,
        }
        return await client.post("/websites/proxies/update", body)

    @mcp.tool()
    async def website_proxies_update(
        website_id: Annotated[int, Field(description="网站 ID")],
        name: Annotated[str, Field(description="反代规则名")],
        proxy_pass: Annotated[str, Field(description="后端地址")],
        match: Annotated[str, Field(description="匹配路径")] = "/",
        proxy_host: Annotated[str, Field(description="转发 Host 头")] = "$host",
        enable: Annotated[bool, Field(description="是否启用")] = True,
        cache: Annotated[bool, Field(description="是否启用代理缓存")] = False,
        cors: Annotated[bool, Field(description="是否启用 CORS")] = False,
        sni: Annotated[bool, Field(description="是否启用 SNI")] = False,
    ) -> dict:
        """⚠️写操作 [网站] 修改反代规则。

        修改已存在的反代规则。对应 POST /websites/proxies/update（operate=update）。

        Args:
            website_id: 网站 ID。
            name: 要修改的规则名。
            proxy_pass: 新的后端地址。
            match: 匹配路径。
            proxy_host: 转发 Host 头。
            enable: 启用开关。
            cache: 代理缓存。
            cors: CORS。
            sni: SNI。
        """
        require_write()
        client = await get_client()
        body: dict[str, Any] = {
            "id": website_id,
            "operate": "update",
            "name": name,
            "match": match,
            "proxyPass": proxy_pass,
            "proxyHost": proxy_host,
            "enable": enable,
            "cache": cache,
            "cors": cors,
            "sni": sni,
        }
        return await client.post("/websites/proxies/update", body)

    @mcp.tool()
    async def website_proxies_delete(
        website_id: Annotated[int, Field(description="网站 ID")],
        name: Annotated[str, Field(description="反代规则名")],
    ) -> dict:
        """⚠️写操作 [网站] 删除反代规则。

        删除指定反代规则。对应 POST /websites/proxies/delete。

        Args:
            website_id: 网站 ID。
            name: 要删除的规则名。
        """
        require_write()
        client = await get_client()
        return await client.post("/websites/proxies/delete", {
            "id": website_id, "name": name,
        })

    @mcp.tool()
    async def website_proxies_status(
        website_id: Annotated[int, Field(description="网站 ID")],
        name: Annotated[str, Field(description="反代规则名")],
        status: Annotated[Literal["enable", "disable"], Field(description="enable 启用 / disable 停用")],
    ) -> dict:
        """⚠️写操作 [网站] 切换反代规则启停状态。

        对应 POST /websites/proxies/status。

        Args:
            website_id: 网站 ID。
            name: 规则名。
            status: enable/disable。
        """
        require_write()
        client = await get_client()
        return await client.post("/websites/proxies/status", {
            "id": website_id, "name": name, "status": status,
        })

    @mcp.tool()
    async def website_proxies_file_get(
        website_id: Annotated[int, Field(description="网站 ID")],
        name: Annotated[str, Field(description="反代规则名")],
    ) -> dict:
        """[网站] 查看反代规则的 nginx 原始配置。读操作。

        返回某条反代规则生成的 nginx 配置文件内容。对应
        POST /websites/proxies/file。

        Args:
            website_id: 网站 ID。
            name: 规则名。
        """
        client = await get_client()
        return await client.post("/websites/proxies/file", {
            "websiteID": website_id, "name": name,
        })

    @mcp.tool()
    async def website_proxy_cache_config(
        website_id: Annotated[int, Field(description="网站 ID")],
        open: Annotated[bool, Field(description="是否开启代理缓存")] = False,
        cache_expire: Annotated[int, Field(description="缓存过期时间数值")] = 1,
        cache_expire_unit: Annotated[str, Field(description="缓存过期单位：m/h/d")] = "m",
        cache_limit: Annotated[int, Field(description="缓存大小数值")] = 100,
        cache_limit_unit: Annotated[str, Field(description="缓存大小单位：MB/GB")] = "MB",
        share_cache: Annotated[int, Field(description="共享缓存大小")] = 10,
        share_cache_unit: Annotated[str, Field(description="共享缓存单位：MB/GB")] = "MB",
    ) -> dict:
        """⚠️写操作 [网站] 配置反代缓存。

        开启/调整反向代理的缓存参数。对应 POST /websites/proxy/config。

        Args:
            website_id: 网站 ID。
            open: 是否开启。
            cache_expire: 缓存过期时间。
            cache_expire_unit: 缓存过期单位。
            cache_limit: 缓存大小。
            cache_limit_unit: 缓存大小单位。
            share_cache: 共享缓存大小。
            share_cache_unit: 共享缓存单位。
        """
        require_write()
        client = await get_client()
        return await client.post("/websites/proxy/config", {
            "websiteID": website_id,
            "open": open,
            "cacheExpire": cache_expire,
            "cacheExpireUnit": cache_expire_unit,
            "cacheLimit": cache_limit,
            "cacheLimitUnit": cache_limit_unit,
            "shareCache": share_cache,
            "shareCacheUnit": share_cache_unit,
        })

    @mcp.tool()
    async def website_proxy_cache_clear(
        website_id: Annotated[int, Field(description="网站 ID")],
    ) -> dict:
        """⚠️写操作 [网站] 清除反代缓存。

        清空指定网站的反向代理缓存。对应 POST /websites/proxy/clear。

        Args:
            website_id: 网站 ID。
        """
        require_write()
        client = await get_client()
        return await client.post("/websites/proxy/clear", {"websiteID": website_id})

    # ====================================================================
    # Website SSL
    # ====================================================================

    @mcp.tool()
    async def website_ssl_search(
        domain: Annotated[Optional[str], Field(description="按域名模糊匹配")] = None,
        acme_account_id: Annotated[Optional[str], Field(description="按 ACME 账号 ID 过滤（字符串）")] = None,
        page: Annotated[int, Field(ge=1, description="页码")] = 1,
        page_size: Annotated[int, Field(ge=1, le=500, description="每页数量")] = 100,
        order_by: Annotated[WebsiteSSLOrderBy, Field(description="排序字段：created_at/expire_date")] = "created_at",
        order: Annotated[Literal["ascending", "descending", "null"], Field(description="排序方向")] = "descending",
    ) -> dict:
        """[SSL] 分页搜索证书列表。读操作。

        返回所有证书（含自动申请的 ACME 证书和手动上传的证书）。
        对应 POST /websites/ssl/search。

        Args:
            domain: 按域名模糊匹配。
            acme_account_id: 按 ACME 账号过滤。
            page: 页码。
            page_size: 每页数量。
            order_by: 排序字段。
            order: 排序方向。
        """
        client = await get_client()
        body: dict[str, Any] = {
            "page": page,
            "pageSize": page_size,
            "orderBy": order_by,
            "order": order,
        }
        if domain is not None:
            body["domain"] = domain
        if acme_account_id is not None:
            body["acmeAccountID"] = acme_account_id
        return await client.post("/websites/ssl/search", body)

    @mcp.tool()
    async def website_ssl_detail(
        ssl_id: Annotated[int, Field(description="SSL 证书 ID")],
    ) -> dict:
        """[SSL] 查看证书详情。读操作。

        返回单条证书详情（域名、过期时间、ACME 账号等）。对应 GET /websites/ssl/{id}。

        Args:
            ssl_id: SSL 证书 ID。
        """
        client = await get_client()
        return await client.get(f"/websites/ssl/{ssl_id}")

    @mcp.tool()
    async def website_ssl_by_website(
        website_id: Annotated[int, Field(description="网站 ID")],
    ) -> dict:
        """[SSL] 查看网站当前使用的证书。读操作。

        返回指定网站正在使用的 SSL 证书。对应
        GET /websites/ssl/website/{websiteId}。

        Args:
            website_id: 网站 ID。
        """
        client = await get_client()
        return await client.get(f"/websites/ssl/website/{website_id}")

    @mcp.tool()
    async def website_ssl_list(
        acme_account_id: Annotated[Optional[str], Field(description="按 ACME 账号 ID 过滤（字符串）")] = None,
    ) -> dict:
        """[SSL] 列出所有证书（简表，用于下拉）。读操作。

        对应 POST /websites/ssl/list，比 search 轻量。

        Args:
            acme_account_id: 按 ACME 账号过滤。
        """
        client = await get_client()
        body: dict[str, Any] = {}
        if acme_account_id is not None:
            body["acmeAccountID"] = acme_account_id
        return await client.post("/websites/ssl/list", body)

    @mcp.tool()
    async def website_ssl_create(
        primary_domain: Annotated[str, Field(description="主域名")],
        acme_account_id: Annotated[int, Field(description="ACME 账号 ID")],
        provider: Annotated[str, Field(description="申请方式：dnsManual 手动/dnsAccount DNS 账号/http HTTP 验证", )] = "dnsManual",
        other_domains: Annotated[str, Field(description="其他域名，逗号分隔")] = "",
        key_type: Annotated[KeyType, Field(description="密钥类型")] = "P256",
        auto_renew: Annotated[bool, Field(description="是否自动续签")] = True,
        apply: Annotated[bool, Field(description="创建后是否立即申请")] = True,
        skip_dns: Annotated[bool, Field(description="是否跳过 DNS 检查")] = False,
        disable_cname: Annotated[bool, Field(description="是否禁用 CNAME")] = False,
        description: Annotated[str, Field(description="备注")] = "",
        dns_account_id: Annotated[Optional[int], Field(description="DNS 账号 ID（provider=dnsAccount 时用）")] = None,
        exec_shell: Annotated[bool, Field(description="签发后是否执行脚本")] = False,
        shell: Annotated[str, Field(description="签发后执行的脚本内容")] = "",
    ) -> dict:
        """⚠️写操作 [SSL] 创建 SSL 证书（配置 ACME 自动申请）。

        创建一条证书申请记录，可立即申请。对应 POST /websites/ssl。

        Args:
            primary_domain: 主域名。
            acme_account_id: ACME 账号 ID（website_acme_list 查到）。
            provider: 申请方式。
            other_domains: 其他域名（逗号分隔）。
            key_type: 密钥类型。
            auto_renew: 自动续签。
            apply: 创建即申请。
            skip_dns: 跳过 DNS 检查。
            disable_cname: 禁用 CNAME。
            description: 备注。
            dns_account_id: DNS 账号 ID。
            exec_shell: 签发后执行脚本。
            shell: 脚本内容。
        """
        require_write()
        client = await get_client()
        body: dict[str, Any] = {
            "primaryDomain": primary_domain,
            "acmeAccountId": acme_account_id,
            "provider": provider,
            "otherDomains": other_domains,
            "keyType": key_type,
            "autoRenew": auto_renew,
            "apply": apply,
            "skipDNS": skip_dns,
            "disableCNAME": disable_cname,
            "description": description,
            "execShell": exec_shell,
            "shell": shell,
        }
        if dns_account_id is not None:
            body["dnsAccountId"] = dns_account_id
        return await client.post("/websites/ssl", body)

    @mcp.tool()
    async def website_ssl_apply(
        ssl_id: Annotated[int, Field(description="SSL 证书 ID")],
        skip_dns_check: Annotated[bool, Field(description="是否跳过 DNS 检查")] = False,
        disable_log: Annotated[bool, Field(description="是否禁用日志")] = False,
        nameservers: Annotated[Optional[list[str]], Field(description="自定义 DNS 服务器列表")] = None,
    ) -> dict:
        """⚠️写操作 [SSL] 申请/续签 SSL 证书。

        触发证书申请或续签。对应 POST /websites/ssl/obtain。

        Args:
            ssl_id: SSL 证书 ID。
            skip_dns_check: 跳过 DNS 检查。
            disable_log: 禁用申请日志。
            nameservers: 自定义 DNS 服务器。
        """
        require_write()
        client = await get_client()
        body: dict[str, Any] = {
            "ID": ssl_id,
            "skipDNSCheck": skip_dns_check,
            "disableLog": disable_log,
        }
        if nameservers is not None:
            body["nameservers"] = nameservers
        return await client.post("/websites/ssl/obtain", body)

    @mcp.tool()
    async def website_ssl_update(
        ssl_id: Annotated[int, Field(description="SSL 证书 ID")],
        primary_domain: Annotated[str, Field(description="主域名")],
        provider: Annotated[str, Field(description="申请方式")] = "dnsManual",
        acme_account_id: Annotated[Optional[int], Field(description="ACME 账号 ID")] = None,
        other_domains: Annotated[str, Field(description="其他域名")] = "",
        key_type: Annotated[KeyType, Field(description="密钥类型")] = "P256",
        auto_renew: Annotated[bool, Field(description="自动续签")] = True,
        apply: Annotated[bool, Field(description="是否立即申请")] = False,
        description: Annotated[str, Field(description="备注")] = "",
        dns_account_id: Annotated[Optional[int], Field(description="DNS 账号 ID")] = None,
    ) -> dict:
        """⚠️写操作 [SSL] 修改 SSL 证书申请配置。

        修改证书的主域名、申请方式、自动续签等。对应 POST /websites/ssl/update。

        Args:
            ssl_id: SSL 证书 ID。
            primary_domain: 主域名。
            provider: 申请方式。
            acme_account_id: ACME 账号 ID。
            other_domains: 其他域名。
            key_type: 密钥类型。
            auto_renew: 自动续签。
            apply: 修改后立即申请。
            description: 备注。
            dns_account_id: DNS 账号 ID。
        """
        require_write()
        client = await get_client()
        body: dict[str, Any] = {
            "id": ssl_id,
            "primaryDomain": primary_domain,
            "provider": provider,
            "otherDomains": other_domains,
            "keyType": key_type,
            "autoRenew": auto_renew,
            "apply": apply,
            "description": description,
        }
        if acme_account_id is not None:
            body["acmeAccountId"] = acme_account_id
        if dns_account_id is not None:
            body["dnsAccountId"] = dns_account_id
        return await client.post("/websites/ssl/update", body)

    @mcp.tool()
    async def website_ssl_upload(
        type: Annotated[SSLUploadType, Field(description="上传方式：paste 粘贴内容/local 本地路径")],
        certificate: Annotated[str, Field(description="证书 PEM 内容（paste）或路径（local）")] = "",
        private_key: Annotated[str, Field(description="私钥 PEM 内容（paste）或路径（local）")] = "",
        certificate_path: Annotated[Optional[str], Field(description="证书文件路径（local 时用）")] = None,
        private_key_path: Annotated[Optional[str], Field(description="私钥文件路径（local 时用）")] = None,
        ssl_id: Annotated[Optional[int], Field(description="已有 SSL ID（覆盖更新时用）")] = None,
        description: Annotated[str, Field(description="备注")] = "",
    ) -> dict:
        """⚠️写操作 [SSL] 手动上传证书。

        粘贴或从本地路径上传已有的证书。对应 POST /websites/ssl/upload。

        Args:
            type: paste 粘贴 / local 本地文件。
            certificate: 证书内容或路径。
            private_key: 私钥内容或路径。
            certificate_path: 证书文件路径（local）。
            private_key_path: 私钥文件路径（local）。
            ssl_id: 覆盖更新已有证书时传其 ID。
            description: 备注。
        """
        require_write()
        client = await get_client()
        body: dict[str, Any] = {
            "type": type,
            "certificate": certificate,
            "privateKey": private_key,
            "description": description,
        }
        if certificate_path is not None:
            body["certificatePath"] = certificate_path
        if private_key_path is not None:
            body["privateKeyPath"] = private_key_path
        if ssl_id is not None:
            body["sslID"] = ssl_id
        return await client.post("/websites/ssl/upload", body)

    @mcp.tool()
    async def website_ssl_delete(
        ssl_ids: Annotated[list[int], Field(description="要删除的 SSL ID 列表")],
        confirm: Annotated[bool, Field(description="删除是高危操作，必须传 true")] = False,
    ) -> dict:
        """⚠️高危 [SSL] 删除 SSL 证书。

        批量删除证书。对应 POST /websites/ssl/del。必须传 confirm=true。

        Args:
            ssl_ids: 要删除的 SSL ID 列表。
            confirm: 必须为 true。
        """
        require_write()
        if not confirm:
            raise ValueError("删除 SSL 证书是高危操作，必须显式传 confirm=true。")
        client = await get_client()
        return await client.post("/websites/ssl/del", {"ids": ssl_ids})

    @mcp.tool()
    async def website_ssl_download(
        ssl_id: Annotated[int, Field(description="SSL 证书 ID")],
    ) -> dict:
        """[SSL] 下载证书文件。读操作。

        返回证书/私钥内容（用于导出备份）。对应 POST /websites/ssl/download。

        Args:
            ssl_id: SSL 证书 ID。
        """
        client = await get_client()
        return await client.post("/websites/ssl/download", {"id": ssl_id})

    @mcp.tool()
    async def website_ssl_resolve_dns(
        acme_account_id: Annotated[int, Field(description="ACME 账号 ID")],
        website_ssl_id: Annotated[int, Field(description="SSL 证书 ID")],
    ) -> dict:
        """[SSL] 解析证书的 DNS 记录（手动 DNS 验证用）。读操作。

        返回需要添加的 TXT 记录。对应 POST /websites/ssl/resolve。

        Args:
            acme_account_id: ACME 账号 ID。
            website_ssl_id: SSL 证书 ID。
        """
        client = await get_client()
        return await client.post("/websites/ssl/resolve", {
            "acmeAccountId": acme_account_id,
            "websiteSSLId": website_ssl_id,
        })

    # ====================================================================
    # Website HTTPS
    # ====================================================================

    @mcp.tool()
    async def website_https_get(
        website_id: Annotated[int, Field(description="网站 ID")],
    ) -> dict:
        """[HTTPS] 查看网站 HTTPS 配置。读操作。

        返回 HTTPS 启用状态、证书、协议版本、HSTS 等。对应
        GET /websites/{id}/https。

        Args:
            website_id: 网站 ID。
        """
        client = await get_client()
        return await client.get(f"/websites/{website_id}/https")

    @mcp.tool()
    async def website_https_update(
        website_id: Annotated[int, Field(description="网站 ID")],
        enable: Annotated[bool, Field(description="是否启用 HTTPS")] = True,
        type: Annotated[SSLCertType, Field(description="证书来源：existed/auto/manual")] = "existed",
        website_ssl_id: Annotated[Optional[int], Field(description="已有 SSL ID（type=existed 时用）")] = None,
        http_config: Annotated[Optional[HttpConfig], Field(description="HTTP 策略：HTTPSOnly/HTTPAlso/HTTPToHTTPS")] = None,
        algorithm: Annotated[Optional[str], Field(description="SSL 算法（type=auto 时用）")] = None,
        certificate: Annotated[Optional[str], Field(description="证书 PEM（type=manual 时用）")] = None,
        private_key: Annotated[Optional[str], Field(description="私钥 PEM（type=manual 时用）")] = None,
        certificate_path: Annotated[Optional[str], Field(description="证书路径（type=manual+local）")] = None,
        private_key_path: Annotated[Optional[str], Field(description="私钥路径（type=manual+local）")] = None,
        ssl_protocol: Annotated[Optional[list[str]], Field(description="启用的 SSL 协议版本")] = None,
        https_ports: Annotated[Optional[list[int]], Field(description="HTTPS 端口列表")] = None,
        hsts: Annotated[bool, Field(description="启用 HSTS")] = False,
        hsts_include_subdomains: Annotated[bool, Field(description="HSTS 覆盖子域")] = False,
        http3: Annotated[bool, Field(description="启用 HTTP/3")] = False,
    ) -> dict:
        """⚠️写操作 [HTTPS] 配置网站 HTTPS。

        启用/修改网站的 HTTPS（选用已有证书/自动申请/手填）。
        对应 POST /websites/{id}/https。

        Args:
            website_id: 网站 ID。
            enable: 是否启用 HTTPS。
            type: 证书来源。
            website_ssl_id: 已有 SSL ID。
            http_config: HTTP 处理策略。
            algorithm: SSL 算法。
            certificate: 证书 PEM。
            private_key: 私钥 PEM。
            certificate_path: 证书文件路径。
            private_key_path: 私钥文件路径。
            ssl_protocol: SSL 协议版本。
            https_ports: HTTPS 端口。
            hsts: HSTS。
            hsts_include_subdomains: HSTS 覆盖子域。
            http3: HTTP/3。
        """
        require_write()
        client = await get_client()
        body: dict[str, Any] = {
            "websiteId": website_id,
            "enable": enable,
            "type": type,
            "hsts": hsts,
            "hstsIncludeSubDomains": hsts_include_subdomains,
            "http3": http3,
        }
        if website_ssl_id is not None:
            body["websiteSSLId"] = website_ssl_id
        if http_config is not None:
            body["httpConfig"] = http_config
        if algorithm is not None:
            body["algorithm"] = algorithm
        if certificate is not None:
            body["certificate"] = certificate
        if private_key is not None:
            body["privateKey"] = private_key
        if certificate_path is not None:
            body["certificatePath"] = certificate_path
        if private_key_path is not None:
            body["privateKeyPath"] = private_key_path
        if ssl_protocol is not None:
            body["SSLProtocol"] = ssl_protocol
        if https_ports is not None:
            body["httpsPorts"] = https_ports
        return await client.post(f"/websites/{website_id}/https", body)

    # ====================================================================
    # Website Nginx（配置）
    # ====================================================================

    @mcp.tool()
    async def website_nginx_get(
        website_id: Annotated[int, Field(description="网站 ID")],
        type: Annotated[Literal["default", "old"], Field(description="配置版本：default 当前/old 上一版")] = "default",
    ) -> dict:
        """[Nginx] 查看网站 nginx 配置（按 id+type）。读操作。

        返回网站生成的 nginx 配置（含历史版本）。对应
        GET /websites/{id}/config/{type}。

        Args:
            website_id: 网站 ID。
            type: default 当前 / old 上一版。
        """
        client = await get_client()
        return await client.get(f"/websites/{website_id}/config/{type}")

    @mcp.tool()
    async def website_nginx_file_get(
        website_id: Annotated[int, Field(description="网站 ID")],
        scope: Annotated[NginxScope, Field(description="配置作用域：index/limit-conn/ssl/cache/http-per/proxy-cache")],
    ) -> dict:
        """[Nginx] 查看网站某作用域的 nginx 配置块。读操作。

        返回指定作用域（如 ssl/cache）的 nginx 配置参数。对应
        POST /websites/config。

        Args:
            website_id: 网站 ID。
            scope: 配置作用域。
        """
        client = await get_client()
        return await client.post("/websites/config", {
            "websiteId": website_id, "scope": scope,
        })

    @mcp.tool()
    async def website_nginx_config_update(
        scope: Annotated[NginxScope, Field(description="配置作用域")],
        operate: Annotated[Literal["add", "update", "delete"], Field(description="操作：add/update/delete")],
        params: Annotated[dict, Field(description="该作用域下的配置参数键值对", )] = None,
        website_id: Annotated[Optional[int], Field(description="网站 ID（部分作用域必填）")] = None,
    ) -> dict:
        """⚠️写操作 [Nginx] 修改网站某作用域的 nginx 配置参数。

        增/改/删某个作用域（如 ssl/cache）的参数。对应 POST /websites/config/update。

        Args:
            scope: 配置作用域。
            operate: 操作类型。
            params: 参数键值对。
            website_id: 网站 ID。
        """
        require_write()
        client = await get_client()
        body: dict[str, Any] = {
            "scope": scope,
            "operate": operate,
            "params": params or {},
        }
        if website_id is not None:
            body["websiteId"] = website_id
        return await client.post("/websites/config/update", body)

    @mcp.tool()
    async def website_nginx_raw_update(
        website_id: Annotated[int, Field(description="网站 ID")],
        content: Annotated[str, Field(description="nginx 配置文件全文")],
    ) -> dict:
        """⚠️写操作 [Nginx] 直接修改网站 nginx 配置全文。

        直接编辑网站的 nginx 配置文件（高级操作，配置错误会导致站点失效）。
        对应 POST /websites/nginx/update。

        Args:
            website_id: 网站 ID。
            content: nginx 配置全文。
        """
        require_write()
        client = await get_client()
        return await client.post("/websites/nginx/update", {
            "id": website_id, "content": content,
        })

    # ====================================================================
    # Website Acme（ACME 账号）
    # ====================================================================

    @mcp.tool()
    async def website_acme_list(
        page: Annotated[int, Field(ge=1, description="页码")] = 1,
        page_size: Annotated[int, Field(ge=1, le=500, description="每页数量")] = 100,
    ) -> dict:
        """[Acme] 分页列出 ACME 账号。读操作。

        返回已注册的 ACME 账号（用于申请 Let's Encrypt 等证书）。
        对应 POST /websites/acme/search。

        Args:
            page: 页码。
            page_size: 每页数量。
        """
        client = await get_client()
        return await client.post("/websites/acme/search", {
            "page": page, "pageSize": page_size,
        })

    @mcp.tool()
    async def website_acme_create(
        email: Annotated[str, Field(description="注册邮箱")],
        type: Annotated[AcmeType, Field(description="CA 类型：letsencrypt/zerossl/buypass/google/custom")],
        key_type: Annotated[KeyType, Field(description="密钥类型")] = "P256",
        ca_dir_url: Annotated[Optional[str], Field(description="自定义 CA 目录 URL（type=custom 时用）")] = None,
        use_eab: Annotated[bool, Field(description="是否使用 EAB（外部账号绑定）")] = False,
        eab_kid: Annotated[Optional[str], Field(description="EAB KID")] = None,
        eab_hmac_key: Annotated[Optional[str], Field(description="EAB HMAC Key")] = None,
        use_proxy: Annotated[bool, Field(description="是否走代理")] = False,
    ) -> dict:
        """⚠️写操作 [Acme] 注册 ACME 账号。

        在指定 CA（Let's Encrypt/ZeroSSL 等）注册 ACME 账号。对应 POST /websites/acme。

        Args:
            email: 注册邮箱。
            type: CA 类型。
            key_type: 账号密钥类型。
            ca_dir_url: 自定义 CA 目录 URL。
            use_eab: 启用 EAB。
            eab_kid: EAB KID。
            eab_hmac_key: EAB HMAC Key。
            use_proxy: 走代理。
        """
        require_write()
        client = await get_client()
        body: dict[str, Any] = {
            "email": email,
            "type": type,
            "keyType": key_type,
            "useEAB": use_eab,
            "useProxy": use_proxy,
        }
        if ca_dir_url is not None:
            body["caDirURL"] = ca_dir_url
        if eab_kid is not None:
            body["eabKid"] = eab_kid
        if eab_hmac_key is not None:
            body["eabHmacKey"] = eab_hmac_key
        return await client.post("/websites/acme", body)

    @mcp.tool()
    async def website_acme_update(
        acme_id: Annotated[int, Field(description="ACME 账号 ID")],
        use_proxy: Annotated[bool, Field(description="是否走代理")] = False,
    ) -> dict:
        """⚠️写操作 [Acme] 修改 ACME 账号（代理开关）。

        目前仅支持切换代理开关。对应 POST /websites/acme/update。

        Args:
            acme_id: ACME 账号 ID。
            use_proxy: 是否走代理。
        """
        require_write()
        client = await get_client()
        return await client.post("/websites/acme/update", {
            "id": acme_id, "useProxy": use_proxy,
        })

    @mcp.tool()
    async def website_acme_delete(
        acme_id: Annotated[int, Field(description="ACME 账号 ID")],
        confirm: Annotated[bool, Field(description="删除是高危操作，必须传 true")] = False,
    ) -> dict:
        """⚠️高危 [Acme] 删除 ACME 账号。

        删除 ACME 账号（关联的证书不会被删，但无法续签）。对应 POST /websites/acme/del。
        必须传 confirm=true。

        Args:
            acme_id: ACME 账号 ID。
            confirm: 必须为 true。
        """
        require_write()
        if not confirm:
            raise ValueError("删除 ACME 账号是高危操作，必须显式传 confirm=true。")
        client = await get_client()
        return await client.post("/websites/acme/del", {"id": acme_id})

    # ====================================================================
    # Website CA（自建 CA，用于签发自签名证书）
    # ====================================================================

    @mcp.tool()
    async def website_ca_list(
        page: Annotated[int, Field(ge=1, description="页码")] = 1,
        page_size: Annotated[int, Field(ge=1, le=500, description="每页数量")] = 100,
    ) -> dict:
        """[CA] 分页列出自建 CA。读操作。

        返回已创建的自建证书颁发机构。对应 POST /websites/ca/search。

        Args:
            page: 页码。
            page_size: 每页数量。
        """
        client = await get_client()
        return await client.post("/websites/ca/search", {
            "page": page, "pageSize": page_size,
        })

    @mcp.tool()
    async def website_ca_detail(
        ca_id: Annotated[int, Field(description="CA ID")],
    ) -> dict:
        """[CA] 查看自建 CA 详情。读操作。

        返回单条 CA 详情（主体、有效期等）。对应 GET /websites/ca/{id}。

        Args:
            ca_id: CA ID。
        """
        client = await get_client()
        return await client.get(f"/websites/ca/{ca_id}")

    @mcp.tool()
    async def website_ca_create(
        name: Annotated[str, Field(description="CA 名称")],
        common_name: Annotated[str, Field(description="通用名 CN")],
        organization: Annotated[str, Field(description="组织 O")],
        country: Annotated[str, Field(description="国家代码，如 CN/US")],
        key_type: Annotated[KeyType, Field(description="密钥类型")] = "P256",
        province: Annotated[str, Field(description="省/州")] = "",
        city: Annotated[str, Field(description="城市")] = "",
        organization_unit: Annotated[str, Field(description="组织单位 OU")] = "",
    ) -> dict:
        """⚠️写操作 [CA] 创建自建 CA。

        创建一个自签名证书颁发机构。对应 POST /websites/ca。

        Args:
            name: CA 名称。
            common_name: 通用名。
            organization: 组织。
            country: 国家代码。
            key_type: 密钥类型。
            province: 省/州。
            city: 城市。
            organization_unit: 组织单位。
        """
        require_write()
        client = await get_client()
        return await client.post("/websites/ca", {
            "name": name,
            "commonName": common_name,
            "organization": organization,
            "country": country,
            "keyType": key_type,
            "province": province,
            "city": city,
            "organizationUint": organization_unit,
        })

    @mcp.tool()
    async def website_ca_obtain(
        ca_id: Annotated[int, Field(description="CA ID")],
        domains: Annotated[str, Field(description="签发的域名，逗号分隔")],
        key_type: Annotated[KeyType, Field(description="证书密钥类型")] = "P256",
        time: Annotated[int, Field(description="有效期数值")] = 1,
        unit: Annotated[str, Field(description="有效期单位：year/month/day")] = "year",
        auto_renew: Annotated[bool, Field(description="自动续签")] = False,
        description: Annotated[str, Field(description="备注")] = "",
    ) -> dict:
        """⚠️写操作 [CA] 用自建 CA 签发证书。

        用指定自建 CA 签发一张证书。对应 POST /websites/ca/obtain。

        Args:
            ca_id: CA ID。
            domains: 签发域名。
            key_type: 证书密钥类型。
            time: 有效期数值。
            unit: 有效期单位。
            auto_renew: 自动续签。
            description: 备注。
        """
        require_write()
        client = await get_client()
        return await client.post("/websites/ca/obtain", {
            "id": ca_id,
            "domains": domains,
            "keyType": key_type,
            "time": time,
            "unit": unit,
            "autoRenew": auto_renew,
            "description": description,
        })

    @mcp.tool()
    async def website_ca_renew(
        ca_id: Annotated[int, Field(description="CA ID")],
        ssl_id: Annotated[Optional[int], Field(description="要续签的 SSL ID")] = None,
        domains: Annotated[str, Field(description="签发域名")] = "",
        key_type: Annotated[KeyType, Field(description="密钥类型")] = "P256",
        time: Annotated[int, Field(description="有效期数值")] = 1,
        unit: Annotated[str, Field(description="有效期单位")] = "year",
    ) -> dict:
        """⚠️写操作 [CA] 用自建 CA 续签证书。

        续签由自建 CA 签发的证书。对应 POST /websites/ca/renew。

        Args:
            ca_id: CA ID。
            ssl_id: 要续签的 SSL ID。
            domains: 域名。
            key_type: 密钥类型。
            time: 有效期数值。
            unit: 有效期单位。
        """
        require_write()
        client = await get_client()
        body: dict[str, Any] = {
            "id": ca_id,
            "domains": domains,
            "keyType": key_type,
            "time": time,
            "unit": unit,
        }
        if ssl_id is not None:
            body["sslID"] = ssl_id
        return await client.post("/websites/ca/renew", body)

    @mcp.tool()
    async def website_ca_download(
        ca_id: Annotated[int, Field(description="CA ID")],
    ) -> dict:
        """[CA] 下载自建 CA 证书文件。读操作。

        对应 POST /websites/ca/download。

        Args:
            ca_id: CA ID。
        """
        client = await get_client()
        return await client.post("/websites/ca/download", {"id": ca_id})

    @mcp.tool()
    async def website_ca_delete(
        ca_id: Annotated[int, Field(description="CA ID")],
        confirm: Annotated[bool, Field(description="删除是高危操作，必须传 true")] = False,
    ) -> dict:
        """⚠️高危 [CA] 删除自建 CA。

        删除自建 CA。对应 POST /websites/ca/del。必须传 confirm=true。

        Args:
            ca_id: CA ID。
            confirm: 必须为 true。
        """
        require_write()
        if not confirm:
            raise ValueError("删除自建 CA 是高危操作，必须显式传 confirm=true。")
        client = await get_client()
        return await client.post("/websites/ca/del", {"id": ca_id})

    # ====================================================================
    # Website DNS（DNS 账号，用于 DNS 验证自动申请证书）
    # ====================================================================

    @mcp.tool()
    async def website_dns_list(
        page: Annotated[int, Field(ge=1, description="页码")] = 1,
        page_size: Annotated[int, Field(ge=1, le=500, description="每页数量")] = 100,
    ) -> dict:
        """[DNS] 分页列出 DNS 账号。读操作。

        返回已配置的 DNS 服务商账号（阿里云/Cloudflare 等，用于自动 DNS 验证）。
        对应 POST /websites/dns/search。

        Args:
            page: 页码。
            page_size: 每页数量。
        """
        client = await get_client()
        return await client.post("/websites/dns/search", {
            "page": page, "pageSize": page_size,
        })

    @mcp.tool()
    async def website_dns_create(
        name: Annotated[str, Field(description="DNS 账号名")],
        type: Annotated[str, Field(description="DNS 服务商类型，如 aliyun/cloudflare/tencent")],
        authorization: Annotated[dict[str, str], Field(description="凭证键值对，如 {'AccessKey':'...', 'SecretKey':'...'}")],
    ) -> dict:
        """⚠️写操作 [DNS] 创建 DNS 账号。

        添加一个 DNS 服务商账号（用于自动 DNS 验证申请证书）。对应 POST /websites/dns。

        Args:
            name: 账号名。
            type: 服务商类型。
            authorization: 凭证键值对（不同服务商字段不同）。
        """
        require_write()
        client = await get_client()
        return await client.post("/websites/dns", {
            "name": name, "type": type, "authorization": authorization,
        })

    @mcp.tool()
    async def website_dns_update(
        dns_id: Annotated[int, Field(description="DNS 账号 ID")],
        name: Annotated[str, Field(description="账号名")],
        type: Annotated[str, Field(description="服务商类型")],
        authorization: Annotated[dict[str, str], Field(description="凭证键值对")],
    ) -> dict:
        """⚠️写操作 [DNS] 修改 DNS 账号。

        修改 DNS 账号的凭证或名称。对应 POST /websites/dns/update。

        Args:
            dns_id: DNS 账号 ID。
            name: 账号名。
            type: 服务商类型。
            authorization: 凭证键值对。
        """
        require_write()
        client = await get_client()
        return await client.post("/websites/dns/update", {
            "id": dns_id, "name": name, "type": type, "authorization": authorization,
        })

    @mcp.tool()
    async def website_dns_delete(
        dns_id: Annotated[int, Field(description="DNS 账号 ID")],
        confirm: Annotated[bool, Field(description="删除是高危操作，必须传 true")] = False,
    ) -> dict:
        """⚠️高危 [DNS] 删除 DNS 账号。

        删除 DNS 服务商账号。对应 POST /websites/dns/del。必须传 confirm=true。

        Args:
            dns_id: DNS 账号 ID。
            confirm: 必须为 true。
        """
        require_write()
        if not confirm:
            raise ValueError("删除 DNS 账号是高危操作，必须显式传 confirm=true。")
        client = await get_client()
        return await client.post("/websites/dns/del", {"id": dns_id})

    # ====================================================================
    # 运行时 / PHP（runtimes，Website PHP tag）
    # ====================================================================

    @mcp.tool()
    async def website_php_version_update(
        website_id: Annotated[int, Field(description="网站 ID")],
        runtime_id: Annotated[int, Field(description="PHP 运行时 ID")],
    ) -> dict:
        """⚠️写操作 [PHP] 修改网站的 PHP 版本（切换运行时）。

        切换网站所用的 PHP 运行时。对应 POST /websites/php/version。

        Args:
            website_id: 网站 ID。
            runtime_id: PHP 运行时 ID。
        """
        require_write()
        client = await get_client()
        return await client.post("/websites/php/version", {
            "websiteID": website_id, "runtimeID": runtime_id,
        })

    @mcp.tool()
    async def runtime_search(
        name: Annotated[Optional[str], Field(description="运行时名模糊匹配")] = None,
        type: Annotated[Optional[str], Field(description="按类型过滤：php/node/java/go/python")] = None,
        status: Annotated[Optional[str], Field(description="按状态过滤")] = None,
        page: Annotated[int, Field(ge=1, description="页码")] = 1,
        page_size: Annotated[int, Field(ge=1, le=500, description="每页数量")] = 100,
    ) -> dict:
        """[运行时] 分页列出运行时（PHP/Node 等）。读操作。

        返回所有运行时（PHP/Node/Java 等，供网站绑定）。对应 POST /runtimes/search。

        Args:
            name: 名称模糊匹配。
            type: 按类型过滤。
            status: 按状态过滤。
            page: 页码。
            page_size: 每页数量。
        """
        client = await get_client()
        body: dict[str, Any] = {
            "page": page,
            "pageSize": page_size,
        }
        if name is not None:
            body["name"] = name
        if type is not None:
            body["type"] = type
        if status is not None:
            body["status"] = status
        return await client.post("/runtimes/search", body)

    @mcp.tool()
    async def runtime_detail(
        runtime_id: Annotated[int, Field(description="运行时 ID")],
    ) -> dict:
        """[运行时] 查看运行时详情。读操作。

        返回运行时的完整配置。对应 GET /runtimes/{id}。

        Args:
            runtime_id: 运行时 ID。
        """
        client = await get_client()
        return await client.get(f"/runtimes/{runtime_id}")

    @mcp.tool()
    async def runtime_operate(
        runtime_id: Annotated[int, Field(description="运行时 ID")],
        operate: Annotated[str, Field(description="操作类型：start/stop/restart/rebuild 等")],
    ) -> dict:
        """⚠️写操作 [运行时] 启动/停止/重启/重建运行时。

        对运行时执行生命周期操作。对应 POST /runtimes/operate。

        Args:
            runtime_id: 运行时 ID。
            operate: 操作类型。
        """
        require_write()
        client = await get_client()
        return await client.post("/runtimes/operate", {
            "ID": runtime_id, "operate": operate,
        })

    @mcp.tool()
    async def runtime_delete(
        runtime_id: Annotated[int, Field(description="运行时 ID")],
        force_delete: Annotated[bool, Field(description="是否强制删除")] = False,
        confirm: Annotated[bool, Field(description="删除是高危操作，必须传 true")] = False,
    ) -> dict:
        """⚠️高危 [运行时] 删除运行时。

        删除运行时（被网站引用的需 force_delete 或先解绑）。对应 POST /runtimes/del。
        必须传 confirm=true。

        Args:
            runtime_id: 运行时 ID。
            force_delete: 强制删除。
            confirm: 必须为 true。
        """
        require_write()
        if not confirm:
            raise ValueError("删除运行时是高危操作，必须显式传 confirm=true。")
        client = await get_client()
        return await client.post("/runtimes/del", {
            "id": runtime_id, "forceDelete": force_delete,
        })

    @mcp.tool()
    async def runtime_delete_check(
        runtime_id: Annotated[int, Field(description="运行时 ID")],
    ) -> dict:
        """[运行时] 删除前检查（哪些网站/资源依赖该运行时）。读操作。

        对应 GET /runtimes/installed/delete/check/{id}。删除运行时前建议先调用。

        Args:
            runtime_id: 运行时 ID。
        """
        client = await get_client()
        return await client.get(f"/runtimes/installed/delete/check/{runtime_id}")

    @mcp.tool()
    async def runtime_sync() -> dict:
        """⚠️写操作 [运行时] 同步所有运行时状态。

        从容器实际状态同步运行时状态。对应 POST /runtimes/sync。
        """
        require_write()
        client = await get_client()
        return await client.post("/runtimes/sync", {})

    @mcp.tool()
    async def runtime_php_extensions_search(
        runtime_id: Annotated[int, Field(description="PHP 运行时 ID")],
        show_all: Annotated[bool, Field(description="是否返回全部（含已装与未装），false 只返回已装")] = False,
        page: Annotated[int, Field(ge=1, description="页码")] = 1,
        page_size: Annotated[int, Field(ge=1, le=500, description="每页数量")] = 100,
    ) -> dict:
        """[PHP] 分页列出 PHP 运行时扩展。读操作。

        返回 PHP 运行时可用/已装的扩展列表。对应 POST /runtimes/php/extensions/search。
        注意：openapi 此接口 body 无 runtimeID 字段，扩展按运行时 ID 路径查询，
        实际 1Panel 需先在 runtime_detail 拿到上下文；此处仅做分页查询。

        Args:
            runtime_id: 运行时 ID（保留参数，用于调用方语义提示）。
            show_all: 是否返回全部（含未装）。
            page: 页码。
            page_size: 每页数量。
        """
        client = await get_client()
        return await client.post("/runtimes/php/extensions/search", {
            "page": page,
            "pageSize": page_size,
            "all": show_all,
        })

    @mcp.tool()
    async def runtime_php_extension_install(
        runtime_id: Annotated[int, Field(description="PHP 运行时 ID")],
        name: Annotated[str, Field(description="扩展名，如 redis/mysqli")],
        task_id: Annotated[str, Field(description="任务 ID")] = "",
    ) -> dict:
        """⚠️写操作 [PHP] 安装 PHP 扩展。

        给 PHP 运行时安装指定扩展。对应 POST /runtimes/php/extensions/install。

        Args:
            runtime_id: 运行时 ID。
            name: 扩展名。
            task_id: 任务跟踪 ID。
        """
        require_write()
        client = await get_client()
        return await client.post("/runtimes/php/extensions/install", {
            "ID": runtime_id, "name": name, "taskID": task_id,
        })

    @mcp.tool()
    async def runtime_php_extension_uninstall(
        runtime_id: Annotated[int, Field(description="PHP 运行时 ID")],
        name: Annotated[str, Field(description="扩展名")],
        task_id: Annotated[str, Field(description="任务 ID")] = "",
    ) -> dict:
        """⚠️写操作 [PHP] 卸载 PHP 扩展。

        从 PHP 运行时卸载扩展。对应 POST /runtimes/php/extensions/uninstall。

        Args:
            runtime_id: 运行时 ID。
            name: 扩展名。
            task_id: 任务跟踪 ID。
        """
        require_write()
        client = await get_client()
        return await client.post("/runtimes/php/extensions/uninstall", {
            "ID": runtime_id, "name": name, "taskID": task_id,
        })

    # ====================================================================
    # 其余网站辅助配置（重写/重定向/CORS/防盗链/认证/真实IP/负载均衡/默认页/数据库/Composer/Stream）
    # ====================================================================

    @mcp.tool()
    async def website_rewrite_get(
        website_id: Annotated[int, Field(description="网站 ID")],
        name: Annotated[str, Field(description="重写模板名，如 default/wordpress/thinkphp")],
    ) -> dict:
        """[Nginx] 查看网站伪静态/重写配置。读操作。

        返回指定重写模板的配置内容。对应 POST /websites/rewrite。

        Args:
            website_id: 网站 ID。
            name: 重写模板名。
        """
        client = await get_client()
        return await client.post("/websites/rewrite", {
            "websiteId": website_id, "name": name,
        })

    @mcp.tool()
    async def website_rewrite_update(
        website_id: Annotated[int, Field(description="网站 ID")],
        name: Annotated[str, Field(description="重写模板名")],
        content: Annotated[Optional[str], Field(description="自定义重写内容（留空使用模板默认）")] = None,
    ) -> dict:
        """⚠️写操作 [Nginx] 修改网站伪静态/重写配置。

        切换或自定义网站的重写规则。对应 POST /websites/rewrite/update。

        Args:
            website_id: 网站 ID。
            name: 重写模板名。
            content: 自定义内容（留空使用模板）。
        """
        require_write()
        client = await get_client()
        body: dict[str, Any] = {"websiteId": website_id, "name": name}
        if content is not None:
            body["content"] = content
        return await client.post("/websites/rewrite/update", body)

    @mcp.tool()
    async def website_rewrite_custom_list() -> dict:
        """[Nginx] 列出自定义重写模板。读操作。

        返回用户保存的自定义伪静态模板。对应 GET /websites/rewrite/custom。
        """
        client = await get_client()
        return await client.get("/websites/rewrite/custom")

    @mcp.tool()
    async def website_rewrite_custom_operate(
        operate: Annotated[Literal["create", "delete"], Field(description="操作：create 新建/delete 删除")],
        name: Annotated[str, Field(description="自定义模板名")],
        content: Annotated[str, Field(description="模板内容（create 时必填）")] = "",
    ) -> dict:
        """⚠️写操作 [Nginx] 新建/删除自定义重写模板。

        对应 POST /websites/rewrite/custom。

        Args:
            operate: create/delete。
            name: 模板名。
            content: 模板内容。
        """
        require_write()
        client = await get_client()
        return await client.post("/websites/rewrite/custom", {
            "operate": operate, "name": name, "content": content,
        })

    @mcp.tool()
    async def website_redirect_get(
        website_id: Annotated[int, Field(description="网站 ID")],
        name: Annotated[str, Field(description="重定向规则名")],
    ) -> dict:
        """[Nginx] 查看网站重定向规则。读操作。

        返回指定重定向规则详情。对应 POST /websites/redirect（共用 WebsiteProxyReq
        结构，1Panel 实际按 name 返回重定向配置）。

        Args:
            website_id: 网站 ID。
            name: 重定向规则名。
        """
        client = await get_client()
        return await client.post("/websites/redirect", {
            "websiteID": website_id, "name": name,
        })

    @mcp.tool()
    async def website_redirect_update(
        website_id: Annotated[int, Field(description="网站 ID")],
        name: Annotated[str, Field(description="重定向规则名")],
        operate: Annotated[str, Field(description="操作：create 新建 / update 修改")],
        type: Annotated[str, Field(description="重定向类型：301/302/path/domain")] = "301",
        redirect: Annotated[str, Field(description="目标地址")] = "",
        target: Annotated[str, Field(description="匹配目标，如路径或域名")] = "",
        path: Annotated[str, Field(description="匹配路径")] = "",
        keep_path: Annotated[bool, Field(description="是否保留原路径")] = True,
        enable: Annotated[bool, Field(description="是否启用")] = True,
    ) -> dict:
        """⚠️写操作 [Nginx] 新增/修改网站重定向规则。

        对应 POST /websites/redirect/update。

        Args:
            website_id: 网站 ID。
            name: 规则名。
            operate: create/update。
            type: 重定向类型。
            redirect: 目标地址。
            target: 匹配目标。
            path: 匹配路径。
            keep_path: 保留原路径。
            enable: 启用开关。
        """
        require_write()
        client = await get_client()
        return await client.post("/websites/redirect/update", {
            "websiteID": website_id,
            "name": name,
            "operate": operate,
            "type": type,
            "redirect": redirect,
            "target": target,
            "path": path,
            "keepPath": keep_path,
            "enable": enable,
        })

    @mcp.tool()
    async def website_redirect_file_get(
        website_id: Annotated[int, Field(description="网站 ID")],
        name: Annotated[str, Field(description="重定向规则名")],
    ) -> dict:
        """[Nginx] 查看重定向规则的 nginx 配置文件。读操作。

        对应 POST /websites/redirect/file。

        Args:
            website_id: 网站 ID。
            name: 规则名。
        """
        client = await get_client()
        return await client.post("/websites/redirect/file", {
            "websiteID": website_id, "name": name,
        })

    @mcp.tool()
    async def website_cors_get(
        website_id: Annotated[int, Field(description="网站 ID")],
    ) -> dict:
        """[Nginx] 查看网站 CORS 配置。读操作。

        返回跨域资源共享配置。对应 GET /websites/cors/{id}。

        Args:
            website_id: 网站 ID。
        """
        client = await get_client()
        return await client.get(f"/websites/cors/{website_id}")

    @mcp.tool()
    async def website_cors_update(
        website_id: Annotated[int, Field(description="网站 ID")],
        cors: Annotated[bool, Field(description="是否启用 CORS")] = False,
        allow_origins: Annotated[str, Field(description="允许的源，* 或具体域名")] = "*",
        allow_methods: Annotated[str, Field(description="允许的方法，如 GET,POST")] = "GET,POST,OPTIONS",
        allow_headers: Annotated[str, Field(description="允许的头")] = "*",
        allow_credentials: Annotated[bool, Field(description="是否允许携带凭证")] = False,
        preflight: Annotated[bool, Field(description="是否处理预检请求")] = True,
    ) -> dict:
        """⚠️写操作 [Nginx] 修改网站 CORS 配置。

        配置跨域策略。对应 POST /websites/cors/update。

        Args:
            website_id: 网站 ID。
            cors: 启用 CORS。
            allow_origins: 允许的源。
            allow_methods: 允许的方法。
            allow_headers: 允许的请求头。
            allow_credentials: 允许凭证。
            preflight: 处理预检。
        """
        require_write()
        client = await get_client()
        return await client.post("/websites/cors/update", {
            "websiteID": website_id,
            "cors": cors,
            "allowOrigins": allow_origins,
            "allowMethods": allow_methods,
            "allowHeaders": allow_headers,
            "allowCredentials": allow_credentials,
            "preflight": preflight,
        })

    @mcp.tool()
    async def website_leech_get(
        website_id: Annotated[int, Field(description="网站 ID")],
    ) -> dict:
        """[Nginx] 查看网站防盗链配置。读操作。

        返回防盗链（AntiLeech）配置。对应 POST /websites/leech。

        Args:
            website_id: 网站 ID。
        """
        client = await get_client()
        return await client.post("/websites/leech", {"websiteID": website_id})

    @mcp.tool()
    async def website_leech_update(
        website_id: Annotated[int, Field(description="网站 ID")],
        enable: Annotated[bool, Field(description="是否启用防盗链")] = False,
        server_names: Annotated[list[str], Field(description="允许的域名列表（白名单）", )] = None,
        none_ref: Annotated[bool, Field(description="是否允许空 Referer")] = True,
        blocked: Annotated[bool, Field(description="阻断未授权访问")] = True,
        cache: Annotated[bool, Field(description="是否缓存")] = False,
        cache_time: Annotated[int, Field(description="缓存时间数值")] = 30,
        cache_unit: Annotated[str, Field(description="缓存单位：m/h")] = "m",
        log_enable: Annotated[bool, Field(description="是否记录日志")] = False,
        extends: Annotated[str, Field(description="受保护的扩展名，逗号分隔")] = "jpg,jpeg,png,gif,mp4",
        return_value: Annotated[str, Field(description="被拦截时返回的内容/地址")] = "",
    ) -> dict:
        """⚠️写操作 [Nginx] 修改网站防盗链配置。

        对应 POST /websites/leech/update。

        Args:
            website_id: 网站 ID。
            enable: 启用防盗链。
            server_names: 允许的域名白名单。
            none_ref: 允许空 Referer。
            blocked: 阻断未授权。
            cache: 缓存。
            cache_time: 缓存时间。
            cache_unit: 缓存单位。
            log_enable: 记录日志。
            extends: 受保护扩展名。
            return_value: 拦截返回内容。
        """
        require_write()
        client = await get_client()
        return await client.post("/websites/leech/update", {
            "websiteID": website_id,
            "enable": enable,
            "serverNames": server_names or [],
            "noneRef": none_ref,
            "blocked": blocked,
            "cache": cache,
            "cacheTime": cache_time,
            "cacheUint": cache_unit,
            "logEnable": log_enable,
            "extends": extends,
            "return": return_value,
        })

    @mcp.tool()
    async def website_authbasic_get(
        website_id: Annotated[int, Field(description="网站 ID")],
    ) -> dict:
        """[Nginx] 查看网站 BasicAuth 用户列表。读操作。

        返回整站 BasicAuth 用户。对应 POST /websites/auths。

        Args:
            website_id: 网站 ID。
        """
        client = await get_client()
        return await client.post("/websites/auths", {"websiteID": website_id})

    @mcp.tool()
    async def website_authbasic_update(
        website_id: Annotated[int, Field(description="网站 ID")],
        operate: Annotated[str, Field(description="操作：create 新建/update 修改/delete 删除")],
        username: Annotated[str, Field(description="用户名")] = "",
        password: Annotated[str, Field(description="密码（明文，1Panel 内部加密）")] = "",
        remark: Annotated[str, Field(description="备注")] = "",
    ) -> dict:
        """⚠️写操作 [Nginx] 管理网站 BasicAuth 用户。

        增/改/删整站 Basic 认证用户。对应 POST /websites/auths/update。

        Args:
            website_id: 网站 ID。
            operate: create/update/delete。
            username: 用户名。
            password: 密码。
            remark: 备注。
        """
        require_write()
        client = await get_client()
        return await client.post("/websites/auths/update", {
            "websiteID": website_id,
            "operate": operate,
            "username": username,
            "password": password,
            "remark": remark,
        })

    @mcp.tool()
    async def website_path_auth_get(
        website_id: Annotated[int, Field(description="网站 ID")],
    ) -> dict:
        """[Nginx] 查看网站按目录的 BasicAuth 配置。读操作。

        返回按路径设置的认证规则。对应 POST /websites/auths/path。

        Args:
            website_id: 网站 ID。
        """
        client = await get_client()
        return await client.post("/websites/auths/path", {"websiteID": website_id})

    @mcp.tool()
    async def website_path_auth_update(
        website_id: Annotated[int, Field(description="网站 ID")],
        operate: Annotated[str, Field(description="操作：create/update/delete")],
        name: Annotated[str, Field(description="规则名")] = "",
        path: Annotated[str, Field(description="受保护的路径，如 /admin")] = "",
        username: Annotated[str, Field(description="用户名")] = "",
        password: Annotated[str, Field(description="密码")] = "",
        remark: Annotated[str, Field(description="备注")] = "",
    ) -> dict:
        """⚠️写操作 [Nginx] 管理网站按目录的 BasicAuth。

        增/改/删针对特定路径的认证规则。对应 POST /websites/auths/path/update。

        Args:
            website_id: 网站 ID。
            operate: 操作类型。
            name: 规则名。
            path: 受保护路径。
            username: 用户名。
            password: 密码。
            remark: 备注。
        """
        require_write()
        client = await get_client()
        return await client.post("/websites/auths/path/update", {
            "websiteID": website_id,
            "operate": operate,
            "name": name,
            "path": path,
            "username": username,
            "password": password,
            "remark": remark,
        })

    @mcp.tool()
    async def website_realip_get(
        website_id: Annotated[int, Field(description="网站 ID")],
    ) -> dict:
        """[Nginx] 查看网站真实 IP 配置。读操作。

        返回从 CDN/代理还原客户端真实 IP 的配置。对应
        GET /websites/realip/config/{id}。

        Args:
            website_id: 网站 ID。
        """
        client = await get_client()
        return await client.get(f"/websites/realip/config/{website_id}")

    @mcp.tool()
    async def website_realip_update(
        website_id: Annotated[int, Field(description="网站 ID")],
        open: Annotated[bool, Field(description="是否启用真实 IP 还原")] = False,
        ip_header: Annotated[str, Field(description="取真实 IP 的 header，如 X-Forwarded-For")] = "X-Forwarded-For",
        ip_from: Annotated[str, Field(description="受信任的来源 IP/网段，逗号分隔")] = "",
        ip_other: Annotated[str, Field(description="其他配置")] = "",
    ) -> dict:
        """⚠️写操作 [Nginx] 修改网站真实 IP 配置。

        配置从反代/CDN 还原客户端真实 IP。对应 POST /websites/realip/config。

        Args:
            website_id: 网站 ID。
            open: 启用。
            ip_header: 取 IP 的 header。
            ip_from: 信任来源。
            ip_other: 其他配置。
        """
        require_write()
        client = await get_client()
        return await client.post("/websites/realip/config", {
            "websiteID": website_id,
            "open": open,
            "ipHeader": ip_header,
            "ipFrom": ip_from,
            "ipOther": ip_other,
        })

    @mcp.tool()
    async def website_crosssite_operate(
        website_id: Annotated[int, Field(description="网站 ID")],
        operation: Annotated[Literal["Enable", "Disable"], Field(description="Enable 启用 / Disable 禁用跨站")],
    ) -> dict:
        """⚠️写操作 [Nginx] 启用/禁用 PHP 跨站访问（open_basedir）。

        控制网站 PHP 是否允许跨目录访问。对应 POST /websites/crosssite。

        Args:
            website_id: 网站 ID。
            operation: Enable/Disable。
        """
        require_write()
        client = await get_client()
        return await client.post("/websites/crosssite", {
            "websiteID": website_id, "operation": operation,
        })

    @mcp.tool()
    async def website_lb_list(
        website_id: Annotated[int, Field(description="网站 ID")],
    ) -> dict:
        """[Nginx] 查看网站负载均衡（upstream）列表。读操作。

        返回网站的反代负载均衡池。对应 GET /websites/lbs（带 body {"id": website_id}，
        1Panel 此接口用 GET + JSON body）。

        Args:
            website_id: 网站 ID。
        """
        client = await get_client()
        return await client.get("/websites/lbs", json={"id": website_id})

    @mcp.tool()
    async def website_lb_create(
        website_id: Annotated[int, Field(description="网站 ID")],
        name: Annotated[str, Field(description="负载均衡池名")],
        servers: Annotated[list[dict], Field(description="后端节点列表，如 [{'server':'127.0.0.1:8080','weight':1}]")],
        algorithm: Annotated[str, Field(description="调度算法：ip_hash/least_conn 等")] = "",
    ) -> dict:
        """⚠️写操作 [Nginx] 创建网站负载均衡池。

        对应 POST /websites/lbs/create。

        Args:
            website_id: 网站 ID。
            name: 池名。
            servers: 后端节点列表。
            algorithm: 调度算法。
        """
        require_write()
        client = await get_client()
        return await client.post("/websites/lbs/create", {
            "websiteID": website_id,
            "name": name,
            "servers": servers,
            "algorithm": algorithm,
        })

    @mcp.tool()
    async def website_lb_update(
        website_id: Annotated[int, Field(description="网站 ID")],
        name: Annotated[str, Field(description="负载均衡池名")],
        servers: Annotated[list[dict], Field(description="后端节点列表")] = None,
        algorithm: Annotated[str, Field(description="调度算法")] = "",
    ) -> dict:
        """⚠️写操作 [Nginx] 修改网站负载均衡池。

        对应 POST /websites/lbs/update。

        Args:
            website_id: 网站 ID。
            name: 池名。
            servers: 后端节点。
            algorithm: 调度算法。
        """
        require_write()
        client = await get_client()
        return await client.post("/websites/lbs/update", {
            "websiteID": website_id,
            "name": name,
            "servers": servers or [],
            "algorithm": algorithm,
        })

    @mcp.tool()
    async def website_lb_delete(
        website_id: Annotated[int, Field(description="网站 ID")],
        name: Annotated[str, Field(description="负载均衡池名")],
    ) -> dict:
        """⚠️写操作 [Nginx] 删除网站负载均衡池。

        对应 POST /websites/lbs/del。

        Args:
            website_id: 网站 ID。
            name: 池名。
        """
        require_write()
        client = await get_client()
        return await client.post("/websites/lbs/del", {
            "websiteID": website_id, "name": name,
        })

    @mcp.tool()
    async def website_lb_file_get(
        website_id: Annotated[int, Field(description="网站 ID")],
        name: Annotated[str, Field(description="负载均衡池名")],
    ) -> dict:
        """[Nginx] 查看负载均衡池的 nginx upstream 配置。读操作。

        对应 POST /websites/lbs/file。

        Args:
            website_id: 网站 ID。
            name: 池名。
        """
        client = await get_client()
        return await client.post("/websites/lbs/file", {
            "websiteID": website_id, "name": name,
        })

    @mcp.tool()
    async def website_default_html_get(
        type: Annotated[Literal["index", "stop", "certificate", "domain"], Field(description="页面类型：index 默认首页/stop 停止页/certificate 证书页/domain 域名页")],
    ) -> dict:
        """[Nginx] 查看默认页 HTML（首页/停止页等）。读操作。

        返回 1Panel 全局默认页内容。对应 GET /websites/default/html/{type}。

        Args:
            type: 页面类型。
        """
        client = await get_client()
        return await client.get(f"/websites/default/html/{type}")

    @mcp.tool()
    async def website_default_html_update(
        type: Annotated[Literal["index", "stop", "certificate", "domain"], Field(description="页面类型")],
        content: Annotated[str, Field(description="HTML 内容")],
        sync: Annotated[bool, Field(description="是否同步到已存在的网站")] = False,
    ) -> dict:
        """⚠️写操作 [Nginx] 修改默认页 HTML。

        对应 POST /websites/default/html/update。

        Args:
            type: 页面类型。
            content: HTML 内容。
            sync: 是否同步到已有网站。
        """
        require_write()
        client = await get_client()
        return await client.post("/websites/default/html/update", {
            "type": type, "content": content, "sync": sync,
        })

    @mcp.tool()
    async def website_default_server_update(
        website_id: Annotated[int, Field(description="网站 ID")],
    ) -> dict:
        """⚠️写操作 [Nginx] 设置默认站点。

        将指定网站设为 nginx 的 default_server（未匹配域名时返回该站点）。
        对应 POST /websites/default/server。

        Args:
            website_id: 网站 ID。
        """
        require_write()
        client = await get_client()
        return await client.post("/websites/default/server", {"id": website_id})

    @mcp.tool()
    async def website_databases_list() -> dict:
        """[网站] 列出可关联的数据库。读操作。

        返回可用于绑定到网站的所有数据库。对应 GET /websites/databases。
        """
        client = await get_client()
        return await client.get("/websites/databases")

    @mcp.tool()
    async def website_database_update(
        website_id: Annotated[int, Field(description="网站 ID")],
        database_id: Annotated[Optional[int], Field(description="数据库 ID（解绑传 None）")] = None,
        database_type: Annotated[Optional[str], Field(description="数据库类型 mysql/pgsql")] = None,
    ) -> dict:
        """⚠️写操作 [网站] 绑定/解绑网站数据库。

        给网站绑定或解绑数据库。对应 POST /websites/databases。

        Args:
            website_id: 网站 ID。
            database_id: 数据库 ID（None 表示解绑）。
            database_type: 数据库类型。
        """
        require_write()
        client = await get_client()
        body: dict[str, Any] = {"websiteID": website_id}
        if database_id is not None:
            body["databaseID"] = database_id
        if database_type is not None:
            body["databaseType"] = database_type
        return await client.post("/websites/databases", body)

    @mcp.tool()
    async def website_composer_exec(
        website_id: Annotated[int, Field(description="网站 ID")],
        command: Annotated[str, Field(description="composer 命令，如 install/update/require")] = "install",
        dir: Annotated[str, Field(description="执行目录（网站内相对路径）")] = "",
        user: Annotated[str, Field(description="执行用户，如 www")] = "www",
        mirror: Annotated[str, Field(description="镜像源，留空用默认")] = "",
        ext_command: Annotated[str, Field(description="额外命令参数")] = "",
        task_id: Annotated[str, Field(description="任务 ID")] = "",
    ) -> dict:
        """⚠️写操作 [网站] 执行 composer 命令。

        在 PHP 网站目录执行 composer。对应 POST /websites/exec/composer。

        Args:
            website_id: 网站 ID。
            command: composer 命令。
            dir: 执行目录。
            user: 执行用户。
            mirror: 镜像源。
            ext_command: 额外参数。
            task_id: 任务跟踪 ID。
        """
        require_write()
        client = await get_client()
        return await client.post("/websites/exec/composer", {
            "websiteID": website_id,
            "command": command,
            "dir": dir,
            "user": user,
            "mirror": mirror,
            "extCommand": ext_command,
            "taskID": task_id,
        })

    @mcp.tool()
    async def website_stream_update(
        website_id: Annotated[int, Field(description="网站 ID")],
        name: Annotated[str, Field(description="stream 名称")] = "",
        ports: Annotated[str, Field(description="端口配置，如 '8080,8081'")] = "",
        servers: Annotated[list[dict], Field(description="后端节点列表")] = None,
        algorithm: Annotated[str, Field(description="调度算法")] = "",
        udp: Annotated[bool, Field(description="是否 UDP")] = False,
    ) -> dict:
        """⚠️写操作 [网站] 配置 TCP/UDP Stream（四层代理）。

        对应 POST /websites/stream/update。

        Args:
            website_id: 网站 ID。
            name: stream 名。
            ports: 监听端口。
            servers: 后端节点。
            algorithm: 调度算法。
            udp: 是否 UDP。
        """
        require_write()
        client = await get_client()
        return await client.post("/websites/stream/update", {
            "websiteID": website_id,
            "name": name,
            "streamPorts": ports,
            "servers": servers or [],
            "algorithm": algorithm,
            "udp": udp,
        })

    @mcp.tool()
    async def website_create_check(
        install_ids: Annotated[list[int], Field(description="待检查的安装 ID 列表")] = None,
    ) -> dict:
        """[网站] 创建网站前预检查（应用是否就绪）。读操作。

        对应 POST /websites/check。

        Args:
            install_ids: 安装 ID 列表。
        """
        client = await get_client()
        return await client.post("/websites/check", {
            "InstallIds": install_ids or [],
        })
