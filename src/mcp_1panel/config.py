"""配置：从环境变量读取 1Panel 连接信息和 MCP 运行参数。

环境变量约定（与 mcphub compose 场景对齐）：
    PANEL_ENDPOINT   1Panel 面板地址，如 https://panel.example.com（不带尾斜杠）
    PANEL_API_KEY    1Panel「设置 → API 接口」里的密钥
    PANEL_TIMEOUT    请求超时秒数，默认 30
    PANEL_READONLY   "true" 时全局只读，写操作直接拒绝（Phase 5 启用）
    PANEL_MODULES    逗号分隔的启用模块列表（如 container,dashboard,monitor），空=注册全部。
                     未注册的模块既不会出现在 tools/list，也无法被 tools/call 调用。

    MCP_TRANSPORT    传输方式，默认 http（streamable-http），可选 stdio/sse（本地调试）
    MCP_HOST         HTTP 监听地址，容器内必须 0.0.0.0，默认 0.0.0.0
    MCP_PORT         HTTP 监听端口，默认 8000
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # 1Panel 面板连接
    panel_endpoint: str = Field(default="", description="1Panel 面板地址")
    panel_api_key: str = Field(default="", description="1Panel API 密钥")
    panel_timeout: float = Field(default=30.0, description="请求超时秒数")
    panel_readonly: bool = Field(default=False, description="只读模式，拒绝写操作")

    # 工具裁剪：全量 543 个工具的 schema 约 24 万 token，客户端按需启用模块
    panel_modules: str = Field(
        default="",
        description="逗号分隔的启用模块列表（dashboard/monitor/system/container/app/...），空=注册全部",
    )

    # MCP 传输
    mcp_transport: str = Field(default="http", description="传输方式: http/stdio/sse")
    mcp_host: str = Field(default="0.0.0.0", description="HTTP 监听地址")
    mcp_port: int = Field(default=8000, description="HTTP 监听端口")

    def assert_panel_configured(self) -> None:
        """启动时校验 1Panel 凭证已配置。"""
        if not self.panel_endpoint or not self.panel_api_key:
            raise RuntimeError(
                "缺少 1Panel 凭证：请设置 PANEL_ENDPOINT 和 PANEL_API_KEY 环境变量。"
                " 在 compose 中通过 environment 注入，详见 .env.example。"
            )


@lru_cache
def get_settings() -> Settings:
    """单例获取配置（lru_cache 保证全局唯一）。"""
    return Settings()
