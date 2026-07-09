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


def _transport_security(port: int) -> TransportSecuritySettings:
    """http 模式的 Host/Origin 校验（MCP 规范要求校验 Origin 防 DNS rebinding，默认启用）。

    白名单 = 127.0.0.1/localhost（本机调试）+ MCP_ALLOWED_HOSTS 追加项（逗号分隔；
    容器部署时注入本服务的 compose 服务名，如 news-mcp:18001，见 docker-compose.yml）。
    仅在完全受控的内网调试时可设 MCP_ALLOWED_HOSTS=* 整体关闭防护。
    """
    raw = os.environ.get("MCP_ALLOWED_HOSTS", "").strip()
    if raw == "*":
        return TransportSecuritySettings(enable_dns_rebinding_protection=False)
    hosts = [f"127.0.0.1:{port}", f"localhost:{port}"]
    hosts += [h.strip() for h in raw.split(",") if h.strip()]
    origins = [f"http://{h}" for h in hosts] + [f"https://{h}" for h in hosts]
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=hosts,
        allowed_origins=origins,
    )


def run_server(mcp: FastMCP, args: argparse.Namespace) -> None:
    setup_logging()
    if args.transport == "http":
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        mcp.settings.transport_security = _transport_security(args.port)
        mcp.run(transport="streamable-http")
    else:
        mcp.run()
