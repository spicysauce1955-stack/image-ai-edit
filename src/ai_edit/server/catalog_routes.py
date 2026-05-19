"""HTTP routes exposing the curated 3D-asset catalog.

Phase 3.A of the AR plan. The catalog itself lives in
:mod:`ai_edit.pipeline.asset_catalog`; this module turns it into a JSON
HTTP surface so the web UI (and any third-party caller) can enumerate
what's available without scraping ``assets/catalog.json``.

Routes mounted under ``/api/catalog``:

``GET /api/catalog``
    List entries. Optional ``?category=fence`` filter.

``GET /api/catalog/categories``
    Distinct category names in manifest order.

``GET /api/catalog/{asset_id}``
    Return one entry or 404.

The asset bytes themselves are still served by the AR routes
(``/ar/{scene_id}/model.glb`` etc.) — this module deals only in
metadata.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from ..pipeline.asset_catalog import AssetCatalog


def _entry_to_payload(entry: Any) -> dict[str, Any]:
    """Serialize an :class:`AssetCatalogEntry` for the wire.

    Adds derived fields that are convenient for clients (the absolute
    AR-route URLs) so the frontend doesn't need to hard-code path
    templates.
    """
    payload = entry.to_dict()
    payload["ar_url"] = f"/ar/{entry.id}"
    payload["glb_local_url"] = f"/ar/{entry.id}/model.glb" if entry.glb_url else None
    payload["usdz_local_url"] = f"/ar/{entry.id}/model.usdz" if entry.usdz_url else None
    return payload


def build_catalog_router(catalog: AssetCatalog) -> APIRouter:
    """Construct the catalog router with ``catalog`` baked in.

    Returning a fresh router per call mirrors :func:`build_ar_router`
    — tests can inject a controlled catalog without touching module
    state.
    """
    router = APIRouter(prefix="/api/catalog", tags=["catalog"])

    # NOTE: register ``/categories`` *before* ``/{asset_id}`` so the
    # literal path wins over the path-param match.

    @router.get("/categories")
    async def list_categories() -> list[str]:
        """Distinct categories in first-seen manifest order."""
        return catalog.categories()

    @router.get("")
    async def list_entries(category: str | None = None) -> list[dict[str, Any]]:
        """List catalog entries, optionally filtered by ``category``.

        Unknown categories return ``[]`` (rather than 404) — this is a
        list endpoint, and an empty list is a valid answer.
        """
        return [_entry_to_payload(e) for e in catalog.list(category)]

    @router.get("/{asset_id}")
    async def get_entry(asset_id: str) -> dict[str, Any]:
        """Return one entry's metadata or 404."""
        entry = catalog.get(asset_id)
        if entry is None:
            raise HTTPException(
                status_code=404, detail=f"Unknown catalog id: {asset_id}"
            )
        return _entry_to_payload(entry)

    return router
