"""共享 HTTP 层：统一 UA、超时、重试、磁盘缓存与离线模式。

降级顺序：新鲜缓存 → live 抓取 → 过期缓存兜底 → 抛错。
设置 MINERAL_OFFLINE=1 后完全不发起网络请求，只读缓存（无缓存则抛 OfflineModeError，
由各数据层落到打包 fixture/快照）。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 mineral-daily-agent/0.1"
)
DEFAULT_TIMEOUT = 15.0
MAX_DOWNLOAD_BYTES = 80 * 1024 * 1024


class OfflineModeError(RuntimeError):
    """离线模式（MINERAL_OFFLINE=1）下无可用缓存。"""


def is_offline() -> bool:
    return os.environ.get("MINERAL_OFFLINE", "").strip().lower() in {"1", "true", "yes"}


def cache_dir() -> Path:
    base = os.environ.get("MINERAL_CACHE_DIR")
    path = Path(base) if base else Path.home() / ".cache" / "mineral-daily"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _key(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]


@dataclass
class FetchedText:
    url: str
    text: str
    status: int
    from_cache: bool
    fetched_at: float


def _cache_read(url: str, max_age: float | None) -> FetchedText | None:
    path = cache_dir() / f"{_key(url)}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if max_age is not None and time.time() - data["fetched_at"] > max_age:
        return None
    return FetchedText(
        url=url,
        text=data["text"],
        status=data["status"],
        from_cache=True,
        fetched_at=data["fetched_at"],
    )


def _cache_write(url: str, text: str, status: int) -> None:
    path = cache_dir() / f"{_key(url)}.json"
    payload = {"url": url, "text": text, "status": status, "fetched_at": time.time()}
    try:
        path.write_text(json.dumps(payload, ensure_ascii=False), "utf-8")
    except OSError:
        logger.warning("缓存写入失败: %s", url)


def _retryable(exc: Exception) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        return code == 429 or code >= 500
    return False


async def fetch_text(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    retries: int = 2,
    cache_ttl: float | None = None,
) -> FetchedText:
    """抓取文本资源。cache_ttl 秒内的缓存直接命中；live 失败时容忍过期缓存。"""
    if cache_ttl is not None:
        cached = _cache_read(url, cache_ttl)
        if cached:
            return cached
    if is_offline():
        cached = _cache_read(url, None)
        if cached:
            return cached
        raise OfflineModeError(f"MINERAL_OFFLINE=1 且无本地缓存: {url}")

    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            async with httpx.AsyncClient(
                headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=timeout
            ) as client:
                resp = await client.get(url)
            resp.raise_for_status()
            _cache_write(url, resp.text, resp.status_code)
            return FetchedText(
                url=url,
                text=resp.text,
                status=resp.status_code,
                from_cache=False,
                fetched_at=time.time(),
            )
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            last_exc = exc
            if _retryable(exc) and attempt < retries:
                await asyncio.sleep(0.5 * (attempt + 1))
                continue
            break

    cached = _cache_read(url, None)
    if cached:
        logger.warning("live 抓取失败，回落过期缓存: %s (%s)", url, last_exc)
        return cached
    assert last_exc is not None
    raise last_exc


async def fetch_file(
    url: str,
    *,
    suffix: str = ".bin",
    timeout: float = 60.0,
    retries: int = 2,
    max_bytes: int = MAX_DOWNLOAD_BYTES,
) -> Path:
    """流式下载二进制资源到缓存目录，返回本地路径；命中缓存则直接返回。"""
    target = cache_dir() / f"{_key(url)}{suffix}"
    if target.exists() and target.stat().st_size > 0:
        return target
    if is_offline():
        raise OfflineModeError(f"MINERAL_OFFLINE=1 且无本地缓存文件: {url}")

    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        tmp = target.with_suffix(target.suffix + ".part")
        try:
            async with httpx.AsyncClient(
                headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=timeout
            ) as client:
                async with client.stream("GET", url) as resp:
                    resp.raise_for_status()
                    size = 0
                    with tmp.open("wb") as fh:
                        async for chunk in resp.aiter_bytes():
                            size += len(chunk)
                            if size > max_bytes:
                                raise ValueError(f"下载超过 {max_bytes} 字节上限: {url}")
                            fh.write(chunk)
            tmp.replace(target)
            return target
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            last_exc = exc
            tmp.unlink(missing_ok=True)
            if _retryable(exc) and attempt < retries:
                await asyncio.sleep(0.5 * (attempt + 1))
                continue
            break
        except ValueError:
            tmp.unlink(missing_ok=True)
            raise
    assert last_exc is not None
    raise last_exc
