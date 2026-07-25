"""分页与通用入参模型。

1Panel v2 的 search 类接口分页参数全部必填，缺 orderBy/order 会 400。
这里提供 Pydantic 模型让工具复用，保证默认值总被填上。
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

SortOrder = Literal["ascending", "descending"]
"""排序方向，1Panel 只接受这两个值。"""


class PageParams(BaseModel):
    """分页查询通用入参（所有 search 接口共用）。

    1Panel 要求 page/pageSize/orderBy/order 全部必填，否则返回：
        400 Field validation for 'OrderBy' failed on the 'required' tag
    """

    model_config = ConfigDict(extra="allow")  # 允许子类/调用方追加过滤字段

    page: Annotated[int, Field(ge=1, description="页码，从 1 开始")] = 1
    page_size: Annotated[int, Field(ge=1, le=500, description="每页数量，上限 500")] = 100
    order_by: Annotated[str, Field(description="排序字段（驼峰），如 createdAt/name/updatedAt；不同模块可选值不同，按 openapi.json 指定")] = "createdAt"
    order: Annotated[SortOrder, Field(description="排序方向：ascending 或 descending")] = "descending"

    def to_payload(self) -> dict:
        """转成 1Panel 期望的 camelCase body。

        1Panel API 用 pageSize（驼峰），不是 page_size（下划线）。
        orderBy 的可选值因模块而异，由调用方按 openapi.json 指定。
        """
        return {
            "page": self.page,
            "pageSize": self.page_size,
            "orderBy": self.order_by,
            "order": self.order,
        }


class IdInput(BaseModel):
    """按 id 操作的通用入参（start/stop/restart/delete 等用）。"""

    model_config = ConfigDict(extra="allow")

    id: Annotated[str, Field(description="资源 ID（1Panel 内部 ID，通常为字符串化的数字）")]
