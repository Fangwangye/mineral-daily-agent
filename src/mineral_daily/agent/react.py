"""ReAct 编排循环：LLM 决策 → MCP 工具并行执行 → 结果回喂 → 简报合成。

守护：最大步数、单工具超时、工具错误以文本回喂（模型自适应换路），
步数耗尽时禁用工具强制合成，保证总能产出简报。
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field

from . import briefing
from .llm import ChatLLM, ToolCall
from .mcp_client import MCPFleet

logger = logging.getLogger(__name__)


@dataclass
class AgentResult:
    briefing_md: str
    steps: int
    tool_calls: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _assistant_message(content: str | None, tool_calls: list[ToolCall]) -> dict:
    msg: dict = {"role": "assistant", "content": content or ""}
    if tool_calls:
        msg["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
            }
            for tc in tool_calls
        ]
    return msg


async def run_agent(
    request: str,
    fleet: MCPFleet,
    llm: ChatLLM,
    *,
    max_steps: int = 12,
    tool_timeout: float = 60.0,
) -> AgentResult:
    notes: list[str] = [
        f"server {name} 不可用: {err}" for name, err in fleet.failed_servers.items()
    ]
    messages: list[dict] = [
        {"role": "system", "content": briefing.SYSTEM_PROMPT},
        {"role": "user", "content": request},
    ]
    tools_schema = fleet.openai_tools()
    call_log: list[dict] = []

    for step in range(1, max_steps + 1):
        reply = await llm.chat(messages, tools=tools_schema)
        if not reply.tool_calls:
            if not reply.content or not reply.content.strip():
                notes.append(f"第 {step} 步模型返回空内容，重试合成")
                messages.append({"role": "user", "content": briefing.force_synthesis_prompt()})
                continue
            return AgentResult(
                briefing_md=reply.content.strip(),
                steps=step,
                tool_calls=call_log,
                notes=notes,
            )

        messages.append(_assistant_message(reply.content, reply.tool_calls))
        logger.info(
            "step %d: %s", step, ", ".join(tc.name for tc in reply.tool_calls)
        )

        async def _dispatch(tc: ToolCall) -> str:
            if tc.parse_error:
                return f"[tool error] {tc.parse_error}"
            return await fleet.call(tc.name, tc.arguments, timeout=tool_timeout)

        results = await asyncio.gather(*[_dispatch(tc) for tc in reply.tool_calls])
        for tc, result in zip(reply.tool_calls, results, strict=True):
            call_log.append(
                {"step": step, "tool": tc.name, "arguments": tc.arguments,
                 "is_error": result.startswith("[tool error]"), "result": result}
            )
            messages.append(
                {"role": "tool", "tool_call_id": tc.id, "content": result}
            )

    notes.append(f"达到最大步数 {max_steps}，强制合成")
    messages.append({"role": "user", "content": briefing.force_synthesis_prompt()})
    reply = await llm.chat(messages, tools=None)
    return AgentResult(
        briefing_md=(reply.content or "").strip() or "（合成失败：模型未返回内容）",
        steps=max_steps + 1,
        tool_calls=call_log,
        notes=notes,
    )
