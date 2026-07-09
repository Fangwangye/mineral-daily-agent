"""mining-news-mcp 工具输出模型（作为 MCP outputSchema 发布）。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class NewsItem(BaseModel):
    title: str
    url: str
    source: str
    published: str | None = Field(None, description="ISO 8601，feed 未提供时为 null")
    summary: str
    score: int = Field(description="词项命中得分（标题×3 + 摘要×1）")


class NewsSearchResult(BaseModel):
    query: str
    days: int
    count: int
    items: list[NewsItem]
    notes: list[str] = Field(description="降级/缓存/离线等数据可用性说明")


class Article(BaseModel):
    url: str
    title: str | None = None
    author: str | None = None
    published: str | None = None
    text: str
    truncated: bool
    note: str | None = None
