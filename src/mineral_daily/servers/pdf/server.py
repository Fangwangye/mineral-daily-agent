"""mineral-pdf-mcp：矿权报告储量抽取 MCP server。

工具：extract_resources(pdf_url)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import anyio
from mcp.server.fastmcp import FastMCP

from mineral_daily.common import http
from mineral_daily.common.runner import build_transport_parser, run_server

from . import parser

logger = logging.getLogger(__name__)

FIXTURE_PDF = Path(__file__).parent / "data" / "fixture_resource_report.pdf"

mcp = FastMCP(
    "mineral-pdf-mcp",
    instructions=(
        "从 NI 43-101 / JORC 矿权报告 PDF 抽取 Mineral Resource 储量表"
        "（Measured/Indicated/Inferred：矿石量 Mt、品位、金属量）。"
        "pdf_url 传 'fixture' 可使用打包示例报告（Pilgangoora 风格，数字为示意值）。"
        "confidence < 0.5 表示 abstain，引用时必须提示人工核对。"
    ),
)


def _ensure_is_pdf(path: Path, origin: str) -> None:
    """校验 PDF 魔数；下载到的重定向页/反爬页要清出缓存并给出可读报错。"""
    with path.open("rb") as fh:
        head = fh.read(1024)
    if b"%PDF" in head:
        return
    size = path.stat().st_size
    if origin.startswith(("http://", "https://")):
        path.unlink(missing_ok=True)  # 避免坏响应永久占据缓存
    raise ValueError(
        f"目标内容不是 PDF（{size} 字节，可能是登录墙/反爬/重定向页）: {origin}。"
        "可改用其他镜像 URL，或传 'fixture' 使用打包示例报告。"
    )


async def _resolve_pdf(pdf_url: str) -> tuple[Path, list[str]]:
    if pdf_url.strip().lower() == "fixture":
        return FIXTURE_PDF, [
            "使用打包 fixture 报告（Pilgangoora 风格示例，数字为示意值，量级参考公开披露）"
        ]
    if pdf_url.startswith(("http://", "https://")):
        try:
            path = await http.fetch_file(pdf_url, suffix=".pdf", timeout=120.0)
            _ensure_is_pdf(path, pdf_url)
            return path, []
        except http.OfflineModeError:
            return FIXTURE_PDF, [
                f"离线模式无法下载 {pdf_url}，已回落到打包 fixture 报告"
                "（注意：内容并非请求的报告）"
            ]
    local = Path(pdf_url)
    if local.exists():
        _ensure_is_pdf(local, pdf_url)
        return local, []
    raise ValueError(f"无法解析 pdf_url（非 URL、非存在的本地路径）: {pdf_url}")


@mcp.tool()
async def extract_resources(pdf_url: str) -> dict[str, Any]:
    """从矿权报告 PDF 抽取储量表（Indicated/Inferred 等类别的矿石量/品位/金属量）。

    Args:
        pdf_url: 报告 PDF 的 http(s) URL、服务器本地路径，或 'fixture'（打包示例）

    Returns:
        rows: 每个类别一行（含来源页码与 raw 单元格）；confidence < 0.5 视为 abstain
    """
    path, notes = await _resolve_pdf(pdf_url)
    result = await anyio.to_thread.run_sync(
        lambda: parser.parse_pdf(path, source=pdf_url)
    )
    result.notes = notes + result.notes
    return result.model_dump()


def main() -> None:
    args = build_transport_parser("mineral-pdf-mcp", default_port=18002).parse_args()
    run_server(mcp, args)


if __name__ == "__main__":
    main()
