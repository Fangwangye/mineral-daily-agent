"""刷新打包价格快照 src/mineral_daily/servers/price/data/prices_snapshot.json。

- copper / zinc / nickel：从 westmetall.com（LME 官方结算价免费镜像）抓取近 90 天真实数据。
- lithium_carbonate / iron_ore：官方源（SMM / 上海钢联 / GFEX）有登录墙或频控，无法程序化
  免费获取；保留现有快照序列不覆盖（其来源与口径见 JSON 的 source/as_of 字段与 README）。

用法：python scripts/snapshot_prices.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mineral_daily.servers.price import providers  # noqa: E402

SNAPSHOT = Path(__file__).resolve().parents[1] / (
    "src/mineral_daily/servers/price/data/prices_snapshot.json"
)
WINDOW_DAYS = 90


async def refresh() -> None:
    existing: dict = {}
    if SNAPSHOT.exists():
        existing = json.loads(SNAPSHOT.read_text("utf-8"))

    cutoff = date.today() - timedelta(days=WINDOW_DAYS)
    for commodity, meta in providers.COMMODITIES.items():
        field = meta["westmetall_field"]
        if not field:
            state = "保留" if commodity in existing else "缺失(需手工维护)"
            print(f"[skip] {commodity}: 无免费 live 源，{state}")
            continue
        try:
            points = await providers.fetch_westmetall_series(field)
        except Exception as exc:  # noqa: BLE001
            print(f"[fail] {commodity}: {exc}（保留旧快照）")
            continue
        windowed = [p for p in points if p.day >= cutoff]
        existing[commodity] = {
            "unit": meta["unit"],
            "source": "westmetall.com (LME official settlement mirror)",
            "as_of": date.today().isoformat(),
            "series": [{"date": p.day.isoformat(), "price": p.price} for p in windowed],
        }
        if windowed:
            span = f"{windowed[0].day} ~ {windowed[-1].day}"
            print(f"[ok]   {commodity}: {len(windowed)} 个点 ({span})")
        else:
            print(f"[warn] {commodity}: 窗口内无数据")

    SNAPSHOT.write_text(json.dumps(existing, ensure_ascii=False, indent=2), "utf-8")
    print(f"快照已写入 {SNAPSHOT}")


if __name__ == "__main__":
    asyncio.run(refresh())
