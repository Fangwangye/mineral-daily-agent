"""测试全局配置：默认离线 + 隔离缓存目录，保证单测不出网、可重复。

需要真实外网的用例用 @pytest.mark.network 标记（默认跳过，见 pyproject addopts）。
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolated_env(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.setenv("MINERAL_CACHE_DIR", str(tmp_path / "cache"))
    if "network" in request.keywords:
        monkeypatch.delenv("MINERAL_OFFLINE", raising=False)
    else:
        monkeypatch.setenv("MINERAL_OFFLINE", "1")
