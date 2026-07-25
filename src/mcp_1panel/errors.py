"""统一异常类型。

1Panel v2 API 统一返回结构：{"code": int, "message": str, "data": ...}
- code == 200 成功
- code == 401 鉴权失败（key 错误 / IP 不在白名单 / 时间戳过期）
- code == 400 参数校验失败
- 其他非 200 视为业务/内部错误

错误透传原则：不吞错，把 1Panel 的原始 message 带给上层（FastMCP 会转成 MCP 错误响应）。
"""

from __future__ import annotations


class PanelError(Exception):
    """1Panel 调用错误的基类。"""


class PanelConfigError(PanelError):
    """配置错误：缺少 endpoint / api_key。"""


class PanelAuthError(PanelError):
    """鉴权失败（401）：key 错误、IP 不在白名单、时间戳过期。"""


class PanelAPIError(PanelError):
    """1Panel 返回业务错误（非 200 非 401）。

    Attributes:
        code: 1Panel 返回的 code 字段
        message: 1Panel 返回的 message 字段
    """

    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(f"1Panel API error {code}: {message}")


class PanelTransportError(PanelError):
    """网络/传输层错误：连接超时、DNS 失败、HTTP 5xx。"""


class PanelReadOnlyError(PanelError):
    """只读模式下调用写操作。"""
