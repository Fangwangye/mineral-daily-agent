"""LLM 接入层：任意 OpenAI 兼容端点（默认 DeepSeek）。

环境变量：
- DEEPSEEK_API_KEY / LLM_API_KEY  二选一
- LLM_BASE_URL  默认 https://api.deepseek.com
- LLM_MODEL     默认 deepseek-chat
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Protocol

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]
    parse_error: str | None = None


@dataclass
class LLMReply:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)


class ChatLLM(Protocol):
    """ReAct 循环依赖的最小接口（测试用 FakeLLM 实现同一协议）。"""

    async def chat(
        self, messages: list[dict], tools: list[dict] | None = None
    ) -> LLMReply: ...


@dataclass
class LLMConfig:
    api_key: str
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    temperature: float = 0.3
    timeout: float = 180.0

    @classmethod
    def from_env(cls) -> LLMConfig:
        api_key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("LLM_API_KEY") or ""
        if not api_key:
            raise RuntimeError(
                "缺少 LLM API key：请在 .env 或环境变量中设置 DEEPSEEK_API_KEY"
                "（或 LLM_API_KEY + LLM_BASE_URL 指向任意 OpenAI 兼容端点）"
            )
        return cls(
            api_key=api_key,
            base_url=os.environ.get("LLM_BASE_URL", DEFAULT_BASE_URL),
            model=os.environ.get("LLM_MODEL", DEFAULT_MODEL),
        )


class OpenAICompatLLM:
    def __init__(self, config: LLMConfig):
        self.config = config
        self._client = AsyncOpenAI(
            api_key=config.api_key, base_url=config.base_url, timeout=config.timeout
        )

    async def chat(
        self, messages: list[dict], tools: list[dict] | None = None
    ) -> LLMReply:
        kwargs: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
        }
        if tools:
            kwargs["tools"] = tools
        resp = await self._client.chat.completions.create(**kwargs)
        message = resp.choices[0].message
        calls: list[ToolCall] = []
        for tc in message.tool_calls or []:
            args: dict[str, Any] = {}
            err = None
            try:
                args = json.loads(tc.function.arguments or "{}")
                if not isinstance(args, dict):
                    args, err = {}, f"arguments 不是对象: {tc.function.arguments!r}"
            except json.JSONDecodeError as exc:
                err = f"arguments JSON 解析失败: {exc}"
            calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args,
                                  parse_error=err))
        return LLMReply(content=message.content, tool_calls=calls)
