"""系统设置与分组模块（对应 openapi.json 的 System Setting / System Group tag，约 49 接口）。

覆盖范围：
- 面板基础设置（端口 / SSL / 安全入口 / 绑定地址 / 代理 / 面板备注 / 菜单）
- 系统信息（版本 / 系统状态 / 备份目录 / 监听地址 / 可用状态）
- 账号安全（面板密码 / MFA / Passkey / API 接口密钥）
- 终端与本地 SSH 连接配置
- 系统升级（升级信息 / 升级版本 / 升级日志 / release 列表）
- 系统快照（创建 / 删除 / 恢复 / 回滚 / 重试 / 导入 / 列表 / 详情）
- 通用分组（System Group：列表 / 创建 / 更新 / 删除）

实现风格照搬 container.py 黄金范式：
1. 工具名 system_<object>_<action>，便于 mcphub 向量检索按模块召回
2. description 结构化（[模块] 开头，写操作加 ⚠️，高危加 confirm 提示）
3. 入参用 Annotated[T, Field(description=...)]，复杂入参用本文件内联 Pydantic 模型
4. 写操作 handler 第一行 require_write()，高危操作（delete/upgrade/restore/rollback）加 confirm

接口来源：references/openapi.json，basePath /api/v2，路径不含前缀。
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Optional

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

from ..client import get_client
from ..safety import require_write


# ---- 枚举 / 类型别名（取自 openapi.json definitions 的 enum）----

# SSL 模式：Enable 启用 / Disable 禁用 / Mux 复用同一端口（面板与终端共享）
SystemSSLStatus = Literal["Enable", "Disable", "Mux"]
# SSL 来源：self 自签 / select 选择已有证书 / import 导入文件 / import-paste 粘贴 / import-local 本地
SystemSSLType = Literal["self", "select", "import", "import-paste", "import-local"]
# 绑定 IPv6 开关
SystemIPv6 = Literal["Enable", "Disable"]
# 快照排序字段（仅 name / createdAt，见 dto.PageSnapshot）
SnapshotOrderBy = Literal["name", "createdAt"]
# 通用排序方向
Order = Literal["ascending", "descending"]


# ---- 复杂入参模型（多字段且语义相关，建 Pydantic 模型保持工具签名清爽）----


class DataTree(BaseModel):
    """快照创建时选择备份目录的树节点（dto.DataTree）。"""

    name: str = Field(description="节点名称")
    path: str = Field(default="", description="节点路径")
    is_check: bool = Field(default=False, description="是否勾选纳入快照")
    is_disable: bool = Field(default=False, description="是否禁用勾选")
    is_local: bool = Field(default=False, description="是否本地目录")
    key: str = Field(default="", description="节点 key")
    label: str = Field(default="", description="展示标签")
    size: int = Field(default=0, description="节点大小（字节）")


def _datatree_to_dict(t: DataTree) -> dict[str, Any]:
    return {
        "name": t.name,
        "path": t.path,
        "isCheck": t.is_check,
        "isDisable": t.is_disable,
        "isLocal": t.is_local,
        "key": t.key,
        "label": t.label,
        "size": t.size,
    }


def register(mcp: FastMCP) -> None:

    # ================================================================
    # 通用分组（System Group：/core/groups、/groups）
    # 分组用于网站 / 数据库等资源归类，按 type 区分（website/database 等）
    # ================================================================

    @mcp.tool()
    async def system_group_search(
        type: Annotated[str, Field(description="分组类型，如 website / database / cronjob 等")],
    ) -> dict:
        """[系统] 列出指定类型的分组。读操作。

        返回该类型下所有分组。对应 POST /core/groups/search（body 仅含 type）。
        网站创建、数据库创建等场景需先取分组列表。

        Args:
            type: 分组类型，常见 website / database。
        """
        client = await get_client()
        return await client.post("/core/groups/search", {"type": type})

    @mcp.tool()
    async def system_group_create(
        name: Annotated[str, Field(description="分组名称")],
        type: Annotated[str, Field(description="分组类型，如 website / database")],
    ) -> dict:
        """⚠️写操作 [系统] 创建分组。

        新建一个指定类型的分组。对应 POST /core/groups（dto.GroupCreate）。

        Args:
            name: 分组名称。
            type: 分组类型。
        """
        require_write()
        client = await get_client()
        return await client.post("/core/groups", {"name": name, "type": type})

    @mcp.tool()
    async def system_group_update(
        id: Annotated[int, Field(description="分组 ID")],
        type: Annotated[str, Field(description="分组类型")],
        name: Annotated[Optional[str], Field(description="新分组名，留空表示不改名")] = None,
        is_default: Annotated[bool, Field(description="是否设为该类型的默认分组")] = False,
    ) -> dict:
        """⚠️写操作 [系统] 更新分组（改名 / 设默认）。

        对应 POST /core/groups/update（dto.GroupUpdate）。

        Args:
            id: 分组 ID。
            type: 分组类型。
            name: 新分组名，留空表示不改名。
            is_default: 是否设为默认分组。
        """
        require_write()
        client = await get_client()
        body: dict[str, Any] = {"id": id, "type": type, "isDefault": is_default}
        if name is not None:
            body["name"] = name
        return await client.post("/core/groups/update", body)

    @mcp.tool()
    async def system_group_delete(
        id: Annotated[int, Field(description="分组 ID")],
        confirm: Annotated[bool, Field(description="删除分组是高危操作，必须传 true")] = False,
    ) -> dict:
        """⚠️高危 [系统] 删除分组。

        删除指定分组（资源会被移到默认分组）。对应 POST /core/groups/del（dto.OperateByID）。
        必须显式传 confirm=true。

        Args:
            id: 分组 ID。
            confirm: 必须为 true 才执行删除。
        """
        require_write()
        if not confirm:
            raise ValueError("删除分组是高危操作，必须显式传 confirm=true。")
        client = await get_client()
        return await client.post("/core/groups/del", {"id": id})

    # ================================================================
    # 面板信息 / 系统状态（只读）
    # ================================================================

    @mcp.tool()
    async def system_info() -> dict:
        """[系统] 获取面板运行信息（版本 / 时区 / 监控 / Docker 等）。读操作。

        返回系统版本、时区、监听地址、监控间隔、Docker sock 路径、回收站状态等。
        对应 POST /settings/search（返回 dto.SettingInfo）。

        这是查看「面板当前运行状态」的统一入口。
        """
        client = await get_client()
        return await client.post("/settings/search", {})

    @mcp.tool()
    async def system_setting_get() -> dict:
        """[系统] 获取面板完整设置（面板设置页数据）。读操作。

        对应 POST /core/settings/search（返回 dto.SettingInfo 的核心设置视图）。
        与 system_info 字段重叠但更偏「设置项」语义。

        Returns:
            面板设置对象（端口、SSL、绑定、安全入口、面板地址等）。
        """
        client = await get_client()
        return await client.post("/core/settings/search", {})

    @mcp.tool()
    async def system_setting_get_by_key(
        key: Annotated[str, Field(description="设置项 key，如 ServerPort / SecurityEntrance")],
    ) -> dict:
        """[系统] 按 key 读取单个面板设置项（返回设置详情对象）。读操作。

        对应 GET /settings/get/{key}（返回 dto.SettingInfo）。key 取值参考面板
        「设置」页字段名，如 ServerPort（面板端口）、SecurityEntrance（安全入口）、
        BindDomain（绑定域名）等。

        Args:
            key: 设置项 key。
        """
        client = await get_client()
        return await client.get(f"/settings/get/{key}")

    @mcp.tool()
    async def system_setting_by_key(
        key: Annotated[str, Field(description="设置项 key")],
    ) -> dict:
        """[系统] 按 key 读取单个面板设置项的值（纯字符串）。读操作。

        对应 POST /core/settings/by（按 key 返回设置项字符串值）。
        与 system_setting_get_by_key 的区别：本接口直接返回 value 字符串，
        而非完整 SettingInfo 对象。

        Args:
            key: 设置项 key。
        """
        client = await get_client()
        return await client.post("/core/settings/by", {"key": key})

    @mcp.tool()
    async def system_available_status() -> dict:
        """[系统] 查询面板可用状态（升级 / 同步等运行态）。读操作。

        对应 GET /settings/search/available。用于判断面板当前是否有后台任务在跑。
        """
        client = await get_client()
        return await client.get("/settings/search/available")

    @mcp.tool()
    async def system_base_dir() -> dict:
        """[系统] 获取本地备份目录路径。读操作。

        对应 GET /settings/basedir。返回 1Panel 本地备份目录的绝对路径。
        """
        client = await get_client()
        return await client.get("/settings/basedir")

    @mcp.tool()
    async def system_interface_list() -> dict:
        """[系统] 获取系统监听地址列表（网卡 IP）。读操作。

        对应 GET /core/settings/interface。返回本机所有可用网络地址，
        用于面板绑定地址 / SSL 域名等场景的下拉选项。
        """
        client = await get_client()
        return await client.get("/core/settings/interface")

    @mcp.tool()
    async def system_memo_get() -> dict:
        """[系统] 获取面板备注内容。读操作。

        对应 GET /core/settings/memo。返回仪表盘上展示的备注文本（最长 500 字符）。
        """
        client = await get_client()
        return await client.get("/core/settings/memo")

    # ================================================================
    # 面板基础设置（写）
    # ================================================================

    @mcp.tool()
    async def system_setting_update(
        key: Annotated[str, Field(description="设置项 key，如 ServerPort / SecurityEntrance")],
        value: Annotated[str, Field(description="设置项新值（统一字符串）")],
    ) -> dict:
        """⚠️写操作 [系统] 更新单个面板设置项（通用 key/value）。

        对应 POST /settings/update（dto.SettingUpdate）。
        用于改面板端口、安全入口、绑定域名、监控间隔等任意 key/value 设置。
        部分设置项改动后会触发面板重启，请谨慎。

        Args:
            key: 设置项 key（参考 system_setting_get 返回的字段名）。
            value: 新值（统一为字符串，数字也传字符串）。
        """
        require_write()
        client = await get_client()
        return await client.post("/settings/update", {"key": key, "value": value})

    @mcp.tool()
    async def system_setting_core_update(
        key: Annotated[str, Field(description="设置项 key")],
        value: Annotated[str, Field(description="设置项新值")],
    ) -> dict:
        """⚠️写操作 [系统] 更新核心设置项（/core/settings/update 入口）。

        与 system_setting_update 类似，对应 POST /core/settings/update（dto.SettingUpdate）。
        部分设置走 core 入口（菜单 / 菜单排序等核心面板配置）。

        Args:
            key: 设置项 key。
            value: 新值。
        """
        require_write()
        client = await get_client()
        return await client.post("/core/settings/update", {"key": key, "value": value})

    @mcp.tool()
    async def system_memo_update(
        content: Annotated[str, Field(max_length=500, description="备注内容，最长 500 字符")],
    ) -> dict:
        """⚠️写操作 [系统] 更新面板备注。

        对应 POST /core/settings/memo（dto.MemoUpdate）。备注展示在仪表盘顶部。

        Args:
            content: 备注文本，最长 500 字符。
        """
        require_write()
        client = await get_client()
        return await client.post("/core/settings/memo", {"content": content})

    @mcp.tool()
    async def system_menu_update(
        key: Annotated[str, Field(description="菜单设置项 key")],
        value: Annotated[str, Field(description="菜单设置项新值（一般为 JSON 字符串）")],
    ) -> dict:
        """⚠️写操作 [系统] 更新菜单设置（显隐 / 排序）。

        对应 POST /core/settings/menu/update（dto.SettingUpdate）。
        value 通常是序列化后的菜单结构 JSON 字符串。

        Args:
            key: 菜单设置项 key。
            value: 菜单设置项新值。
        """
        require_write()
        client = await get_client()
        return await client.post("/core/settings/menu/update", {"key": key, "value": value})

    @mcp.tool()
    async def system_description_save(
        id: Annotated[str, Field(description="资源 ID（字符串形式）")],
        type: Annotated[str, Field(description="资源类型，如 website / app / database")],
        description: Annotated[str, Field(default="", description="备注描述")] = "",
        detail_type: Annotated[str, Field(default="", description="子类型，部分资源用")] = "",
        is_pinned: Annotated[bool, Field(default=False, description="是否置顶")] = False,
    ) -> dict:
        """⚠️写操作 [系统] 保存资源备注描述（通用）。

        对应 POST /settings/description/save（dto.CommonDescription）。
        给网站 / 应用 / 数据库等资源设置描述文本。

        Args:
            id: 资源 ID。
            type: 资源类型。
            description: 描述内容。
            detail_type: 子类型（部分资源区分，如 mysql/redis）。
            is_pinned: 是否置顶展示。
        """
        require_write()
        client = await get_client()
        return await client.post("/settings/description/save", {
            "id": id,
            "type": type,
            "description": description,
            "detailType": detail_type,
            "isPinned": is_pinned,
        })

    # ================================================================
    # 端口 / 绑定 / 代理
    # ================================================================

    @mcp.tool()
    async def system_port_update(
        server_port: Annotated[int, Field(ge=1, le=65535, description="新的面板监听端口")],
    ) -> dict:
        """⚠️写操作 [系统] 修改面板监听端口。

        对应 POST /core/settings/port/update（dto.PortUpdate）。改端口后面板会重启，
        新端口需在防火墙放行，否则将无法访问面板。

        Args:
            server_port: 新端口，1-65535。
        """
        require_write()
        client = await get_client()
        return await client.post("/core/settings/port/update", {"serverPort": server_port})

    @mcp.tool()
    async def system_bind_update(
        bind_address: Annotated[str, Field(description="绑定地址，如 0.0.0.0 或具体 IP / 域名")],
        ipv6: Annotated[SystemIPv6, Field(description="是否启用 IPv6：Enable / Disable")] = "Disable",
    ) -> dict:
        """⚠️写操作 [系统] 更新面板绑定地址与 IPv6 开关。

        对应 POST /core/settings/bind/update（dto.BindInfo）。

        Args:
            bind_address: 绑定地址（IP 或域名）。
            ipv6: IPv6 开关，Enable 启用 / Disable 禁用。
        """
        require_write()
        client = await get_client()
        return await client.post("/core/settings/bind/update", {
            "bindAddress": bind_address,
            "ipv6": ipv6,
        })

    @mcp.tool()
    async def system_proxy_update(
        proxy_type: Annotated[str, Field(description="代理类型，如 http / socks5 / 关闭留空字符串")],
        proxy_url: Annotated[str, Field(default="", description="代理地址")] = "",
        proxy_port: Annotated[str, Field(default="", description="代理端口（字符串）")] = "",
        proxy_user: Annotated[str, Field(default="", description="代理用户名")] = "",
        proxy_passwd: Annotated[str, Field(default="", description="代理密码（明文，由面板加密存储）")] = "",
        proxy_passwd_keep: Annotated[str, Field(default="", description="保留密码（改其他项时复用）")] = "",
        proxy_docker: Annotated[bool, Field(default=False, description="是否同步给 Docker")] = False,
        with_docker_restart: Annotated[bool, Field(default=False, description="是否在更新后重启 Docker")] = False,
    ) -> dict:
        """⚠️写操作 [系统] 更新系统代理（面板 / Docker 拉镜像走代理）。

        对应 POST /core/settings/proxy/update（dto.ProxyUpdate）。
        配置后 1Panel 自身及（可选）Docker daemon 将通过该代理出网。

        Args:
            proxy_type: 代理类型（留空字符串表示关闭代理）。
            proxy_url: 代理地址。
            proxy_port: 代理端口。
            proxy_user: 代理用户名。
            proxy_passwd: 代理密码。
            proxy_passwd_keep: 保留密码。
            proxy_docker: 是否同步配置到 Docker。
            with_docker_restart: 是否在更新后重启 Docker（同步 docker 配置时建议 true）。
        """
        require_write()
        client = await get_client()
        return await client.post("/core/settings/proxy/update", {
            "proxyType": proxy_type,
            "proxyUrl": proxy_url,
            "proxyPort": proxy_port,
            "proxyUser": proxy_user,
            "proxyPasswd": proxy_passwd,
            "proxyPasswdKeep": proxy_passwd_keep,
            "proxyDocker": proxy_docker,
            "withDockerRestart": with_docker_restart,
        })

    # ================================================================
    # SSL（面板 HTTPS）
    # ================================================================

    @mcp.tool()
    async def system_ssl_info() -> dict:
        """[系统] 获取面板 SSL 证书信息。读操作。

        对应 GET /core/settings/ssl/info。返回当前证书的域名、颁发者、有效期等。
        """
        client = await get_client()
        return await client.get("/core/settings/ssl/info")

    @mcp.tool()
    async def system_ssl_update(
        ssl: Annotated[SystemSSLStatus, Field(description="SSL 模式：Enable/Disable/Mux")],
        ssl_type: Annotated[SystemSSLType, Field(description="证书来源：self/select/import/import-paste/import-local")],
        domain: Annotated[str, Field(default="", description="绑定的域名（self/select 场景用）")] = "",
        ssl_id: Annotated[Optional[int], Field(default=None, description="已有证书 ID（select 场景）")] = None,
        cert: Annotated[str, Field(default="", description="证书内容（import-paste 场景）")] = "",
        key: Annotated[str, Field(default="", description="私钥内容（import-paste 场景）")] = "",
    ) -> dict:
        """⚠️写操作 [系统] 更新面板 SSL 配置（启用 / 禁用 / 换证书）。

        对应 POST /core/settings/ssl/update（dto.SSLUpdate）。
        ssl=Mux 表示面板与终端复用同一端口。改完 SSL 后面板会重启。

        Args:
            ssl: SSL 模式，Enable 启用 / Disable 禁用 / Mux 复用端口。
            ssl_type: 证书来源，self 自签 / select 选已有 / import* 导入。
            domain: 绑定域名。
            ssl_id: 选择已有证书时的证书 ID。
            cert: 粘贴导入时的证书 PEM 文本。
            key: 粘贴导入时的私钥 PEM 文本。
        """
        require_write()
        client = await get_client()
        body: dict[str, Any] = {"ssl": ssl, "sslType": ssl_type}
        if domain:
            body["domain"] = domain
        if ssl_id is not None:
            body["sslID"] = ssl_id
        if cert:
            body["cert"] = cert
        if key:
            body["key"] = key
        return await client.post("/core/settings/ssl/update", body)

    @mcp.tool()
    async def system_ssl_download() -> dict:
        """⚠️写操作 [系统] 下载面板 SSL 证书（证书 + 私钥打包）。

        对应 POST /core/settings/ssl/download。返回证书文件内容，便于本地备份。
        """
        require_write()
        client = await get_client()
        return await client.post("/core/settings/ssl/download", {})

    # ================================================================
    # 账号安全：密码 / MFA / Passkey / API
    # ================================================================

    @mcp.tool()
    async def system_password_update(
        old_password: Annotated[str, Field(description="当前面板密码")],
        new_password: Annotated[str, Field(description="新面板密码")],
    ) -> dict:
        """⚠️写操作 [系统] 修改面板登录密码。

        对应 POST /core/settings/password/update（dto.PasswordUpdate）。

        Args:
            old_password: 当前密码。
            new_password: 新密码。
        """
        require_write()
        client = await get_client()
        return await client.post("/core/settings/password/update", {
            "oldPassword": old_password,
            "newPassword": new_password,
        })

    @mcp.tool()
    async def system_password_expired_handle(
        old_password: Annotated[str, Field(description="原密码")],
        new_password: Annotated[str, Field(description="新密码")],
    ) -> dict:
        """⚠️写操作 [系统] 重置已过期的面板密码。

        密码到期强制重置场景使用。对应 POST /core/settings/expired/handle（dto.PasswordUpdate）。

        Args:
            old_password: 原密码。
            new_password: 新密码。
        """
        require_write()
        client = await get_client()
        return await client.post("/core/settings/expired/handle", {
            "oldPassword": old_password,
            "newPassword": new_password,
        })

    @mcp.tool()
    async def system_mfa_info(
        secret: Annotated[str, Field(description="MFA secret（生成 QR 用）")],
        code: Annotated[str, Field(description="当前 6 位验证码")],
        interval: Annotated[str, Field(description="时间步长间隔，一般为 30")] = "30",
    ) -> dict:
        """[系统] 获取 MFA 绑定信息（secret / QR / otpauth）。读操作。

        对应 POST /core/settings/mfa（dto.MfaCredential，返回 mfa.Otp）。
        用于在绑定 MFA 前展示二维码与 secret。

        Args:
            secret: MFA secret。
            code: 当前 6 位验证码。
            interval: 时间步长，默认 30 秒。
        """
        client = await get_client()
        body = {"secret": secret, "code": code, "interval": interval}
        return await client.post("/core/settings/mfa", body)

    @mcp.tool()
    async def system_mfa_bind(
        secret: Annotated[str, Field(description="MFA secret（绑定流程返回的密钥）")],
        code: Annotated[str, Field(description="当前 6 位验证码")],
        interval: Annotated[str, Field(description="时间步长间隔，一般为 30")] = "30",
    ) -> dict:
        """⚠️写操作 [系统] 绑定 / 验证 MFA 两步验证。

        对应 POST /core/settings/mfa/bind（dto.MfaCredential）。提交 secret+code
        完成绑定或登录二次验证。

        Args:
            secret: MFA secret。
            code: 当前 6 位验证码。
            interval: 时间步长，默认 30 秒。
        """
        require_write()
        client = await get_client()
        body = {"secret": secret, "code": code, "interval": interval}
        return await client.post("/core/settings/mfa/bind", body)

    @mcp.tool()
    async def system_passkey_list() -> dict:
        """[系统] 列出已注册的 Passkey 列表。读操作。

        对应 GET /core/settings/passkey/list。返回每个 passkey 的 id / name / 创建时间。
        """
        client = await get_client()
        return await client.get("/core/settings/passkey/list")

    @mcp.tool()
    async def system_passkey_register_begin(
        name: Annotated[str, Field(description="新 passkey 的名称，如 '我的笔记本'")],
    ) -> dict:
        """⚠️写操作 [系统] 开始注册 Passkey（返回 WebAuthn 注册挑战）。

        对应 POST /core/settings/passkey/register/begin（dto.PasskeyRegisterRequest）。
        返回的 challenge 需交给浏览器 WebAuthn API 完成认证，再用 finish 接口提交。

        Args:
            name: passkey 名称。
        """
        require_write()
        client = await get_client()
        return await client.post("/core/settings/passkey/register/begin", {"name": name})

    @mcp.tool()
    async def system_passkey_register_finish(
        credential: Annotated[str, Field(description="WebAuthn 注册响应（attestationObject JSON 字符串）")],
    ) -> dict:
        """⚠️写操作 [系统] 完成 Passkey 注册（提交 WebAuthn 响应）。

        对应 POST /core/settings/passkey/register/finish。接收 begin 接口返回的
        challenge 经浏览器 WebAuthn API 处理后的 attestation 响应，完成注册。

        Args:
            credential: WebAuthn 注册响应（通常为序列化后的 JSON 字符串）。
        """
        require_write()
        client = await get_client()
        return await client.post("/core/settings/passkey/register/finish", {
            "credential": credential,
        })

    @mcp.tool()
    async def system_passkey_delete(
        id: Annotated[str, Field(description="passkey ID")],
        confirm: Annotated[bool, Field(description="删除 passkey 是高危操作，必须传 true")] = False,
    ) -> dict:
        """⚠️高危 [系统] 删除已注册的 Passkey。

        对应 DELETE /core/settings/passkey/{id}。删除后该 passkey 无法再登录。
        必须显式传 confirm=true。

        Args:
            id: passkey ID。
            confirm: 必须为 true 才执行删除。
        """
        require_write()
        if not confirm:
            raise ValueError("删除 passkey 是高危操作，必须显式传 confirm=true。")
        client = await get_client()
        return await client.request("DELETE", f"/core/settings/passkey/{id}")

    @mcp.tool()
    async def system_api_key_generate() -> dict:
        """⚠️写操作 [系统] 生成新的 API 接口密钥。

        对应 POST /core/settings/api/config/generate/key。返回新 API key，
        会替换旧 key（旧 key 立即失效，本 MCP server 配置的 key 可能也需要同步更新）。
        """
        require_write()
        client = await get_client()
        return await client.post("/core/settings/api/config/generate/key", {})

    @mcp.tool()
    async def system_api_config_update(
        api_interface_status: Annotated[str, Field(default="", description="接口开关：Enable / Disable")] = "",
        api_key: Annotated[str, Field(default="", description="API 密钥")] = "",
        api_key_validity_time: Annotated[str, Field(default="", description="密钥有效期（分钟，字符串）")] = "",
        ip_white_list: Annotated[str, Field(default="", description="IP 白名单，逗号分隔")] = "",
    ) -> dict:
        """⚠️写操作 [系统] 更新 API 接口配置（开关 / 密钥 / 白名单）。

        对应 POST /core/settings/api/config/update（dto.ApiInterfaceConfig）。

        Args:
            api_interface_status: 接口启用状态 Enable/Disable。
            api_key: API 密钥。
            api_key_validity_time: 密钥有效期（分钟）。
            ip_white_list: IP 白名单，逗号分隔。
        """
        require_write()
        client = await get_client()
        return await client.post("/core/settings/api/config/update", {
            "apiInterfaceStatus": api_interface_status,
            "apiKey": api_key,
            "apiKeyValidityTime": api_key_validity_time,
            "ipWhiteList": ip_white_list,
        })

    # ================================================================
    # 终端 / 本地 SSH 连接
    # ================================================================

    @mcp.tool()
    async def system_terminal_get() -> dict:
        """[系统] 获取面板终端设置（字体 / 颜色 / 行为）。读操作。

        对应 POST /core/settings/terminal/search（返回 dto.TerminalInfo）。
        """
        client = await get_client()
        return await client.post("/core/settings/terminal/search", {})

    @mcp.tool()
    async def system_terminal_update(
        font_family: Annotated[str, Field(default="", description="字体族")] = "",
        font_size: Annotated[str, Field(default="", description="字号（字符串）")] = "",
        background_color: Annotated[str, Field(default="", description="背景色")] = "",
        foreground_color: Annotated[str, Field(default="", description="前景色")] = "",
        line_height: Annotated[str, Field(default="", description="行高")] = "",
        letter_spacing: Annotated[str, Field(default="", description="字间距")] = "",
        cursor_style: Annotated[str, Field(default="", description="光标样式")] = "",
        cursor_blink: Annotated[str, Field(default="", description="光标闪烁 Enable/Disable")] = "",
        scrollback: Annotated[str, Field(default="", description="回滚行数")] = "",
        scroll_sensitivity: Annotated[str, Field(default="", description="滚动灵敏度")] = "",
    ) -> dict:
        """⚠️写操作 [系统] 更新面板终端外观与行为设置。

        对应 POST /core/settings/terminal/update（dto.TerminalInfo）。所有字段为字符串。

        Args:
            font_family: 字体族。
            font_size: 字号。
            background_color: 背景色。
            foreground_color: 前景色。
            line_height: 行高。
            letter_spacing: 字间距。
            cursor_style: 光标样式。
            cursor_blink: 光标是否闪烁。
            scrollback: 回滚行数。
            scroll_sensitivity: 滚动灵敏度。
        """
        require_write()
        client = await get_client()
        return await client.post("/core/settings/terminal/update", {
            "fontFamily": font_family,
            "fontSize": font_size,
            "backgroundColor": background_color,
            "foregroundColor": foreground_color,
            "lineHeight": line_height,
            "letterSpacing": letter_spacing,
            "cursorStyle": cursor_style,
            "cursorBlink": cursor_blink,
            "scrollback": scrollback,
            "scrollSensitivity": scroll_sensitivity,
        })

    @mcp.tool()
    async def system_ssh_conn_get() -> dict:
        """[系统] 获取本地 SSH 连接配置。读操作。

        对应 GET /settings/ssh/conn（返回 dto.SSHConnData）。
        """
        client = await get_client()
        return await client.get("/settings/ssh/conn")

    @mcp.tool()
    async def system_ssh_check() -> dict:
        """[系统] 检查本地 SSH 连接信息是否可用。读操作。

        对应 POST /settings/ssh/check/info（返回 boolean）。
        """
        client = await get_client()
        return await client.post("/settings/ssh/check/info", {})

    @mcp.tool()
    async def system_ssh_save() -> dict:
        """⚠️写操作 [系统] 保存本地 SSH 连接信息。

        对应 POST /settings/ssh。保存后面板终端 / 远程连接功能会复用该连接配置。
        """
        require_write()
        client = await get_client()
        return await client.post("/settings/ssh", {})

    @mcp.tool()
    async def system_ssh_default_conn(
        default_conn: Annotated[str, Field(description="默认连接方式，如 password / key")] = "",
        with_reset: Annotated[bool, Field(default=False, description="是否同时重置已有配置")] = False,
    ) -> dict:
        """⚠️写操作 [系统] 设置默认 SSH 连接方式。

        对应 POST /settings/ssh/conn/default（dto.SSHDefaultConn）。

        Args:
            default_conn: 默认连接方式（password / key）。
            with_reset: 是否重置现有连接配置。
        """
        require_write()
        client = await get_client()
        return await client.post("/settings/ssh/conn/default", {
            "defaultConn": default_conn,
            "withReset": with_reset,
        })

    # ================================================================
    # 系统升级（1Panel 自身版本升级）
    # ================================================================

    @mcp.tool()
    async def system_upgrade_info() -> dict:
        """[系统] 获取升级信息（当前版本 / 最新版本 / 是否可升级）。读操作。

        对应 GET /core/settings/upgrade（返回 dto.UpgradeInfo）。
        """
        client = await get_client()
        return await client.get("/core/settings/upgrade")

    @mcp.tool()
    async def system_upgrade_releases() -> dict:
        """[系统] 获取可升级的 release 版本列表。读操作。

        对应 GET /core/settings/upgrade/releases（返回 dto.ReleasesNotes 数组）。
        """
        client = await get_client()
        return await client.get("/core/settings/upgrade/releases")

    @mcp.tool()
    async def system_upgrade(
        version: Annotated[str, Field(description="目标版本号，如 v2.0.0")],
        confirm: Annotated[bool, Field(description="升级面板是高危操作，必须传 true")] = False,
    ) -> dict:
        """⚠️高危 [系统] 升级 1Panel 到指定版本。

        对应 POST /core/settings/upgrade（dto.Upgrade）。
        升级期间面板会重启，期间服务短暂不可用，升级失败可能损坏面板。
        必须显式传 confirm=true。

        Args:
            version: 目标版本号（参考 system_upgrade_releases 返回）。
            confirm: 必须为 true 才执行升级。
        """
        require_write()
        if not confirm:
            raise ValueError("升级 1Panel 是高危操作，必须显式传 confirm=true。")
        client = await get_client()
        return await client.post("/core/settings/upgrade", {"version": version})

    @mcp.tool()
    async def system_upgrade_notes(
        version: Annotated[str, Field(description="目标版本号，查询该版本的升级日志")],
    ) -> dict:
        """[系统] 查询指定版本的升级日志 / Release Notes。读操作。

        对应 POST /core/settings/upgrade/notes（dto.Upgrade，返回该版本 changelog）。

        Args:
            version: 版本号。
        """
        client = await get_client()
        return await client.post("/core/settings/upgrade/notes", {"version": version})

    # ================================================================
    # 系统快照（snapshot：全量备份 / 灾难恢复）
    # ================================================================

    @mcp.tool()
    async def system_snapshot_search(
        info: Annotated[str, Field(default="", description="名称 / 描述模糊匹配")] = "",
        page: Annotated[int, Field(ge=1, description="页码")] = 1,
        page_size: Annotated[int, Field(ge=1, le=500, description="每页数量")] = 100,
        order_by: Annotated[SnapshotOrderBy, Field(description="排序字段：name / createdAt")] = "createdAt",
        order: Annotated[Order, Field(description="排序方向")] = "descending",
    ) -> dict:
        """[系统] 分页查询系统快照列表。读操作。

        对应 POST /settings/snapshot/search（dto.PageSnapshot）。
        返回快照的 id / name / 版本 / 大小 / 状态 / 描述等。

        Args:
            info: 名称或描述模糊匹配。
            page: 页码。
            page_size: 每页数量。
            order_by: 排序字段，仅支持 name / createdAt。
            order: 排序方向。
        """
        client = await get_client()
        body = {
            "page": page,
            "pageSize": page_size,
            "orderBy": order_by,
            "order": order,
        }
        if info:
            body["info"] = info
        return await client.post("/settings/snapshot/search", body)

    @mcp.tool()
    async def system_snapshot_load() -> dict:
        """[系统] 获取创建快照所需的源数据（备份账号 / 目录树）。读操作。

        对应 GET /settings/snapshot/load（返回 dto.SnapshotData）。
        创建快照前调用此接口拿到备份账号列表与目录树结构。
        """
        client = await get_client()
        return await client.get("/settings/snapshot/load")

    @mcp.tool()
    async def system_snapshot_create(
        download_account_id: Annotated[int, Field(description="快照上传目标备份账号 ID")],
        source_account_ids: Annotated[str, Field(description="源备份账号 ID 列表，逗号分隔，至少一个")],
        name: Annotated[str, Field(default="", description="快照名称，留空自动生成")] = "",
        description: Annotated[str, Field(default="", max_length=256, description="快照描述")] = "",
        panel_data: Annotated[Optional[list[DataTree]], Field(default=None, description="面板数据目录勾选项")] = None,
        app_data: Annotated[Optional[list[DataTree]], Field(default=None, description="应用数据目录勾选项")] = None,
        backup_data: Annotated[Optional[list[DataTree]], Field(default=None, description="本地备份目录勾选项")] = None,
        ignore_files: Annotated[Optional[list[str]], Field(default=None, description="要忽略的文件 / 目录路径列表")] = None,
        with_monitor_data: Annotated[bool, Field(default=False, description="是否包含监控数据")] = False,
        with_operation_log: Annotated[bool, Field(default=False, description="是否包含操作日志")] = False,
        with_login_log: Annotated[bool, Field(default=False, description="是否包含登录日志")] = False,
        with_system_log: Annotated[bool, Field(default=False, description="是否包含系统日志")] = False,
        with_task_log: Annotated[bool, Field(default=False, description="是否包含任务日志")] = False,
        with_docker_conf: Annotated[bool, Field(default=False, description="是否包含 Docker 配置")] = False,
        timeout: Annotated[Optional[int], Field(default=None, ge=0, description="超时秒数")] = None,
        secret: Annotated[str, Field(default="", description="加密密钥（可选，加密快照）")] = "",
    ) -> dict:
        """⚠️高危 [系统] 创建系统快照（全量备份）。

        对应 POST /settings/snapshot（dto.SnapshotCreate）。快照是面板级全量备份，
        创建耗时较长（后台异步执行），可通过 system_snapshot_search 查进度。
        此操作占用磁盘 / 备份账号存储，且可能锁定部分资源，故归为高危，需 confirm。

        Args:
            download_account_id: 快照上传的目标备份账号 ID。
            source_account_ids: 源备份账号 ID 列表（逗号分隔字符串）。
            name: 快照名称。
            description: 快照描述。
            panel_data: 面板数据目录勾选项。
            app_data: 应用数据目录勾选项。
            backup_data: 本地备份目录勾选项。
            ignore_files: 要忽略的文件 / 目录路径。
            with_monitor_data: 是否备份监控数据。
            with_operation_log: 是否备份操作日志。
            with_login_log: 是否备份登录日志。
            with_system_log: 是否备份系统日志。
            with_task_log: 是否备份任务日志。
            with_docker_conf: 是否备份 Docker 配置。
            timeout: 快照超时秒数。
            secret: 快照加密密钥（可选）。
        """
        require_write()
        client = await get_client()
        body: dict[str, Any] = {
            "downloadAccountID": download_account_id,
            "sourceAccountIDs": source_account_ids,
            "name": name,
            "description": description,
            "ignoreFiles": ignore_files or [],
            "withMonitorData": with_monitor_data,
            "withOperationLog": with_operation_log,
            "withLoginLog": with_login_log,
            "withSystemLog": with_system_log,
            "withTaskLog": with_task_log,
            "withDockerConf": with_docker_conf,
            "secret": secret,
            "panelData": [_datatree_to_dict(t) for t in (panel_data or [])],
            "appData": [_datatree_to_dict(t) for t in (app_data or [])],
            "backupData": [_datatree_to_dict(t) for t in (backup_data or [])],
        }
        if timeout is not None:
            body["timeout"] = timeout
        return await client.post("/settings/snapshot", body)

    @mcp.tool()
    async def system_snapshot_delete(
        ids: Annotated[list[int], Field(description="要删除的快照 ID 列表")],
        delete_with_file: Annotated[bool, Field(default=True, description="是否同时删除远端备份文件")] = True,
        confirm: Annotated[bool, Field(description="删除快照是高危操作，必须传 true")] = False,
    ) -> dict:
        """⚠️高危 [系统] 批量删除系统快照。

        对应 POST /settings/snapshot/del（dto.SnapshotBatchDelete）。
        delete_with_file=true 时会同时删除备份账号里的快照文件，不可恢复。
        必须显式传 confirm=true。

        Args:
            ids: 快照 ID 列表。
            delete_with_file: 是否同时删除远端备份文件。
            confirm: 必须为 true 才执行删除。
        """
        require_write()
        if not confirm:
            raise ValueError("删除快照是高危操作，必须显式传 confirm=true。")
        client = await get_client()
        return await client.post("/settings/snapshot/del", {
            "ids": ids,
            "deleteWithFile": delete_with_file,
        })

    @mcp.tool()
    async def system_snapshot_description_update(
        id: Annotated[int, Field(description="快照 ID")],
        description: Annotated[str, Field(default="", max_length=256, description="新描述")] = "",
    ) -> dict:
        """⚠️写操作 [系统] 更新快照描述。

        对应 POST /settings/snapshot/description/update（dto.UpdateDescription）。

        Args:
            id: 快照 ID。
            description: 新描述（最长 256 字符）。
        """
        require_write()
        client = await get_client()
        return await client.post("/settings/snapshot/description/update", {
            "id": id,
            "description": description,
        })

    @mcp.tool()
    async def system_snapshot_import(
        names: Annotated[list[str], Field(description="要导入的快照文件名列表")],
        backup_account_id: Annotated[int, Field(description="快照所在备份账号 ID")] = 0,
        description: Annotated[str, Field(default="", max_length=256, description="导入后的描述")] = "",
    ) -> dict:
        """⚠️写操作 [系统] 从备份账号导入快照记录。

        对应 POST /settings/snapshot/import（dto.SnapshotImport）。
        用于把备份账号里已存在的快照文件纳入面板管理。

        Args:
            names: 快照文件名列表。
            backup_account_id: 备份账号 ID。
            description: 导入后快照的描述。
        """
        require_write()
        client = await get_client()
        return await client.post("/settings/snapshot/import", {
            "names": names,
            "backupAccountID": backup_account_id,
            "description": description,
        })

    @mcp.tool()
    async def system_snapshot_recover(
        id: Annotated[int, Field(description="快照 ID")],
        secret: Annotated[str, Field(default="", description="快照加密密钥（加密快照必填）")] = "",
        re_download: Annotated[bool, Field(default=False, description="是否重新从备份账号下载快照")] = False,
        is_new: Annotated[bool, Field(default=False, description="是否作为新快照恢复（不影响原记录）")] = False,
        confirm: Annotated[bool, Field(description="恢复快照是高危操作，必须传 true")] = False,
    ) -> dict:
        """⚠️高危 [系统] 从快照恢复系统（灾难恢复）。

        对应 POST /settings/snapshot/recover（dto.SnapshotRecover）。
        恢复会覆盖当前面板配置 / 数据，耗时较长，期间面板不可用，是极高危操作。
        必须显式传 confirm=true。

        Args:
            id: 快照 ID。
            secret: 加密快照的密钥。
            re_download: 是否重新下载快照文件。
            is_new: 是否作为新快照恢复（保留原快照记录）。
            confirm: 必须为 true 才执行恢复。
        """
        require_write()
        if not confirm:
            raise ValueError("从快照恢复系统是高危操作，必须显式传 confirm=true。")
        client = await get_client()
        return await client.post("/settings/snapshot/recover", {
            "id": id,
            "secret": secret,
            "reDownload": re_download,
            "isNew": is_new,
        })

    @mcp.tool()
    async def system_snapshot_rollback(
        id: Annotated[int, Field(description="快照 ID")],
        secret: Annotated[str, Field(default="", description="快照加密密钥（加密快照必填）")] = "",
        re_download: Annotated[bool, Field(default=False, description="是否重新下载快照")] = False,
        is_new: Annotated[bool, Field(default=False, description="是否作为新快照回滚")] = False,
        confirm: Annotated[bool, Field(description="回滚快照是高危操作，必须传 true")] = False,
    ) -> dict:
        """⚠️高危 [系统] 回滚到指定快照。

        对应 POST /settings/snapshot/rollback（dto.SnapshotRecover）。
        回滚会撤销恢复操作，恢复到回滚前的状态，与 recover 互为逆向。
        必须显式传 confirm=true。

        Args:
            id: 快照 ID。
            secret: 加密快照的密钥。
            re_download: 是否重新下载快照。
            is_new: 是否作为新快照回滚。
            confirm: 必须为 true 才执行回滚。
        """
        require_write()
        if not confirm:
            raise ValueError("回滚快照是高危操作，必须显式传 confirm=true。")
        client = await get_client()
        return await client.post("/settings/snapshot/rollback", {
            "id": id,
            "secret": secret,
            "reDownload": re_download,
            "isNew": is_new,
        })

    @mcp.tool()
    async def system_snapshot_recreate(
        id: Annotated[int, Field(description="失败的快照 ID")],
    ) -> dict:
        """⚠️写操作 [系统] 重新创建（重试）失败的快照。

        对应 POST /settings/snapshot/recreate（dto.OperateByID）。
        仅对创建失败的快照有效，会基于原配置重试。

        Args:
            id: 快照 ID。
        """
        require_write()
        client = await get_client()
        return await client.post("/settings/snapshot/recreate", {"id": id})
