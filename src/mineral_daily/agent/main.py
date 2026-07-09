"""矿权日报 Agent CLI。

用法：
    mineral-daily "给我生成一份关于 Pilbara 锂矿的今日简报"
    mineral-daily --offline "..."      # 全离线（fixture/快照），无外网也能跑
    mineral-daily --http "..."         # 连接 docker-compose 的 http server
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import io
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from mineral_daily.common.logging import setup_logging

from . import briefing
from .llm import LLMConfig, OpenAICompatLLM
from .mcp_client import MCPFleet, resolve_specs
from .react import run_agent

DEFAULT_REQUEST = "给我生成一份关于 Pilbara 锂矿的今日简报"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mineral-daily", description="矿权日报 Agent（3 个 MCP server + ReAct 编排）"
    )
    parser.add_argument("request", nargs="?", default=DEFAULT_REQUEST,
                        help=f"自然语言需求（默认：{DEFAULT_REQUEST}）")
    parser.add_argument("--http", action="store_true",
                        help="连接 streamable-http server（默认 stdio 子进程）")
    parser.add_argument("--offline", action="store_true",
                        help="MINERAL_OFFLINE=1：不出网，用缓存/fixture/快照")
    parser.add_argument("--max-steps", type=int, default=12, help="ReAct 最大步数（默认 12）")
    parser.add_argument("--tool-timeout", type=float, default=60.0,
                        help="单次工具调用超时秒数（默认 60）")
    parser.add_argument("--out-dir", default="briefings", help="简报输出目录（默认 briefings/）")
    parser.add_argument("--trace", metavar="PATH",
                        help="把本次运行（简报+工具原始返回+notes）转储为 JSON，供 eval 评测")
    return parser


async def _run(args: argparse.Namespace) -> int:
    if args.offline:
        os.environ["MINERAL_OFFLINE"] = "1"
    try:
        llm = OpenAICompatLLM(LLMConfig.from_env())
    except RuntimeError as exc:
        print(f"[配置错误] {exc}", file=sys.stderr)
        return 2

    specs = resolve_specs()
    mode = "http" if args.http else "stdio"
    print(f"[1/3] 启动 MCP 连接（{mode}）…", file=sys.stderr)
    async with MCPFleet(specs=specs, mode=mode) as fleet:
        print(
            f"[2/3] 工具就绪: {', '.join(fleet.tools)}；开始 ReAct 编排…",
            file=sys.stderr,
        )
        result = await run_agent(
            args.request, fleet, llm,
            max_steps=args.max_steps, tool_timeout=args.tool_timeout,
        )

    path = briefing.save_briefing(result.briefing_md, args.request, Path(args.out_dir))
    calls = sum(1 for c in result.tool_calls)
    errors = sum(1 for c in result.tool_calls if c["is_error"])
    print(
        f"[3/3] 完成：{result.steps} 步，{calls} 次工具调用（{errors} 次错误），"
        f"简报已保存 -> {path}",
        file=sys.stderr,
    )
    if args.trace:
        trace = {
            "request": args.request,
            "briefing_md": result.briefing_md,
            "steps": result.steps,
            "tool_calls": result.tool_calls,
            "notes": result.notes,
        }
        Path(args.trace).write_text(json.dumps(trace, ensure_ascii=False, indent=2), "utf-8")
        print(f"      运行痕迹已转储 -> {args.trace}", file=sys.stderr)
    print(result.briefing_md)
    return 0


def main() -> None:
    load_dotenv()
    setup_logging()
    # Windows 控制台默认 GBK，强制 UTF-8 避免中文简报打印失败
    with contextlib.suppress(Exception):
        for stream in (sys.stdout, sys.stderr):
            if isinstance(stream, io.TextIOWrapper):
                stream.reconfigure(encoding="utf-8")
    args = build_parser().parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
