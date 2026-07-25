"""文件管理模块（对应 openapi.json 的 File tag，39 个端点）。

实现风格遵循黄金范式 container.py：
1. 工具名：file_<action> / file_<object>_<action>
2. description：[文件] 开头，写操作加 ⚠️，高危加 ⚠️高危，便于 mcphub 向量召回
3. 入参用 Annotated[T, Field(description=...)]，复杂入参内联 dict
4. handler 用 await get_client() 拿共享客户端，调 .post() / .get()
5. 写操作开头调 require_write()，高危加 confirm 参数

安全分层：
- 读操作：file_list/file_tree/file_read/file_content/file_preview/file_size/
          file_dir_size/file_check/file_batch_check/file_mount/file_user_group/
          file_favorite_list/file_remarks/file_convert_log/file_upload_search/
          file_recycle_list/file_recycle_status
- 写操作（require_write）：file_create/file_save/file_move/file_copy/file_rename/
                          file_compress/file_decompress/file_chmod/file_batch_chmod/
                          file_chown/file_wget/file_favorite/file_favorite_delete/
                          file_remark/file_convert/file_recycle_restore
- 高危（confirm）：file_delete/file_batch_delete/file_recycle_clear（不可恢复）

接口来源：references/openapi.json 的 /files/* 路径，basePath /api/v2。
"""

from __future__ import annotations

from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..client import get_client
from ..safety import require_write


# ---- 枚举（来自 openapi.json / 1Panel 源码 frontend/src/enums/files.ts） ----

# 压缩/解压格式：zip / tar / tar.gz / tar.bz2 / tar.xz
CompressType = Literal["zip", "tar", "tar.gz", "tar.bz2", "tar.xz"]

# /files/search 的排序字段（openapi 仅标 string，1Panel 前端用 name/size/modTime/extension 等）
FileSortBy = Literal["name", "size", "modTime", "extension", ""]
FileSortOrder = Literal["ascending", "descending", ""]


def register(mcp: FastMCP) -> None:

    # ============ 读：文件列表与浏览 ============

    @mcp.tool()
    async def file_list(
        path: Annotated[str, Field(description="目录绝对路径，如 /opt/1panel 或 /root")],
        search: Annotated[str, Field(description="文件名模糊匹配，留空则列出全部")] = "",
        page: Annotated[int, Field(ge=1, description="页码，从 1 开始")] = 1,
        page_size: Annotated[int, Field(ge=1, le=500, description="每页数量")] = 100,
        sort_by: Annotated[FileSortBy, Field(description="排序字段：name/size/modTime/extension")] = "",
        sort_order: Annotated[FileSortOrder, Field(description="排序方向")] = "",
        show_hidden: Annotated[bool, Field(description="是否显示隐藏文件（.开头）")] = False,
        contain_sub: Annotated[bool, Field(description="search 时是否递归子目录匹配")] = False,
        expand: Annotated[bool, Field(description="是否展开（含目录统计等附加信息）")] = False,
        is_detail: Annotated[bool, Field(description="是否返回详情（含 mode/user/group 等）")] = False,
    ) -> dict:
        """[文件] 列出目录下的文件/子目录（文件管理器主接口）。读操作。

        1Panel 文件浏览的核心分页接口，对应 POST /files/search。
        返回该目录下的文件列表（名称、大小、修改时间、类型、权限等）。

        Args:
            path: 目录绝对路径。
            search: 文件名模糊匹配；留空则列出 path 下所有条目。
            page: 页码。
            page_size: 每页数量。
            sort_by: 排序字段，留空用 1Panel 默认。
            sort_order: 排序方向，留空用 1Panel 默认。
            show_hidden: 是否显示隐藏文件。
            contain_sub: 搜索时是否递归子目录。
            expand: 是否展开附加信息。
            is_detail: 是否返回详情字段。
        """
        client = await get_client()
        body = {
            "page": page,
            "pageSize": page_size,
            "path": path,
            "search": search,
            "sortBy": sort_by,
            "sortOrder": sort_order,
            "showHidden": show_hidden,
            "containSub": contain_sub,
            "expand": expand,
            "isDetail": is_detail,
            "dir": True,
        }
        return await client.post("/files/search", body)

    @mcp.tool()
    async def file_tree(
        path: Annotated[str, Field(description="根目录绝对路径")],
        expand: Annotated[bool, Field(description="是否展开子目录")] = False,
        show_hidden: Annotated[bool, Field(description="是否显示隐藏文件")] = False,
    ) -> dict:
        """[文件] 加载目录树（用于文件选择器/树形浏览）。读操作。

        返回嵌套的 FileTree 节点（name/path/isDir/children）。对应 POST /files/tree。

        Args:
            path: 根目录路径。
            expand: 是否展开子目录。
            show_hidden: 是否显示隐藏文件。
        """
        client = await get_client()
        return await client.post("/files/tree", {
            "path": path,
            "expand": expand,
            "showHidden": show_hidden,
            "dir": True,
        })

    @mcp.tool()
    async def file_content(
        path: Annotated[str, Field(description="文件绝对路径")],
        is_detail: Annotated[bool, Field(description="是否返回详情（含 mode/user/group）")] = False,
    ) -> dict:
        """[文件] 读取文件完整内容。读操作。

        适合读取配置文件、脚本等中小型文本文件。对应 POST /files/content。
        返回 FileInfo（含 content 字段为文件全文）。

        大文件（日志）请改用 file_read（按行分页）。

        Args:
            path: 文件绝对路径。
            is_detail: 是否返回详情字段。
        """
        client = await get_client()
        return await client.post("/files/content", {
            "path": path,
            "isDetail": is_detail,
        })

    @mcp.tool()
    async def file_read(
        type: Annotated[Literal["LogFile"], Field(description="读取类型，目前仅支持 LogFile（按行读文件）")] = "LogFile",
        name: Annotated[str, Field(description="文件绝对路径")] = "",
        page: Annotated[int, Field(ge=1, description="页码，从 1 开始")] = 1,
        page_size: Annotated[int, Field(ge=1, le=2000, description="每页行数")] = 100,
        latest: Annotated[bool, Field(description="是否只读末尾（最新）内容")] = False,
    ) -> dict:
        """[文件] 按行分页读取文件（适合大文件/日志）。读操作。

        对应 POST /files/read（request.FileReadByLineReq）。
        返回 FileLineContent（lines 行数组 + totalLines 总行数 + end 是否到尾）。
        适合读取大日志文件而不一次性载入内存。

        Args:
            type: 读取类型，目前固定 LogFile。
            name: 文件绝对路径。
            page: 页码（行分页）。
            page_size: 每页行数。
            latest: True 时跳转到末尾最新内容。
        """
        client = await get_client()
        return await client.post("/files/read", {
            "type": type,
            "name": name,
            "page": page,
            "pageSize": page_size,
            "latest": latest,
        })

    @mcp.tool()
    async def file_preview(
        path: Annotated[str, Field(description="文件绝对路径")],
    ) -> dict:
        """[文件] 预览文件内容（前端预览器用）。读操作。

        与 file_content 类似，但供预览器使用，返回 FileInfo。对应 POST /files/preview。

        Args:
            path: 文件绝对路径。
        """
        client = await get_client()
        return await client.post("/files/preview", {"path": path, "isDetail": False})

    @mcp.tool()
    async def file_size(
        path: Annotated[str, Field(description="目录绝对路径")],
    ) -> dict:
        """[文件] 计算目录/文件占用大小（du 等价）。读操作。

        对应 POST /files/size（request.DirSizeReq）。返回目录总大小（字节）。
        大目录可能耗时。

        Args:
            path: 目录或文件绝对路径。
        """
        client = await get_client()
        return await client.post("/files/size", {"path": path})

    @mcp.tool()
    async def file_dir_size(
        path: Annotated[str, Field(description="目录绝对路径")],
    ) -> dict:
        """[文件] 批量计算多个文件/子目录大小。读操作。

        对应 POST /files/depth/size（request.DirSizeReq），用于文件列表里逐项显示大小。

        Args:
            path: 目录绝对路径。
        """
        client = await get_client()
        return await client.post("/files/depth/size", {"path": path})

    # ============ 读：检查与系统信息 ============

    @mcp.tool()
    async def file_check(
        path: Annotated[str, Field(description="待检查路径（绝对路径）")],
        with_init: Annotated[bool, Field(description="是否含初始化目录检查")] = False,
    ) -> dict:
        """[文件] 检查文件/目录是否存在。读操作。

        对应 POST /files/check（request.FilePathCheck），返回 boolean。

        Args:
            path: 待检查路径。
            with_init: 是否含初始化目录检查。
        """
        client = await get_client()
        return await client.post("/files/check", {
            "path": path,
            "withInit": with_init,
        })

    @mcp.tool()
    async def file_batch_check(
        paths: Annotated[list[str], Field(description="待检查路径列表")],
    ) -> dict:
        """[文件] 批量检查多个文件是否存在。读操作。

        对应 POST /files/batch/check（request.FilePathsCheck），返回 ExistFileInfo 列表。

        Args:
            paths: 待检查路径列表。
        """
        client = await get_client()
        return await client.post("/files/batch/check", {"paths": paths})

    @mcp.tool()
    async def file_mount() -> dict:
        """[文件] 列出系统磁盘/挂载点信息。读操作。

        对应 POST /files/mount，返回 DiskInfo（含各挂载点容量、可用空间）。
        """
        client = await get_client()
        return await client.post("/files/mount")

    @mcp.tool()
    async def file_user_group() -> dict:
        """[文件] 列出系统用户与用户组（用于改权限时选择 owner/group）。读操作。

        对应 POST /files/user/group，返回 UserGroupResponse（users + groups）。
        """
        client = await get_client()
        return await client.post("/files/user/group")

    # ============ 读：收藏 / 备注 / 转换日志 / 上传任务 ============

    @mcp.tool()
    async def file_favorite_list(
        page: Annotated[int, Field(ge=1, description="页码")] = 1,
        page_size: Annotated[int, Field(ge=1, le=500, description="每页数量")] = 100,
    ) -> dict:
        """[文件] 列出收藏的文件/目录。读操作。

        对应 POST /files/favorite/search（dto.PageInfo），返回分页收藏列表。

        Args:
            page: 页码。
            page_size: 每页数量。
        """
        client = await get_client()
        return await client.post("/files/favorite/search", {
            "page": page,
            "pageSize": page_size,
        })

    @mcp.tool()
    async def file_remarks(
        paths: Annotated[list[str], Field(description="要查备注的路径列表")],
    ) -> dict:
        """[文件] 批量获取文件备注。读操作。

        对应 POST /files/remarks（request.FileRemarkBatch），返回各路径的备注。

        Args:
            paths: 路径列表。
        """
        client = await get_client()
        return await client.post("/files/remarks", {"paths": paths})

    @mcp.tool()
    async def file_convert_log(
        page: Annotated[int, Field(ge=1, description="页码")] = 1,
        page_size: Annotated[int, Field(ge=1, le=500, description="每页数量")] = 100,
    ) -> dict:
        """[文件] 查询文件转换任务日志（分页）。读操作。

        对应 POST /files/convert/log（dto.PageInfo）。

        Args:
            page: 页码。
            page_size: 每页数量。
        """
        client = await get_client()
        return await client.post("/files/convert/log", {
            "page": page,
            "pageSize": page_size,
        })

    @mcp.tool()
    async def file_upload_search(
        path: Annotated[str, Field(description="目标目录绝对路径")],
        page: Annotated[int, Field(ge=1, description="页码")] = 1,
        page_size: Annotated[int, Field(ge=1, le=500, description="每页数量")] = 100,
    ) -> dict:
        """[文件] 查询上传任务记录（分页）。读操作。

        对应 POST /files/upload/search（request.SearchUploadWithPage）。
        注意：这是查询上传任务历史，不是上传文件本身。

        Args:
            path: 目标目录路径。
            page: 页码。
            page_size: 每页数量。
        """
        client = await get_client()
        return await client.post("/files/upload/search", {
            "path": path,
            "page": page,
            "pageSize": page_size,
        })

    # ============ 读：回收站 ============

    @mcp.tool()
    async def file_recycle_status() -> dict:
        """[文件] 查询回收站是否启用。读操作。

        对应 GET /files/recycle/status，返回 FileRecycleBin 设置值（true=已启用）。
        """
        client = await get_client()
        return await client.get("/files/recycle/status")

    @mcp.tool()
    async def file_recycle_list(
        page: Annotated[int, Field(ge=1, description="页码")] = 1,
        page_size: Annotated[int, Field(ge=1, le=500, description="每页数量")] = 100,
    ) -> dict:
        """[文件] 列出回收站中的文件（分页）。读操作。

        对应 POST /files/recycle/search（dto.PageInfo）。
        返回 PageResult（items: RecycleBinDTO，含原始路径、删除时间、来源 from、回收名 rName）。
        rName/from 用于 file_recycle_restore 还原。

        Args:
            page: 页码。
            page_size: 每页数量。
        """
        client = await get_client()
        return await client.post("/files/recycle/search", {
            "page": page,
            "pageSize": page_size,
        })

    # ============ 写：创建/编辑 ============

    @mcp.tool()
    async def file_create(
        path: Annotated[str, Field(description="新建条目的绝对路径（含文件名/目录名）")],
        is_dir: Annotated[bool, Field(description="True 创建目录，False 创建文件")] = False,
        content: Annotated[str, Field(description="文件初始内容（is_dir=False 时有效）")] = "",
        mode: Annotated[int, Field(description="权限 mode（八进制整型，如 0o644 传 420；0 表示默认）")] = 0,
        sub: Annotated[bool, Field(description="是否递归创建父目录（mkdir -p 语义）")] = False,
        is_link: Annotated[bool, Field(description="是否创建软链接（已废弃，用 is_symlink）")] = False,
        is_symlink: Annotated[bool, Field(description="是否创建软链接，配合 link_path")] = False,
        link_path: Annotated[str, Field(description="软链接指向的真实路径")] = "",
    ) -> dict:
        """⚠️写操作 [文件] 创建目录或文件。

        对应 POST /files（request.FileCreate）。is_dir=true 时 mkdir，false 时 touch 文件
        （可带初始 content）。is_symlink=true 时创建软链接（link_path 为目标）。

        Args:
            path: 新建条目绝对路径。
            is_dir: True=目录，False=文件。
            content: 文件初始内容。
            mode: 权限 mode（八进制整型值，如 0o755=493）。
            sub: 是否递归创建父目录。
            is_link: （已废弃）软链接标志。
            is_symlink: 是否创建软链接。
            link_path: 软链接目标路径。
        """
        require_write()
        client = await get_client()
        return await client.post("/files", {
            "path": path,
            "isDir": is_dir,
            "content": content,
            "mode": mode,
            "sub": sub,
            "isLink": is_link,
            "isSymlink": is_symlink,
            "linkPath": link_path,
        })

    @mcp.tool()
    async def file_save(
        path: Annotated[str, Field(description="文件绝对路径")],
        content: Annotated[str, Field(description="要写入的完整内容")],
    ) -> dict:
        """⚠️写操作 [文件] 编辑/保存文件内容（覆盖写）。

        对应 POST /files/save（request.FileEdit），用 content 整体覆盖原文件。
        ⚠️ 是全量覆盖，不是追加。

        Args:
            path: 文件绝对路径。
            content: 新的完整文件内容。
        """
        require_write()
        client = await get_client()
        return await client.post("/files/save", {
            "path": path,
            "content": content,
        })

    # ============ 写：移动 / 复制 / 重命名 ============

    @mcp.tool()
    async def file_move(
        old_paths: Annotated[list[str], Field(description="源路径列表（绝对路径）")],
        new_path: Annotated[str, Field(description="目标目录（绝对路径）")],
        cover: Annotated[bool, Field(description="目标已存在时是否覆盖")] = False,
        cover_paths: Annotated[list[str], Field(description="确认覆盖的具体路径列表")] = None,
        name: Annotated[str, Field(description="任务名（一般留空）")] = "",
        type: Annotated[Literal["move", "copy"], Field(description="操作类型：move=移动，copy=复制")] = "move",
    ) -> dict:
        """⚠️写操作 [文件] 移动或复制文件/目录（type 控制语义）。

        对应 POST /files/move（request.FileMove）。
        type=move 时移动（剪切），type=copy 时复制。支持批量 old_paths。

        Args:
            old_paths: 源路径列表。
            new_path: 目标目录。
            cover: 是否覆盖已存在目标。
            cover_paths: 确认覆盖的路径列表。
            name: 任务名。
            type: move=移动（mv），copy=复制（cp -r）。
        """
        require_write()
        client = await get_client()
        return await client.post("/files/move", {
            "oldPaths": old_paths,
            "newPath": new_path,
            "type": type,
            "cover": cover,
            "coverPaths": cover_paths or [],
            "name": name,
        })

    @mcp.tool()
    async def file_copy(
        old_paths: Annotated[list[str], Field(description="源路径列表（绝对路径）")],
        new_path: Annotated[str, Field(description="目标目录（绝对路径）")],
        cover: Annotated[bool, Field(description="目标已存在时是否覆盖")] = False,
    ) -> dict:
        """⚠️写操作 [文件] 复制文件/目录（file_move 的 copy 便捷封装）。

        等价于 file_move(type="copy")。对应 POST /files/move。

        Args:
            old_paths: 源路径列表。
            new_path: 目标目录。
            cover: 是否覆盖已存在目标。
        """
        require_write()
        client = await get_client()
        return await client.post("/files/move", {
            "oldPaths": old_paths,
            "newPath": new_path,
            "type": "copy",
            "cover": cover,
            "coverPaths": [],
            "name": "",
        })

    @mcp.tool()
    async def file_rename(
        old_name: Annotated[str, Field(description="旧文件名/目录名（绝对路径）")],
        new_name: Annotated[str, Field(description="新文件名/目录名（绝对路径）")],
    ) -> dict:
        """⚠️写操作 [文件] 重命名文件/目录。

        对应 POST /files/rename（request.FileRename）。
        old_name/new_name 都是绝对路径（含父目录）。

        Args:
            old_name: 旧路径。
            new_name: 新路径。
        """
        require_write()
        client = await get_client()
        return await client.post("/files/rename", {
            "oldName": old_name,
            "newName": new_name,
        })

    # ============ 写：压缩 / 解压 ============

    @mcp.tool()
    async def file_compress(
        files: Annotated[list[str], Field(description="要打包的源文件/目录路径列表")],
        dst: Annotated[str, Field(description="输出压缩文件所在目录（绝对路径）")],
        name: Annotated[str, Field(description="压缩包文件名（不含扩展名）")],
        type: Annotated[CompressType, Field(description="压缩格式：zip/tar/tar.gz/tar.bz2/tar.xz")] = "zip",
        secret: Annotated[str, Field(description="压缩密码（仅 zip 支持，留空不加密）")] = "",
        replace: Annotated[bool, Field(description="目标已存在时是否覆盖")] = False,
    ) -> dict:
        """⚠️写操作 [文件] 压缩文件/目录为归档包。

        对应 POST /files/compress（request.FileCompress）。
        把 files 列表打包到 dst/name.type。

        Args:
            files: 源路径列表。
            dst: 输出目录。
            name: 压缩包名（不含扩展）。
            type: 压缩格式：zip/tar/tar.gz/tar.bz2/tar.xz。
            secret: zip 加密密码。
            replace: 是否覆盖已存在的目标包。
        """
        require_write()
        client = await get_client()
        return await client.post("/files/compress", {
            "files": files,
            "dst": dst,
            "name": name,
            "type": type,
            "secret": secret,
            "replace": replace,
        })

    @mcp.tool()
    async def file_decompress(
        path: Annotated[str, Field(description="压缩包绝对路径")],
        dst: Annotated[str, Field(description="解压目标目录（绝对路径）")],
        type: Annotated[CompressType, Field(description="压缩格式：zip/tar/tar.gz/tar.bz2/tar.xz")] = "zip",
        secret: Annotated[str, Field(description="解压密码（仅 zip 加密包需要）")] = "",
    ) -> dict:
        """⚠️写操作 [文件] 解压归档包到指定目录。

        对应 POST /files/decompress（request.FileDeCompress）。
        把 path 压缩包解压到 dst。

        Args:
            path: 压缩包绝对路径。
            dst: 解压目标目录。
            type: 压缩格式。
            secret: 解压密码。
        """
        require_write()
        client = await get_client()
        return await client.post("/files/decompress", {
            "path": path,
            "dst": dst,
            "type": type,
            "secret": secret,
        })

    # ============ 写：权限 / 属主 ============

    @mcp.tool()
    async def file_chmod(
        path: Annotated[str, Field(description="目标文件/目录绝对路径")],
        mode: Annotated[int, Field(description="权限 mode（八进制整型值，如 0o755=493）")],
        sub: Annotated[bool, Field(description="是否递归修改子项（chmod -R）")] = False,
    ) -> dict:
        """⚠️写操作 [文件] 修改文件/目录权限（chmod）。

        对应 POST /files/mode（request.FileCreate，仅用 path/mode/sub 字段）。
        mode 是八进制权限的整型值（Python 里 0o755 == 493）。

        Args:
            path: 目标路径。
            mode: 八进制权限整型值。
            sub: 是否递归。
        """
        require_write()
        client = await get_client()
        return await client.post("/files/mode", {
            "path": path,
            "mode": mode,
            "sub": sub,
        })

    @mcp.tool()
    async def file_chown(
        path: Annotated[str, Field(description="目标文件/目录绝对路径")],
        user: Annotated[str, Field(description="属主用户名，如 root")],
        group: Annotated[str, Field(description="属组名，如 root")],
        sub: Annotated[bool, Field(description="是否递归修改子项（chown -R）")] = False,
    ) -> dict:
        """⚠️写操作 [文件] 修改文件/目录属主和属组（chown）。

        对应 POST /files/owner（request.FileRoleUpdate）。

        Args:
            path: 目标路径。
            user: 属主用户名。
            group: 属组名。
            sub: 是否递归。
        """
        require_write()
        client = await get_client()
        return await client.post("/files/owner", {
            "path": path,
            "user": user,
            "group": group,
            "sub": sub,
        })

    @mcp.tool()
    async def file_batch_chmod(
        paths: Annotated[list[str], Field(description="目标路径列表")],
        mode: Annotated[int, Field(description="权限 mode（八进制整型值，如 0o644=420）")],
        user: Annotated[str, Field(description="属主用户名")] = "",
        group: Annotated[str, Field(description="属组名")] = "",
        sub: Annotated[bool, Field(description="是否递归修改子项")] = False,
    ) -> dict:
        """⚠️写操作 [文件] 批量修改多个文件/目录的权限（和属主属组）。

        对应 POST /files/batch/role（request.FileRoleReq），一次给 paths 全部设权限。
        user/group 留空则只改权限不改属主。

        Args:
            paths: 目标路径列表。
            mode: 八进制权限整型值。
            user: 属主用户名（留空不改）。
            group: 属组名（留空不改）。
            sub: 是否递归。
        """
        require_write()
        client = await get_client()
        return await client.post("/files/batch/role", {
            "paths": paths,
            "mode": mode,
            "user": user,
            "group": group,
            "sub": sub,
        })

    # ============ 写：远程下载（wget）============

    @mcp.tool()
    async def file_wget(
        url: Annotated[str, Field(description="下载地址（http/https）")],
        path: Annotated[str, Field(description="保存目录（绝对路径）")],
        name: Annotated[str, Field(description="保存文件名")],
        ignore_certificate: Annotated[bool, Field(description="是否忽略 TLS 证书校验")] = False,
    ) -> dict:
        """⚠️写操作 [文件] 从 URL 下载文件到指定目录（服务端 wget）。

        对应 POST /files/wget（request.FileWget）。1Panel 在服务端发起下载，
        适合拉取大文件到服务器（不经过客户端）。

        Args:
            url: 下载 URL。
            path: 保存目录。
            name: 保存文件名。
            ignore_certificate: 是否忽略 TLS 证书。
        """
        require_write()
        client = await get_client()
        return await client.post("/files/wget", {
            "url": url,
            "path": path,
            "name": name,
            "ignoreCertificate": ignore_certificate,
        })

    # ============ 写：收藏 / 备注 ============

    @mcp.tool()
    async def file_favorite(
        path: Annotated[str, Field(description="要收藏的文件/目录绝对路径")],
    ) -> dict:
        """⚠️写操作 [文件] 收藏文件/目录。

        对应 POST /files/favorite（request.FavoriteCreate），返回新建的 Favorite 记录。

        Args:
            path: 要收藏的路径。
        """
        require_write()
        client = await get_client()
        return await client.post("/files/favorite", {"path": path})

    @mcp.tool()
    async def file_favorite_delete(
        favorite_id: Annotated[int, Field(description="收藏记录 ID（file_favorite_list 返回的 id）")],
    ) -> dict:
        """⚠️写操作 [文件] 取消收藏（删除收藏记录，不删原文件）。

        对应 POST /files/favorite/del（request.FavoriteDelete）。
        注意：仅删除收藏标记，原文件不受影响。

        Args:
            favorite_id: 收藏记录 ID。
        """
        require_write()
        client = await get_client()
        return await client.post("/files/favorite/del", {"id": favorite_id})

    @mcp.tool()
    async def file_remark(
        path: Annotated[str, Field(description="文件/目录绝对路径")],
        remark: Annotated[str, Field(description="备注文本，留空表示清除备注")] = "",
    ) -> dict:
        """⚠️写操作 [文件] 设置/更新文件备注。

        对应 POST /files/remark（request.FileRemarkUpdate）。remark 留空清除备注。

        Args:
            path: 目标路径。
            remark: 备注内容。
        """
        require_write()
        client = await get_client()
        return await client.post("/files/remark", {
            "path": path,
            "remark": remark,
        })

    # ============ 写：文件格式转换 ============

    @mcp.tool()
    async def file_convert(
        path: Annotated[str, Field(description="输出目录（绝对路径）")],
        input_file: Annotated[str, Field(description="源文件绝对路径")],
        type: Annotated[str, Field(description="转换类型，如 office/pdf 等（1Panel 定义）")] = "",
        extension: Annotated[str, Field(description="源文件扩展名，如 docx")] = "",
        output_format: Annotated[str, Field(description="目标格式，如 pdf")] = "pdf",
        status: Annotated[str, Field(description="任务状态（一般留空）")] = "",
    ) -> dict:
        """⚠️写操作 [文件] 转换文件格式（如 office 转 pdf）。

        对应 POST /files/convert（request.FileConvert）。
        需要 1Panel 已配置对应转换工具（LibreOffice 等）。

        Args:
            path: 输出目录。
            input_file: 源文件路径。
            type: 转换类型。
            extension: 源文件扩展名。
            output_format: 目标格式。
            status: 任务状态。
        """
        require_write()
        client = await get_client()
        return await client.post("/files/convert", {
            "path": path,
            "inputFile": input_file,
            "type": type,
            "extension": extension,
            "outputFormat": output_format,
            "status": status,
        })

    # ============ 高危：删除 ============

    @mcp.tool()
    async def file_delete(
        path: Annotated[str, Field(description="待删除文件/目录绝对路径")],
        is_dir: Annotated[bool, Field(description="是否目录（影响删除方式）")] = False,
        force_delete: Annotated[bool, Field(description="True=直接物理删除；False=进回收站（若启用）")] = False,
        confirm: Annotated[bool, Field(description="删除是高危操作，必须传 true")] = False,
    ) -> dict:
        """⚠️高危 [文件] 删除文件或目录。

        对应 POST /files/del（request.FileDelete）。force_delete=false 且回收站启用时
        会进入回收站（可还原）；force_delete=true 直接物理删除不可恢复。

        必须显式传 confirm=true。

        Args:
            path: 待删除路径。
            is_dir: 是否目录。
            force_delete: True 物理删除，False 进回收站。
            confirm: 必须为 true。
        """
        require_write()
        if not confirm:
            raise ValueError("删除文件是高危操作，必须显式传 confirm=true。")
        client = await get_client()
        return await client.post("/files/del", {
            "path": path,
            "isDir": is_dir,
            "forceDelete": force_delete,
        })

    @mcp.tool()
    async def file_batch_delete(
        paths: Annotated[list[str], Field(description="待删除路径列表")],
        is_dir: Annotated[bool, Field(description="是否均为目录")] = False,
        confirm: Annotated[bool, Field(description="批量删除是高危操作，必须传 true")] = False,
    ) -> dict:
        """⚠️高危 [文件] 批量删除多个文件/目录。

        对应 POST /files/batch/del（request.FileBatchDelete）。
        批量删除可能不可逆，必须显式传 confirm=true。

        Args:
            paths: 待删除路径列表。
            is_dir: 是否均为目录。
            confirm: 必须为 true。
        """
        require_write()
        if not confirm:
            raise ValueError("批量删除是高危操作，必须显式传 confirm=true。")
        client = await get_client()
        return await client.post("/files/batch/del", {
            "paths": paths,
            "isDir": is_dir,
        })

    # ============ 回收站：还原 / 清空 ============

    @mcp.tool()
    async def file_recycle_restore(
        from_: Annotated[str, Field(description="回收站来源目录（RecycleBinDTO.from）")],
        r_name: Annotated[str, Field(description="回收站内条目名（RecycleBinDTO.rName）")],
        name: Annotated[str, Field(description="原始文件名（RecycleBinDTO.name，可留空）")] = "",
    ) -> dict:
        """⚠️写操作 [文件] 从回收站还原文件/目录。

        对应 POST /files/recycle/reduce（request.RecycleBinReduce）。
        把回收站条目还原到原始路径。from_/r_name 来自 file_recycle_list 的返回。

        注：Python 关键字 from 不能作参数名，故入参用 from_（带下划线）。

        Args:
            from_: 回收站来源目录（.Trash 目录下的来源子目录）。
            r_name: 回收站内的条目名（含时间戳前缀）。
            name: 原始文件名（可选）。
        """
        require_write()
        client = await get_client()
        return await client.post("/files/recycle/reduce", {
            "from": from_,
            "rName": r_name,
            "name": name,
        })

    @mcp.tool()
    async def file_recycle_clear(
        confirm: Annotated[bool, Field(description="清空回收站不可恢复，必须传 true")] = False,
    ) -> dict:
        """⚠️高危 [文件] 清空回收站（永久删除全部）。

        对应 POST /files/recycle/clear（无 body）。
        清空所有挂载点的回收站，不可恢复。必须显式传 confirm=true。

        Args:
            confirm: 必须为 true。
        """
        require_write()
        if not confirm:
            raise ValueError("清空回收站是高危操作（永久删除全部），必须显式传 confirm=true。")
        client = await get_client()
        return await client.post("/files/recycle/clear")

    # ============ 上传 / 下载（multipart，需要 client 扩展，暂留 TODO） ============
    #
    # /files/download        GET，无 body，返回文件流（二进制下载）
    # /files/chunkdownload   POST application/json（request.FileDownload），分块下载元信息
    # /files/upload          POST multipart/form-data（formData: file）
    # /files/chunkupload     POST multipart/form-data（formData: file），分块上传
    #
    # 这 4 个端点涉及二进制流 / multipart，当前 PanelClient 只支持 JSON body 与
    # URL params。完整支持需要扩展 client（加 files/content 参数 + 流式响应处理），
    # 此处暂不实现，避免半成品。file_upload_search 已覆盖上传任务历史查询；
    # file_wget 已覆盖「服务端拉取文件」场景。
