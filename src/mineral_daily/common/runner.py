"""MCP server 统一启动器：stdio（默认，接 Claude Desktop）或 streamable-http（docker-compose）。"""

from __future__ import annotations

import argparse
import os

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from .logging import setup_logging


def build_transport_parser(name: str, default_port: int) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=name, description=f"{name} MCP server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="stdio（默认，Claude Desktop/本地子进程）或 http（streamable-http，容器部署）",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=default_port)
    return parser


def _transport_security() -> TransportSecuritySettings:
    """http 模式的 Host 校验策略。

    SDK 默认的 DNS-rebinding 防护只放行 localhost 类 Host，容器间用服务名
    （如 news-mcp:18001）寻址会被 421 拒绝。因此默认关闭该防护（compose 内网/
    本地演示场景）；对外部署时设置 MCP_ALLOWED_HOSTS=host1:port,host2:port 启用白名单。
    """
    raw = os.environ.get("MCP_ALLOWED_HOSTS", "").strip()
    if not raw or raw == "*":
        return TransportSecuritySettings(enable_dns_rebinding_protection=False)
    hosts = [h.strip() for h in raw.split(",") if h.strip()]
    origins = [f"http://{h}" for h in hosts] + [f"https://{h}" for h in hosts]
    return TransportSecuritySettings(allowed_hosts=hosts, allowed_origins=origins)


def run_server(mcp: FastMCP, args: argparse.Namespace) -> None:
    setup_logging()
    if args.transport == "http":
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        mcp.settings.transport_security = _transport_security()
        mcp.run(transport="streamable-http")
    else:
        mcp.run()
