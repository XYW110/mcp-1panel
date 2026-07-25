"""读写安全分层。

- 写操作（create/update/delete/install/restart/operate 等）受 PANEL_READONLY 控制
- 高危操作（delete/del/remove）需要显式 confirm 参数
- 工具 description 自动加 ⚠️ 标记由各工具自行写明（此处只管运行时拦截）
"""

from __future__ import annotations

from functools import wraps
from typing import Any, Awaitable, Callable

from .config import get_settings
from .errors import PanelReadOnlyError


def require_write():
    """运行时校验：只读模式下调用写操作直接拒绝。

    在写工具 handler 开头调用 `require_write()`。
    """
    if get_settings().panel_readonly:
        raise PanelReadOnlyError(
            "当前为只读模式（PANEL_READONLY=true），写操作被拒绝。"
            " 如需执行写操作，请关闭只读模式后重启。"
        )


def write_op(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
    """装饰器：标记为写操作。只读模式下被装饰函数直接抛 PanelReadOnlyError。

    用法：
        @mcp.tool
        @write_op
        async def container_start(...): ...
    """

    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        require_write()
        return await func(*args, **kwargs)

    return wrapper
