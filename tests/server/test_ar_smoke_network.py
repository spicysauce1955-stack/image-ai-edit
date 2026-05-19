"""End-to-end CI smoke test for the AR delivery pipeline.

Phase 4.D. Gated by ``RUN_NETWORK_TESTS=1`` so the offline ``pytest``
default stays fast. When enabled, the test:

1. Loads the real in-tree catalog (``assets/catalog.json``).
2. Fetches the ``box`` entry through ``catalog_fetch.fetch_entry``
   (real Khronos URL → real GLB → AR store on a tmp path).
3. Spins up a TestClient against an app rooted on that tmp store.
4. Asserts the AR viewer page renders, ``/model.glb`` returns the
   right MIME, and the catalog API exposes Box.

If any link in the chain breaks (URL moved, validator regression,
route mis-mount), this test fails fast.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from ai_edit.models import MIME_GLB
from ai_edit.pipeline.ar_store import FilesystemARStore
from ai_edit.pipeline.asset_catalog import AssetCatalog
from ai_edit.pipeline.catalog_fetch import fetch_entry
from ai_edit.server.app import create_app


@pytest.mark.network
def test_ar_pipeline_end_to_end_via_box(tmp_path: Path) -> None:
    catalog = AssetCatalog.load()
    box = catalog.get("box")
    assert box is not None, "box entry should be in the seed manifest"

    store = FilesystemARStore(tmp_path)
    with httpx.Client(timeout=30, follow_redirects=True) as http:
        result = fetch_entry(box, store, client=http)

    assert result.glb.ok, f"box fetch failed: {result.glb.error!r}"

    client = TestClient(create_app(ar_store=store, catalog=catalog))

    # AR viewer renders.
    viewer = client.get("/ar/box")
    assert viewer.status_code == 200
    assert "<model-viewer" in viewer.text
    assert 'src="/ar/box/model.glb"' in viewer.text

    # The GLB serves with the right MIME and validator-approved bytes.
    glb = client.get("/ar/box/model.glb")
    assert glb.status_code == 200
    assert glb.headers["content-type"] == MIME_GLB
    assert glb.content[:4] == b"glTF"

    # Catalog API exposes the entry.
    api = client.get("/api/catalog/box")
    assert api.status_code == 200
    assert api.json()["id"] == "box"
