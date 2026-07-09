"""mining-news-mcp：矿业新闻聚合 MCP server。

工具：search(query, days, limit) · fetch_article(url)
返回类型为 pydantic 模型 → SDK 自动发布 outputSchema 并附带 structuredContent。
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from mineral_daily.common.runner import build_transport_parser, run_server

from . import article, feeds
from .models import Article, NewsSearchResult

mcp = FastMCP(
    "mining-news-mcp",
    instructions=(
        "矿业新闻聚合（默认源 mining.com RSS，全部为英文内容）。"
        "先用 search 找到候选文章，再用 fetch_article 取全文。"
        "search 的 query 请使用英文关键词，例如 'Pilbara lithium'。"
    ),
)


@mcp.tool()
async def search(query: str, days: int = 7, limit: int = 20) -> NewsSearchResult:
    """按关键词检索近 N 天矿业新闻，返回标题/链接/摘要，按相关度+时间排序。

    Args:
        query: 英文关键词（新闻源为英文），多个词为 OR 语义按命中数排序，如 "Pilbara lithium"
        days: 时间窗天数，1–60，默认 7
        limit: 返回条数上限，1–50，默认 20
    """
    return NewsSearchResult(**await feeds.search(query, days=days, limit=limit))


@mcp.tool()
async def fetch_article(url: str) -> Article:
    """抓取一篇新闻的正文全文（trafilatura 抽取，超 8000 字符截断）。

    Args:
        url: search 结果中的文章链接
    """
    return Article(**await article.fetch_article(url))


def main() -> None:
    args = build_transport_parser("mining-news-mcp", default_port=18001).parse_args()
    run_server(mcp, args)


if __name__ == "__main__":
    main()
