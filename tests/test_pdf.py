"""mineral-pdf-mcp 测试：fixture PDF 结构化解析 + 文本行回退 + 输入校验。"""

from __future__ import annotations

from pathlib import Path

import pytest

from mineral_daily.servers.pdf import parser
from mineral_daily.servers.pdf.server import _ensure_is_pdf, extract_resources

FIXTURE_PDF = (
    Path(__file__).resolve().parents[1]
    / "src/mineral_daily/servers/pdf/data/fixture_resource_report.pdf"
)


class TestFixtureParse:
    def test_structured_extraction(self):
        result = parser.parse_pdf(FIXTURE_PDF)
        assert result.confidence >= 0.9
        assert result.resource_pages == [1, 2]
        by_cat = {(r.page, r.category): r for r in result.rows}

        indicated = by_cat[(1, "Indicated")]
        assert indicated.ore_tonnage_mt == 152.3
        assert indicated.grade == 1.09
        assert indicated.grade_unit == "% Li2O"
        assert indicated.contained_metal == 1660.0
        assert indicated.metal_unit == "kt"

        gold = by_cat[(2, "Inferred")]
        assert gold.grade_unit == "g/t Au"
        assert gold.metal_unit == "koz"
        assert gold.contained_metal == 644.0

    def test_merged_category_normalized(self):
        result = parser.parse_pdf(FIXTURE_PDF)
        cats = {r.category for r in result.rows}
        assert "Measured + Indicated" in cats


class TestTextLineFallback:
    TEXT = """Table 1: Pilgangoora Mineral Resource estimate (0.2% Li 2 O cut-off)
Category Tonnes (Mt) Li 2 O (%) Ta 2 O 5 (ppm)
Measured 22.1 1.34 146 0.44 0.3 7
Indicated and Inferred Resources. The Mineral Resource models were established
Indicated 315.2 1.15 106 0.53 3.6 74
Inferred 76.6 1.07 124 0.54 0.8 21
Total 2023 outlook remains
"""

    def test_parses_numeric_rows_only(self):
        rows = parser._parse_text_lines(self.TEXT, page_no=2)
        cats = [r.category for r in rows]
        assert cats == ["Measured", "Indicated", "Inferred"]  # 叙述句被守卫拒绝
        assert rows[0].ore_tonnage_mt == 22.1
        assert rows[0].grade == 1.34

    def test_grade_unit_sniffed_from_squished_subscript(self):
        rows = parser._parse_text_lines(self.TEXT, page_no=2)
        assert rows[0].grade_unit == "% Li2O"

    def test_gold_unit_sniff(self):
        text = "Resource grade g/t Au basis\nIndicated 42.5 1.35 1845 900\n"
        rows = parser._parse_text_lines(text, page_no=1)
        assert rows[0].grade_unit == "g/t Au"


class TestTonnageScale:
    def test_kt_header_converted_to_mt(self):
        table = [
            ["Category", "Tonnes (kt)", "Grade (% Cu)", "Contained Cu (kt)"],
            ["Indicated", "1,500", "0.55", "8.2"],
        ]
        rows, conf, notes = parser._parse_table(table, page_no=9)
        assert rows[0].ore_tonnage_mt == 1.5
        assert any("kt→Mt" in n for n in notes)
        assert conf > 0.5


class TestServerTool:
    async def test_fixture_keyword(self):
        result = await extract_resources("fixture")
        assert result["confidence"] >= 0.9
        assert len(result["rows"]) == 7
        assert any("fixture" in n for n in result["notes"])

    async def test_offline_http_falls_back_to_fixture(self):
        result = await extract_resources("https://example.com/report.pdf")
        assert any("回落" in n for n in result["notes"])
        assert result["rows"]

    async def test_bad_path_rejected(self):
        with pytest.raises(ValueError, match="无法解析"):
            await extract_resources("Z:/no/such/file.pdf")

    def test_non_pdf_content_rejected_and_cleaned(self, tmp_path: Path):
        junk = tmp_path / "fake.pdf"
        junk.write_text("<html>login wall</html>", "utf-8")
        with pytest.raises(ValueError, match="不是 PDF"):
            _ensure_is_pdf(junk, str(junk))
        assert junk.exists()  # 本地文件不删，只有 http 下载缓存才清理
