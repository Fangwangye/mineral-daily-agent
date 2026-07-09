"""日志配置。

MCP stdio 传输把 stdout 用作 JSON-RPC 信道，因此所有日志必须走 stderr。
"""

from __future__ import annotations

import logging
import os
import sys

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s - %(message)s"


def setup_logging(level: str | None = None) -> None:
    """初始化根日志器：输出到 stderr，级别取 LOG_LEVEL 环境变量（默认 INFO）。"""
    resolved = (level or os.environ.get("LOG_LEVEL", "INFO")).upper()
    logging.basicConfig(stream=sys.stderr, level=resolved, format=_FORMAT)
    # 降低三方库噪音
    for noisy in ("httpx", "httpcore", "pdfminer", "trafilatura", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
