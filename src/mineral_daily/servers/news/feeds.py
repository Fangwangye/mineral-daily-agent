"""RSS 新闻聚合数据层。

降级顺序：live RSS（10 分钟缓存）→ 任一 feed 失败记入 notes → 全部失败或离线时
回落打包 fixture（真实抓取的 mining.com RSS 快照，采集时间见 data/fixture_meta.json）。
fixture 模式下不做时间窗过滤（快照会随时间老化），notes 中明确标注。
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import feedparser

from mineral_daily.common import http

logger = logging.getLogger(__name__)

DEFAULT_FEEDS = ("https://www.mining.com/feed/",)
_DATA_DIR = Path(__file__).parent / "data"
_RSS_FIXTURE = _DATA_DIR / "rss_fixture.xml"
_FEED_CACHE_TTL = 600.0
_SUMMARY_LIMIT = 400


def feed_urls() -> list[str]:
    """feed 列表：NEWS_FEEDS 环境变量（逗号分隔）覆盖默认值。"""
    import os

    raw = os.environ.get("NEWS_FEEDS", "").strip()
    if raw:
        return [u.strip() for u in raw.split(",") if u.strip()]
    return list(DEFAULT_FEEDS)


def _strip_html(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()


def _entry_datetime(entry: Any) -> datetime | None:
    for attr in ("published_parsed", "updated_parsed"):
        t = entry.get(attr)
        if t:
            return datetime(t[0], t[1], t[2], t[3], t[4], t[5], tzinfo=UTC)
    return None


def _normalize(entry: Any, source: str) -> dict[str, Any] | None:
    link = entry.get("link")
    title = _strip_html(entry.get("title", ""))
    if not link or not title:
        return None
    published = _entry_datetime(entry)
    summary = _strip_html(entry.get("summary", ""))[:_SUMMARY_LIMIT]
    return {
        "title": title,
        "url": link,
        "source": source,
        "published": published.isoformat() if published else None,
        "summary": summary,
        "_dt": published,
    }


def _parse_feed(xml_text: str, fallback_source: str) -> list[dict[str, Any]]:
    parsed = feedparser.parse(xml_text)
    source = (parsed.feed.get("title") or fallback_source).strip()
    items = []
    for entry in parsed.entries:
        normalized = _normalize(entry, source)
        if normalized:
            items.append(normalized)
    return items


def tokenize(query: str) -> list[str]:
    """抽取查询词项：连续 2+ 位的字母数字或汉字串，小写化。"""
    return [t.lower() for t in re.findall(r"[A-Za-z0-9一-鿿]{2,}", query)]


def score_item(item: dict[str, Any], terms: list[str]) -> int:
    title = item["title"].lower()
    summary = item["summary"].lower()
    return sum(3 for t in terms if t in title) + sum(1 for t in terms if t in summary)


async def _collect_entries() -> tuple[list[dict[str, Any]], list[str], bool]:
    """抓取全部 feed。返回 (条目, 备注, 是否 fixture 模式)。"""
    entries: list[dict[str, Any]] = []
    notes: list[str] = []
    for url in feed_urls():
        try:
            fetched = await http.fetch_text(url, cache_ttl=_FEED_CACHE_TTL)
            items = _parse_feed(fetched.text, urlparse(url).netloc)
            if fetched.from_cache:
                notes.append(f"{url}: 使用本地缓存")
            entries.extend(items)
        except http.OfflineModeError:
            notes.append(f"{url}: 离线模式且无缓存")
        except Exception as exc:  # noqa: BLE001 - 单个 feed 失败不应中断聚合
            logger.warning("feed 抓取失败 %s: %s", url, exc)
            notes.append(f"{url}: 抓取失败 ({type(exc).__name__})")

    if entries:
        return entries, notes, False

    if _RSS_FIXTURE.exists():
        meta_path = _DATA_DIR / "fixture_meta.json"
        captured = ""
        if meta_path.exists():
            captured = json.loads(meta_path.read_text("utf-8")).get("captured_at", "")
        notes.append(f"全部 feed 不可用，使用打包 RSS fixture（真实快照，采集于 {captured}）")
        return _parse_feed(_RSS_FIXTURE.read_text("utf-8"), "mining.com [fixture]"), notes, True

    return [], notes, False


async def search(query: str, days: int = 7, limit: int = 20) -> dict[str, Any]:
    """按关键词检索近 N 天新闻，按相关度+时间排序。"""
    if not 1 <= days <= 60:
        raise ValueError("days 需在 1–60 之间")
    if not 1 <= limit <= 50:
        raise ValueError("limit 需在 1–50 之间")

    entries, notes, fixture_mode = await _collect_entries()

    seen: set[str] = set()
    deduped = []
    for e in entries:
        if e["url"] not in seen:
            seen.add(e["url"])
            deduped.append(e)

    cutoff = None if fixture_mode else datetime.now(UTC) - timedelta(days=days)
    if cutoff is not None:
        deduped = [e for e in deduped if e["_dt"] and e["_dt"] >= cutoff]

    terms = tokenize(query)
    results = []
    for e in deduped:
        s = score_item(e, terms)
        if terms and s == 0:
            continue
        results.append({**e, "score": s})

    epoch = datetime.min.replace(tzinfo=UTC)
    results.sort(key=lambda e: (e["score"], e["_dt"] or epoch), reverse=True)
    items = [{k: v for k, v in e.items() if k != "_dt"} for e in results[:limit]]

    if terms and not items:
        notes.append("无词项命中；建议改用英文关键词（新闻源为英文），如 'Pilbara lithium'")
    return {
        "query": query,
        "days": days,
        "count": len(items),
        "items": items,
        "notes": notes,
    }
