"""测试辅助函数。

FastMCP 的 call_tool 返回 ContentBlock 序列（TextContent 为主），
返回 dict 时整体包成一个 TextContent（JSON 字符串），
返回 list 时逐元素各包一个 TextContent。
这里提供统一的解包 helper。
"""

from __future__ import annotations

import json
from typing import Any


def parse_tool_result(result: Any) -> Any:
    """把 FastMCP call_tool 的返回解包成原始 Python 对象。

    - ContentBlock 序列：每个取 text，JSON 解析
    - 单元素：直接返回解析后的对象
    - 多元素（list 展平场景）：返回 list
    - 已经是 dict/list：原样返回
    """
    if isinstance(result, (dict, list)) and not (
        isinstance(result, list) and result and hasattr(result[0], "text")
    ):
        return result

    if not isinstance(result, list):
        result = [result]

    texts = [getattr(b, "text", str(b)) for b in result]
    parsed = [json.loads(t) for t in texts]
    return parsed[0] if len(parsed) == 1 else parsed
