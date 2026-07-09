"""Agent 离线 E2E：FakeLLM 脚本化决策 + 真实 MCP stdio 全链路。

验证点：3 个 server 子进程拉起与握手、5 个工具自动发现、并行工具调用、
结果回喂、简报落盘。不依赖外网与 LLM API key。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mineral_daily.agent import briefing
from mineral_daily.agent.llm import LLMReply, ToolCall
from mineral_daily.agent.mcp_client import MCPFleet, resolve_specs
from mineral_daily.agent.react import run_agent

EXPECTED_TOOLS = {
    "news__search",
    "news__fetch_article",
    "pdf__extract_resources",
    "price__get_price",
    "price__get_trend",
}


class FakeLLM:
    """第 1 轮并行调用三个 server 的工具，第 2 轮基于工具结果输出简报。"""

    def __init__(self) -> None:
        self.rounds = 0
        self.tool_results: list[str] = []

    async def chat(self, messages: list[dict], tools: list[dict] | None = None) -> LLMReply:
        self.rounds += 1
        if self.rounds == 1:
            assert tools is not None
            assert {t["function"]["name"] for t in tools} == EXPECTED_TOOLS
            return LLMReply(
                content=None,
                tool_calls=[
                    ToolCall("c1", "news__search", {"query": "lithium", "days": 7, "limit": 5}),
                    ToolCall(
                        "c2", "price__get_trend", {"commodity": "lithium_carbonate", "days": 30}
                    ),
                    ToolCall("c3", "pdf__extract_resources", {"pdf_url": "fixture"}),
                ],
            )
        self.tool_results = [m["content"] for m in messages if m["role"] == "tool"]
        md = (
            "# Pilbara 锂矿日报 — 2026-07-09\n"
            "## 摘要\n- fake\n## 新闻动态\n- fake\n## 储量数据\n- fake\n"
            "## 价格走势\n- fake\n## 风险提示\n- fake\n## 数据可用性\n- fake\n"
        )
        return LLMReply(content=md, tool_calls=[])


class TestOfflineE2E:
    async def test_full_pipeline_over_real_mcp_stdio(self, tmp_path: Path):
        fake = FakeLLM()
        async with MCPFleet(specs=resolve_specs(), mode="stdio") as fleet:
            assert set(fleet.tools) == EXPECTED_TOOLS
            assert fleet.failed_servers == {}
            result = await run_agent("Pilbara 锂矿今日简报", fleet, fake, max_steps=6)

        assert result.steps == 2
        assert len(result.tool_calls) == 3
        assert all(not c["is_error"] for c in result.tool_calls)

        news, price, pdf = fake.tool_results
        news_data = json.loads(news)
        assert news_data["count"] >= 1
        assert any("fixture" in n for n in news_data["notes"])  # 离线降级如实上报

        price_data = json.loads(price)
        assert price_data["end_price"] == 158000.0
        assert price_data["is_live"] is False

        pdf_data = json.loads(pdf)
        assert {r["category"] for r in pdf_data["rows"]} >= {"Indicated", "Inferred"}
        assert pdf_data["confidence"] >= 0.9

        out = briefing.save_briefing(result.briefing_md, "Pilbara 锂矿今日简报", tmp_path)
        assert out.exists()
        assert "## 数据可用性" in out.read_text("utf-8")


class TestUnits:
    def test_slugify(self):
        assert briefing.slugify("Pilbara 锂矿 今日简报!") == "pilbara-锂矿-今日简报"
        assert briefing.slugify("!!!") == "briefing"

    def test_resolve_specs_env_override(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("MCP_SERVERS", "news=http://news-mcp:9001/mcp")
        specs = {s.name: s for s in resolve_specs()}
        assert specs["news"].http_url == "http://news-mcp:9001/mcp"
        assert specs["price"].http_url == "http://127.0.0.1:18003/mcp"
