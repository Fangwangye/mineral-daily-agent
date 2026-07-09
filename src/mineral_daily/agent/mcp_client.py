"""MCP 多 server 连接管理。

两种模式：
- stdio（默认）：用当前解释器把 3 个 server 拉成子进程，单命令即可运行；
- http：连接 docker-compose 暴露的 streamable-http 端点（MCP_SERVERS 环境变量可覆盖）。

工具以 "<server>__<tool>" 命名空间注册（如 news__search），自动转换为
OpenAI function calling schema 供 LLM 使用。
"""

from __future__ import annotations

import json
import logging
import os
import sys
from contextlib import AsyncExitStack
from dataclasses import dataclass, field

import anyio
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
    ServerSpec("news", "mineral_daily.servers.news.server", "http://127.0.0.1:18001/mcp"),
    ServerSpec("pdf", "mineral_daily.servers.pdf.server", "http://127.0.0.1:18002/mcp"),
    ServerSpec("price", "mineral_daily.servers.price.server", "http://127.0.0.1:18003/mcp"),
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
        # 每个 server 独立 ExitStack：单点失败/关闭异常不拖垮其余连接
        self._stacks: list[AsyncExitStack] = []

    async def __aenter__(self) -> MCPFleet:
        for spec in self.specs:
            stack = AsyncExitStack()
            await stack.__aenter__()
            try:
                await self._connect(spec, stack)
                self._stacks.append(stack)
            except Exception as exc:  # noqa: BLE001 - 单 server 故障降级，不中断整体
                logger.warning("server %s 连接失败: %s", spec.name, exc)
                self.failed_servers[spec.name] = f"{type(exc).__name__}: {exc}"
                await self._close_stack(stack)
        if not self.tools:
            raise RuntimeError(f"所有 MCP server 均不可用: {self.failed_servers}")
        return self

    async def __aexit__(self, *exc_info) -> None:
        for stack in reversed(self._stacks):
            await self._close_stack(stack)
        self._stacks.clear()

    @staticmethod
    async def _close_stack(stack: AsyncExitStack) -> None:
        try:
            await stack.aclose()
        except Exception as exc:  # noqa: BLE001 - 传输层清理异常只记日志
            logger.debug("关闭 MCP 连接时忽略异常: %r", exc)

    async def _connect(self, spec: ServerSpec, stack: AsyncExitStack) -> None:
        if self.mode == "stdio":
            env = get_default_environment()
            for key in _PASSTHROUGH_ENV:
                if key in os.environ:
                    env[key] = os.environ[key]
            params = StdioServerParameters(
                command=sys.executable, args=["-m", spec.stdio_module], env=env
            )
            read, write = await stack.enter_async_context(stdio_client(params))
        else:
            read, write, _ = await stack.enter_async_context(
                streamablehttp_client(spec.http_url)
            )
        session = await stack.enter_async_context(ClientSession(read, write))
        # 注意不要用 asyncio.wait_for：MCP 会话运行在 anyio cancel scope 内，
        # asyncio 取消会以 CancelledError 逃逸；anyio.fail_after 抛标准 TimeoutError
        with anyio.fail_after(30):
            await session.initialize()
        names: list[str] = []
        cursor: str | None = None
        while True:  # 规范允许 tools/list 分页，循环 nextCursor 取全量
            listed = await session.list_tools(cursor=cursor)
            for tool in listed.tools:
                self.tools[f"{spec.name}__{tool.name}"] = _ToolEntry(session, tool, spec.name)
                names.append(tool.name)
            cursor = listed.nextCursor
            if not cursor:
                break
        logger.info("server %s 就绪 (%s): %s", spec.name, self.mode, ", ".join(names))

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
            with anyio.fail_after(timeout):
                result = await entry.session.call_tool(entry.tool.name, arguments)
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
