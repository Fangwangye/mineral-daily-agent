"""runner 的 http 传输安全策略测试。"""

from __future__ import annotations

import pytest

from mineral_daily.common.runner import _transport_security


class TestTransportSecurity:
    def test_default_enables_protection_with_localhost(self):
        sec = _transport_security(18001)
        assert sec.enable_dns_rebinding_protection is True
        assert "127.0.0.1:18001" in sec.allowed_hosts
        assert "localhost:18001" in sec.allowed_hosts
        assert "http://127.0.0.1:18001" in sec.allowed_origins

    def test_env_appends_service_hosts(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("MCP_ALLOWED_HOSTS", "news-mcp:18001, lan-host:18001")
        sec = _transport_security(18001)
        assert sec.enable_dns_rebinding_protection is True
        assert "news-mcp:18001" in sec.allowed_hosts
        assert "lan-host:18001" in sec.allowed_hosts
        assert "127.0.0.1:18001" in sec.allowed_hosts  # 本机调试仍然可用

    def test_star_disables_protection(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("MCP_ALLOWED_HOSTS", "*")
        sec = _transport_security(18001)
        assert sec.enable_dns_rebinding_protection is False
