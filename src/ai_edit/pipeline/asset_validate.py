"""Lightweight asset validators run after a download / bundle.

Phase 4.C of the AR plan. Each validator either returns silently or
raises :class:`AssetValidationError` with a message specific enough
that the catalog fetcher can show it in its summary table.

These are *minimal* validators — they catch the cases that actually
break ``<model-viewer>`` and OS native viewers (corrupted downloads,
wrong format, length mismatches, broken JSON chunk, bad container
magic). A full Khronos glTF validator would also catch logical
errors (accessor index out of range, malformed material refs, etc.)
but it requires running their Node.js tool. Out of scope here.
"""

from __future__ import annotations

import json

# ASCII bytes the glTF binary container starts with.
_GLB_MAGIC = b"glTF"
# ASCII bytes for the GLB JSON chunk type identifier.
_GLB_CHUNK_JSON = b"JSON"
# Standard ZIP local-file header magic. USDZ is an uncompressed zip.
_ZIP_MAGIC = b"PK\x03\x04"


class AssetValidationError(ValueError):
    """Raised when downloaded bytes don't form a valid asset.

    Inherits from :class:`ValueError` so callers that already handle
    value errors (e.g. JSON decoding paths) don't need a new except
    branch.
    """


def validate_glb(data: bytes) -> None:
    """Verify ``data`` is a structurally valid GLB 2.0 container.

    Checks: magic, version, header length matches buffer length, the
    first chunk is JSON, the JSON chunk parses, ``asset.version`` is
    ``"2.0"``.

    Does *not* validate scene graph semantics — that's the job of a
    Khronos validator integration (future work).
    """
    if len(data) < 12:
        raise AssetValidationError(
            f"GLB shorter than the 12-byte header: got {len(data)} bytes"
        )

    if data[0:4] != _GLB_MAGIC:
        raise AssetValidationError(
            f"GLB magic mismatch: expected {_GLB_MAGIC!r}, got {data[0:4]!r}"
        )

    version = int.from_bytes(data[4:8], "little")
    if version != 2:
        raise AssetValidationError(f"unsupported glTF binary version: {version}")

    total_length = int.from_bytes(data[8:12], "little")
    if total_length != len(data):
        raise AssetValidationError(
            f"GLB length mismatch: header says {total_length}, payload is {len(data)}"
        )

    # First chunk after the header must be JSON.
    if len(data) < 20:
        raise AssetValidationError("GLB has no JSON chunk")

    json_chunk_length = int.from_bytes(data[12:16], "little")
    json_chunk_type = data[16:20]
    if json_chunk_type != _GLB_CHUNK_JSON:
        raise AssetValidationError(
            f"first GLB chunk type is not JSON: got {json_chunk_type!r}"
        )

    json_chunk_end = 20 + json_chunk_length
    if json_chunk_end > len(data):
        raise AssetValidationError(
            f"JSON chunk extends beyond GLB payload "
            f"({json_chunk_end} > {len(data)})"
        )

    # GLB JSON chunks are zero- or space-padded to 4-byte alignment.
    json_bytes = data[20:json_chunk_end].rstrip(b" \x00")
    try:
        manifest = json.loads(json_bytes)
    except json.JSONDecodeError as exc:
        raise AssetValidationError(f"GLB JSON chunk unparseable: {exc}") from exc

    asset_version = ((manifest.get("asset") or {}).get("version"))
    if asset_version != "2.0":
        raise AssetValidationError(
            f"glTF asset.version is not '2.0': got {asset_version!r}"
        )


def validate_usdz(data: bytes) -> None:
    """Verify ``data`` looks like a USDZ container.

    USDZ is an uncompressed zip with at least one ``.usd*`` member.
    A full content check requires opening the zip; this minimal
    validator only checks the zip local-file-header magic so a
    Cloudflare HTML 404 page can't be smuggled in as a "USDZ".
    """
    if len(data) < 4:
        raise AssetValidationError(f"USDZ too small: {len(data)} bytes")
    if data[0:4] != _ZIP_MAGIC:
        raise AssetValidationError(
            f"USDZ not a zip container: magic {data[0:4]!r}"
        )
