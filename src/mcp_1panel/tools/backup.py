"""备份账号与备份记录管理模块（对应 openapi.json 的 Backup Account tag，25 个端点）。

照 container.py 黄金范式风格：
1. 工具名：backup_<action>（backup_account_search / backup_account_create / ...）
2. description：[备份] 开头，写操作加 ⚠️，高危加 confirm
3. 入参用 Annotated[T, Field(description=...)]
4. handler 用 `await get_client()` 拿共享客户端，调 .post() / .get() / .search()
5. 写操作开头调 require_write()，删除/恢复类加 confirm 参数

接口来源：references/openapi.json 的 /backups/* 与 /core/backups/* 路径，basePath /api/v2。

1Panel 备份账号类型（dto.BackupOperate.type，free string，常见取值）：
- LOCAL        本地目录备份
- OSS          阿里云 OSS
- S3           S3 兼容存储（AWS / MinIO / R2 / 等）
- MINIO        MinIO 对象存储
- COS          腾讯云 COS
- KODO         七牛云 Kodo
- OneDrive     微软 OneDrive
- GoogleDrive  Google Drive
- Dropbox      Dropbox
- UPYUN        又拍云 USS
- US3          UCloud US3
- SFTP         SFTP 远程目录
- WebDAV       WebDAV 远程目录
- Alist        Alist 网盘聚合
具体取值由调用方按业务填入，本模块不强校验。

备份目标类型（dto.CommonBackup.type，受 enum 约束）：
app / mysql / mariadb / redis / website / postgresql /
mysql-cluster / postgresql-cluster / redis-cluster

⚠️ 本模块有两类路径：
- /backups/*     ：主控端备份账号与备份记录管理（常规 1Panel 单机部署用这套）
- /core/backups/*：1Panel-Core / 多节点架构的「节点端」备份账号管理（节点侧 CRUD）
  命名上以 backup_account_node_* 区分，避免与主控端混淆。
"""

from __future__ import annotations

from typing import Annotated, Literal, Optional

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..client import get_client
from ..safety import require_write


# ---- 枚举 ----

# 备份账号类型（free string，给常用值做 Literal 便于召回）
BackupAccountType = Literal[
    "LOCAL", "OSS", "S3", "MINIO", "COS", "KODO",
    "OneDrive", "GoogleDrive", "Dropbox", "UPYUN", "US3",
    "SFTP", "WebDAV", "Alist",
]

# 备份/恢复目标类型（受 enum 约束，来自 dto.CommonBackup.type）
BackupTargetType = Literal[
    "app", "mysql", "mariadb", "redis", "website",
    "postgresql", "mysql-cluster", "postgresql-cluster", "redis-cluster",
]

BackupOrderBy = Literal["name", "type", "createdAt"]


def register(mcp: FastMCP) -> None:

    # ================================================================
    # 备份账号管理（主控端 /backups/*）
    # ================================================================

    @mcp.tool()
    async def backup_account_search(
        info: Annotated[str, Field(description="名称/类型模糊匹配，留空返回全部")] = "",
        type: Annotated[Optional[str], Field(description="按账号类型过滤，如 S3/OSS/LOCAL")] = None,
        page: Annotated[int, Field(ge=1, description="页码")] = 1,
        page_size: Annotated[int, Field(ge=1, le=500, description="每页数量")] = 100,
        order_by: Annotated[BackupOrderBy, Field(description="排序字段：name/type/createdAt")] = "createdAt",
        order: Annotated[Literal["ascending", "descending"], Field(description="排序方向")] = "descending",
    ) -> dict:
        """[备份] 列出或搜索备份账号。读操作。

        1Panel 备份账号分页查询接口，支持按名称、类型过滤。对应
        POST /backups/search。返回分页账号列表（含名称、类型、容量、关联目录等）。

        Args:
            info: 名称/类型模糊匹配，留空返回全部。
            type: 按账号类型过滤，如 S3/OSS/LOCAL/OneDrive，留空不过滤。
            page: 页码，从 1 开始。
            page_size: 每页数量，上限 500。
            order_by: 排序字段：name/type/createdAt。
            order: 排序方向：ascending/descending。
        """
        client = await get_client()
        body = {
            "page": page,
            "pageSize": page_size,
            "orderBy": order_by,
            "order": order,
            "info": info or "",
            "type": type or "",
        }
        return await client.post("/backups/search", body)

    @mcp.tool()
    async def backup_account_options() -> dict:
        """[备份] 列出所有备份账号简要选项（id/name/type）。读操作。

        返回所有备份账号的精简列表，常用于下拉选择。对应 GET /backups/options。

        Returns:
            备份账号选项列表（[{id, name, type, isPublic}, ...]）。
        """
        client = await get_client()
        return await client.get("/backups/options")

    @mcp.tool()
    async def backup_account_local_dir() -> dict:
        """[备份] 获取本地备份目录路径。读操作。

        返回 1Panel 服务端本地备份目录的绝对路径（备份账号类型 LOCAL 用）。
        对应 GET /backups/local。

        Returns:
            含 local 备份目录路径的对象。
        """
        client = await get_client()
        return await client.get("/backups/local")

    @mcp.tool()
    async def backup_account_buckets(
        type: Annotated[BackupAccountType, Field(description="账号类型，如 S3/OSS/MINIO/COS/KODO")],
        access_key: Annotated[str, Field(description="对象存储 AccessKey / 账户凭证")],
        credential: Annotated[str, Field(description="对象存储 SecretKey / 密钥凭证")],
        vars: Annotated[str, Field(description="其他参数 JSON 字符串，如 region/endpoint")],
    ) -> dict:
        """[备份] 列出对象存储可用 Bucket 列表。读操作。

        在新建/校验 S3/OSS/MINIO/COS/KODO 等对象存储备份账号时，列出该凭证下
        可访问的桶。对应 POST /backups/buckets。

        Args:
            type: 账号类型，如 S3/OSS/MINIO/COS/KODO。
            access_key: 对象存储 AccessKey 或账户凭证。
            credential: 对象存储 SecretKey 或密钥凭证。
            vars: 其他参数，JSON 字符串（如 region、endpoint、force_path_style 等）。
        """
        client = await get_client()
        return await client.post("/backups/buckets", {
            "type": type,
            "accessKey": access_key,
            "credential": credential,
            "vars": vars,
        })

    @mcp.tool()
    async def backup_account_files(
        id: Annotated[int, Field(description="备份账号 ID")],
    ) -> dict:
        """[备份] 列出某备份账号根目录下的文件列表。读操作。

        返回该账号下的备份目录/文件名列表。对应 POST /backups/search/files。

        Args:
            id: 备份账号 ID。
        """
        client = await get_client()
        return await client.post("/backups/search/files", {"id": id})

    @mcp.tool()
    async def backup_account_check(
        type: Annotated[BackupAccountType, Field(description="账号类型，如 S3/OSS/OneDrive/SFTP")],
        vars: Annotated[str, Field(description="连接参数 JSON 字符串，含 endpoint/region/bucket/path 等")],
        access_key: Annotated[str, Field(description="账号 AccessKey 或用户名")] = "",
        credential: Annotated[str, Field(description="账号 SecretKey 或密码")] = "",
        bucket: Annotated[str, Field(description="对象存储桶名，对象存储类型必填")] = "",
        backup_path: Annotated[str, Field(description="备份目录路径")] = "",
        is_public: Annotated[bool, Field(description="是否公开桶（部分类型有效）")] = False,
        remember_auth: Annotated[bool, Field(description="是否记住鉴权（OneDrive/GoogleDrive 等有效）")] = False,
    ) -> dict:
        """[备份] 校验备份账号连通性。读操作。

        在创建/更新备份账号前，校验凭证与连接参数是否正确，不落库。
        对应 POST /backups/check。

        Args:
            type: 账号类型，如 S3/OSS/OneDrive/SFTP/WebDAV。
            vars: 连接参数，JSON 字符串（region、endpoint、port 等，类型不同字段不同）。
            access_key: 账号 AccessKey 或用户名（对象存储/SSH 类）。
            credential: 账号 SecretKey 或密码。
            bucket: 对象存储桶名，对象存储类型必填。
            backup_path: 备份目录路径，留空使用账号默认。
            is_public: 是否公开桶（部分对象存储类型有效）。
            remember_auth: 是否记住鉴权信息（OneDrive/GoogleDrive 等有效）。
        """
        client = await get_client()
        return await client.post("/backups/check", {
            "type": type,
            "vars": vars,
            "accessKey": access_key,
            "credential": credential,
            "bucket": bucket,
            "backupPath": backup_path,
            "isPublic": is_public,
            "rememberAuth": remember_auth,
        })

    @mcp.tool()
    async def backup_account_create(
        type: Annotated[BackupAccountType, Field(description="账号类型，如 S3/OSS/MINIO/OneDrive/SFTP/LOCAL")],
        vars: Annotated[str, Field(description="连接参数 JSON 字符串，含 endpoint/region/path/port 等")],
        access_key: Annotated[str, Field(description="账号 AccessKey 或用户名")] = "",
        credential: Annotated[str, Field(description="账号 SecretKey 或密码")] = "",
        bucket: Annotated[str, Field(description="对象存储桶名，对象存储类型必填")] = "",
        backup_path: Annotated[str, Field(description="备份目录路径，留空使用默认")] = "",
        is_public: Annotated[bool, Field(description="是否公开桶（部分类型有效）")] = False,
        remember_auth: Annotated[bool, Field(description="是否记住鉴权（OneDrive/GoogleDrive 等有效）")] = False,
    ) -> dict:
        """⚠️写操作 [备份] 新建备份账号。

        创建一个备份账号（S3/OSS/MinIO/COS/Kodo/OneDrive/GoogleDrive/SFTP/WebDAV/LOCAL 等）。
        建议先调 backup_account_check 校验连通性再创建。对应 POST /backups。

        Args:
            type: 账号类型，如 S3/OSS/MINIO/COS/KODO/OneDrive/SFTP/WebDAV/LOCAL。
            vars: 连接参数，JSON 字符串（region、endpoint、port、path 等，类型不同字段不同）。
            access_key: 账号 AccessKey 或用户名（对象存储/SSH 类）。
            credential: 账号 SecretKey 或密码。
            bucket: 对象存储桶名，对象存储类型必填。
            backup_path: 备份目录路径，留空使用默认。
            is_public: 是否公开桶（部分对象存储类型有效）。
            remember_auth: 是否记住鉴权信息（OneDrive/GoogleDrive 等有效）。
        """
        require_write()
        client = await get_client()
        return await client.post("/backups", {
            "type": type,
            "vars": vars,
            "accessKey": access_key,
            "credential": credential,
            "bucket": bucket,
            "backupPath": backup_path,
            "isPublic": is_public,
            "rememberAuth": remember_auth,
        })

    @mcp.tool()
    async def backup_account_update(
        type: Annotated[BackupAccountType, Field(description="账号类型，如 S3/OSS/MINIO/OneDrive/SFTP/LOCAL")],
        vars: Annotated[str, Field(description="连接参数 JSON 字符串")],
        id: Annotated[int, Field(description="待更新账号 ID")] = 0,
        access_key: Annotated[str, Field(description="账号 AccessKey 或用户名")] = "",
        credential: Annotated[str, Field(description="账号 SecretKey 或密码")] = "",
        bucket: Annotated[str, Field(description="对象存储桶名")] = "",
        backup_path: Annotated[str, Field(description="备份目录路径")] = "",
        is_public: Annotated[bool, Field(description="是否公开桶")] = False,
        remember_auth: Annotated[bool, Field(description="是否记住鉴权")] = False,
    ) -> dict:
        """⚠️写操作 [备份] 更新备份账号。

        修改已有备份账号的凭证或连接参数。建议先调 backup_account_check 校验。
        对应 POST /backups/update。

        Args:
            type: 账号类型。
            vars: 连接参数，JSON 字符串。
            id: 待更新账号 ID。
            access_key: 账号 AccessKey 或用户名。
            credential: 账号 SecretKey 或密码。
            bucket: 对象存储桶名。
            backup_path: 备份目录路径。
            is_public: 是否公开桶。
            remember_auth: 是否记住鉴权。
        """
        require_write()
        client = await get_client()
        return await client.post("/backups/update", {
            "id": id,
            "type": type,
            "vars": vars,
            "accessKey": access_key,
            "credential": credential,
            "bucket": bucket,
            "backupPath": backup_path,
            "isPublic": is_public,
            "rememberAuth": remember_auth,
        })

    @mcp.tool()
    async def backup_account_delete(
        id: Annotated[int, Field(description="待删除备份账号 ID")],
        confirm: Annotated[bool, Field(description="删除是高危操作，必须传 true")] = False,
    ) -> dict:
        """⚠️高危 [备份] 删除备份账号。

        删除指定备份账号（按 ID）。已产生的备份文件记录不会被一并删除，
        但账号删除后将无法访问远端文件。对应 POST /backups/del。
        必须显式传 confirm=true 才执行。

        Args:
            id: 待删除备份账号 ID。
            confirm: 必须为 true 才执行删除。
        """
        require_write()
        if not confirm:
            raise ValueError("删除备份账号是高危操作，必须显式传 confirm=true。")
        client = await get_client()
        return await client.post("/backups/del", {"id": id})

    @mcp.tool()
    async def backup_account_refresh_token(
        type: Annotated[BackupAccountType, Field(description="账号类型，如 OneDrive/GoogleDrive/Alist")],
        vars: Annotated[str, Field(description="连接参数 JSON 字符串")] = "",
        access_key: Annotated[str, Field(description="账号 AccessKey")] = "",
        credential: Annotated[str, Field(description="账号 SecretKey 或 refresh_token")] = "",
        bucket: Annotated[str, Field(description="对象存储桶名")] = "",
        backup_path: Annotated[str, Field(description="备份目录路径")] = "",
        is_public: Annotated[bool, Field(description="是否公开桶")] = False,
        remember_auth: Annotated[bool, Field(description="是否记住鉴权")] = True,
        id: Annotated[int, Field(description="已存在账号 ID，更新已有账号时传入")] = 0,
    ) -> dict:
        """⚠️写操作 [备份] 刷新 OAuth 类备份账号的 Token。

        用于 OneDrive / GoogleDrive / Dropbox / Alist 等 OAuth 凭证过期时，
        用 refresh_token 换取新的访问令牌。对应 POST /backups/refresh/token。

        Args:
            type: 账号类型，如 OneDrive/GoogleDrive/Alist。
            vars: 连接参数，JSON 字符串。
            access_key: 账号 AccessKey。
            credential: 账号 SecretKey 或 refresh_token。
            bucket: 对象存储桶名。
            backup_path: 备份目录路径。
            is_public: 是否公开桶。
            remember_auth: 是否记住鉴权。
            id: 已存在账号 ID，更新已有账号时传入。
        """
        require_write()
        client = await get_client()
        return await client.post("/backups/refresh/token", {
            "id": id,
            "type": type,
            "vars": vars,
            "accessKey": access_key,
            "credential": credential,
            "bucket": bucket,
            "backupPath": backup_path,
            "isPublic": is_public,
            "rememberAuth": remember_auth,
        })

    # ================================================================
    # 备份 / 恢复 / 上传（主控端 /backups/*）
    # ================================================================

    @mcp.tool()
    async def backup_run(
        type: Annotated[BackupTargetType, Field(description="备份目标类型：app/mysql/mariadb/redis/website/postgresql 等")],
        name: Annotated[str, Field(description="备份对象名称，如应用名/库名/网站名（type=snapshot 留空）")],
        detail_name: Annotated[str, Field(description="子对象名，如数据库实例下具体库名，可空")] = "",
        file_name: Annotated[str, Field(description="指定备份文件名，留空自动生成")] = "",
        description: Annotated[str, Field(description="备份描述，便于回溯")] = "",
        secret: Annotated[str, Field(description="备份加密密码，留空不加密")] = "",
    ) -> dict:
        """⚠️写操作 [备份] 立即执行一次备份。

        对指定对象（应用 / 数据库 / 网站 / 集群）立即生成一份备份，写入指定备份账号。
        1Panel 内部走异步任务，返回 taskID 用于查询进度。对应 POST /backups/backup。

        Args:
            type: 备份目标类型：app/mysql/mariadb/redis/website/postgresql/
                mysql-cluster/postgresql-cluster/redis-cluster。
            name: 备份对象名称，如应用名、库名、网站域名。
            detail_name: 子对象名（如数据库实例下具体库名），可空。
            file_name: 指定备份文件名，留空由系统按时间生成。
            description: 备份描述。
            secret: 备份加密密码，留空表示不加密。
        """
        require_write()
        client = await get_client()
        return await client.post("/backups/backup", {
            "type": type,
            "name": name,
            "detailName": detail_name,
            "fileName": file_name,
            "description": description,
            "secret": secret,
        })

    @mcp.tool()
    async def backup_restore(
        type: Annotated[BackupTargetType, Field(description="恢复目标类型：app/mysql/mariadb/redis/website/postgresql 等")],
        download_account_id: Annotated[int, Field(description="从哪个备份账号下载，0 表示本地")] = 0,
        name: Annotated[str, Field(description="恢复到的目标对象名称")] = "",
        detail_name: Annotated[str, Field(description="子对象名，可空")] = "",
        file: Annotated[str, Field(description="备份文件路径（含目录），必填")] = "",
        secret: Annotated[str, Field(description="解密密码，加密备份必填")] = "",
        confirm: Annotated[bool, Field(description="恢复会覆盖目标数据，是高危操作，必须传 true")] = False,
    ) -> dict:
        """⚠️高危 [备份] 从备份账号恢复数据。

        从指定备份账号下载备份文件并恢复到目标对象，会覆盖现有数据，是高危操作。
        对应 POST /backups/recover。必须显式传 confirm=true。

        Args:
            type: 恢复目标类型：app/mysql/mariadb/redis/website/postgresql/
                mysql-cluster/postgresql-cluster/redis-cluster。
            download_account_id: 从哪个备份账号下载文件，0 表示本地。
            name: 恢复到的目标对象名称（应用名/库名/网站名）。
            detail_name: 子对象名，可空。
            file: 备份文件路径（含目录），必填。
            secret: 解密密码，加密备份必填。
            confirm: 恢复会覆盖现有数据，必须为 true。
        """
        require_write()
        if not confirm:
            raise ValueError("恢复数据是高危操作，必须显式传 confirm=true。")
        client = await get_client()
        return await client.post("/backups/recover", {
            "type": type,
            "downloadAccountID": download_account_id,
            "name": name,
            "detailName": detail_name,
            "file": file,
            "secret": secret,
        })

    @mcp.tool()
    async def backup_upload(
        file_path: Annotated[str, Field(description="服务端临时文件路径，1Panel 上传后返回的路径")],
        target_dir: Annotated[str, Field(description="目标备份目录，留空使用默认")] = "",
    ) -> dict:
        """⚠️写操作 [备份] 上传本地备份文件用于恢复。

        把一个本地备份文件登记到 1Panel，用于后续按上传文件恢复
        （backup_restore_by_upload）。对应 POST /backups/upload。

        Args:
            file_path: 服务端临时文件路径（通常是 1Panel 文件管理器内路径）。
            target_dir: 目标备份目录，留空使用默认。
        """
        require_write()
        client = await get_client()
        return await client.post("/backups/upload", {
            "filePath": file_path,
            "targetDir": target_dir,
        })

    @mcp.tool()
    async def backup_restore_by_upload(
        type: Annotated[BackupTargetType, Field(description="恢复目标类型：app/mysql/mariadb/redis/website/postgresql 等")],
        download_account_id: Annotated[int, Field(description="备份账号 ID（上传文件所在账号）")] = 0,
        name: Annotated[str, Field(description="恢复到的目标对象名称")] = "",
        detail_name: Annotated[str, Field(description="子对象名，可空")] = "",
        file: Annotated[str, Field(description="已上传的备份文件路径，必填")] = "",
        secret: Annotated[str, Field(description="解密密码")] = "",
        confirm: Annotated[bool, Field(description="恢复覆盖现有数据，是高危操作，必须传 true")] = False,
    ) -> dict:
        """⚠️高危 [备份] 从已上传文件恢复数据。

        与 backup_restore 类似，但备份文件来自本地上传（先调 backup_upload 登记），
        而非远端账号。会覆盖现有数据，是高危操作。对应 POST /backups/recover/byupload。
        必须显式传 confirm=true。

        Args:
            type: 恢复目标类型：app/mysql/mariadb/redis/website/postgresql 等。
            download_account_id: 备份账号 ID（上传文件所在账号）。
            name: 恢复到的目标对象名称。
            detail_name: 子对象名，可空。
            file: 已上传的备份文件路径，必填。
            secret: 解密密码。
            confirm: 必须为 true。
        """
        require_write()
        if not confirm:
            raise ValueError("从上传文件恢复是高危操作，必须显式传 confirm=true。")
        client = await get_client()
        return await client.post("/backups/recover/byupload", {
            "type": type,
            "downloadAccountID": download_account_id,
            "name": name,
            "detailName": detail_name,
            "file": file,
            "secret": secret,
        })

    # ================================================================
    # 备份记录管理（主控端 /backups/record/*）
    # ================================================================

    @mcp.tool()
    async def backup_record_search(
        type: Annotated[str, Field(description="按备份目标类型过滤，如 app/mysql/website/snapshot，必填")] = "",
        detail_name: Annotated[str, Field(description="子对象名模糊匹配")] = "",
        name: Annotated[str, Field(description="对象名模糊匹配")] = "",
        info: Annotated[str, Field(description="综合模糊匹配")] = "",
        page: Annotated[int, Field(ge=1, description="页码")] = 1,
        page_size: Annotated[int, Field(ge=1, le=500, description="每页数量")] = 100,
    ) -> dict:
        """[备份] 分页查询备份记录。读操作。

        返回历次备份产生的文件记录（文件名、大小、账号、来源、时间、描述等）。
        对应 POST /backups/record/search。type 为必填筛选条件。

        Args:
            type: 按备份目标类型过滤，如 app/mysql/website/snapshot，必填。
            detail_name: 子对象名模糊匹配。
            name: 对象名模糊匹配。
            info: 综合模糊匹配。
            page: 页码。
            page_size: 每页数量。
        """
        client = await get_client()
        body = {
            "page": page,
            "pageSize": page_size,
            "type": type or "",
            "detailName": detail_name,
            "name": name,
            "info": info,
        }
        return await client.post("/backups/record/search", body)

    @mcp.tool()
    async def backup_record_search_by_cronjob(
        cronjob_id: Annotated[int, Field(description="计划任务 ID")],
        page: Annotated[int, Field(ge=1, description="页码")] = 1,
        page_size: Annotated[int, Field(ge=1, le=500, description="每页数量")] = 100,
    ) -> dict:
        """[备份] 按计划任务分页查询其产生的备份记录。读操作。

        某个备份类计划任务（type=app/database/website/snapshot）历次执行产生的
        备份文件记录。对应 POST /backups/record/search/bycronjob。

        Args:
            cronjob_id: 计划任务 ID。
            page: 页码。
            page_size: 每页数量。
        """
        client = await get_client()
        return await client.post("/backups/record/search/bycronjob", {
            "cronjobID": cronjob_id,
            "page": page,
            "pageSize": page_size,
        })

    @mcp.tool()
    async def backup_record_size(
        page: Annotated[int, Field(ge=1, description="页码")] = 1,
        page_size: Annotated[int, Field(ge=1, le=500, description="每页数量")] = 100,
        type: Annotated[str, Field(description="按目标类型过滤，可空")] = "",
        info: Annotated[str, Field(description="综合模糊匹配")] = "",
    ) -> dict:
        """[备份] 查询备份记录占用的存储大小。读操作。

        分页返回各备份记录的文件大小，用于容量统计。对应 POST /backups/record/size。

        Args:
            page: 页码。
            page_size: 每页数量。
            type: 按目标类型过滤，可空。
            info: 综合模糊匹配。
        """
        client = await get_client()
        return await client.post("/backups/record/size", {
            "page": page,
            "pageSize": page_size,
            "type": type,
            "info": info,
        })

    @mcp.tool()
    async def backup_record_download_url(
        download_account_id: Annotated[int, Field(description="从哪个备份账号下载")],
        file_dir: Annotated[str, Field(description="备份文件所在目录")],
        file_name: Annotated[str, Field(description="备份文件名")],
    ) -> dict:
        """[备份] 获取备份记录的下载地址。读操作。

        生成某条备份记录的可下载 URL（带临时签名）。对应 POST /backups/record/download。

        Args:
            download_account_id: 从哪个备份账号下载。
            file_dir: 备份文件所在目录。
            file_name: 备份文件名。
        """
        client = await get_client()
        return await client.post("/backups/record/download", {
            "downloadAccountID": download_account_id,
            "fileDir": file_dir,
            "fileName": file_name,
        })

    @mcp.tool()
    async def backup_record_update_description(
        id: Annotated[int, Field(description="备份记录 ID")],
        description: Annotated[str, Field(description="新描述（最长 256 字符）")],
    ) -> dict:
        """⚠️写操作 [备份] 更新备份记录的描述。

        修改某条备份记录的备注描述。对应 POST /backups/record/description/update。

        Args:
            id: 备份记录 ID。
            description: 新描述（最长 256 字符）。
        """
        require_write()
        client = await get_client()
        return await client.post("/backups/record/description/update", {
            "id": id,
            "description": description,
        })

    @mcp.tool()
    async def backup_record_delete(
        ids: Annotated[list[int], Field(description="待删除的备份记录 ID 列表")],
        confirm: Annotated[bool, Field(description="删除备份文件不可恢复，是高危操作，必须传 true")] = False,
    ) -> dict:
        """⚠️高危 [备份] 删除备份记录（含远端文件）。

        批量删除备份记录，会同步删除远端/本地的备份文件，不可恢复。
        对应 POST /backups/record/del。必须显式传 confirm=true。

        Args:
            ids: 待删除的备份记录 ID 列表。
            confirm: 必须为 true 才执行删除。
        """
        require_write()
        if not confirm:
            raise ValueError("删除备份记录是高危操作，必须显式传 confirm=true。")
        client = await get_client()
        return await client.post("/backups/record/del", {"ids": ids})

    # ================================================================
    # 节点端备份账号管理（1Panel-Core 多节点架构 /core/backups/*）
    #
    # 单机部署用不到这套；多节点架构下，节点侧用名字（OperateByName）
    # 而非 ID 操作备份账号。
    # ================================================================

    @mcp.tool()
    async def backup_account_node_info(
        client_type: Annotated[str, Field(description="客户端类型，如 onedrive/google-drive/alist")],
    ) -> dict:
        """[备份] 获取 OAuth 类备份账号的客户端基础信息（节点端）。读操作。

        返回 OAuth 客户端的 client_id / client_secret / redirect_uri，用于节点端
        OAuth 授权流程。对应 GET /core/backups/client/{clientType}。

        Args:
            client_type: 客户端类型，如 onedrive/google-drive/alist/dropbox。
        """
        client = await get_client()
        return await client.get(f"/core/backups/client/{client_type}")

    @mcp.tool()
    async def backup_account_node_create(
        type: Annotated[BackupAccountType, Field(description="账号类型，如 S3/OSS/OneDrive/SFTP")],
        vars: Annotated[str, Field(description="连接参数 JSON 字符串")],
        access_key: Annotated[str, Field(description="账号 AccessKey 或用户名")] = "",
        credential: Annotated[str, Field(description="账号 SecretKey 或密码")] = "",
        bucket: Annotated[str, Field(description="对象存储桶名")] = "",
        backup_path: Annotated[str, Field(description="备份目录路径")] = "",
        is_public: Annotated[bool, Field(description="是否公开桶")] = False,
        remember_auth: Annotated[bool, Field(description="是否记住鉴权")] = False,
    ) -> dict:
        """⚠️写操作 [备份] 新建备份账号（节点端）。

        在 1Panel-Core 多节点架构下，于节点侧创建备份账号。对应 POST /core/backups。

        Args:
            type: 账号类型。
            vars: 连接参数，JSON 字符串。
            access_key: 账号 AccessKey 或用户名。
            credential: 账号 SecretKey 或密码。
            bucket: 对象存储桶名。
            backup_path: 备份目录路径。
            is_public: 是否公开桶。
            remember_auth: 是否记住鉴权。
        """
        require_write()
        client = await get_client()
        return await client.post("/core/backups", {
            "type": type,
            "vars": vars,
            "accessKey": access_key,
            "credential": credential,
            "bucket": bucket,
            "backupPath": backup_path,
            "isPublic": is_public,
            "rememberAuth": remember_auth,
        })

    @mcp.tool()
    async def backup_account_node_update(
        type: Annotated[BackupAccountType, Field(description="账号类型")],
        vars: Annotated[str, Field(description="连接参数 JSON 字符串")],
        access_key: Annotated[str, Field(description="账号 AccessKey 或用户名")] = "",
        credential: Annotated[str, Field(description="账号 SecretKey 或密码")] = "",
        bucket: Annotated[str, Field(description="对象存储桶名")] = "",
        backup_path: Annotated[str, Field(description="备份目录路径")] = "",
        is_public: Annotated[bool, Field(description="是否公开桶")] = False,
        remember_auth: Annotated[bool, Field(description="是否记住鉴权")] = False,
    ) -> dict:
        """⚠️写操作 [备份] 更新备份账号（节点端）。

        在节点侧修改备份账号。对应 POST /core/backups/update。

        Args:
            type: 账号类型。
            vars: 连接参数，JSON 字符串。
            access_key: 账号 AccessKey 或用户名。
            credential: 账号 SecretKey 或密码。
            bucket: 对象存储桶名。
            backup_path: 备份目录路径。
            is_public: 是否公开桶。
            remember_auth: 是否记住鉴权。
        """
        require_write()
        client = await get_client()
        return await client.post("/core/backups/update", {
            "type": type,
            "vars": vars,
            "accessKey": access_key,
            "credential": credential,
            "bucket": bucket,
            "backupPath": backup_path,
            "isPublic": is_public,
            "rememberAuth": remember_auth,
        })

    @mcp.tool()
    async def backup_account_node_delete(
        name: Annotated[str, Field(description="待删除备份账号名")],
        confirm: Annotated[bool, Field(description="删除是高危操作，必须传 true")] = False,
    ) -> dict:
        """⚠️高危 [备份] 删除备份账号（节点端）。

        节点侧按账号名删除备份账号。对应 POST /core/backups/del。
        必须显式传 confirm=true。

        Args:
            name: 待删除备份账号名。
            confirm: 必须为 true。
        """
        require_write()
        if not confirm:
            raise ValueError("删除备份账号是高危操作，必须显式传 confirm=true。")
        client = await get_client()
        return await client.post("/core/backups/del", {"name": name})

    @mcp.tool()
    async def backup_account_node_refresh_token(
        name: Annotated[str, Field(description="备份账号名")],
    ) -> dict:
        """⚠️写操作 [备份] 刷新 OAuth 备份账号 Token（节点端）。

        节点侧按账号名刷新 OAuth 类备份账号的访问令牌。对应 POST /core/backups/refresh/token。

        Args:
            name: 备份账号名。
        """
        require_write()
        client = await get_client()
        return await client.post("/core/backups/refresh/token", {"name": name})
