"""Shared pytest fixtures and config.

Kept deliberately tiny — most tests are pure-function unit tests on the
dataclasses and capability ABCs in :mod:`ai_edit.models`. Network-
dependent tests must be gated behind ``RUN_NETWORK_TESTS=1`` so the
default ``pytest`` invocation stays offline and fast.
"""

from __future__ import annotations

import os

import pytest


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip ``@pytest.mark.network`` tests unless ``RUN_NETWORK_TESTS=1``."""
    if os.environ.get("RUN_NETWORK_TESTS") == "1":
        return
    skip_network = pytest.mark.skip(reason="set RUN_NETWORK_TESTS=1 to run network tests")
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip_network)


def minimal_glb_bytes() -> bytes:
    """Build a tiny but spec-valid GLB.

    Phase 4.C added GLB validation to the fetch path, so tests can no
    longer mock the bytes as ``b"GLB-BYTES"``. This helper hands out a
    well-formed asset; tests that need to differentiate inputs can
    append unique bytes (kept under the JSON chunk padding).
    """
    import json

    json_bytes = json.dumps({"asset": {"version": "2.0"}}, separators=(",", ":")).encode()
    pad = (-len(json_bytes)) % 4
    json_bytes += b" " * pad
    chunk = len(json_bytes).to_bytes(4, "little") + b"JSON" + json_bytes
    total = 12 + len(chunk)
    header = b"glTF" + (2).to_bytes(4, "little") + total.to_bytes(4, "little")
    return header + chunk


def minimal_usdz_bytes() -> bytes:
    """Build the smallest payload that satisfies :func:`validate_usdz`.

    Real USDZ files are uncompressed zips with USD members; the
    validator only checks the ZIP local-file-header magic so this is
    enough to pass.
    """
    return b"PK\x03\x04" + b"\x00" * 26


@pytest.fixture
def minimal_glb() -> bytes:
    return minimal_glb_bytes()


@pytest.fixture
def minimal_usdz() -> bytes:
    return minimal_usdz_bytes()
