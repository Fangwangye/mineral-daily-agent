"""NI 43-101 / JORC 报告储量表解析（pdfplumber 确定性启发式，server 内不调 LLM）。

流程：关键词定位候选页（"Mineral Resource/Ore Reserve" + 类别词）→ 提取表格 →
表头列映射（吨位/品位/金属量）→ 类别行解析 → 单位归一（kt→Mt 等）。
结果带 confidence 与 raw 单元格：confidence < 0.5 视为 abstain（notes 提示人工核对），
宁可低置信也不硬给结论。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pdfplumber

from mineral_daily.common.parsing import parse_number

from .models import ExtractionResult, ResourceRow

logger = logging.getLogger(__name__)

DEFAULT_MAX_PAGES = 150

_KEYWORD_RE = re.compile(r"mineral\s+resources?|ore\s+reserves?", re.I)
_HAS_CAT_RE = re.compile(r"\b(measured|indicated|inferred|proved|probable)\b", re.I)
_CATEGORY_RE = re.compile(
    r"^\s*(measured\s*(?:\+|and)\s*indicated|measured|indicated|inferred"
    r"|proved|probable|total|subtotal)\b",
    re.I,
)

_TONNAGE_HDR_RE = re.compile(r"tonn|\bmt\b|million\s+tonnes|\bkt\b|000\s*t\b", re.I)
_GRADE_HDR_RE = re.compile(r"grade|g/t|%", re.I)
_METAL_HDR_RE = re.compile(r"contained|metal|\bmoz\b|\bkoz\b|\boz\b|\bkt\b", re.I)

_GRADE_UNIT_RE = re.compile(r"(g/t\s*[A-Za-z0-9]*|%\s*[A-Za-z][A-Za-z0-9]*)", re.I)
_METAL_UNIT_RE = re.compile(r"\b(moz|koz|oz|mlb|klb|kt|t)\b", re.I)


def _clean(cell: str | None) -> str:
    return re.sub(r"\s+", " ", (cell or "").strip())


def _find_header(table: list[list[str | None]]) -> int | None:
    """在表格前几行内找同时含吨位与品位语义的表头行。"""
    for i, row in enumerate(table[:4]):
        joined = " ".join(_clean(c) for c in row)
        if _TONNAGE_HDR_RE.search(joined) and _GRADE_HDR_RE.search(joined):
            return i
    return None


def _map_columns(header: list[str | None]) -> tuple[int | None, int | None, int | None]:
    """返回 (吨位列, 品位列, 金属量列) 下标。金属量列优先取 'contained/metal' 语义。"""
    cells = [_clean(c) for c in header]
    tonnage = grade = metal = None
    for idx, cell in enumerate(cells):
        low = cell.lower()
        if not low:
            continue
        if metal is None and ("contained" in low or "metal" in low):
            metal = idx
            continue
        if tonnage is None and _TONNAGE_HDR_RE.search(low):
            tonnage = idx
            continue
        if grade is None and ("grade" in low or "g/t" in low or "%" in low):
            grade = idx
    if metal is None:  # 兜底：品位列之后第一个含单位词的列
        for idx in range((grade or 0) + 1, len(cells)):
            if _METAL_UNIT_RE.search(cells[idx].lower()):
                metal = idx
                break
    return tonnage, grade, metal


def _tonnage_scale(header_cell: str) -> tuple[float, str | None]:
    """吨位列换算到 Mt。返回 (倍率, 换算说明)。"""
    low = header_cell.lower()
    if "mt" in low or "million" in low:
        return 1.0, None
    if "kt" in low or re.search(r"000\s*t\b", low):
        return 0.001, f"吨位列 {header_cell!r} 按 kt→Mt 换算(÷1000)"
    return 1.0, f"吨位列 {header_cell!r} 未识别单位，按 Mt 处理（请核对）"


def _extract_units(header: list[str | None], grade_col: int | None, metal_col: int | None):
    grade_unit = metal_unit = None
    if grade_col is not None and grade_col < len(header):
        m = _GRADE_UNIT_RE.search(_clean(header[grade_col]))
        if m:
            grade_unit = re.sub(r"\s+", " ", m.group(1)).strip()
    if metal_col is not None and metal_col < len(header):
        m = _METAL_UNIT_RE.search(_clean(header[metal_col]))
        if m:
            metal_unit = m.group(1).lower()
    return grade_unit, metal_unit


def _normalize_category(raw: str) -> str:
    low = re.sub(r"\s+", " ", raw.lower().strip())
    if re.match(r"measured\s*(\+|and)\s*indicated", low):
        return "Measured + Indicated"
    return low.split()[0].title()


def _parse_table(
    table: list[list[str | None]], page_no: int
) -> tuple[list[ResourceRow], float, list[str]]:
    notes: list[str] = []
    header_idx = _find_header(table)
    if header_idx is None:
        return [], 0.0, []
    header = table[header_idx]
    t_col, g_col, m_col = _map_columns(header)
    if t_col is None and g_col is None:
        return [], 0.0, []
    scale, scale_note = (1.0, None) if t_col is None else _tonnage_scale(_clean(header[t_col]))
    if scale_note:
        notes.append(f"p{page_no}: {scale_note}")
    grade_unit, metal_unit = _extract_units(header, g_col, m_col)

    def cell_at(cells: list[str], idx: int | None) -> float | None:
        if idx is None or idx >= len(cells):
            return None
        return parse_number(cells[idx])

    rows: list[ResourceRow] = []
    for raw_row in table[header_idx + 1 :]:
        cells = [_clean(c) for c in raw_row]
        if not cells or not cells[0] or not _CATEGORY_RE.match(cells[0]):
            continue
        tonnage = cell_at(cells, t_col)
        rows.append(
            ResourceRow(
                category=_normalize_category(cells[0]),
                ore_tonnage_mt=round(tonnage * scale, 4) if tonnage is not None else None,
                grade=cell_at(cells, g_col),
                grade_unit=grade_unit,
                contained_metal=cell_at(cells, m_col),
                metal_unit=metal_unit,
                page=page_no,
                raw=cells,
            )
        )
    if not rows:
        return [], 0.0, notes

    mapped = sum(col is not None for col in (t_col, g_col, m_col))
    confidence = 0.35 + 0.2 * mapped  # 三列齐全 0.95
    numeric_fields = [r.ore_tonnage_mt for r in rows] + [r.grade for r in rows]
    filled = sum(v is not None for v in numeric_fields) / max(len(numeric_fields), 1)
    confidence *= 0.5 + 0.5 * filled
    return rows, round(min(confidence, 0.95), 2), notes


_NUMERIC_REST_RE = re.compile(r"^[\s\d.,%()\-–]+$")
_NUM_TOKEN_RE = re.compile(r"-?\d[\d,.]*")


def _sniff_grade_unit(text: str) -> str | None:
    """从页面文本嗅探主品位单位（PDF 中下标常被拆成 'Li 2 O'，先归并）。"""
    squished = re.sub(r"(?<=[A-Za-z])\s+(?=\d)|(?<=\d)\s+(?=[A-Za-z])", "", text)
    m = re.search(r"g/t\s*(Au|Ag|Pt|Pd)\b", squished, re.I)
    if m:
        return f"g/t {m.group(1).title()}"
    for oxide in ("Li2O", "Ta2O5", "Fe2O3", "P2O5", "U3O8"):
        if oxide.lower() in squished.lower():
            return f"% {oxide}"
    m = re.search(r"%\s*(Cu|Ni|Zn|Pb|Co|Mn)\b|\b(Cu|Ni|Zn|Pb|Co|Mn)\s*%", squished)
    if m:
        return f"% {(m.group(1) or m.group(2)).title()}"
    return None


def _parse_text_lines(text: str, page_no: int) -> list[ResourceRow]:
    """无网格线表格的回退：解析 '类别 + 一串数字' 的文本行。

    守卫：类别词之后必须是纯数字串（拒绝叙述句），且至少 3 个数值。
    列语义按公告惯例取 [吨位, 首个品位, ...]，金属量不猜测（置 None）。
    """
    grade_unit = _sniff_grade_unit(text)
    rows: list[ResourceRow] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        m = _CATEGORY_RE.match(line)
        if not m:
            continue
        rest = line[m.end() :].strip()
        if not rest or not _NUMERIC_REST_RE.match(rest):
            continue
        nums = [parse_number(tok) for tok in _NUM_TOKEN_RE.findall(rest)]
        nums = [n for n in nums if n is not None]
        if len(nums) < 3:
            continue
        tonnage = nums[0]
        if not 0 < tonnage < 100_000:  # Mt 量级 sanity check
            continue
        rows.append(
            ResourceRow(
                category=_normalize_category(m.group(1)),
                ore_tonnage_mt=tonnage,
                grade=nums[1],
                grade_unit=grade_unit,
                contained_metal=None,
                metal_unit=None,
                page=page_no,
                raw=[line],
            )
        )
    return rows


def parse_pdf(
    path: Path | str, *, source: str | None = None, max_pages: int = DEFAULT_MAX_PAGES
) -> ExtractionResult:
    """解析 PDF，返回全部识别出的储量行与整体置信度。

    双通道：先按结构化表格（pdfplumber lines 策略）解析；关键词页无结构化产出时
    回退到文本行解析（无网格线的公告类表格），置信度上限 0.55 并在 notes 标注。
    """
    path = Path(path)
    all_rows: list[ResourceRow] = []
    notes: list[str] = []
    resource_pages: list[int] = []
    best_conf = 0.0
    used_text_fallback = False

    with pdfplumber.open(path) as pdf:
        total = len(pdf.pages)
        scan = pdf.pages[:max_pages]
        if total > max_pages:
            notes.append(f"报告共 {total} 页，仅扫描前 {max_pages} 页（PDF_MAX_PAGES 可调）")
        for page in scan:
            text = page.extract_text() or ""
            if not (_KEYWORD_RE.search(text) and _HAS_CAT_RE.search(text)):
                continue
            page_rows: list[ResourceRow] = []
            for table in page.extract_tables():
                rows, conf, table_notes = _parse_table(table, page.page_number)
                if rows:
                    page_rows.extend(rows)
                    notes.extend(table_notes)
                    best_conf = max(best_conf, conf)
            if not page_rows:
                fallback_rows = _parse_text_lines(text, page.page_number)
                if fallback_rows:
                    page_rows.extend(fallback_rows)
                    used_text_fallback = True
                    best_conf = max(best_conf, 0.55)
            if page_rows:
                all_rows.extend(page_rows)
                if page.page_number not in resource_pages:
                    resource_pages.append(page.page_number)

    if used_text_fallback:
        notes.append(
            "部分页面使用文本行回退解析（表格无网格线）：金属量列未抽取，"
            "品位单位为整页嗅探结果，请对照 raw 行人工核对"
        )

    if not all_rows:
        notes.append("未识别出储量表：可能为扫描件（无文本层）或表格样式超出启发式覆盖，建议人工处理")
    elif best_conf < 0.5:
        notes.append("置信度 < 0.5（abstain）：结果仅供参考，请对照 raw 单元格人工核对")

    return ExtractionResult(
        source=source or str(path),
        pages_scanned=min(total, max_pages),
        resource_pages=resource_pages,
        rows=all_rows,
        confidence=best_conf,
        notes=notes,
    )
