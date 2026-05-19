"""Unit tests for the asset validators.

Phase 4.C. Verifies validate_glb / validate_usdz catch the failure
modes the fetcher would otherwise silently let through.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_edit.pipeline.asset_validate import (
    AssetValidationError,
    validate_glb,
    validate_usdz,
)


def _make_minimal_glb(*, json_payload: dict | None = None) -> bytes:
    """Construct a hand-rolled minimal valid GLB.

    Useful for tests because the seeded Khronos models aren't always
    on disk during a `tests/` run. The result is 100% spec-shaped:
    12-byte header + one JSON chunk, no BIN chunk.
    """
    manifest = json_payload if json_payload is not None else {"asset": {"version": "2.0"}}
    json_bytes = json.dumps(manifest, separators=(",", ":")).encode()
    # JSON chunks must align to 4 bytes; pad with spaces.
    pad = (-len(json_bytes)) % 4
    json_bytes += b" " * pad

    chunk = (
        len(json_bytes).to_bytes(4, "little")
        + b"JSON"
        + json_bytes
    )
    total = 12 + len(chunk)
    header = b"glTF" + (2).to_bytes(4, "little") + total.to_bytes(4, "little")
    return header + chunk


class TestValidateGlb:
    def test_accepts_minimal_valid_glb(self) -> None:
        validate_glb(_make_minimal_glb())

    def test_rejects_too_short(self) -> None:
        with pytest.raises(AssetValidationError, match="shorter than"):
            validate_glb(b"abc")

    def test_rejects_bad_magic(self) -> None:
        bad = b"NOPE" + (2).to_bytes(4, "little") + (12).to_bytes(4, "little")
        with pytest.raises(AssetValidationError, match="magic mismatch"):
            validate_glb(bad)

    def test_rejects_wrong_version(self) -> None:
        bad = b"glTF" + (1).to_bytes(4, "little") + (12).to_bytes(4, "little")
        with pytest.raises(AssetValidationError, match="version"):
            validate_glb(bad)

    def test_rejects_length_mismatch(self) -> None:
        valid = _make_minimal_glb()
        # Lie about length in the header.
        bad = valid[:8] + (len(valid) + 100).to_bytes(4, "little") + valid[12:]
        with pytest.raises(AssetValidationError, match="length mismatch"):
            validate_glb(bad)

    def test_rejects_non_json_first_chunk(self) -> None:
        # Build a GLB whose first chunk type is BIN\0 instead of JSON
        bin_chunk = (4).to_bytes(4, "little") + b"BIN\x00" + b"\x00" * 4
        total = 12 + len(bin_chunk)
        bad = b"glTF" + (2).to_bytes(4, "little") + total.to_bytes(4, "little") + bin_chunk
        with pytest.raises(AssetValidationError, match="first GLB chunk type is not JSON"):
            validate_glb(bad)

    def test_rejects_chunk_overrunning_payload(self) -> None:
        # Header says total length is short but chunk claims more.
        chunk_header = (1000).to_bytes(4, "little") + b"JSON"
        bad = b"glTF" + (2).to_bytes(4, "little") + (20).to_bytes(4, "little") + chunk_header
        with pytest.raises(AssetValidationError, match="length mismatch|extends beyond"):
            validate_glb(bad)

    def test_rejects_unparseable_json(self) -> None:
        # Truncate inside the JSON body so json.loads fails.
        manifest = '{"asset": {"version": "2.0"}'  # missing closing brace
        body = manifest.encode().ljust((len(manifest) + 3) & ~3, b" ")
        chunk = len(body).to_bytes(4, "little") + b"JSON" + body
        total = 12 + len(chunk)
        bad = b"glTF" + (2).to_bytes(4, "little") + total.to_bytes(4, "little") + chunk
        with pytest.raises(AssetValidationError, match="JSON chunk unparseable"):
            validate_glb(bad)

    def test_rejects_wrong_asset_version(self) -> None:
        with pytest.raises(AssetValidationError, match="asset.version"):
            validate_glb(_make_minimal_glb(json_payload={"asset": {"version": "1.0"}}))

    def test_rejects_missing_asset_object(self) -> None:
        with pytest.raises(AssetValidationError, match="asset.version"):
            validate_glb(_make_minimal_glb(json_payload={}))


class TestValidateUsdz:
    def test_accepts_zip_header(self) -> None:
        validate_usdz(b"PK\x03\x04" + b"\x00" * 20)

    def test_rejects_too_short(self) -> None:
        with pytest.raises(AssetValidationError, match="too small"):
            validate_usdz(b"PK")

    def test_rejects_html_404_page(self) -> None:
        # A real-world failure: CDN serves a 200 HTML 404 page.
        html = b"<!doctype html><h1>Not found</h1>"
        with pytest.raises(AssetValidationError, match="not a zip"):
            validate_usdz(html)


class TestRealSeedAsset:
    """Sanity check that the in-tree Box GLB (if fetched) passes.

    Skipped when ``out/scenes/box/model.glb`` isn't present so the
    test suite stays hermetic — the file lands after running
    ``fetch_catalog.py --id box`` and is git-ignored.
    """

    def test_seeded_box_passes(self) -> None:
        path = Path(__file__).resolve().parents[2] / "out" / "scenes" / "box" / "model.glb"
        if not path.is_file():
            pytest.skip(f"{path} not present — run fetch_catalog.py to seed")
        validate_glb(path.read_bytes())
