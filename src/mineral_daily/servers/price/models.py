"""lme-price-mcp 工具输出模型（作为 MCP outputSchema 发布，client 可拿到结构化校验）。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class PricePointOut(BaseModel):
    date: str = Field(description="交易日 YYYY-MM-DD")
    price: float


class PriceQuote(BaseModel):
    """单日价格。"""

    commodity: str
    name: str = Field(description="价格口径全称")
    requested_date: str
    date: str = Field(description="实际命中的交易日（非交易日自动回退）")
    price: float
    unit: str
    source: str
    is_live: bool = Field(description="False 表示来自快照/缓存而非实时抓取")
    note: str | None = None


class PriceTrend(BaseModel):
    """近 N 天走势与统计。"""

    commodity: str
    name: str
    unit: str
    source: str
    is_live: bool
    days: int
    start_date: str
    end_date: str
    start_price: float
    end_price: float
    change_pct: float
    min: float
    max: float
    direction: str = Field(description="up | down | sideways（±2% 阈值）")
    points: list[PricePointOut]
