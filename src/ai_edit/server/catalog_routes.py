"""HTTP routes exposing the curated 3D-asset catalog.

Phases 3.A (JSON API) and 3.B (HTML browse page) of the AR plan. The
catalog itself lives in :mod:`ai_edit.pipeline.asset_catalog`; this
module turns it into HTTP surfaces.

Two routers are exported:

- :func:`build_catalog_api_router` mounted under ``/api/catalog`` —
  JSON endpoints for programmatic consumers and the frontend.
- :func:`build_catalog_browse_router` mounted at the root — a
  zero-JS ``GET /catalog`` page rendering cards with thumbnails +
  "View in AR" links.

The asset bytes themselves are still served by the AR routes
(``/ar/{scene_id}/model.glb`` etc.) — this module deals only in
metadata + a thin browsing UI.
"""

from __future__ import annotations

import html
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from ..pipeline.asset_catalog import AssetCatalog, AssetCatalogEntry


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


def build_catalog_api_router(catalog: AssetCatalog) -> APIRouter:
    """Construct the JSON API router with ``catalog`` baked in.

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


def _render_card(entry: AssetCatalogEntry) -> str:
    """Render one catalog entry as an HTML card.

    All user-controllable fields are :func:`html.escape`-quoted; the
    manifest is checked into git so it's trusted today, but escaping
    keeps us safe if the catalog ever sources from user input.
    """
    safe_id = html.escape(entry.id, quote=True)
    safe_name = html.escape(entry.name, quote=True)
    safe_category = html.escape(entry.category, quote=True)
    safe_desc = html.escape(entry.description, quote=True)
    safe_license = html.escape(entry.license, quote=True)
    safe_attribution = html.escape(entry.attribution, quote=True)
    safe_source = html.escape(entry.source_url, quote=True)

    if entry.thumbnail_url:
        thumb_html = (
            f'<img class="thumb" src="{html.escape(entry.thumbnail_url, quote=True)}" '
            f'alt="{safe_name} thumbnail" loading="lazy">'
        )
    else:
        thumb_html = '<div class="thumb thumb-placeholder">no preview</div>'

    attribution_html = (
        f'<div class="attribution">by {safe_attribution}</div>'
        if entry.attribution
        else ""
    )

    return f"""<article class="card">
  {thumb_html}
  <div class="meta">
    <h2>{safe_name}</h2>
    <div class="category">{safe_category}</div>
    <p class="desc">{safe_desc}</p>
    <div class="license"><a href="{safe_source}" target="_blank" rel="noopener">{safe_license}</a></div>
    {attribution_html}
  </div>
  <a class="cta" href="/ar/{safe_id}">View in AR</a>
</article>"""


def _render_browse_html(entries: list[AssetCatalogEntry]) -> str:
    """Render the catalog browse page.

    Server-rendered: no JS, no frontend framework. Easier to keep
    accessible and easier to test.
    """
    if entries:
        cards_html = "\n".join(_render_card(e) for e in entries)
        empty_html = ""
    else:
        cards_html = ""
        empty_html = '<div class="empty">No models in the catalog yet.</div>'

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>AR catalog — image-ai-edit</title>
<style>
  :root {{ color-scheme: dark; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; min-height: 100vh; background: #111; color: #eee;
         font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
         line-height: 1.4; }}
  header {{ padding: 24px 32px; border-bottom: 1px solid #222; }}
  header h1 {{ margin: 0 0 4px; font-size: 22px; font-weight: 600; }}
  header p {{ margin: 0; color: #999; font-size: 14px; }}
  main {{ padding: 24px 32px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
           gap: 16px; }}
  .card {{ display: flex; flex-direction: column; background: #181818;
           border: 1px solid #222; border-radius: 12px; overflow: hidden;
           transition: transform 120ms ease, border-color 120ms ease; }}
  .card:hover {{ border-color: #444; transform: translateY(-2px); }}
  .thumb {{ width: 100%; aspect-ratio: 1 / 1; object-fit: cover; background: #0a0a0a;
            display: flex; align-items: center; justify-content: center;
            color: #555; font-size: 13px; }}
  .thumb-placeholder {{ font-style: italic; }}
  .meta {{ padding: 14px 16px 4px; flex: 1; }}
  .meta h2 {{ margin: 0 0 2px; font-size: 16px; font-weight: 600; }}
  .category {{ font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em;
               color: #888; margin-bottom: 8px; }}
  .desc {{ margin: 0 0 10px; font-size: 13px; color: #bbb; }}
  .license {{ font-size: 12px; color: #777; }}
  .license a {{ color: inherit; text-decoration: underline; text-decoration-color: #333; }}
  .attribution {{ font-size: 12px; color: #666; margin-top: 2px; }}
  .cta {{ display: block; margin: 12px 16px 16px; padding: 10px;
          background: #fff; color: #111; text-align: center; text-decoration: none;
          border-radius: 8px; font-weight: 600; font-size: 14px; }}
  .cta:hover {{ background: #ddd; }}
  .empty {{ padding: 48px; text-align: center; color: #777; }}
  .count {{ color: #888; font-size: 13px; margin-bottom: 16px; }}
</style>
</head>
<body>
<header>
  <h1>AR catalog</h1>
  <p>Curated 3D models — tap a card to preview in AR on your phone.</p>
</header>
<main>
  <div class="count">{len(entries)} model{'' if len(entries) == 1 else 's'}</div>
  <div class="grid">
    {cards_html}
  </div>
  {empty_html}
</main>
</body>
</html>
"""


def build_catalog_browse_router(catalog: AssetCatalog) -> APIRouter:
    """Construct the ``GET /catalog`` HTML browse router.

    Zero-JS — the page is fully server-rendered. Each card links to
    ``/ar/<id>`` so the AR delivery path Phase 1 already built handles
    the actual viewer.
    """
    router = APIRouter(tags=["catalog-browse"])

    @router.get("/catalog", response_class=HTMLResponse)
    async def browse() -> HTMLResponse:
        return HTMLResponse(_render_browse_html(catalog.list()))

    return router
