"""Expose the local dev server over HTTPS via Cloudflare Tunnel.

Phase 6.A's ``/ar/<id>/live`` page uses WebXR, which browsers gate
behind a *secure context*. ``localhost`` is exempt; LAN IPs are not.
Cloudflare's Quick Tunnel mode opens a public
``https://<words>.trycloudflare.com`` URL that proxies to a local
port, giving us a real cert chain on a real public hostname — no
phone-side root-CA install, no SAN gymnastics.

Run ``scripts/serve.py`` in one terminal, this in another. The
script prints the public URL prominently and keeps the tunnel
open until Ctrl-C.

Usage::

    .venv/bin/python scripts/dev_tunnel.py             # tunnel to localhost:8000
    .venv/bin/python scripts/dev_tunnel.py --port 8080

Trade-offs (see docs/runbook.md → HTTPS for phone testing):
- Public URL — discoverable while the tunnel is up.
- Internet dependency.
- Cloudflare sees the traffic.
- URL rotates per session (quick-tunnel mode); no Cloudflare
  account required.
"""

from __future__ import annotations

import argparse
import os
import platform
import re
import shutil
import subprocess
import sys

# Cloudflare Quick Tunnel URLs always live under trycloudflare.com.
# The host label is a hyphen-separated set of words/digits (the exact
# format is up to Cloudflare; the regex matches their current
# pattern while tolerating future variation in the label).
_TRYCLOUDFLARE_RE = re.compile(
    r"https://[A-Za-z0-9][A-Za-z0-9-]*\.trycloudflare\.com",
)


def _install_hint() -> str:
    """Platform-specific install instructions for cloudflared.

    Always returns non-empty text. The "other" branch points at
    upstream docs rather than guessing.
    """
    system = platform.system()
    if system == "Darwin":
        return "brew install cloudflared"
    if system == "Linux":
        return (
            "curl -L https://pkg.cloudflare.com/cloudflared-stable-linux-amd64.deb"
            " -o /tmp/cloudflared.deb && \\\n"
            "    sudo dpkg -i /tmp/cloudflared.deb"
        )
    if system == "Windows":
        return "winget install --id Cloudflare.cloudflared"
    return "See https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"


def require_cloudflared() -> str:
    """Return the resolved cloudflared path, or exit 127 with hints.

    Exit 127 follows shell convention for "command not found".
    """
    path = shutil.which("cloudflared")
    if path:
        return path
    print("error: cloudflared is not on PATH.", file=sys.stderr)
    print("", file=sys.stderr)
    print("Install cloudflared, then re-run this script:", file=sys.stderr)
    print("", file=sys.stderr)
    for line in _install_hint().splitlines():
        print(f"  {line}", file=sys.stderr)
    print("", file=sys.stderr)
    print(
        "Docs: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/",
        file=sys.stderr,
    )
    sys.exit(127)


def extract_public_url(line: str) -> str | None:
    """Pull a ``trycloudflare.com`` URL out of a cloudflared log line.

    Pure function — easy to test. Returns the first match or None.
    """
    match = _TRYCLOUDFLARE_RE.search(line)
    return match.group(0) if match else None


def _banner(public_url: str, port: int) -> str:
    """Render the loud-banner block printed once the URL is known."""
    bar = "=" * 60
    return (
        f"\n{bar}\n"
        f" PUBLIC URL:  {public_url}\n"
        f"\n"
        f" Phone test (Android Chrome — WebXR):\n"
        f"   {public_url}/ar/chainlink_fence/live\n"
        f"\n"
        f" Phone test (iOS Safari — Quick Look):\n"
        f"   {public_url}/ar/teapot\n"
        f"\n"
        f" Catalog browser:\n"
        f"   {public_url}/catalog\n"
        f"\n"
        f" Tunnel proxies to:  http://localhost:{port}\n"
        f"{bar}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Local port to expose (default: 8000, matches scripts/serve.py).",
    )
    args = parser.parse_args(argv)

    if os.name != "posix":
        # cloudflared's stdio buffering depends on a TTY (Go stdlib
        # default). We allocate one with the ``pty`` module — POSIX
        # only. On Windows, drop the user into the upstream CLI.
        print(
            "scripts/dev_tunnel.py uses a pty (POSIX-only) to capture\n"
            "cloudflared's URL output. On Windows, run cloudflared directly:\n"
            f"  cloudflared tunnel --url http://localhost:{args.port}",
            file=sys.stderr,
        )
        return 2

    cloudflared = require_cloudflared()
    target = f"http://localhost:{args.port}"

    print(f"==> starting Cloudflare Quick Tunnel  →  {target}")
    print("    (waiting for cloudflared to allocate a public URL…)")
    print()

    return _run_cloudflared_in_pty(
        [cloudflared, "tunnel", "--url", target],
        on_line=_handle_line_factory(args.port),
    )


def _handle_line_factory(port: int):
    """Build the per-line callback used by :func:`_run_cloudflared_in_pty`.

    Closure carries the "banner already printed" flag so the loud
    banner shows up exactly once.
    """
    state = {"banner_printed": False}

    def on_line(line: str) -> None:
        # Always echo cloudflared's log verbatim — colored ANSI
        # escape codes pass through to the terminal unchanged.
        sys.stdout.write(line)
        sys.stdout.flush()
        if not state["banner_printed"]:
            url = extract_public_url(line)
            if url:
                print(_banner(url, port))
                state["banner_printed"] = True

    return on_line


def _run_cloudflared_in_pty(argv: list[str], *, on_line) -> int:
    """Spawn ``argv`` with stdout+stderr attached to a pty so the
    child's logger line-buffers naturally, then stream lines to
    ``on_line`` until EOF.

    cloudflared (Go binary) detects a non-TTY stdout and switches to
    block-buffered output — without this trick we'd never see the
    public URL until the process terminated. A POSIX pty bypasses
    that.
    """
    # Imported here, inside the POSIX branch, so the script module
    # still imports cleanly on Windows (for unit tests).
    import pty

    master_fd, slave_fd = pty.openpty()
    proc = subprocess.Popen(
        argv,
        stdout=slave_fd,
        stderr=slave_fd,
        close_fds=True,
    )
    os.close(slave_fd)

    try:
        with os.fdopen(master_fd, "r", encoding="utf-8", errors="replace") as master:
            for line in master:
                on_line(line)
    except OSError:
        # The master fd closes when the child exits — treat the read
        # error as a normal EOF instead of a fatal one.
        pass
    except KeyboardInterrupt:
        proc.terminate()
        try:
            return proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        return 0
    return proc.wait()


if __name__ == "__main__":
    raise SystemExit(main())
