"""数据库管理模块（对应 openapi.json 的 Database / Database Mysql /
Database PostgreSQL / Database Redis / Database Common tag，共 42 个端点）。

照 container.py 黄金范式实现：
1. 工具名：<module>_<object>_<action>（database_mysql_list / database_pg_create / ...）
2. description：结构化，[数据库] 开头，写操作加 ⚠️，便于 mcphub 向量搜索召回
3. 入参用 Annotated[T, Field(description=...)]，枚举用 Literal
4. handler 用 `await get_client()` 拿共享客户端，调 .search() / .post() / .get()
5. 写操作开头调 require_write()，高危（delete）额外加 confirm 参数

模块结构（按 1Panel 的 tag 分组）：
- 通用（Database / Database Common）：远程数据库实例注册的增删改查、连接信息、状态、配置
- MySQL（Database Mysql）：MySQL/MariaDB 数据库与用户/权限管理、运行时变量
- PostgreSQL（Database PostgreSQL）：PG 数据库与用户/权限管理
- Redis（Database Redis）：Redis 配置、持久化、密码、状态

接口来源：references/openapi.json 的 /databases* 路径，basePath /api/v2。
注意：本模块的 orderBy 枚举值为 name/createdAt（驼峰，与 container 一致）。
"""

from __future__ import annotations

from typing import Annotated, Literal, Optional

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..client import get_client
from ..safety import require_write


# ---- 枚举（严格按 openapi.json 的 enum 定义，传错会被 1Panel 拒绝）----

# 搜索类接口的排序字段（dto.MysqlDBSearch / dto.DatabaseSearch / dto.PostgresqlDBSearch）
DBOrderBy = Literal["name", "createdAt"]

# 通用数据库类型（dto.ChangeDBInfo / dto.DBConfUpdateByFile）
DbType = Literal[
    "mysql",
    "mariadb",
    "postgresql",
    "redis",
    "mysql-cluster",
    "postgresql-cluster",
    "redis-cluster",
]
# MySQL/MariaDB 系
MysqlType = Literal["mysql", "mariadb", "mysql-cluster"]
# PostgreSQL 系
PgType = Literal["postgresql", "postgresql-cluster"]
# Redis 系
RedisDbType = Literal["redis", "redis-cluster"]


def register(mcp: FastMCP) -> None:

    # ================================================================
    # 通用（Database / Database Common tag）
    # 远程数据库实例的注册、连接信息、运行时状态、配置文件读写
    # ================================================================

    @mcp.tool()
    async def database_list(
        type: Annotated[Optional[str], Field(description="按数据库类型过滤，如 mysql/postgresql/redis；留空返回全部")] = None,
        info: Annotated[str, Field(description="模糊匹配（库名/实例名等）")] = "",
        page: Annotated[int, Field(ge=1, description="页码，从 1 开始")] = 1,
        page_size: Annotated[int, Field(ge=1, le=500, description="每页数量")] = 100,
        order_by: Annotated[DBOrderBy, Field(description="排序字段：name/createdAt")] = "createdAt",
        order: Annotated[Literal["null", "ascending", "descending"], Field(description="排序方向")] = "descending",
    ) -> dict:
        """[数据库] 列出/搜索已注册的数据库实例（远程 + 本地）。读操作。

        分页返回 1Panel 已纳管的所有数据库实例（按 type 区分 mysql/pg/redis 等）。
        对应 POST /databases/db/search，请求体 dto.DatabaseSearch。

        Args:
            type: 数据库类型过滤，留空返回全部类型。
            info: 模糊匹配关键字。
            page: 页码。
            page_size: 每页数量。
            order_by: 排序字段：name/createdAt。
            order: 排序方向。
        """
        client = await get_client()
        body = {
            "page": page,
            "pageSize": page_size,
            "orderBy": order_by,
            "order": order,
            "info": info,
            "type": type or "",
        }
        return await client.post("/databases/db/search", body)

    @mcp.tool()
    async def database_get(
        name: Annotated[str, Field(description="数据库实例名称")],
    ) -> dict:
        """[数据库] 查看指定数据库实例的详情（连接信息、版本、SSL 配置等）。读操作。

        返回 DatabaseInfo（地址、端口、用户名、版本、SSL 证书、初始库等）。
        对应 GET /databases/db/:name。

        Args:
            name: 数据库实例名称。
        """
        client = await get_client()
        return await client.get(f"/databases/db/{name}")

    @mcp.tool()
    async def database_db_list(
        type: Annotated[str, Field(description="数据库类型，如 mysql/postgresql/redis/mysql-cluster")],
    ) -> dict:
        """[数据库] 列出指定类型的数据库实例选项（含版本、地址）。读操作。

        返回 DatabaseOption 数组，常用于前端下拉选择（部署数据库时选实例）。
        对应 GET /databases/db/list/:type。

        Args:
            type: 数据库类型字符串（mysql/mariadb/postgresql/redis 等）。
        """
        client = await get_client()
        return await client.get(f"/databases/db/list/{type}")

    @mcp.tool()
    async def database_db_items(
        type: Annotated[str, Field(description="数据库类型")],
    ) -> dict:
        """[数据库] 列出指定类型的数据库实例条目（id/name/from）。读操作。

        返回 DatabaseItem 数组，比 database_db_list 更轻量，仅含 id/name/from。
        对应 GET /databases/db/item/:type。

        Args:
            type: 数据库类型。
        """
        client = await get_client()
        return await client.get(f"/databases/db/item/{type}")

    @mcp.tool()
    async def database_info(
        name: Annotated[str, Field(description="数据库实例名称（如 mysql、postgresql）")],
        type: Annotated[DbType, Field(description="数据库类型")],
    ) -> dict:
        """[数据库] 加载数据库实例的基础信息（容器名、服务名、端口）。读操作。

        返回 DBBaseInfo（containerName/name/port），用于判断实例归属容器。
        对应 POST /databases/common/info，请求体 dto.OperationWithNameAndType。

        Args:
            name: 数据库实例名称。
            type: 数据库类型。
        """
        client = await get_client()
        return await client.post("/databases/common/info", {"name": name, "type": type})

    @mcp.tool()
    async def database_status(
        name: Annotated[str, Field(description="数据库实例名称")],
        type: Annotated[DbType, Field(description="数据库类型")],
    ) -> dict:
        """[数据库] 加载数据库运行状态信息。读操作。

        MySQL 系返回 MysqlStatus（连接数、线程、缓冲池等运行时指标），
        Redis 系建议改用 database_redis_status。对应 POST /databases/status，
        请求体 dto.OperationWithNameAndType。

        Args:
            name: 数据库实例名称。
            type: 数据库类型。
        """
        client = await get_client()
        return await client.post("/databases/status", {"name": name, "type": type})

    @mcp.tool()
    async def database_conf(
        name: Annotated[str, Field(description="数据库实例名称")],
        type: Annotated[DbType, Field(description="数据库类型")],
    ) -> dict:
        """[数据库] 加载数据库配置文件内容。读操作。

        返回实例主配置文件的文本内容（my.cnf / postgresql.conf / redis.conf 等）。
        对应 POST /databases/common/load/file，请求体 dto.OperationWithNameAndType。

        Args:
            name: 数据库实例名称。
            type: 数据库类型。
        """
        client = await get_client()
        return await client.post("/databases/common/load/file", {"name": name, "type": type})

    @mcp.tool()
    async def database_conf_update(
        database: Annotated[str, Field(description="数据库实例名称")],
        type: Annotated[DbType, Field(description="数据库类型")],
        file: Annotated[str, Field(description="配置文件的完整新内容")],
    ) -> dict:
        """⚠️写操作 [数据库] 通过上传文件内容更新数据库配置文件。

        直接覆盖实例主配置文件，写错可能导致实例无法启动。对应
        POST /databases/common/update/conf，请求体 dto.DBConfUpdateByFile。
        建议先用 database_conf 读取当前内容做备份再写。

        Args:
            database: 数据库实例名称。
            type: 数据库类型。
            file: 新的配置文件文本。
        """
        require_write()
        client = await get_client()
        return await client.post("/databases/common/update/conf", {
            "database": database, "type": type, "file": file,
        })

    @mcp.tool()
    async def database_create(
        name: Annotated[str, Field(description="远程数据库实例名称（maxLength 256）")],
        type: Annotated[DbType, Field(description="数据库类型")],
        username: Annotated[str, Field(description="连接用户名")],
        version: Annotated[str, Field(description="数据库版本，如 8.0/16/7.x")],
        from_: Annotated[Literal["local", "remote"], Field(description="来源：local 本地或 remote 外部（参数名 from_ 因 from 是 Python 关键字，请求体映射为 from）")] = "remote",
        address: Annotated[str, Field(description="远程地址（host:port 或仅 host）")] = "",
        port: Annotated[int, Field(description="端口，如 3306/5432/6379", ge=1, le=65535)] = 0,
        password: Annotated[str, Field(description="连接密码")] = "",
        description: Annotated[str, Field(description="描述")] = "",
        ssl: Annotated[bool, Field(description="是否启用 SSL")] = False,
        skip_verify: Annotated[bool, Field(description="SSL 是否跳过证书校验")] = False,
        root_cert: Annotated[str, Field(description="CA 证书内容")] = "",
        client_cert: Annotated[str, Field(description="客户端证书内容")] = "",
        client_key: Annotated[str, Field(description="客户端私钥内容")] = "",
        timeout: Annotated[int, Field(description="连接超时秒", ge=0)] = 0,
        initial_db: Annotated[str, Field(description="初始库（建表用）")] = "",
    ) -> dict:
        """⚠️写操作 [数据库] 注册一个远程数据库实例到 1Panel（纳管）。

        把外部/本地的数据库实例接入 1Panel 进行纳管。对应 POST /databases/db，
        请求体 dto.DatabaseCreate。注册前可先调 database_check 校验连接。

        Args:
            name: 实例名称。
            type: 数据库类型。
            username: 连接用户名。
            version: 数据库版本。
            from_: 来源 local/remote（参数名加下划线是因为 from 是 Python 关键字）。
            address: 远程地址。
            port: 端口。
            password: 密码。
            description: 描述。
            ssl: 是否启用 SSL。
            skip_verify: 是否跳过证书校验。
            root_cert: CA 证书。
            client_cert: 客户端证书。
            client_key: 客户端私钥。
            timeout: 连接超时。
            initial_db: 初始库。
        """
        require_write()
        client = await get_client()
        body = {
            "name": name, "type": type, "username": username, "version": version,
            "from": from_, "description": description, "ssl": ssl,
            "skipVerify": skip_verify, "timeout": timeout,
        }
        # 仅在非默认/非空时带上的可选字段
        if address:
            body["address"] = address
        if port:
            body["port"] = port
        if password:
            body["password"] = password
        if root_cert:
            body["rootCert"] = root_cert
        if client_cert:
            body["clientCert"] = client_cert
        if client_key:
            body["clientKey"] = client_key
        if initial_db:
            body["initialDB"] = initial_db
        return await client.post("/databases/db", body)

    @mcp.tool()
    async def database_check(
        name: Annotated[str, Field(description="数据库实例名称（maxLength 256）")],
        type: Annotated[DbType, Field(description="数据库类型")],
        username: Annotated[str, Field(description="连接用户名")],
        version: Annotated[str, Field(description="数据库版本")],
        from_: Annotated[Literal["local", "remote"], Field(description="来源 local/remote（参数名 from_，请求体映射为 from）")] = "remote",
        address: Annotated[str, Field(description="远程地址")] = "",
        port: Annotated[int, Field(description="端口", ge=1, le=65535)] = 0,
        password: Annotated[str, Field(description="密码")] = "",
        ssl: Annotated[bool, Field(description="是否启用 SSL")] = False,
    ) -> dict:
        """⚠️写操作 [数据库] 测试数据库连接（注册前校验）。

        用提供的连接信息测试能否连上目标数据库，不落库。对应
        POST /databases/db/check，请求体同 dto.DatabaseCreate。

        Args:
            name: 实例名称。
            type: 数据库类型。
            username: 用户名。
            version: 版本。
            from_: 来源 local/remote。
            address: 地址。
            port: 端口。
            password: 密码。
            ssl: 是否启用 SSL。
        """
        require_write()
        client = await get_client()
        body = {
            "name": name, "type": type, "username": username, "version": version,
            "from": from_, "ssl": ssl,
        }
        if address:
            body["address"] = address
        if port:
            body["port"] = port
        if password:
            body["password"] = password
        return await client.post("/databases/db/check", body)

    @mcp.tool()
    async def database_update(
        id: Annotated[int, Field(description="数据库实例 ID")],
        type: Annotated[DbType, Field(description="数据库类型")],
        username: Annotated[str, Field(description="连接用户名")],
        version: Annotated[str, Field(description="数据库版本")],
        address: Annotated[str, Field(description="远程地址")] = "",
        port: Annotated[int, Field(description="端口", ge=1, le=65535)] = 0,
        password: Annotated[str, Field(description="密码（不修改留空）")] = "",
        description: Annotated[str, Field(description="描述")] = "",
        ssl: Annotated[bool, Field(description="是否启用 SSL")] = False,
        skip_verify: Annotated[bool, Field(description="是否跳过证书校验")] = False,
        root_cert: Annotated[str, Field(description="CA 证书")] = "",
        client_cert: Annotated[str, Field(description="客户端证书")] = "",
        client_key: Annotated[str, Field(description="客户端私钥")] = "",
        timeout: Annotated[int, Field(description="连接超时秒", ge=0)] = 0,
        initial_db: Annotated[str, Field(description="初始库")] = "",
    ) -> dict:
        """⚠️写操作 [数据库] 更新已纳管数据库实例的连接信息。

        修改实例的地址/端口/凭证/SSL 等。对应 POST /databases/db/update，
        请求体 dto.DatabaseUpdate。

        Args:
            id: 实例 ID。
            type: 数据库类型。
            username: 用户名。
            version: 版本。
            address: 远程地址。
            port: 端口。
            password: 密码（不修改留空）。
            description: 描述。
            ssl: 是否启用 SSL。
            skip_verify: 是否跳过证书校验。
            root_cert: CA 证书。
            client_cert: 客户端证书。
            client_key: 客户端私钥。
            timeout: 连接超时。
            initial_db: 初始库。
        """
        require_write()
        client = await get_client()
        body: dict = {
            "id": id, "type": type, "username": username, "version": version,
            "description": description, "ssl": ssl, "skipVerify": skip_verify,
            "timeout": timeout,
        }
        if address:
            body["address"] = address
        if port:
            body["port"] = port
        if password:
            body["password"] = password
        if root_cert:
            body["rootCert"] = root_cert
        if client_cert:
            body["clientCert"] = client_cert
        if client_key:
            body["clientKey"] = client_key
        if initial_db:
            body["initialDB"] = initial_db
        return await client.post("/databases/db/update", body)

    @mcp.tool()
    async def database_delete_check(
        id: Annotated[int, Field(description="数据库实例 ID")],
    ) -> dict:
        """[数据库] 删除前校验远程数据库实例（检查是否有关联资源）。读操作。

        删除前预检查，返回是否可删/受影响的资源。对应
        POST /databases/db/del/check，请求体 dto.OperateByID。

        Args:
            id: 实例 ID。
        """
        client = await get_client()
        return await client.post("/databases/db/del/check", {"id": id})

    @mcp.tool()
    async def database_delete(
        id: Annotated[int, Field(description="数据库实例 ID")],
        confirm: Annotated[bool, Field(description="删除是高危操作，必须传 true")] = False,
        delete_backup: Annotated[bool, Field(description="是否同时删除关联备份记录")] = False,
        force_delete: Annotated[bool, Field(description="是否强制删除（忽略校验失败）")] = False,
    ) -> dict:
        """⚠️高危 [数据库] 删除（解绑）已纳管的远程数据库实例。

        将实例从 1Panel 移除（不会真正删除远端的数据）。对应
        POST /databases/db/del，请求体 dto.DatabaseDelete。建议先调
        database_delete_check 预检查。必须显式传 confirm=true。

        Args:
            id: 实例 ID。
            confirm: 必须为 true 才执行。
            delete_backup: 是否同时删除关联的备份记录。
            force_delete: 是否强制删除。
        """
        require_write()
        if not confirm:
            raise ValueError("删除数据库实例是高危操作，必须显式传 confirm=true。")
        client = await get_client()
        return await client.post("/databases/db/del", {
            "id": id,
            "deleteBackup": delete_backup,
            "forceDelete": force_delete,
        })

    # ================================================================
    # MySQL / MariaDB（Database Mysql tag）
    # 数据库（schema）+ 用户/权限管理 + 运行时变量
    # ================================================================

    @mcp.tool()
    async def database_mysql_list(
        database: Annotated[str, Field(description="MySQL 实例名称（database 字段，如 mysql）")] = "",
        info: Annotated[str, Field(description="模糊匹配库名")] = "",
        page: Annotated[int, Field(ge=1, description="页码")] = 1,
        page_size: Annotated[int, Field(ge=1, le=500, description="每页数量")] = 100,
        order_by: Annotated[DBOrderBy, Field(description="排序字段：name/createdAt")] = "createdAt",
        order: Annotated[Literal["null", "ascending", "descending"], Field(description="排序方向")] = "descending",
    ) -> dict:
        """[MySQL] 列出/搜索 MySQL/MariaDB 的库（schema）。读操作。

        分页返回某个 MySQL 实例下管理的所有数据库（schema）。对应
        POST /databases/search，请求体 dto.MysqlDBSearch。

        Args:
            database: MySQL 实例名称（必填字段，留空 1Panel 会用默认实例）。
            info: 库名模糊匹配。
            page: 页码。
            page_size: 每页数量。
            order_by: 排序字段：name/createdAt。
            order: 排序方向。
        """
        client = await get_client()
        body = {
            "page": page,
            "pageSize": page_size,
            "orderBy": order_by,
            "order": order,
            "database": database,
            "info": info,
        }
        return await client.post("/databases/search", body)

    @mcp.tool()
    async def database_mysql_create(
        name: Annotated[str, Field(description="MySQL 实例名称（database 字段）")],
        database: Annotated[str, Field(description="要创建的库名（schema 名）")],
        username: Annotated[str, Field(description="关联用户名")],
        password: Annotated[str, Field(description="用户密码")],
        permission: Annotated[str, Field(description="权限，如 %（任意主机）或具体 IP")] = "%",
        format: Annotated[str, Field(description="字符集格式，如 utf8mb4（建议先查 database_mysql_format_options）")] = "utf8mb4",
        collation: Annotated[str, Field(description="排序规则，留空则按 format 默认")] = "",
        description: Annotated[str, Field(description="备注")] = "",
        from_: Annotated[Literal["local", "remote"], Field(description="来源 local/remote（参数名 from_ 因 from 是 Python 关键字，请求体映射为 from）")] = "local",
    ) -> dict:
        """⚠️写操作 [MySQL] 在 MySQL 实例下创建库（schema）并绑定用户。

        同时创建库和关联用户（含权限）。对应 POST /databases，请求体
        dto.MysqlDBCreate。from=remote 时为远程实例，from=local 时为本机实例。

        Args:
            name: MySQL 实例名称。
            database: 要创建的库名。
            username: 关联用户名。
            password: 用户密码。
            permission: 访问权限，% 表示任意主机。
            format: 字符集，常用 utf8mb4。
            collation: 排序规则。
            description: 备注。
            from_: 来源 local/remote。
        """
        require_write()
        client = await get_client()
        body = {
            "name": name, "database": database, "username": username,
            "password": password, "permission": permission, "format": format,
            "from": from_, "description": description,
        }
        if collation:
            body["collation"] = collation
        return await client.post("/databases", body)

    @mcp.tool()
    async def database_mysql_delete_check(
        id: Annotated[int, Field(description="库 ID")],
        database: Annotated[str, Field(description="MySQL 实例名称（database 字段）")],
        type: Annotated[MysqlType, Field(description="MySQL 系类型：mysql/mariadb/mysql-cluster")] = "mysql",
    ) -> dict:
        """[MySQL] 删除前校验 MySQL 库（检查关联用户/备份）。读操作。

        删除前预检查。对应 POST /databases/del/check，请求体 dto.MysqlDBDeleteCheck。

        Args:
            id: 库 ID。
            database: MySQL 实例名称。
            type: MySQL 系类型。
        """
        client = await get_client()
        return await client.post("/databases/del/check", {
            "id": id, "database": database, "type": type,
        })

    @mcp.tool()
    async def database_mysql_delete(
        id: Annotated[int, Field(description="库 ID")],
        database: Annotated[str, Field(description="MySQL 实例名称（database 字段）")],
        type: Annotated[MysqlType, Field(description="MySQL 系类型：mysql/mariadb/mysql-cluster")] = "mysql",
        confirm: Annotated[bool, Field(description="删除是高危操作，必须传 true")] = False,
        delete_backup: Annotated[bool, Field(description="是否同时删除该库的备份")] = False,
        force_delete: Annotated[bool, Field(description="是否强制删除")] = False,
    ) -> dict:
        """⚠️高危 [MySQL] 删除 MySQL/MariaDB 的库（schema）及其关联用户。

        删除指定库，会同时清理关联的备份/用户。对应 POST /databases/del，
        请求体 dto.MysqlDBDelete。建议先调 database_mysql_delete_check。
        必须显式传 confirm=true。

        Args:
            id: 库 ID。
            database: MySQL 实例名称。
            type: MySQL 系类型。
            confirm: 必须为 true 才执行。
            delete_backup: 是否同时删除该库的备份。
            force_delete: 是否强制删除。
        """
        require_write()
        if not confirm:
            raise ValueError("删除 MySQL 库是高危操作，必须显式传 confirm=true。")
        client = await get_client()
        return await client.post("/databases/del", {
            "id": id, "database": database, "type": type,
            "deleteBackup": delete_backup, "forceDelete": force_delete,
        })

    @mcp.tool()
    async def database_mysql_password(
        database: Annotated[str, Field(description="MySQL 实例名称（database 字段）")],
        type: Annotated[MysqlType, Field(description="MySQL 系类型")] = "mysql",
        id: Annotated[int, Field(description="库 ID")] = 0,
        from_: Annotated[Literal["local", "remote"], Field(description="来源 local/remote（参数名 from_ 因 from 是 Python 关键字，请求体映射为 from）")] = "local",
        value: Annotated[str, Field(description="新密码")] = "",
    ) -> dict:
        """⚠️写操作 [MySQL] 修改 MySQL 库关联用户的密码。

        对应 POST /databases/change/password，请求体 dto.ChangeDBInfo
        （value 字段为新密码）。

        Args:
            database: MySQL 实例名称。
            type: MySQL 系类型。
            id: 库 ID（用于定位用户）。
            from_: 来源 local/remote。
            value: 新密码。
        """
        require_write()
        client = await get_client()
        body = {
            "database": database, "type": type, "from": from_,
            "value": value,
        }
        if id:
            body["id"] = id
        return await client.post("/databases/change/password", body)

    @mcp.tool()
    async def database_mysql_privileges(
        database: Annotated[str, Field(description="MySQL 实例名称（database 字段）")],
        value: Annotated[str, Field(description="权限字符串，如 %（任意主机）或具体 IP/CIDR")],
        type: Annotated[MysqlType, Field(description="MySQL 系类型")] = "mysql",
        id: Annotated[int, Field(description="库 ID")] = 0,
        from_: Annotated[Literal["local", "remote"], Field(description="来源 local/remote（参数名 from_ 因 from 是 Python 关键字，请求体映射为 from）")] = "local",
    ) -> dict:
        """⚠️写操作 [MySQL] 修改 MySQL 库的访问权限（允许连接的主机）。

        value 通常为主机白名单：%（任意）、具体 IP、CIDR 段。对应
        POST /databases/change/access，请求体 dto.ChangeDBInfo。

        Args:
            database: MySQL 实例名称。
            value: 权限/主机白名单。
            type: MySQL 系类型。
            id: 库 ID。
            from_: 来源 local/remote。
        """
        require_write()
        client = await get_client()
        body = {
            "database": database, "type": type, "from": from_,
            "value": value,
        }
        if id:
            body["id"] = id
        return await client.post("/databases/change/access", body)

    @mcp.tool()
    async def database_mysql_bind(
        database: Annotated[str, Field(description="MySQL 实例名称（database 字段）")],
        db: Annotated[str, Field(description="目标库名（schema）")],
        username: Annotated[str, Field(description="要绑定的用户名")],
        password: Annotated[str, Field(description="用户密码（新建用户时）")] = "",
        permission: Annotated[str, Field(description="访问权限/主机，如 %")] = "%",
    ) -> dict:
        """⚠️写操作 [MySQL] 为 MySQL 库绑定/解绑用户（授权）。

        把用户绑定到指定库并授予权限。对应 POST /databases/bind，
        请求体 dto.BindUser。

        Args:
            database: MySQL 实例名称。
            db: 目标库名。
            username: 用户名。
            password: 密码。
            permission: 主机权限。
        """
        require_write()
        client = await get_client()
        return await client.post("/databases/bind", {
            "database": database, "db": db, "username": username,
            "password": password, "permission": permission,
        })

    @mcp.tool()
    async def database_mysql_load(
        database: Annotated[str, Field(description="MySQL 实例名称（database 字段）")],
        type: Annotated[MysqlType, Field(description="MySQL 系类型")] = "mysql",
        from_: Annotated[Literal["local", "remote"], Field(description="来源 local/remote（参数名 from_ 因 from 是 Python 关键字，请求体映射为 from）")] = "local",
    ) -> dict:
        """⚠️写操作 [MySQL] 从 MySQL 实例加载已存在的库列表（纳管远端库）。

        读取远端实例上已有的库，导入到 1Panel 纳管。对应
        POST /databases/load，请求体 dto.MysqlLoadDB。

        Args:
            database: MySQL 实例名称。
            type: MySQL 系类型。
            from_: 来源 local/remote。
        """
        require_write()
        client = await get_client()
        return await client.post("/databases/load", {
            "database": database, "type": type, "from": from_,
        })

    @mcp.tool()
    async def database_mysql_remote(
        database: Annotated[str, Field(description="MySQL 实例名称（database 字段）")],
        type: Annotated[MysqlType, Field(description="MySQL 系类型")] = "mysql",
        name: Annotated[str, Field(description="库名（可选，定位具体库）")] = "",
    ) -> dict:
        """[MySQL] 加载 MySQL 远程访问配置（白名单、bind-address）。读操作。

        对应 POST /databases/remote，请求体 dto.OperationWithNameAndType。

        Args:
            database: MySQL 实例名称。
            type: MySQL 系类型。
            name: 库名（可选）。
        """
        client = await get_client()
        body: dict = {"database": database, "type": type}
        if name:
            body["name"] = name
        return await client.post("/databases/remote", body)

    @mcp.tool()
    async def database_mysql_variables(
        database: Annotated[str, Field(description="MySQL 实例名称（database 字段）")],
        type: Annotated[MysqlType, Field(description="MySQL 系类型")] = "mysql",
    ) -> dict:
        """[MySQL] 加载 MySQL 运行时变量（SHOW VARIABLES）。读操作。

        对应 POST /databases/variables，请求体 dto.OperationWithNameAndType。

        Args:
            database: MySQL 实例名称。
            type: MySQL 系类型。
        """
        client = await get_client()
        return await client.post("/databases/variables", {
            "database": database, "type": type,
        })

    @mcp.tool()
    async def database_mysql_variables_update(
        database: Annotated[str, Field(description="MySQL 实例名称（database 字段）")],
        type: Annotated[MysqlType, Field(description="MySQL 系类型")] = "mysql",
        variables: Annotated[
            list[dict],
            Field(description="要修改变量的列表，每项形如 {\"param\": \"max_connections\", \"value\": 500}"),
        ] = None,
    ) -> dict:
        """⚠️写操作 [MySQL] 修改 MySQL 运行时变量（SET GLOBAL）。

        批量修改变量。对应 POST /databases/variables/update，请求体
        dto.MysqlVariablesUpdate（variables 是 MysqlVariablesUpdateHelper 数组）。
        ⚠️ 参数调整可能影响性能/稳定性，操作前请确认取值。

        Args:
            database: MySQL 实例名称。
            type: MySQL 系类型。
            variables: 变量列表，每项 {param, value}。
        """
        require_write()
        client = await get_client()
        return await client.post("/databases/variables/update", {
            "database": database,
            "type": type,
            "variables": variables or [],
        })

    @mcp.tool()
    async def database_mysql_description(
        id: Annotated[int, Field(description="库 ID")],
        description: Annotated[str, Field(description="新备注（maxLength 256）", max_length=256)] = "",
    ) -> dict:
        """⚠️写操作 [MySQL] 更新 MySQL 库的备注/描述。

        对应 POST /databases/description/update，请求体 dto.UpdateDescription。

        Args:
            id: 库 ID。
            description: 新备注。
        """
        require_write()
        client = await get_client()
        return await client.post("/databases/description/update", {
            "id": id, "description": description,
        })

    @mcp.tool()
    async def database_mysql_format_options(
        name: Annotated[str, Field(description="MySQL 实例名称（database 字段）")],
    ) -> dict:
        """[MySQL] 加载 MySQL 字符集/排序规则可选项。读操作。

        建库前查询可用的字符集（utf8mb4 等）及其排序规则。对应
        POST /databases/format/options，请求体 dto.OperationWithName。

        Args:
            name: MySQL 实例名称。
        """
        client = await get_client()
        return await client.post("/databases/format/options", {"name": name})

    # ================================================================
    # PostgreSQL（Database PostgreSQL tag）
    # 数据库 + 用户/权限管理
    # ================================================================

    @mcp.tool()
    async def database_pg_list(
        database: Annotated[str, Field(description="PG 实例名称（database 字段）")] = "",
        info: Annotated[str, Field(description="模糊匹配库名")] = "",
        page: Annotated[int, Field(ge=1, description="页码")] = 1,
        page_size: Annotated[int, Field(ge=1, le=500, description="每页数量")] = 100,
        order_by: Annotated[DBOrderBy, Field(description="排序字段：name/createdAt")] = "createdAt",
        order: Annotated[Literal["null", "ascending", "descending"], Field(description="排序方向")] = "descending",
    ) -> dict:
        """[PostgreSQL] 列出/搜索 PostgreSQL 的库。读操作。

        分页返回某个 PG 实例下纳管的所有库。对应 POST /databases/pg/search，
        请求体 dto.PostgresqlDBSearch。

        Args:
            database: PG 实例名称。
            info: 库名模糊匹配。
            page: 页码。
            page_size: 每页数量。
            order_by: 排序字段：name/createdAt。
            order: 排序方向。
        """
        client = await get_client()
        body = {
            "page": page,
            "pageSize": page_size,
            "orderBy": order_by,
            "order": order,
            "database": database,
            "info": info,
        }
        return await client.post("/databases/pg/search", body)

    @mcp.tool()
    async def database_pg_create(
        name: Annotated[str, Field(description="PG 实例名称（database 字段）")],
        database: Annotated[str, Field(description="要创建的库名")],
        username: Annotated[str, Field(description="关联用户名")],
        password: Annotated[str, Field(description="用户密码")],
        from_: Annotated[Literal["local", "remote"], Field(description="来源 local/remote（参数名 from_ 因 from 是 Python 关键字，请求体映射为 from）")] = "local",
        format: Annotated[str, Field(description="编码格式，如 UTF8")] = "",
        description: Annotated[str, Field(description="备注")] = "",
        super_user: Annotated[bool, Field(description="是否授予超级用户权限")] = False,
    ) -> dict:
        """⚠️写操作 [PostgreSQL] 在 PG 实例下创建库并绑定用户。

        同时创建库和关联用户。对应 POST /databases/pg，请求体
        dto.PostgresqlDBCreate。

        Args:
            name: PG 实例名称。
            database: 要创建的库名。
            username: 用户名。
            password: 密码。
            from_: 来源 local/remote。
            format: 编码格式。
            description: 备注。
            super_user: 是否授予超级用户权限。
        """
        require_write()
        client = await get_client()
        body = {
            "name": name, "database": database, "username": username,
            "password": password, "from": from_,
            "superUser": super_user, "description": description,
        }
        if format:
            body["format"] = format
        return await client.post("/databases/pg", body)

    @mcp.tool()
    async def database_pg_delete_check(
        id: Annotated[int, Field(description="库 ID")],
        database: Annotated[str, Field(description="PG 实例名称（database 字段）")],
        type: Annotated[PgType, Field(description="PG 系类型：postgresql/postgresql-cluster")] = "postgresql",
    ) -> dict:
        """[PostgreSQL] 删除前校验 PG 库（检查关联用户/备份）。读操作。

        删除前预检查。对应 POST /databases/pg/del/check，请求体
        dto.PostgresqlDBDeleteCheck。

        Args:
            id: 库 ID。
            database: PG 实例名称。
            type: PG 系类型。
        """
        client = await get_client()
        return await client.post("/databases/pg/del/check", {
            "id": id, "database": database, "type": type,
        })

    @mcp.tool()
    async def database_pg_delete(
        id: Annotated[int, Field(description="库 ID")],
        database: Annotated[str, Field(description="PG 实例名称（database 字段）")],
        type: Annotated[PgType, Field(description="PG 系类型：postgresql/postgresql-cluster")] = "postgresql",
        confirm: Annotated[bool, Field(description="删除是高危操作，必须传 true")] = False,
        delete_backup: Annotated[bool, Field(description="是否同时删除该库的备份")] = False,
        force_delete: Annotated[bool, Field(description="是否强制删除")] = False,
    ) -> dict:
        """⚠️高危 [PostgreSQL] 删除 PostgreSQL 的库及其关联用户。

        删除指定库，会同时清理关联的备份/用户。对应 POST /databases/pg/del，
        请求体 dto.PostgresqlDBDelete。建议先调 database_pg_delete_check。
        必须显式传 confirm=true。

        Args:
            id: 库 ID。
            database: PG 实例名称。
            type: PG 系类型。
            confirm: 必须为 true 才执行。
            delete_backup: 是否同时删除该库的备份。
            force_delete: 是否强制删除。
        """
        require_write()
        if not confirm:
            raise ValueError("删除 PostgreSQL 库是高危操作，必须显式传 confirm=true。")
        client = await get_client()
        return await client.post("/databases/pg/del", {
            "id": id, "database": database, "type": type,
            "deleteBackup": delete_backup, "forceDelete": force_delete,
        })

    @mcp.tool()
    async def database_pg_password(
        database: Annotated[str, Field(description="PG 实例名称（database 字段）")],
        value: Annotated[str, Field(description="新密码")],
        type: Annotated[PgType, Field(description="PG 系类型")] = "postgresql",
        id: Annotated[int, Field(description="库 ID")] = 0,
        from_: Annotated[Literal["local", "remote"], Field(description="来源 local/remote（参数名 from_ 因 from 是 Python 关键字，请求体映射为 from）")] = "local",
    ) -> dict:
        """⚠️写操作 [PostgreSQL] 修改 PG 库关联用户的密码。

        对应 POST /databases/pg/password，请求体 dto.ChangeDBInfo。

        Args:
            database: PG 实例名称。
            value: 新密码。
            type: PG 系类型。
            id: 库 ID。
            from_: 来源 local/remote。
        """
        require_write()
        client = await get_client()
        body = {
            "database": database, "type": type, "from": from_, "value": value,
        }
        if id:
            body["id"] = id
        return await client.post("/databases/pg/password", body)

    @mcp.tool()
    async def database_pg_privileges(
        database: Annotated[str, Field(description="PG 实例名称（database 字段）")],
        value: Annotated[str, Field(description="权限/主机白名单字符串")],
        type: Annotated[PgType, Field(description="PG 系类型")] = "postgresql",
        id: Annotated[int, Field(description="库 ID")] = 0,
        from_: Annotated[Literal["local", "remote"], Field(description="来源 local/remote（参数名 from_ 因 from 是 Python 关键字，请求体映射为 from）")] = "local",
    ) -> dict:
        """⚠️写操作 [PostgreSQL] 修改 PG 库的访问权限。

        对应 POST /databases/pg/privileges，请求体 dto.ChangeDBInfo。

        Args:
            database: PG 实例名称。
            value: 权限/主机白名单。
            type: PG 系类型。
            id: 库 ID。
            from_: 来源 local/remote。
        """
        require_write()
        client = await get_client()
        body = {
            "database": database, "type": type, "from": from_, "value": value,
        }
        if id:
            body["id"] = id
        return await client.post("/databases/pg/privileges", body)

    @mcp.tool()
    async def database_pg_bind(
        database: Annotated[str, Field(description="PG 实例名称（database 字段）")],
        name: Annotated[str, Field(description="目标库名")],
        username: Annotated[str, Field(description="要绑定的用户名")],
        password: Annotated[str, Field(description="用户密码")] = "",
        super_user: Annotated[bool, Field(description="是否授予超级用户权限")] = False,
    ) -> dict:
        """⚠️写操作 [PostgreSQL] 为 PG 库绑定用户（授权）。

        把用户绑定到指定库并授予权限。对应 POST /databases/pg/bind，
        请求体 dto.PostgresqlBindUser。

        Args:
            database: PG 实例名称。
            name: 目标库名。
            username: 用户名。
            password: 密码。
            super_user: 是否授予超级用户权限。
        """
        require_write()
        client = await get_client()
        return await client.post("/databases/pg/bind", {
            "database": database, "name": name, "username": username,
            "password": password, "superUser": super_user,
        })

    @mcp.tool()
    async def database_pg_load(
        database: Annotated[str, Field(description="PG 实例名称（database 字段）")],
        type: Annotated[PgType, Field(description="PG 系类型")] = "postgresql",
        from_: Annotated[Literal["local", "remote"], Field(description="来源 local/remote（参数名 from_ 因 from 是 Python 关键字，请求体映射为 from）")] = "local",
    ) -> dict:
        """⚠️写操作 [PostgreSQL] 从 PG 实例加载已存在的库列表（纳管远端库）。

        读取远端实例上已有的库，导入到 1Panel 纳管。对应
        POST /databases/pg/:database/load，请求体 dto.PostgresqlLoadDB。

        Args:
            database: PG 实例名称。
            type: PG 系类型。
            from_: 来源 local/remote。
        """
        require_write()
        client = await get_client()
        return await client.post(f"/databases/pg/{database}/load", {
            "database": database, "type": type, "from": from_,
        })

    @mcp.tool()
    async def database_pg_description(
        id: Annotated[int, Field(description="库 ID")],
        description: Annotated[str, Field(description="新备注（maxLength 256）", max_length=256)] = "",
    ) -> dict:
        """⚠️写操作 [PostgreSQL] 更新 PG 库的备注/描述。

        对应 POST /databases/pg/description，请求体 dto.UpdateDescription。

        Args:
            id: 库 ID。
            description: 新备注。
        """
        require_write()
        client = await get_client()
        return await client.post("/databases/pg/description", {
            "id": id, "description": description,
        })

    # ================================================================
    # Redis（Database Redis tag）
    # 配置、持久化、密码、状态、CLI 安装
    # ================================================================

    @mcp.tool()
    async def database_redis_status(
        name: Annotated[str, Field(description="Redis 实例名称")],
        type: Annotated[RedisDbType, Field(description="Redis 系类型：redis/redis-cluster")] = "redis",
    ) -> dict:
        """[Redis] 加载 Redis 运行时状态信息。读操作。

        返回 INFO 等运行时指标。对应 POST /databases/redis/status，
        请求体 dto.LoadRedisStatus。

        Args:
            name: Redis 实例名称。
            type: Redis 系类型。
        """
        client = await get_client()
        return await client.post("/databases/redis/status", {
            "name": name, "type": type,
        })

    @mcp.tool()
    async def database_redis_conf(
        name: Annotated[str, Field(description="Redis 实例名称")],
        type: Annotated[RedisDbType, Field(description="Redis 系类型")] = "redis",
    ) -> dict:
        """[Redis] 加载 Redis 配置（maxclients/maxmemory/timeout）。读操作。

        对应 POST /databases/redis/conf，请求体 dto.LoadRedisStatus。

        Args:
            name: Redis 实例名称。
            type: Redis 系类型。
        """
        client = await get_client()
        return await client.post("/databases/redis/conf", {
            "name": name, "type": type,
        })

    @mcp.tool()
    async def database_redis_conf_update(
        database: Annotated[str, Field(description="Redis 实例名称（database 字段）")],
        db_type: Annotated[RedisDbType, Field(description="Redis 系类型：redis/redis-cluster")] = "redis",
        maxclients: Annotated[str, Field(description="最大客户端连接数，如 10000（字符串形式）")] = "",
        maxmemory: Annotated[str, Field(description="最大内存，如 2gb（字符串形式）")] = "",
        timeout: Annotated[str, Field(description="空闲超时秒，如 0 表示不超时")] = "",
    ) -> dict:
        """⚠️写操作 [Redis] 更新 Redis 配置（maxclients/maxmemory/timeout）。

        修改 Redis 运行参数。对应 POST /databases/redis/conf/update，
        请求体 dto.RedisConfUpdate。⚠️ maxmemory 设置不当可能触发淘汰策略。

        Args:
            database: Redis 实例名称。
            db_type: Redis 系类型。
            maxclients: 最大客户端连接数。
            maxmemory: 最大内存。
            timeout: 空闲超时秒。
        """
        require_write()
        client = await get_client()
        body = {"database": database, "dbType": db_type}
        if maxclients:
            body["maxclients"] = maxclients
        if maxmemory:
            body["maxmemory"] = maxmemory
        if timeout:
            body["timeout"] = timeout
        return await client.post("/databases/redis/conf/update", body)

    @mcp.tool()
    async def database_redis_password(
        database: Annotated[str, Field(description="Redis 实例名称（database 字段）")],
        value: Annotated[str, Field(description="新密码（留空则取消密码）")] = "",
    ) -> dict:
        """⚠️写操作 [Redis] 修改 Redis 实例密码。

        对应 POST /databases/redis/password，请求体 dto.ChangeRedisPass。
        修改后需要用新密码重连。

        Args:
            database: Redis 实例名称。
            value: 新密码。
        """
        require_write()
        client = await get_client()
        return await client.post("/databases/redis/password", {
            "database": database, "value": value,
        })

    @mcp.tool()
    async def database_redis_persistence_conf(
        name: Annotated[str, Field(description="Redis 实例名称")],
        type: Annotated[RedisDbType, Field(description="Redis 系类型")] = "redis",
    ) -> dict:
        """[Redis] 加载 Redis 持久化配置（AOF/RDB）。读操作。

        对应 POST /databases/redis/persistence/conf，请求体 dto.LoadRedisStatus。

        Args:
            name: Redis 实例名称。
            type: Redis 系类型。
        """
        client = await get_client()
        return await client.post("/databases/redis/persistence/conf", {
            "name": name, "type": type,
        })

    @mcp.tool()
    async def database_redis_persistence_update(
        database: Annotated[str, Field(description="Redis 实例名称（database 字段）")],
        type: Annotated[Literal["aof", "rbd"], Field(description="持久化类型：aof（appendonly）或 rbd（save）")],
        db_type: Annotated[RedisDbType, Field(description="Redis 系类型：redis/redis-cluster")] = "redis",
        appendonly: Annotated[str, Field(description="是否启用 AOF，如 yes/no（仅 aof 生效）")] = "",
        appendfsync: Annotated[str, Field(description="AOF 刷盘策略 always/everysec/no（仅 aof 生效）")] = "",
        save: Annotated[str, Field(description="RDB 快照规则，如 '3600 1 300 100'（仅 rbd 生效）")] = "",
    ) -> dict:
        """⚠️写操作 [Redis] 更新 Redis 持久化配置（AOF 或 RDB）。

        对应 POST /databases/redis/persistence/update，请求体
        dto.RedisConfPersistenceUpdate。type=aof 时修改 appendonly/appendfsync；
        type=rbd 时修改 save 规则。

        Args:
            database: Redis 实例名称。
            type: 持久化类型 aof/rbd。
            db_type: Redis 系类型。
            appendonly: AOF 开关（aof 用）。
            appendfsync: AOF 刷盘策略（aof 用）。
            save: RDB 快照规则（rbd 用）。
        """
        require_write()
        client = await get_client()
        body = {
            "database": database, "dbType": db_type, "type": type,
        }
        if appendonly:
            body["appendonly"] = appendonly
        if appendfsync:
            body["appendfsync"] = appendfsync
        if save:
            body["save"] = save
        return await client.post("/databases/redis/persistence/update", body)

    @mcp.tool()
    async def database_redis_install_cli() -> dict:
        """⚠️写操作 [Redis] 安装 Redis CLI 工具。

        在 1Panel 宿主机安装 redis-cli，便于在面板内执行命令。对应
        POST /databases/redis/install/cli（无请求体）。
        """
        require_write()
        client = await get_client()
        return await client.post("/databases/redis/install/cli")
