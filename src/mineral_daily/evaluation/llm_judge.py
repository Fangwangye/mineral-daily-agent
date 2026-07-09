"""可选的 LLM faithfulness 评审（需要 API key，CI 默认不跑）。

确定性 scorecard 查"数字是否溯源、章节是否齐全"，但查不了"论断是否被证据支撑"。
这一层用另一个 LLM 当裁判，只依据工具返回的事实给简报的 faithfulness 打 1–5 分，
并列出无证据支撑的论断。裁判被要求严格、宁可扣分。
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from mineral_daily.agent.llm import ChatLLM

JUDGE_PROMPT = """你是简报事实核查裁判。下面给你【工具返回的原始事实】和【待评简报】。
只依据工具事实判断简报，评估 faithfulness（忠实度）：简报的每个论断是否有工具事实支撑。

严格打分，宁可扣分：
- 5 = 全部论断有据，无编造
- 3 = 主体有据，个别论断超出证据
- 1 = 多处论断无据或与事实矛盾

只输出 JSON：{"score": <1-5 整数>, "unsupported": ["无据论断1", ...], "comment": "一句话"}"""


@dataclass
class JudgeVerdict:
    score: int
    unsupported: list[str]
    comment: str


def _extract_json(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        return json.loads(text[start : end + 1])
    raise ValueError(f"裁判未返回 JSON: {text[:200]}")


async def judge_faithfulness(
    briefing_md: str, tool_calls: list[dict], llm: ChatLLM
) -> JudgeVerdict:
    facts = "\n\n".join(
        f"[{c['tool']}] {str(c.get('result', ''))[:2000]}" for c in tool_calls
    )
    user_content = f"【工具返回的原始事实】\n{facts}\n\n【待评简报】\n{briefing_md}"
    messages = [
        {"role": "system", "content": JUDGE_PROMPT},
        {"role": "user", "content": user_content},
    ]
    reply = await llm.chat(messages, tools=None)  # 裁判不需要工具，只做判断
    data = _extract_json(reply.content or "")
    return JudgeVerdict(
        score=int(data.get("score", 0)),
        unsupported=list(data.get("unsupported", [])),
        comment=str(data.get("comment", "")),
    )
