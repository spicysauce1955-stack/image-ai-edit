"""Unit tests for scripts/dev_tunnel.py.

Covers pure-function behaviour only — the URL regex and the per-OS
install hints. The cloudflared subprocess pipe is exercised by the
manual smoke in ``docs/runbook.md``; mocking it here would just
assert "we called subprocess with these argv tokens", a tautology.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# scripts/ isn't a package — load dev_tunnel.py by path so this test
# file doesn't need any conftest manipulation.
_DEV_TUNNEL_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "dev_tunnel.py"
)
_spec = importlib.util.spec_from_file_location("dev_tunnel", _DEV_TUNNEL_PATH)
assert _spec is not None and _spec.loader is not None
dev_tunnel = importlib.util.module_from_spec(_spec)
sys.modules["dev_tunnel"] = dev_tunnel
_spec.loader.exec_module(dev_tunnel)


class TestExtractPublicUrl:
    @pytest.mark.parametrize(
        "line, expected",
        [
            (
                "Your quick Tunnel has been created! Visit it at:\n",
                None,
            ),
            (
                "|  https://swift-banana-grove-x42.trycloudflare.com  |\n",
                "https://swift-banana-grove-x42.trycloudflare.com",
            ),
            (
                "2026-05-20T11:30:00Z INF +-- "
                "https://red-fox-meadow.trycloudflare.com",
                "https://red-fox-meadow.trycloudflare.com",
            ),
            (
                "INF Connecting to https://api.trycloudflare.com/...",
                "https://api.trycloudflare.com",
            ),
        ],
    )
    def test_matches_real_log_lines(self, line: str, expected: str | None) -> None:
        assert dev_tunnel.extract_public_url(line) == expected

    def test_returns_none_for_unrelated_lines(self) -> None:
        # Plain log noise.
        assert dev_tunnel.extract_public_url("2026-05-20T11:30:00Z INF starting") is None
        assert dev_tunnel.extract_public_url("") is None

    def test_returns_none_for_unrelated_https_urls(self) -> None:
        assert (
            dev_tunnel.extract_public_url(
                "see https://developers.cloudflare.com/cloudflare-one/"
            )
            is None
        )
        assert dev_tunnel.extract_public_url("https://example.com") is None

    def test_captures_url_without_trailing_punctuation(self) -> None:
        # Cloudflared often boxes the URL in pipes or brackets; the
        # regex should pull just the URL.
        line = "(https://abc-def.trycloudflare.com)"
        assert dev_tunnel.extract_public_url(line) == "https://abc-def.trycloudflare.com"

    def test_first_match_wins_when_multiple(self) -> None:
        line = (
            "first https://one.trycloudflare.com "
            "second https://two.trycloudflare.com"
        )
        assert dev_tunnel.extract_public_url(line) == "https://one.trycloudflare.com"


class TestInstallHint:
    @pytest.mark.parametrize(
        "system",
        ["Darwin", "Linux", "Windows", "FreeBSD", ""],
    )
    def test_returns_non_empty_per_platform(self, system: str) -> None:
        with patch.object(dev_tunnel.platform, "system", return_value=system):
            hint = dev_tunnel._install_hint()
        assert hint, f"empty hint for system={system!r}"

    def test_darwin_recommends_brew(self) -> None:
        with patch.object(dev_tunnel.platform, "system", return_value="Darwin"):
            assert "brew" in dev_tunnel._install_hint()

    def test_linux_uses_official_deb(self) -> None:
        with patch.object(dev_tunnel.platform, "system", return_value="Linux"):
            hint = dev_tunnel._install_hint()
        assert "cloudflared-stable-linux-amd64.deb" in hint
        assert "dpkg" in hint

    def test_windows_uses_winget(self) -> None:
        with patch.object(dev_tunnel.platform, "system", return_value="Windows"):
            assert "winget" in dev_tunnel._install_hint()


class TestRequireCloudflared:
    def test_returns_path_when_present(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(dev_tunnel.shutil, "which", lambda name: "/fake/cloudflared")
        assert dev_tunnel.require_cloudflared() == "/fake/cloudflared"

    def test_exits_127_when_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(dev_tunnel.shutil, "which", lambda name: None)
        with pytest.raises(SystemExit) as excinfo:
            dev_tunnel.require_cloudflared()
        assert excinfo.value.code == 127


class TestBanner:
    def test_includes_url_and_port(self) -> None:
        banner = dev_tunnel._banner("https://x.trycloudflare.com", 8000)
        assert "https://x.trycloudflare.com" in banner
        assert "localhost:8000" in banner

    def test_includes_deep_links_to_real_catalog_entries(self) -> None:
        # These deep-link examples are the most useful starting
        # points; if the catalog ever drops chainlink_fence or
        # teapot, update both the catalog manifest and this banner.
        banner = dev_tunnel._banner("https://x.trycloudflare.com", 8000)
        assert "/ar/chainlink_fence/live" in banner
        assert "/ar/teapot" in banner
        assert "/catalog" in banner
