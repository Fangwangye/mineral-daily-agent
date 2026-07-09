"""lme-price-mcp 数据层测试（全部离线：解析器 + 快照降级路径）。"""

from __future__ import annotations

import pytest

from mineral_daily.servers.price import providers


class TestParseNumber:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("9 456,00", 9456.0),
            ("9.456,00", 9456.0),
            ("9,456.00", 9456.0),
            ("13090", 13090.0),
            ("1,234", 1234.0),
            ("98,86", 98.86),
            ("&nbsp;3 529,50 ", 3529.5),
        ],
    )
    def test_formats(self, raw: str, expected: float):
        assert providers.parse_number(raw) == expected

    @pytest.mark.parametrize("raw", ["", "n.a.", "-", "<td>"])
    def test_garbage_returns_none(self, raw: str):
        assert providers.parse_number(raw) is None


class TestParseWestmetall:
    HTML = """
    <table>
      <tr><th>date</th><th>cash</th><th>3month</th></tr>
      <tr><td class="datum">7. July 2026</td><td>13 001,00</td><td>13 100,00</td></tr>
      <tr><td class="datum">8. July 2026</td><td>13 090,00</td><td>13 150,00</td></tr>
      <tr><td class="datum">bogus row</td><td>1</td></tr>
    </table>
    """

    def test_parses_rows_ascending(self):
        points = providers.parse_westmetall(self.HTML)
        assert [(p.day.isoformat(), p.price) for p in points] == [
            ("2026-07-07", 13001.0),
            ("2026-07-08", 13090.0),
        ]

    def test_empty_html(self):
        assert providers.parse_westmetall("<html></html>") == []


class TestSnapshotFallback:
    """MINERAL_OFFLINE=1（conftest 注入）下应完全依赖打包快照。"""

    async def test_offline_falls_to_snapshot(self):
        series = await providers.get_series("copper", days=30)
        assert series.is_live is False
        assert "快照" in series.source
        assert series.points, "快照序列不应为空"

    async def test_unknown_commodity(self):
        with pytest.raises(ValueError, match="未知 commodity"):
            await providers.get_series("unobtainium", days=30)

    async def test_price_on_specific_date(self):
        result = await providers.price_on("lithium_carbonate", "2026-07-05")
        assert result["price"] == 166000.0
        assert result["date"] == "2026-07-05"
        assert result["unit"] == "CNY/t"
        assert result["is_live"] is False

    async def test_price_on_nontrading_day_falls_back(self):
        # 2026-07-04/05 为周末样式场景：目标日在序列内直接命中；
        # 目标日晚于最后数据点时应回退并带 note
        result = await providers.price_on("iron_ore", "2026-06-15")
        assert result["date"] == "2026-05-31"
        assert "note" in result

    async def test_trend_stats(self):
        result = await providers.trend("lithium_carbonate", days=180)
        assert result["end_price"] == 158000.0
        assert result["min"] <= result["max"]
        assert result["direction"] in {"up", "down", "sideways"}
        assert len(result["points"]) >= 2

    async def test_trend_days_out_of_range(self):
        with pytest.raises(ValueError, match="1–180"):
            await providers.trend("copper", days=999)
