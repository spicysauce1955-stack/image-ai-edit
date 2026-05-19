"""Unit tests for the texture bundler.

The pygltflib-backed assembly step is exercised end-to-end against a
real Poly Haven URL in a separate ``@pytest.mark.network`` test below,
gated behind ``RUN_NETWORK_TESTS=1``. Plain unit tests mock httpx and
verify the orchestration: which URLs are fetched, what files land on
disk, how the .gltf JSON is parsed.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from ai_edit.pipeline.asset_bundle import (
    discover_external_refs,
    download_gltf_assembly,
)


# -- discover_external_refs --------------------------------------------------


class TestDiscoverExternalRefs:
    def test_returns_buffer_and_image_uris(self) -> None:
        gltf = {
            "buffers": [{"uri": "model.bin", "byteLength": 100}],
            "images": [{"uri": "textures/diff.png"}, {"uri": "textures/nor.png"}],
        }
        assert discover_external_refs(gltf) == [
            "model.bin",
            "textures/diff.png",
            "textures/nor.png",
        ]

    def test_skips_data_uris(self) -> None:
        gltf = {
            "buffers": [{"uri": "data:application/octet-stream;base64,AAAA"}],
            "images": [{"uri": "textures/real.png"}],
        }
        assert discover_external_refs(gltf) == ["textures/real.png"]

    def test_skips_absolute_urls(self) -> None:
        # A glTF may legally reference an absolute URL. We don't try
        # to bundle those — they'd require their own retry / hosting
        # decisions.
        gltf = {
            "images": [
                {"uri": "https://cdn.example.invalid/tex.png"},
                {"uri": "relative.png"},
            ],
        }
        assert discover_external_refs(gltf) == ["relative.png"]

    def test_no_buffers_or_images(self) -> None:
        assert discover_external_refs({}) == []
        assert discover_external_refs({"buffers": [], "images": []}) == []

    def test_handles_uri_missing(self) -> None:
        # Buffers / images can omit ``uri`` when they reference an
        # already-bundled buffer view.
        gltf = {
            "buffers": [{"byteLength": 100}],
            "images": [{"bufferView": 0}],
        }
        assert discover_external_refs(gltf) == []

    def test_handles_null_entries(self) -> None:
        # Defensive: real-world manifests sometimes have None entries
        # (the glTF spec doesn't forbid trailing nulls).
        gltf = {"buffers": [None, {"uri": "ok.bin"}]}
        assert discover_external_refs(gltf) == ["ok.bin"]


# -- download_gltf_assembly --------------------------------------------------


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


class TestDownloadGltfAssembly:
    def test_writes_gltf_and_external_refs(self, tmp_path: Path) -> None:
        gltf_json = {
            "asset": {"version": "2.0"},
            "buffers": [{"uri": "model.bin", "byteLength": 4}],
            "images": [{"uri": "textures/diff.png"}],
        }
        downloads: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            downloads.append(url)
            if url.endswith(".gltf"):
                return httpx.Response(200, json=gltf_json)
            if url.endswith("model.bin"):
                return httpx.Response(200, content=b"BIN!")
            if url.endswith("diff.png"):
                return httpx.Response(200, content=b"PNG-BYTES")
            return httpx.Response(404)

        with _client(handler) as client:
            gltf_path = download_gltf_assembly(
                "https://example.invalid/path/model.gltf",
                tmp_path,
                client=client,
            )

        assert gltf_path == tmp_path / "model.gltf"
        assert gltf_path.is_file()
        # JSON is preserved verbatim.
        assert json.loads(gltf_path.read_text()) == gltf_json
        # External resources land at their relative paths.
        assert (tmp_path / "model.bin").read_bytes() == b"BIN!"
        assert (tmp_path / "textures" / "diff.png").read_bytes() == b"PNG-BYTES"
        # Every external ref + the gltf itself produced exactly one request.
        assert sorted(downloads) == sorted(
            [
                "https://example.invalid/path/model.gltf",
                "https://example.invalid/path/model.bin",
                "https://example.invalid/path/textures/diff.png",
            ]
        )

    def test_creates_subdirs_for_nested_refs(self, tmp_path: Path) -> None:
        gltf_json = {
            "asset": {"version": "2.0"},
            "images": [{"uri": "deep/sub/dir/tex.png"}],
        }

        def handler(request: httpx.Request) -> httpx.Response:
            if str(request.url).endswith(".gltf"):
                return httpx.Response(200, json=gltf_json)
            return httpx.Response(200, content=b"X")

        with _client(handler) as client:
            download_gltf_assembly(
                "https://example.invalid/model.gltf", tmp_path, client=client
            )

        assert (tmp_path / "deep" / "sub" / "dir" / "tex.png").is_file()

    def test_404_on_texture_propagates(self, tmp_path: Path) -> None:
        gltf_json = {"images": [{"uri": "missing.png"}]}

        def handler(request: httpx.Request) -> httpx.Response:
            if str(request.url).endswith(".gltf"):
                return httpx.Response(200, json=gltf_json)
            return httpx.Response(404)

        with _client(handler) as client:
            with pytest.raises(httpx.HTTPStatusError):
                download_gltf_assembly(
                    "https://example.invalid/model.gltf", tmp_path, client=client
                )


# -- Integration test (network-gated) ---------------------------------------


@pytest.mark.network
def test_bundle_khronos_box_gltf_produces_valid_glb() -> None:
    """End-to-end smoke against Khronos's Box.gltf (gltf + .bin).

    Gated by ``RUN_NETWORK_TESTS=1`` (see conftest.py) — skipped by
    default to keep ``pytest`` offline. Verifies the bundler produces
    real GLB bytes from a real multi-file glTF whose relative paths
    resolve naively against the .gltf's base URL.

    Poly Haven assets need a custom URL rewriter (their .gltf's
    relative paths don't match their CDN layout) — that's wired up in
    Phase 4.B.
    """
    from ai_edit.pipeline.asset_bundle import bundle_remote_gltf

    url = (
        "https://raw.githubusercontent.com/KhronosGroup/glTF-Sample-Assets/"
        "main/Models/Box/glTF/Box.gltf"
    )
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        glb = bundle_remote_gltf(url, client=client)

    # GLB magic = ASCII "glTF"
    assert glb[:4] == b"glTF", "output is not a glTF binary"
    # Version 2 at bytes 4-7 little-endian.
    assert int.from_bytes(glb[4:8], "little") == 2
    # Header advertises total length in bytes 8-11.
    advertised = int.from_bytes(glb[8:12], "little")
    assert advertised == len(glb), "GLB header length disagrees with payload"
    assert len(glb) > 200, "GLB unexpectedly tiny — buffer probably missed"
