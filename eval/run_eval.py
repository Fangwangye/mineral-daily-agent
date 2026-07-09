"""简报质量评测 CLI。

两种用法：
  1) 评已有 trace（离线、无需 key）：
       python eval/run_eval.py --trace trace.json
  2) 跑用例集并评测（需要 LLM key）：
       python eval/run_eval.py                 # 跑 eval/cases.jsonl 全部用例
       python eval/run_eval.py --offline        # 数据侧离线（fixture/快照），仍需 LLM key
       python eval/run_eval.py --llm-judge       # 额外做 LLM faithfulness 评审

退出码：所有用例达标(overall ≥ --min-score 且各项 passed) → 0，否则 1（可接 CI 门禁）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mineral_daily.evaluation import Scorecard, score_briefing  # noqa: E402

CASES = Path(__file__).parent / "cases.jsonl"


def _load_cases() -> list[dict]:
    return [json.loads(ln) for ln in CASES.read_text("utf-8").splitlines() if ln.strip()]


def _print_scorecard(label: str, card: Scorecard, judge: object | None = None) -> None:
    mark = "PASS" if card.passed else "FAIL"
    print(f"\n[{mark}] {label}  overall={card.overall}")
    for c in card.checks:
        tick = "✓" if c.passed else "✗"
        print(f"  {tick} {c.name:<11} {c.score:>5}  {c.detail}")
    if judge is not None:
        print(f"  · llm-faithfulness {judge.score}/5  {judge.comment}")  # type: ignore[attr-defined]
        for u in judge.unsupported:  # type: ignore[attr-defined]
            print(f"      无据: {u}")


async def _run_cases(args: argparse.Namespace) -> int:
    if args.offline:
        os.environ["MINERAL_OFFLINE"] = "1"
    try:
        from mineral_daily.agent.llm import LLMConfig, OpenAICompatLLM
        from mineral_daily.agent.mcp_client import MCPFleet, resolve_specs
        from mineral_daily.agent.react import run_agent
    except ImportError as exc:  # pragma: no cover
        print(f"导入失败: {exc}", file=sys.stderr)
        return 2
    try:
        llm = OpenAICompatLLM(LLMConfig.from_env())
    except RuntimeError as exc:
        print(f"[配置错误] {exc}", file=sys.stderr)
        return 2

    judge_llm = llm if args.llm_judge else None
    all_pass = True
    async with MCPFleet(specs=resolve_specs(), mode="stdio") as fleet:
        for case in _load_cases():
            result = await run_agent(case["request"], fleet, llm, max_steps=args.max_steps)
            card = score_briefing(
                result.briefing_md, result.tool_calls, case.get("expect_keywords")
            )
            verdict = None
            if judge_llm is not None:
                from mineral_daily.evaluation.llm_judge import judge_faithfulness
                verdict = await judge_faithfulness(result.briefing_md, result.tool_calls, judge_llm)
            _print_scorecard(case["id"], card, verdict)
            all_pass = all_pass and card.passed and card.overall >= args.min_score
    return 0 if all_pass else 1


def _run_trace(args: argparse.Namespace) -> int:
    trace = json.loads(Path(args.trace).read_text("utf-8"))
    card = score_briefing(trace["briefing_md"], trace.get("tool_calls", []))
    _print_scorecard(Path(args.trace).name, card)
    ok = card.passed and card.overall >= args.min_score
    return 0 if ok else 1


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="简报质量评测")
    parser.add_argument("--trace", help="评一个已有的 trace JSON（离线，无需 key）")
    parser.add_argument("--offline", action="store_true", help="跑用例时数据侧离线")
    parser.add_argument("--llm-judge", action="store_true", help="额外做 LLM faithfulness 评审")
    parser.add_argument("--max-steps", type=int, default=12)
    parser.add_argument("--min-score", type=float, default=0.8, help="达标阈值（默认 0.8）")
    args = parser.parse_args()

    if args.trace:
        raise SystemExit(_run_trace(args))
    raise SystemExit(asyncio.run(_run_cases(args)))


if __name__ == "__main__":
    main()
