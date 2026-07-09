"""mineral-pdf-mcp 输出模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ResourceRow(BaseModel):
    """储量表中的一行（一个资源类别）。"""

    category: str = Field(description="Measured / Indicated / Inferred / Total 等")
    ore_tonnage_mt: float | None = Field(None, description="矿石量，百万吨 (Mt)")
    grade: float | None = Field(None, description="品位数值")
    grade_unit: str | None = Field(None, description="品位单位，如 '% Li2O'、'g/t Au'")
    contained_metal: float | None = Field(None, description="金属量数值")
    metal_unit: str | None = Field(None, description="金属量单位，如 'kt'、'koz'")
    page: int = Field(description="来源页码（1 起）")
    raw: list[str] = Field(default_factory=list, description="原始单元格，便于人工核对")


class ExtractionResult(BaseModel):
    """一次 PDF 储量抽取的完整结果。"""

    source: str = Field(description="输入的 pdf_url / 路径")
    pages_scanned: int
    resource_pages: list[int] = Field(description="识别出储量表的页码")
    rows: list[ResourceRow]
    confidence: float = Field(description="0–1 启发式置信度；<0.5 视为 abstain，需人工核对")
    notes: list[str] = Field(default_factory=list)
