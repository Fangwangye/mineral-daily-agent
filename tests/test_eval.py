"""评分器单测：每项检查都用"正例 + 反例"验证，确保它真的会抓问题。"""

from __future__ import annotations

from mineral_daily.evaluation import score_briefing
from mineral_daily.evaluation.scorecard import (
    _sections,
    check_citations,
    check_grounding,
    check_honesty,
    check_keywords,
)

GOOD_BRIEFING = """# Pilbara 锂矿日报 — 2026-07-09
## 摘要
- 碳酸锂下跌。
## 新闻动态
**Chile lithium exports top $3.2B**（2026-07-08）
- 出口回升。 [来源](https://www.mining.com/chile-lithium/)
## 储量数据
| 类别 | 矿石量 (Mt) | 品位 (% Li2O) |
|:---|:---|:---|
| Indicated | 315.2 | 1.15 |
| Inferred | 76.6 | 1.07 |
## 价格走势
| 商品 | 最新价 | 区间 |
|:---|:---|:---|
| 碳酸锂 | 158000 | 158000–166000 |
## 风险提示
- 价格下行。
## 数据可用性
- 碳酸锂为快照数据，非实时。
"""

# tool_calls 里出现过的数字：315.2 / 76.6 / 1.15 / 1.07 / 158000 / 166000
TOOL_CALLS = [
    {"tool": "pdf__extract_resources", "result":
     '{"rows":[{"category":"Indicated","ore_tonnage_mt":315.2,"grade":1.15},'
     '{"category":"Inferred","ore_tonnage_mt":76.6,"grade":1.07}],"confidence":0.55}'},
    {"tool": "price__get_trend", "result":
     '{"end_price":158000,"min":158000,"max":166000,"is_live":false,"source":"SunSirs 快照"}'},
    {"tool": "news__search", "result":
     '{"items":[{"title":"Chile lithium","url":"https://www.mining.com/chile-lithium/"}]}'},
]


class TestFullScore:
    def test_good_briefing_passes_all(self):
        card = score_briefing(GOOD_BRIEFING, TOOL_CALLS, expect_keywords=["Pilbara", "碳酸锂"])
        assert card.passed, card.as_dict()
        # 各项均达标；citations 仅 1 条链接(满分需 2 条)故整体 0.9
        assert card.overall >= 0.9
        assert {c.name for c in card.checks} == {
            "structure", "citations", "grounding", "honesty", "topicality"
        }


class TestGrounding:
    """反幻觉：编造的数字必须被抓出来。"""

    def test_hallucinated_number_flagged(self):
        # 把储量改成工具里没有的 999.9
        bad = GOOD_BRIEFING.replace("315.2", "999.9")
        sections = _sections(bad)
        tool_nums = [315.2, 76.6, 1.15, 1.07, 158000.0, 166000.0]
        result = check_grounding(sections, tool_nums)
        assert not result.passed
        assert 999.9 in [round(x, 1) for x in _flagged(result)]

    def test_rounding_tolerance(self):
        # 1.150 与工具的 1.15 应视为溯源成功（1% 容差）
        sections = _sections(GOOD_BRIEFING.replace("1.15", "1.150"))
        result = check_grounding(sections, [315.2, 76.6, 1.15, 1.07, 158000.0, 166000.0])
        assert result.passed


def _flagged(result) -> list[float]:
    # 从 detail 文本里解析出被标记的数字，供断言用
    import re
    return [float(x) for x in re.findall(r"\d+\.?\d*", result.detail.split("疑似幻觉")[-1])]


class TestCitations:
    def test_missing_citation_fails(self):
        no_url = GOOD_BRIEFING.replace("[来源](https://www.mining.com/chile-lithium/)", "无链接")
        assert not check_citations(_sections(no_url)).passed

    def test_has_citation_passes(self):
        assert check_citations(_sections(GOOD_BRIEFING)).passed


class TestHonesty:
    def test_snapshot_not_acknowledged_fails(self):
        # 工具返回 is_live:false + 快照，但简报删掉"数据可用性"声明
        no_ack = GOOD_BRIEFING.replace("- 碳酸锂为快照数据，非实时。", "- 一切正常。")
        result = check_honesty(no_ack, [c["result"] for c in TOOL_CALLS])
        assert not result.passed

    def test_acknowledged_passes(self):
        result = check_honesty(GOOD_BRIEFING, [c["result"] for c in TOOL_CALLS])
        assert result.passed

    def test_no_degradation_auto_passes(self):
        result = check_honesty("# 简报\n一切实时。", ['{"is_live": true}'])
        assert result.passed


class TestKeywords:
    def test_missing_keyword_fails(self):
        assert not check_keywords(GOOD_BRIEFING, ["镍矿"]).passed

    def test_all_present_passes(self):
        assert check_keywords(GOOD_BRIEFING, ["Pilbara", "碳酸锂"]).passed


class TestStructure:
    def test_missing_section_fails(self):
        incomplete = "# 日报\n## 摘要\n- x\n## 价格走势\n- y\n"
        card = score_briefing(incomplete, [])
        structure = next(c for c in card.checks if c.name == "structure")
        assert not structure.passed
        assert "新闻" in structure.detail
