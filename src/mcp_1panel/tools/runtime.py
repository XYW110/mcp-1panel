"""运行时管理模块（对应 openapi.json 的 Runtime tag）。

⚠️ 与 website.py 的关系：website.py 已实现运行时主体生命周期相关的 9 个工具
（runtime_search / runtime_detail / runtime_operate / runtime_delete /
runtime_delete_check / runtime_sync 以及 PHP 扩展的 search/install/uninstall）。
**本文件只实现 website.py 未覆盖的 Runtime tag 接口**，避免重名注册报错。

覆盖范围（19 个工具）：
- 运行时 CRUD 增补：runtime_create / runtime_update / runtime_remark
- Node 运行时：runtime_node_modules / runtime_node_modules_operate /
  runtime_node_package_scripts
- PHP 配置/容器/FPM/文件：runtime_php_config_get / runtime_php_config_update /
  runtime_php_container_get / runtime_php_container_update /
  runtime_php_fpm_config_get / runtime_php_fpm_config_update /
  runtime_php_fpm_status / runtime_php_file_get / runtime_php_file_update /
  runtime_php_extensions_list
- Supervisor 进程：runtime_supervisor_process_get /
  runtime_supervisor_process_operate / runtime_supervisor_process_file

实现风格对齐黄金范式 container.py：
1. 工具名：<module>_<action>，所有写操作加 ⚠️
2. description：结构化，[运行时]/[PHP]/[Node]/[Supervisor] 开头，便于向量搜索召回
3. 入参用 Annotated[T, Field(description=...)]，复杂 body 在 handler 里拼 dict
4. handler 用 `await get_client()` 拿共享客户端，调 .post() / .get()
5. 写操作开头调 require_write()
6. docstring 的 Args 段补充参数语义（FastMCP 会解析进 inputSchema）

接口来源：references/openapi.json 的 /runtimes/* 路径，basePath /api/v2。
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Optional

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..client import get_client
from ..safety import require_write


def register(mcp: FastMCP) -> None:

    # ====================================================================
    # 运行时 CRUD 增补（search/detail/operate/delete/sync 已在 website.py）
    # ====================================================================

    @mcp.tool()
    async def runtime_create(
        name: Annotated[str, Field(description="运行时名称")],
        type: Annotated[str, Field(description="运行时类型：php/node/java/go/python 等")],
        version: Annotated[str, Field(description="版本号，如 8.2 / 18 / 17")],
        image: Annotated[str, Field(description="容器镜像名（自定义镜像时填）")] = "",
        source: Annotated[str, Field(description="来源：app_store（应用商店）/local（本地镜像）", )] = "app_store",
        app_detail_id: Annotated[int, Field(description="应用商店详情 ID（source=app_store 时必填）", )] = 0,
        resource: Annotated[str, Field(description="资源标识（应用商店来源时）")] = "",
        code_dir: Annotated[str, Field(description="代码挂载目录")] = "",
        install: Annotated[bool, Field(description="是否安装到 1Panel")] = True,
        clean: Annotated[bool, Field(description="是否清理临时文件")] = False,
        remark: Annotated[str, Field(description="备注")] = "",
    ) -> dict:
        """⚠️写操作 [运行时] 创建运行时（PHP/Node/Java/Go/Python 等）。

        新建一个运行时环境供网站绑定。对应 POST /runtimes。
        source=app_store 时需提供 app_detail_id/resource 指定应用商店镜像；
        source=local 时直接用 image 字段指定的本地/远程镜像。

        Args:
            name: 运行时名称（唯一）。
            type: 运行时类型。
            version: 版本号。
            image: 自定义镜像名（local 来源时必填）。
            source: app_store（从应用商店）或 local（本地镜像）。
            app_detail_id: 应用商店详情 ID（app_store 来源必填）。
            resource: 应用资源标识（app_store 来源）。
            code_dir: 代码挂载目录。
            install: 是否安装到 1Panel（false 仅记录不拉起容器）。
            clean: 是否清理临时构建文件。
            remark: 备注。
        """
        require_write()
        client = await get_client()
        body: dict[str, Any] = {
            "name": name,
            "type": type,
            "version": version,
            "source": source,
            "install": install,
            "clean": clean,
        }
        if image:
            body["image"] = image
        if app_detail_id:
            body["appDetailId"] = app_detail_id
        if resource:
            body["resource"] = resource
        if code_dir:
            body["codeDir"] = code_dir
        if remark:
            body["remark"] = remark
        return await client.post("/runtimes", body)

    @mcp.tool()
    async def runtime_update(
        runtime_id: Annotated[int, Field(description="运行时 ID")],
        name: Annotated[Optional[str], Field(description="运行时名称")] = None,
        version: Annotated[Optional[str], Field(description="版本号")] = None,
        image: Annotated[Optional[str], Field(description="容器镜像名")] = None,
        source: Annotated[Optional[str], Field(description="来源：app_store/local")] = None,
        code_dir: Annotated[Optional[str], Field(description="代码挂载目录")] = None,
        rebuild: Annotated[bool, Field(description="是否在更新后重建容器")] = False,
        clean: Annotated[bool, Field(description="是否清理临时文件")] = False,
        remark: Annotated[Optional[str], Field(description="备注")] = None,
    ) -> dict:
        """⚠️写操作 [运行时] 更新运行时配置。

        修改已存在的运行时配置（名称/版本/镜像等）。对应 POST /runtimes/update。
        rebuild=true 会在保存后重建容器使配置生效。

        Args:
            runtime_id: 运行时 ID。
            name: 运行时名称。
            version: 版本号。
            image: 容器镜像名。
            source: 来源。
            code_dir: 代码挂载目录。
            rebuild: 保存后是否重建容器。
            clean: 是否清理临时文件。
            remark: 备注。
        """
        require_write()
        client = await get_client()
        body: dict[str, Any] = {
            "id": runtime_id,
            "rebuild": rebuild,
            "clean": clean,
        }
        if name is not None:
            body["name"] = name
        if version is not None:
            body["version"] = version
        if image is not None:
            body["image"] = image
        if source is not None:
            body["source"] = source
        if code_dir is not None:
            body["codeDir"] = code_dir
        if remark is not None:
            body["remark"] = remark
        return await client.post("/runtimes/update", body)

    @mcp.tool()
    async def runtime_remark(
        runtime_id: Annotated[int, Field(description="运行时 ID")],
        remark: Annotated[str, Field(description="新备注内容")],
    ) -> dict:
        """⚠️写操作 [运行时] 更新运行时备注。

        仅修改备注字段，不影响运行时配置。对应 POST /runtimes/remark。

        Args:
            runtime_id: 运行时 ID。
            remark: 新备注。
        """
        require_write()
        client = await get_client()
        return await client.post("/runtimes/remark", {
            "id": runtime_id, "remark": remark,
        })

    # ====================================================================
    # Node 运行时（模块/包管理）
    # ====================================================================

    @mcp.tool()
    async def runtime_node_modules(
        runtime_id: Annotated[int, Field(description="Node 运行时 ID")],
    ) -> dict:
        """[Node] 列出 Node 运行时已安装的 npm 模块。读操作。

        返回该运行时项目下已安装的 node_modules（含名称/版本/description/license）。
        对应 POST /runtimes/node/modules。

        Args:
            runtime_id: Node 运行时 ID。
        """
        client = await get_client()
        return await client.post("/runtimes/node/modules", {"ID": runtime_id})

    @mcp.tool()
    async def runtime_node_modules_operate(
        runtime_id: Annotated[int, Field(description="Node 运行时 ID")],
        operate: Annotated[str, Field(description="操作类型，如 install/uninstall/update")],
        name: Annotated[str, Field(description="npm 模块名")] = "",
    ) -> dict:
        """⚠️写操作 [Node] 安装/卸载/更新 Node 运行时的 npm 模块。

        对 Node 运行时项目执行 npm 包管理操作。对应 POST /runtimes/node/modules/operate。

        Args:
            runtime_id: Node 运行时 ID。
            operate: 操作类型（install 安装 / uninstall 卸载 / update 更新 等）。
            name: 目标 npm 模块名。
        """
        require_write()
        client = await get_client()
        body: dict[str, Any] = {"ID": runtime_id, "operate": operate}
        if name:
            body["name"] = name
        return await client.post("/runtimes/node/modules/operate", body)

    @mcp.tool()
    async def runtime_node_package_scripts(
        code_dir: Annotated[str, Field(description="项目代码目录（含 package.json 的路径）")],
    ) -> dict:
        """[Node] 获取 Node 项目的 package.json 脚本（npm scripts）。读操作。

        读取指定目录下 package.json 的 scripts 段，返回可执行的 npm 脚本列表。
        对应 POST /runtimes/node/package。

        Args:
            code_dir: 项目代码目录（含 package.json）。
        """
        client = await get_client()
        return await client.post("/runtimes/node/package", {"codeDir": code_dir})

    # ====================================================================
    # PHP 运行时配置/容器/FPM/文件
    # ====================================================================

    @mcp.tool()
    async def runtime_php_config_get(
        runtime_id: Annotated[int, Field(description="PHP 运行时 ID")],
    ) -> dict:
        """[PHP] 获取 PHP 运行时配置（php.ini 关键项）。读操作。

        返回 PHP 运行时的核心配置（maxExecutionTime/uploadMaxSize/disableFunctions 等）。
        对应 GET /runtimes/php/config/{id}。

        Args:
            runtime_id: PHP 运行时 ID。
        """
        client = await get_client()
        return await client.get(f"/runtimes/php/config/{runtime_id}")

    @mcp.tool()
    async def runtime_php_config_update(
        runtime_id: Annotated[int, Field(description="PHP 运行时 ID")],
        scope: Annotated[str, Field(description="配置作用域，如 runtime/website")] = "runtime",
        max_execution_time: Annotated[Optional[str], Field(description="最大执行时间，如 30 / 300")] = None,
        upload_max_size: Annotated[Optional[str], Field(description="上传大小上限，如 50M")] = None,
        disable_functions: Annotated[Optional[list[str]], Field(description="禁用的函数名列表")] = None,
        params: Annotated[Optional[dict[str, str]], Field(description="其它自定义 php.ini 键值对")] = None,
    ) -> dict:
        """⚠️写操作 [PHP] 更新 PHP 运行时配置（php.ini 关键项）。

        修改 PHP 运行时的 max_execution_time / upload_max_size / disable_functions
        等核心参数。对应 POST /runtimes/php/config。

        Args:
            runtime_id: PHP 运行时 ID。
            scope: 配置作用域（runtime 运行时级 / website 网站级）。
            max_execution_time: 最大执行时间（秒）。
            upload_max_size: 上传大小上限。
            disable_functions: 禁用的函数名列表。
            params: 其它 php.ini 键值对。
        """
        require_write()
        client = await get_client()
        body: dict[str, Any] = {"id": runtime_id, "scope": scope}
        if max_execution_time is not None:
            body["maxExecutionTime"] = max_execution_time
        if upload_max_size is not None:
            body["uploadMaxSize"] = upload_max_size
        if disable_functions is not None:
            body["disableFunctions"] = disable_functions
        if params is not None:
            body["params"] = params
        return await client.post("/runtimes/php/config", body)

    @mcp.tool()
    async def runtime_php_container_get(
        runtime_id: Annotated[int, Field(description="PHP 运行时 ID")],
    ) -> dict:
        """[PHP] 获取 PHP 运行时容器配置（环境变量/端口/挂载/extra_hosts）。读操作。

        返回 PHP 运行时底层容器的运行参数。对应 GET /runtimes/php/container/{id}。

        Args:
            runtime_id: PHP 运行时 ID。
        """
        client = await get_client()
        return await client.get(f"/runtimes/php/container/{runtime_id}")

    @mcp.tool()
    async def runtime_php_container_update(
        runtime_id: Annotated[int, Field(description="PHP 运行时 ID")],
        container_name: Annotated[Optional[str], Field(description="容器名")] = None,
        environments: Annotated[Optional[list[dict[str, str]]], Field(description="环境变量列表 [{key,value}]")] = None,
        exposed_ports: Annotated[Optional[list[dict[str, Any]]], Field(description="端口映射列表 [{containerPort,hostPort,hostIP}]")] = None,
        extra_hosts: Annotated[Optional[list[dict[str, str]]], Field(description="extra_hosts 列表 [{hostname,ip}]")] = None,
        volumes: Annotated[Optional[list[dict[str, str]]], Field(description="卷挂载列表 [{source,target}]")] = None,
    ) -> dict:
        """⚠️写操作 [PHP] 更新 PHP 运行时容器配置。

        修改 PHP 运行时底层容器的环境变量/端口映射/挂载等。对应
        POST /runtimes/php/container/update。

        Args:
            runtime_id: PHP 运行时 ID。
            container_name: 容器名。
            environments: 环境变量列表，元素为 {key, value}。
            exposed_ports: 端口映射列表，元素为 {containerPort, hostPort, hostIP}。
            extra_hosts: extra_hosts 列表，元素为 {hostname, ip}。
            volumes: 卷挂载列表，元素为 {source, target}。
        """
        require_write()
        client = await get_client()
        body: dict[str, Any] = {"id": runtime_id}
        if container_name is not None:
            body["containerName"] = container_name
        if environments is not None:
            body["environments"] = environments
        if exposed_ports is not None:
            body["exposedPorts"] = exposed_ports
        if extra_hosts is not None:
            body["extraHosts"] = extra_hosts
        if volumes is not None:
            body["volumes"] = volumes
        return await client.post("/runtimes/php/container/update", body)

    @mcp.tool()
    async def runtime_php_fpm_config_get(
        runtime_id: Annotated[int, Field(description="PHP 运行时 ID")],
    ) -> dict:
        """[PHP] 获取 PHP-FPM 配置。读操作。

        返回 PHP-FPM 进程管理器配置（pm.max_children / pm.start_servers 等）。
        对应 GET /runtimes/php/fpm/config/{id}。

        Args:
            runtime_id: PHP 运行时 ID。
        """
        client = await get_client()
        return await client.get(f"/runtimes/php/fpm/config/{runtime_id}")

    @mcp.tool()
    async def runtime_php_fpm_config_update(
        runtime_id: Annotated[int, Field(description="PHP 运行时 ID")],
        params: Annotated[dict[str, Any], Field(description="PHP-FPM 配置键值对，如 {pm_max_children: 50}")],
    ) -> dict:
        """⚠️写操作 [PHP] 更新 PHP-FPM 配置。

        修改 PHP-FPM 进程管理器参数。对应 POST /runtimes/php/fpm/config。

        Args:
            runtime_id: PHP 运行时 ID。
            params: PHP-FPM 配置键值对（如 pm.max_children / pm.start_servers 等）。
        """
        require_write()
        client = await get_client()
        return await client.post("/runtimes/php/fpm/config", {
            "id": runtime_id, "params": params,
        })

    @mcp.tool()
    async def runtime_php_fpm_status(
        runtime_id: Annotated[int, Field(description="PHP 运行时 ID")],
    ) -> dict:
        """[PHP] 获取 PHP-FPM 运行状态。读操作。

        返回 PHP-FPM 的实时运行状态（pool 信息/进程数/请求统计等）。
        对应 GET /runtimes/php/fpm/status/{id}。

        Args:
            runtime_id: PHP 运行时 ID。
        """
        client = await get_client()
        return await client.get(f"/runtimes/php/fpm/status/{runtime_id}")

    @mcp.tool()
    async def runtime_php_file_get(
        runtime_id: Annotated[int, Field(description="PHP 运行时 ID")],
        type: Annotated[str, Field(description="配置文件类型，如 php/fpm/supervisor")],
    ) -> dict:
        """[PHP] 获取 PHP 运行时配置文件内容。读操作。

        返回指定类型配置文件的原始内容（如 php.ini / fpm.conf）。
        对应 POST /runtimes/php/file。

        Args:
            runtime_id: PHP 运行时 ID。
            type: 配置文件类型（php / fpm / supervisor 等）。
        """
        client = await get_client()
        return await client.post("/runtimes/php/file", {
            "id": runtime_id, "type": type,
        })

    @mcp.tool()
    async def runtime_php_file_update(
        runtime_id: Annotated[int, Field(description="PHP 运行时 ID")],
        type: Annotated[str, Field(description="配置文件类型，如 php/fpm/supervisor")],
        content: Annotated[str, Field(description="配置文件完整内容")],
    ) -> dict:
        """⚠️写操作 [PHP] 更新 PHP 运行时配置文件内容。

        覆盖写入指定类型的配置文件（如 php.ini / fpm.conf）。
        对应 POST /runtimes/php/update。⚠️ 直接覆盖原始配置，修改前建议先调用
        runtime_php_file_get 备份现有内容。

        Args:
            runtime_id: PHP 运行时 ID。
            type: 配置文件类型。
            content: 配置文件完整内容（覆盖写）。
        """
        require_write()
        client = await get_client()
        return await client.post("/runtimes/php/update", {
            "id": runtime_id, "type": type, "content": content,
        })

    @mcp.tool()
    async def runtime_php_extensions_list(
        runtime_id: Annotated[int, Field(description="PHP 运行时 ID（字符串形式，路径参数）")],
    ) -> dict:
        """[PHP] 按运行时 ID 获取 PHP 扩展列表。读操作。

        返回指定 PHP 运行时已安装的扩展列表。对应 GET /runtimes/php/{id}/extensions。
        与 website.py 的 runtime_php_extensions_search（POST 分页查询）不同，
        此接口按运行时 ID 路径直接取该运行时的扩展。

        Args:
            runtime_id: PHP 运行时 ID。
        """
        client = await get_client()
        return await client.get(f"/runtimes/php/{runtime_id}/extensions")

    # ====================================================================
    # Supervisor 进程管理（PHP 运行时常驻进程守护）
    # ====================================================================

    @mcp.tool()
    async def runtime_supervisor_process_get(
        runtime_id: Annotated[int, Field(description="PHP 运行时 ID")],
    ) -> dict:
        """[Supervisor] 获取 PHP 运行时的 Supervisor 进程列表。读操作。

        返回该运行时下所有 Supervisor 守护进程配置及运行状态。
        对应 GET /runtimes/supervisor/process/{id}。

        Args:
            runtime_id: PHP 运行时 ID。
        """
        client = await get_client()
        return await client.get(f"/runtimes/supervisor/process/{runtime_id}")

    @mcp.tool()
    async def runtime_supervisor_process_operate(
        runtime_id: Annotated[int, Field(description="PHP 运行时 ID")],
        operate: Annotated[str, Field(description="操作类型：create/update/start/stop/restart/delete 等")],
        name: Annotated[str, Field(description="进程名")] = "",
        command: Annotated[str, Field(description="进程启动命令")] = "",
        dir: Annotated[str, Field(description="工作目录")] = "",
        user: Annotated[str, Field(description="运行用户")] = "",
        numprocs: Annotated[str, Field(description="进程数，如 1/4")] = "",
        auto_start: Annotated[str, Field(description="是否自动启动：true/false")] = "",
        auto_restart: Annotated[str, Field(description="是否自动重启：true/false")] = "",
        environment: Annotated[str, Field(description="环境变量，如 KEY=val,KEY2=val2")] = "",
    ) -> dict:
        """⚠️写操作 [Supervisor] 创建/更新/启停/删除 Supervisor 守护进程。

        对 PHP 运行时的 Supervisor 进程执行生命周期管理。对应
        POST /runtimes/supervisor/process。

        Args:
            runtime_id: PHP 运行时 ID。
            operate: 操作类型（create 创建 / update 更新 / start 启动 /
                stop 停止 / restart 重启 / delete 删除 等）。
            name: 进程名（operate=create/update 时必填）。
            command: 进程启动命令（create 时必填）。
            dir: 工作目录。
            user: 运行用户。
            numprocs: 进程数。
            auto_start: 是否自动启动（true/false）。
            auto_restart: 是否自动重启（true/false）。
            environment: 环境变量（逗号分隔 KEY=val）。
        """
        require_write()
        client = await get_client()
        body: dict[str, Any] = {"id": runtime_id, "operate": operate}
        if name:
            body["name"] = name
        if command:
            body["command"] = command
        if dir:
            body["dir"] = dir
        if user:
            body["user"] = user
        if numprocs:
            body["numprocs"] = numprocs
        if auto_start:
            body["autoStart"] = auto_start
        if auto_restart:
            body["autoRestart"] = auto_restart
        if environment:
            body["environment"] = environment
        return await client.post("/runtimes/supervisor/process", body)

    @mcp.tool()
    async def runtime_supervisor_process_file(
        runtime_id: Annotated[int, Field(description="PHP 运行时 ID")],
        name: Annotated[str, Field(description="进程名")],
        operate: Annotated[Literal["get", "clear", "update"], Field(description="操作：get 读取 / clear 清空 / update 更新")],
        file: Annotated[Literal["out.log", "err.log", "config"], Field(description="目标文件：out.log 标准输出 / err.log 错误输出 / config 进程配置")],
        content: Annotated[str, Field(description="文件新内容（operate=update 时必填）")] = "",
    ) -> dict:
        """⚠️写操作 [Supervisor] 读取/清空/更新 Supervisor 进程文件。

        操作 Supervisor 守护进程关联的文件：标准输出日志、错误输出日志、进程配置。
        对应 POST /runtimes/supervisor/process/file。

        Args:
            runtime_id: PHP 运行时 ID。
            name: 进程名。
            operate: get 读取 / clear 清空 / update 更新（覆盖写）。
            file: out.log 标准输出日志 / err.log 错误输出日志 / config 进程配置。
            content: operate=update 时的文件新内容。
        """
        require_write()
        client = await get_client()
        body: dict[str, Any] = {
            "id": runtime_id,
            "name": name,
            "operate": operate,
            "file": file,
        }
        if content:
            body["content"] = content
        return await client.post("/runtimes/supervisor/process/file", body)
