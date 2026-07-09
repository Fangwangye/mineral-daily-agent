"""mining-news-mcp 测试：离线 fixture 路径 + respx 模拟的 live 路径。"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from pathlib import Path

import httpx
import pytest
import respx

from mineral_daily.servers.news import article, feeds

FIXTURE_META = json.loads(
    (
        Path(__file__).resolve().parents[1]
        / "src/mineral_daily/servers/news/data/fixture_meta.json"
    ).read_text("utf-8")
)


class TestScoring:
    def test_tokenize_mixed_language(self):
        assert feeds.tokenize("Pilbara lithium 锂矿价格!") == [
            "pilbara",
            "lithium",
            "锂矿价格",
        ]

    def test_score_title_weighted_over_summary(self):
        item = {"title": "Pilbara update", "summary": "lithium market news"}
        assert feeds.score_item(item, ["pilbara"]) == 3
        assert feeds.score_item(item, ["lithium"]) == 1
        assert feeds.score_item(item, ["pilbara", "lithium"]) == 4


class TestOfflineSearch:
    """MINERAL_OFFLINE=1（conftest 注入）→ 回落打包 RSS fixture。"""

    async def test_falls_back_to_fixture(self):
        result = await feeds.search("lithium", days=7, limit=5)
        assert result["count"] >= 1
        assert any("fixture" in n for n in result["notes"])
        assert all(it["score"] > 0 for it in result["items"])

    async def test_limit_respected(self):
        result = await feeds.search("", days=7, limit=3)
        assert result["count"] <= 3

    async def test_param_validation(self):
        with pytest.raises(ValueError, match="days"):
            await feeds.search("x", days=0)
        with pytest.raises(ValueError, match="limit"):
            await feeds.search("x", limit=0)


class TestOfflineArticle:
    async def test_fixture_article_extracts(self):
        result = await article.fetch_article(FIXTURE_META["article_url"])
        assert result["title"]
        assert len(result["text"]) > 200
        assert "fixture" in result.get("note", "")

    async def test_unknown_url_raises_with_hint(self):
        with pytest.raises(ValueError, match="离线模式"):
            await article.fetch_article("https://example.com/nope")

    async def test_non_http_url_rejected(self):
        with pytest.raises(ValueError, match="http"):
            await article.fetch_article("file:///etc/passwd")


def _rss(entries: list[tuple[str, str, datetime]]) -> str:
    items = "".join(
        f"<item><title>{title}</title><link>{link}</link>"
        f"<pubDate>{format_datetime(dt)}</pubDate>"
        f"<description>desc</description></item>"
        for title, link, dt in entries
    )
    return (
        '<?xml version="1.0"?><rss version="2.0"><channel>'
        f"<title>Test Feed</title>{items}</channel></rss>"
    )


class TestLiveSearch:
    """respx 模拟 live feed（无真实外网），验证时间窗过滤。"""

    @respx.mock
    async def test_window_filters_old_entries(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("MINERAL_OFFLINE")
        now = datetime.now(UTC)
        xml = _rss(
            [
                ("Fresh lithium news", "https://t.example/fresh", now - timedelta(days=1)),
                ("Stale lithium news", "https://t.example/stale", now - timedelta(days=30)),
            ]
        )
        respx.get("https://www.mining.com/feed/").mock(
            return_value=httpx.Response(200, text=xml)
        )
        result = await feeds.search("lithium", days=7, limit=10)
        urls = [it["url"] for it in result["items"]]
        assert urls == ["https://t.example/fresh"]

    @respx.mock
    async def test_feed_error_falls_back_to_fixture(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("MINERAL_OFFLINE")
        respx.get("https://www.mining.com/feed/").mock(
            return_value=httpx.Response(503, text="boom")
        )
        result = await feeds.search("lithium", days=7, limit=5)
        assert any("fixture" in n for n in result["notes"])
        assert result["count"] >= 1
