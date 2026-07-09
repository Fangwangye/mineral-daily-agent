"""采集真实 RSS + 一篇文章页面作为离线 fixture（供单测与 MINERAL_OFFLINE=1 离线模式）。

产物：
- src/mineral_daily/servers/news/data/rss_fixture.xml       mining.com RSS 原文
- src/mineral_daily/servers/news/data/article_fixture.html  RSS 内一篇文章的完整 HTML
- src/mineral_daily/servers/news/data/fixture_meta.json     采集时间与文章 URL

优先挑选含 lithium/Pilbara 关键词的条目，便于 Pilbara 锂矿类简报请求在离线模式下自然命中。

用法：python scripts/capture_news_fixture.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import feedparser  # noqa: E402

from mineral_daily.common import http  # noqa: E402

FEED_URL = "https://www.mining.com/feed/"
DATA_DIR = Path(__file__).resolve().parents[1] / "src/mineral_daily/servers/news/data"
PREFERRED_TERMS = ("lithium", "pilbara", "pls", "spodumene")


async def capture() -> None:
    fetched = await http.fetch_text(FEED_URL, cache_ttl=0)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "rss_fixture.xml").write_text(fetched.text, "utf-8")

    parsed = feedparser.parse(fetched.text)
    entries = parsed.entries
    if not entries:
        raise SystemExit("RSS 无条目，采集失败")
    print(f"[ok] RSS: {len(entries)} 条")

    def hit(e) -> bool:
        blob = (e.get("title", "") + " " + e.get("summary", "")).lower()
        return any(t in blob for t in PREFERRED_TERMS)

    chosen = next((e for e in entries if hit(e)), entries[0])
    url = chosen["link"]
    print(f"[ok] 选中文章: {chosen.get('title')!r} -> {url}")

    page = await http.fetch_text(url, cache_ttl=0, timeout=30)
    (DATA_DIR / "article_fixture.html").write_text(page.text, "utf-8")

    meta = {
        "captured_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "feed_url": FEED_URL,
        "article_url": url,
        "article_title": chosen.get("title"),
    }
    (DATA_DIR / "fixture_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), "utf-8"
    )
    print(f"[ok] fixture 已写入 {DATA_DIR}")


if __name__ == "__main__":
    asyncio.run(capture())
