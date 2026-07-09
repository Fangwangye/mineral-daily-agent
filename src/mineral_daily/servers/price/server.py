"""lme-price-mcp：金属价格行情 MCP server。

工具：get_price(commodity, date) · get_trend(commodity, days)
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from mineral_daily.common.runner import build_transport_parser, run_server

from . import providers

mcp = FastMCP(
    "lme-price-mcp",
    instructions=(
        "金属价格行情：LME 铜/锌/镍官方结算价（live 抓取，失败回落打包快照），"
        "碳酸锂与铁矿石为标注来源的快照序列。commodity 可选值："
        "copper, zinc, nickel, lithium_carbonate, iron_ore。"
    ),
)


@mcp.tool()
async def get_price(commodity: str, date: str | None = None) -> dict[str, Any]:
    """查询某商品单日价格。

    Args:
        commodity: copper | zinc | nickel | lithium_carbonate | iron_ore
        date: YYYY-MM-DD，缺省为最新交易日；非交易日自动回退到最近交易日
    """
    return await providers.price_on(commodity, date)


@mcp.tool()
async def get_trend(commodity: str, days: int = 30) -> dict[str, Any]:
    """查询某商品近 N 天价格走势（序列 + 涨跌幅/最值/方向统计）。

    Args:
        commodity: copper | zinc | nickel | lithium_carbonate | iron_ore
        days: 时间窗天数，1–180，默认 30
    """
    return await providers.trend(commodity, days)


def main() -> None:
    args = build_transport_parser("lme-price-mcp", default_port=18003).parse_args()
    run_server(mcp, args)


if __name__ == "__main__":
    main()
