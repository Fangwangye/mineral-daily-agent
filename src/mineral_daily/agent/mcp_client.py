"""MCP 多 server 连接管理。

两种模式：
- stdio（默认）：用当前解释器把 3 个 server 拉成子进程，单命令即可运行；
- http：连接 docker-compose 暴露的 streamable-http 端点（MCP_SERVERS 环境变量可覆盖）。

工具以 "<server>__<tool>" 命名空间注册（如 news__search），自动转换为
OpenAI function calling schema 供 LLM 使用。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from contextlib import AsyncExitStack
from dataclasses import dataclass, field

from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import get_default_environment, stdio_client
from mcp.client.streamable_http import streamablehttp_client

logger = logging.getLogger(__name__)

TOOL_RESULT_LIMIT = 12_000
_PASSTHROUGH_ENV = ("MINERAL_OFFLINE", "MINERAL_CACHE_DIR", "NEWS_FEEDS", "LOG_LEVEL",
                    "PDF_MAX_PAGES")


@dataclass
class ServerSpec:
    name: str
    stdio_module: str
    http_url: str


DEFAULT_SPECS = (
    ServerSpec("news", "mineral_daily.servers.news.server", "http://127.0.0.1:8001/mcp"),
    ServerSpec("pdf", "mineral_daily.servers.pdf.server", "http://127.0.0.1:8002/mcp"),
    ServerSpec("price", "mineral_daily.servers.price.server", "http://127.0.0.1:8003/mcp"),
)


def resolve_specs() -> list[ServerSpec]:
    """MCP_SERVERS="news=http://host:8001/mcp,pdf=..." 覆盖默认 http 端点。"""
    overrides: dict[str, str] = {}
    raw = os.environ.get("MCP_SERVERS", "").strip()
    if raw:
        for pair in raw.split(","):
            name, _, url = pair.strip().partition("=")
            if name and url:
                overrides[name.strip()] = url.strip()
    return [
        ServerSpec(s.name, s.stdio_module, overrides.get(s.name, s.http_url))
        for s in DEFAULT_SPECS
    ]


@dataclass
class _ToolEntry:
    session: ClientSession
    tool: types.Tool
    server: str


@dataclass
class MCPFleet:
    """聚合 3 个 MCP server 的连接、工具目录与调用分发。"""

    specs: list[ServerSpec]
    mode: str = "stdio"  # stdio | http
    tools: dict[str, _ToolEntry] = field(default_factory=dict)
    failed_servers: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._stack = AsyncExitStack()

    async def __aenter__(self) -> MCPFleet:
        await self._stack.__aenter__()
        for spec in self.specs:
            try:
                await self._connect(spec)
            except Exception as exc:  # noqa: BLE001 - 单 server 故障降级，不中断整体
                logger.warning("server %s 连接失败: %s", spec.name, exc)
                self.failed_servers[spec.name] = f"{type(exc).__name__}: {exc}"
        if not self.tools:
            await self._stack.aclose()
            raise RuntimeError(f"所有 MCP server 均不可用: {self.failed_servers}")
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self._stack.__aexit__(*exc_info)

    async def _connect(self, spec: ServerSpec) -> None:
        if self.mode == "stdio":
            env = get_default_environment()
            for key in _PASSTHROUGH_ENV:
                if key in os.environ:
                    env[key] = os.environ[key]
            params = StdioServerParameters(
                command=sys.executable, args=["-m", spec.stdio_module], env=env
            )
            read, write = await self._stack.enter_async_context(stdio_client(params))
        else:
            read, write, _ = await self._stack.enter_async_context(
                streamablehttp_client(spec.http_url)
            )
        session = await self._stack.enter_async_context(ClientSession(read, write))
        await asyncio.wait_for(session.initialize(), timeout=30)
        listed = await session.list_tools()
        for tool in listed.tools:
            self.tools[f"{spec.name}__{tool.name}"] = _ToolEntry(session, tool, spec.name)
        logger.info(
            "server %s 就绪 (%s): %s",
            spec.name,
            self.mode,
            ", ".join(t.name for t in listed.tools),
        )

    def openai_tools(self) -> list[dict]:
        """把 MCP 工具目录转成 OpenAI function calling schema。"""
        return [
            {
                "type": "function",
                "function": {
                    "name": full_name,
                    "description": (entry.tool.description or "")[:1024],
                    "parameters": entry.tool.inputSchema
                    or {"type": "object", "properties": {}},
                },
            }
            for full_name, entry in self.tools.items()
        ]

    async def call(self, full_name: str, arguments: dict, *, timeout: float = 60.0) -> str:
        """调用工具并把结果拍平成文本。任何失败以 [tool error] 文本返回（回喂模型自适应）。"""
        entry = self.tools.get(full_name)
        if entry is None:
            return f"[tool error] 未知工具 {full_name}，可用: {', '.join(self.tools)}"
        try:
            result = await asyncio.wait_for(
                entry.session.call_tool(entry.tool.name, arguments), timeout=timeout
            )
        except TimeoutError:
            return f"[tool error] {full_name} 超时（>{timeout:.0f}s）"
        except Exception as exc:  # noqa: BLE001
            return f"[tool error] {full_name} 调用异常: {type(exc).__name__}: {exc}"

        parts = [b.text for b in result.content if isinstance(b, types.TextContent)]
        text = "\n".join(parts) if parts else json.dumps(
            result.model_dump(mode="json"), ensure_ascii=False
        )
        if len(text) > TOOL_RESULT_LIMIT:
            text = text[:TOOL_RESULT_LIMIT] + "\n…[工具结果已截断]"
        if getattr(result, "isError", False):
            return f"[tool error] {text}"
        return text
