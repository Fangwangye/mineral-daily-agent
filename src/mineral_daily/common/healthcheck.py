"""MCP 层健康检查：对 streamable-http 端点完成一次真实 initialize 握手。

TCP 端口通不代表 MCP 就绪（进程可能起了但会话管理器异常），因此 compose 的
healthcheck 用本探针：python -m mineral_daily.common.healthcheck <url>
成功 exit 0，失败 exit 1。
"""

from __future__ import annotations

import asyncio
import sys

import anyio
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def check(url: str, timeout: float = 8.0) -> None:
    ok = False
    try:
        with anyio.fail_after(timeout):
            async with streamablehttp_client(url) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    ok = True
    except Exception:
        # 握手成功后传输层清理偶发的 ExceptionGroup 不算不健康
        if not ok:
            raise


def main() -> None:
    url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:18001/mcp"
    try:
        asyncio.run(check(url))
    except Exception as exc:  # noqa: BLE001 - 探针以退出码表达结果
        print(f"unhealthy: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    print("healthy")


if __name__ == "__main__":
    main()
