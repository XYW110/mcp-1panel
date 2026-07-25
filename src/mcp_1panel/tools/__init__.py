"""tools 包：按 1Panel openapi.json 的 tag 拆分业务模块。

每个模块文件导出 `register(mcp: FastMCP) -> None`，把本模块的工具注册到 mcp 实例。
命名规范：<module>_<action>（如 container_search / website_create）。
"""
