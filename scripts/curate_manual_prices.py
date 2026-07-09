"""人工策展 lithium_carbonate / iron_ore 快照序列（无免费可编程 live 源的商品）。

数据出处（2026-07-09 采集，均为公开页面报道的真实价格）：
- lithium_carbonate：生意社 SunSirs 电池级碳酸锂(99.5%)中国现货日度价
  https://www.sunsirs.com/m/page/commodity-price-detail/commodity-price-detail-1162.html
  交叉参考：TradingEconomics 报 2026-07-07 三个月低点 151,750 CNY/t（口径不同，未混入序列）。
- iron_ore：countryeconomy.com 铁矿石 62% Fe 中国进口（天津港 CIF）月度均价
  https://countryeconomy.com/raw-materials/iron-ore
  月度均价以月末日期入序列；交叉参考：TradingEconomics 报 2026-07-08 日度价 98.86 USD/t
 （CFR 口径，未混入序列）。

单一商品坚持单一来源，避免不同口径混排造成虚假跳变。

用法：python scripts/curate_manual_prices.py
"""

from __future__ import annotations

import json
from pathlib import Path

SNAPSHOT = Path(__file__).resolve().parents[1] / (
    "src/mineral_daily/servers/price/data/prices_snapshot.json"
)

CURATED = {
    "lithium_carbonate": {
        "unit": "CNY/t",
        "source": "SunSirs 生意社 battery-grade Li2CO3 99.5% China spot (sunsirs.com)",
        "as_of": "2026-07-09",
        "series": [
            {"date": "2026-07-03", "price": 166000.0},
            {"date": "2026-07-04", "price": 166000.0},
            {"date": "2026-07-05", "price": 166000.0},
            {"date": "2026-07-06", "price": 162000.0},
            {"date": "2026-07-07", "price": 162000.0},
            {"date": "2026-07-08", "price": 163000.0},
            {"date": "2026-07-09", "price": 158000.0},
        ],
    },
    "iron_ore": {
        "unit": "USD/t",
        "source": (
            "Iron ore 62% Fe China import CIF Tianjin, monthly average "
            "(countryeconomy.com)"
        ),
        "as_of": "2026-05-31",
        "series": [
            {"date": "2025-06-30", "price": 96.17},
            {"date": "2025-07-31", "price": 101.22},
            {"date": "2025-08-31", "price": 103.29},
            {"date": "2025-09-30", "price": 106.41},
            {"date": "2025-10-31", "price": 106.87},
            {"date": "2025-11-30", "price": 106.23},
            {"date": "2025-12-31", "price": 107.59},
            {"date": "2026-01-31", "price": 107.45},
            {"date": "2026-02-28", "price": 100.97},
            {"date": "2026-03-31", "price": 107.58},
            {"date": "2026-04-30", "price": 109.39},
            {"date": "2026-05-31", "price": 111.65},
        ],
    },
}


def main() -> None:
    existing = json.loads(SNAPSHOT.read_text("utf-8")) if SNAPSHOT.exists() else {}
    existing.update(CURATED)
    SNAPSHOT.write_text(json.dumps(existing, ensure_ascii=False, indent=2), "utf-8")
    for name, item in CURATED.items():
        print(f"[ok] {name}: {len(item['series'])} 个点, as_of {item['as_of']}")
    print(f"快照已写入 {SNAPSHOT}")


if __name__ == "__main__":
    main()
