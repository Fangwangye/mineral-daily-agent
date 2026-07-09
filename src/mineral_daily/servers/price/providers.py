"""价格数据层。

数据源与降级策略（详见 README「数据降级」一节）：
- copper / zinc / nickel：westmetall.com 免费镜像的 LME 官方结算价，live 抓取
  （6h 磁盘缓存）→ 失败回落打包快照。
- lithium_carbonate / iron_ore：SMM / 上海钢联 / GFEX 官方源均有登录墙或频控，
  使用打包快照序列，来源与截止日期随字段返回，不伪装成实时数据。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from mineral_daily.common import http

logger = logging.getLogger(__name__)

WESTMETALL_URL = "https://www.westmetall.com/en/markdaten.php?action=table&field={field}"
_SNAPSHOT_PATH = Path(__file__).parent / "data" / "prices_snapshot.json"
_LIVE_CACHE_TTL = 6 * 3600.0

COMMODITIES: dict[str, dict[str, Any]] = {
    "copper": {
        "name": "LME Copper cash settlement",
        "westmetall_field": "LME_Cu_cash",
        "unit": "USD/t",
    },
    "zinc": {
        "name": "LME Zinc cash settlement",
        "westmetall_field": "LME_Zn_cash",
        "unit": "USD/t",
    },
    "nickel": {
        "name": "LME Nickel cash settlement",
        "westmetall_field": "LME_Ni_cash",
        "unit": "USD/t",
    },
    "lithium_carbonate": {
        "name": "Lithium carbonate 99.5% battery grade, China spot",
        "westmetall_field": None,
        "unit": "CNY/t",
    },
    "iron_ore": {
        "name": "Iron ore fines 62% Fe, CFR China",
        "westmetall_field": None,
        "unit": "USD/t",
    },
}

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}

# westmetall 表格行形如: <tr><td>18. June 2026</td><td>9 456,00</td><td>...</td></tr>
_ROW_PAT = re.compile(
    r"<tr[^>]*>\s*<td[^>]*>\s*(\d{1,2})\.\s*([A-Za-z]+)\s*(\d{4})\s*</td>\s*<td[^>]*>([^<]+)</td>",
    re.IGNORECASE,
)


@dataclass
class PricePoint:
    day: date
    price: float


@dataclass
class PriceSeries:
    commodity: str
    unit: str
    source: str
    is_live: bool
    points: list[PricePoint]  # 按日期升序


def parse_number(raw: str) -> float | None:
    """解析欧式/美式混排数字："9 456,00"、"9.456,00"、"9,456.00"、"9456"。"""
    s = raw.replace("\xa0", " ").replace("&nbsp;", " ").strip()
    s = re.sub(r"\s+", "", s)
    if not s or not re.search(r"\d", s):
        return None
    if "," in s and "." in s:
        # 最后出现的分隔符是小数点
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        head, _, tail = s.rpartition(",")
        if len(tail) == 3 and head:  # 千分位
            s = s.replace(",", "")
        else:
            s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def parse_westmetall(html: str) -> list[PricePoint]:
    """从 westmetall 历史表 HTML 解析 (日期, 结算价) 序列，升序返回。"""
    points: list[PricePoint] = []
    for m in _ROW_PAT.finditer(html):
        day_s, month_s, year_s, price_s = m.groups()
        month = _MONTHS.get(month_s.lower())
        if month is None:
            continue
        price = parse_number(price_s)
        if price is None:
            continue
        try:
            d = date(int(year_s), month, int(day_s))
        except ValueError:
            continue
        points.append(PricePoint(day=d, price=price))
    points.sort(key=lambda p: p.day)
    return points


def _load_snapshot() -> dict[str, Any]:
    with _SNAPSHOT_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _snapshot_series(commodity: str) -> PriceSeries:
    snap = _load_snapshot().get(commodity)
    if not snap or not snap.get("series"):
        raise ValueError(f"快照中没有 {commodity} 的数据")
    points = [
        PricePoint(day=date.fromisoformat(p["date"]), price=float(p["price"]))
        for p in snap["series"]
    ]
    points.sort(key=lambda p: p.day)
    return PriceSeries(
        commodity=commodity,
        unit=snap["unit"],
        source=f"{snap['source']} [快照, 截至 {snap['as_of']}]",
        is_live=False,
        points=points,
    )


async def fetch_westmetall_series(field: str) -> list[PricePoint]:
    """抓取 westmetall 全量历史表（公开页面，带 6h 缓存避免频繁请求）。"""
    fetched = await http.fetch_text(
        WESTMETALL_URL.format(field=field), cache_ttl=_LIVE_CACHE_TTL
    )
    points = parse_westmetall(fetched.text)
    if not points:
        raise ValueError("westmetall 页面解析结果为空（页面结构可能已变化）")
    return points


async def get_series(commodity: str, days: int) -> PriceSeries:
    """获取近 N 天价格序列：live 优先，任何失败回落快照。"""
    meta = COMMODITIES.get(commodity)
    if meta is None:
        raise ValueError(
            f"未知 commodity: {commodity!r}，可选值: {', '.join(sorted(COMMODITIES))}"
        )
    cutoff = date.today() - timedelta(days=days)
    field = meta["westmetall_field"]
    if field:
        try:
            points = await fetch_westmetall_series(field)
            windowed = [p for p in points if p.day >= cutoff]
            if windowed:
                return PriceSeries(
                    commodity=commodity,
                    unit=meta["unit"],
                    source="westmetall.com (LME official settlement mirror)",
                    is_live=True,
                    points=windowed,
                )
            logger.warning("westmetall %s 在时间窗内无数据，回落快照", commodity)
        except Exception as exc:  # noqa: BLE001 - 任何 live 失败都应降级而非中断
            logger.warning("live 价格抓取失败 (%s)，回落快照: %s", commodity, exc)
    series = _snapshot_series(commodity)
    windowed = [p for p in series.points if p.day >= cutoff]
    if windowed:
        series.points = windowed
    else:
        # 快照过旧时保留最近 10 个点并在 source 中已标注截止日期
        series.points = series.points[-10:]
    return series


async def price_on(commodity: str, date_str: str | None = None) -> dict[str, Any]:
    """单日价格：取 <= 目标日的最近交易日（周末/假日自动回退）。"""
    target = date.fromisoformat(date_str) if date_str else date.today()
    lookback = max((date.today() - target).days + 45, 45)
    series = await get_series(commodity, days=lookback)
    eligible = [p for p in series.points if p.day <= target]
    if not eligible:
        raise ValueError(
            f"{commodity} 在 {target.isoformat()} 及之前无可用数据"
            f"（最早数据点: {series.points[0].day.isoformat()}）"
        )
    hit = eligible[-1]
    result: dict[str, Any] = {
        "commodity": commodity,
        "name": COMMODITIES[commodity]["name"],
        "requested_date": target.isoformat(),
        "date": hit.day.isoformat(),
        "price": hit.price,
        "unit": series.unit,
        "source": series.source,
        "is_live": series.is_live,
    }
    if hit.day != target:
        result["note"] = "目标日无报价（非交易日或数据缺口），返回最近一个交易日"
    return result


async def trend(commodity: str, days: int = 30) -> dict[str, Any]:
    """近 N 天走势：序列 + 涨跌统计。"""
    if not 1 <= days <= 180:
        raise ValueError("days 需在 1–180 之间")
    series = await get_series(commodity, days=days)
    if not series.points:
        raise ValueError(f"{commodity} 无可用数据")
    prices = [p.price for p in series.points]
    start, end = prices[0], prices[-1]
    change_pct = (end - start) / start * 100 if start else 0.0
    if change_pct > 2:
        direction = "up"
    elif change_pct < -2:
        direction = "down"
    else:
        direction = "sideways"
    return {
        "commodity": commodity,
        "name": COMMODITIES[commodity]["name"],
        "unit": series.unit,
        "source": series.source,
        "is_live": series.is_live,
        "days": days,
        "start_date": series.points[0].day.isoformat(),
        "end_date": series.points[-1].day.isoformat(),
        "start_price": start,
        "end_price": end,
        "change_pct": round(change_pct, 2),
        "min": min(prices),
        "max": max(prices),
        "direction": direction,
        "points": [{"date": p.day.isoformat(), "price": p.price} for p in series.points],
    }
