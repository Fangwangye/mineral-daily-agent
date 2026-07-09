"""MCP server 统一启动器：stdio（默认，接 Claude Desktop）或 streamable-http（docker-compose）。"""

from __future__ import annotations

import argparse

from mcp.server.fastmcp import FastMCP

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


def run_server(mcp: FastMCP, args: argparse.Namespace) -> None:
    setup_logging()
    if args.transport == "http":
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        mcp.run(transport="streamable-http")
    else:
        mcp.run()
