"""新闻全文抽取：httpx 抓取（24h 缓存）+ trafilatura 正文解析。

离线时仅可用已缓存 URL 或打包 fixture 文章（真实抓取的 mining.com 页面）。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import trafilatura

from mineral_daily.common import http

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parent / "data"
_ARTICLE_FIXTURE = _DATA_DIR / "article_fixture.html"
_FIXTURE_META = _DATA_DIR / "fixture_meta.json"
_TEXT_LIMIT = 8000


def _fixture_meta() -> dict[str, Any]:
    if _FIXTURE_META.exists():
        return json.loads(_FIXTURE_META.read_text("utf-8"))
    return {}


def _extract(html: str, url: str) -> dict[str, Any]:
    try:
        raw = trafilatura.extract(
            html, url=url, output_format="json", with_metadata=True, include_comments=False
        )
    except TypeError:  # 兼容旧版 trafilatura 无 with_metadata 参数
        raw = trafilatura.extract(html, url=url, output_format="json", include_comments=False)
    if not raw:
        raise ValueError(f"正文抽取失败（页面可能非文章页）: {url}")
    data = json.loads(raw)
    text = (data.get("text") or "").strip()
    truncated = len(text) > _TEXT_LIMIT
    if truncated:
        text = text[:_TEXT_LIMIT] + "\n…[已截断]"
    return {
        "url": url,
        "title": data.get("title"),
        "author": data.get("author"),
        "published": data.get("date"),
        "text": text,
        "truncated": truncated,
    }


async def fetch_article(url: str) -> dict[str, Any]:
    """抓取并抽取一篇文章的正文与元数据。"""
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"仅支持 http(s) URL: {url}")
    note = None
    try:
        fetched = await http.fetch_text(url, cache_ttl=86400.0)
        html = fetched.text
        if fetched.from_cache:
            note = "来自本地缓存"
    except http.OfflineModeError:
        meta = _fixture_meta()
        fixture_url = meta.get("article_url")
        if _ARTICLE_FIXTURE.exists() and url == fixture_url:
            html = _ARTICLE_FIXTURE.read_text("utf-8")
            note = f"离线 fixture（真实页面快照，采集于 {meta.get('captured_at', '?')}）"
        else:
            hint = f"；离线可用 fixture URL: {fixture_url}" if fixture_url else ""
            raise ValueError(f"离线模式且该 URL 无缓存: {url}{hint}") from None

    result = _extract(html, url)
    if note:
        result["note"] = note
    return result
