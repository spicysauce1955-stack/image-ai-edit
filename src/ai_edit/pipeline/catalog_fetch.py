"""Download catalog entries into an :class:`ARStore`.

Phase 2.B of the AR plan. Pure orchestration: takes a loaded
:class:`AssetCatalog`, an :class:`ARStore`, and an ``httpx`` client; for
each entry it fetches whichever of ``glb_url`` / ``usdz_url`` are set
and writes the bytes into the store under the entry's ``id``.

The CLI surface lives in ``scripts/fetch_catalog.py``; everything that
benefits from being importable + unit-testable lives here.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx

from ..models.base import MIME_GLB, MIME_USDZ, Scene3DAsset
from .ar_store import ARStore
from .asset_bundle import bundle_remote_gltf, get_rewriter
from .asset_catalog import AssetCatalog, AssetCatalogEntry

DEFAULT_TIMEOUT_S = 60


@dataclass
class FetchOutcome:
    """Result of fetching one format (GLB or USDZ) for one entry.

    Exactly one of ``bytes_written`` / ``skipped_reason`` /
    ``error`` is populated for any given outcome.
    """

    bytes_written: int | None = None
    skipped_reason: str | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        """True only if the format was attempted *and* succeeded."""
        return self.bytes_written is not None


@dataclass
class FetchResult:
    """Per-entry outcome aggregated across formats."""

    asset_id: str
    glb: FetchOutcome = field(default_factory=FetchOutcome)
    usdz: FetchOutcome = field(default_factory=FetchOutcome)

    @property
    def any_success(self) -> bool:
        """True if at least one format was written to the store."""
        return self.glb.ok or self.usdz.ok

    @property
    def any_error(self) -> bool:
        """True if any *attempted* format errored."""
        return self.glb.error is not None or self.usdz.error is not None


def _download(client: httpx.Client, url: str) -> bytes:
    """GET ``url`` and return the body, following redirects.

    Caller is responsible for try/except — we let HTTP / network
    errors surface so :func:`fetch_entry` can record them in the
    outcome.
    """
    response = client.get(url)
    response.raise_for_status()
    return response.content


def fetch_entry(
    entry: AssetCatalogEntry,
    store: ARStore,
    *,
    client: httpx.Client,
) -> FetchResult:
    """Fetch all available formats for ``entry`` and write them to
    ``store``.

    Per-format failures are isolated: a 404 on the USDZ does not stop
    the GLB from landing, and vice versa.
    """
    result = FetchResult(asset_id=entry.id)

    if entry.glb_url:
        try:
            data = _download(client, entry.glb_url)
            store.put(
                entry.id,
                Scene3DAsset(data=data, mime_type=MIME_GLB, extension=".glb"),
            )
            result.glb.bytes_written = len(data)
        except Exception as exc:  # noqa: BLE001 — capture everything for the report
            result.glb.error = f"{type(exc).__name__}: {exc}"
    elif entry.glb_bundle:
        try:
            rewriter = get_rewriter(entry.glb_bundle.rewriter)
            data = bundle_remote_gltf(
                entry.glb_bundle.gltf_url, client=client, rewriter=rewriter
            )
            store.put(
                entry.id,
                Scene3DAsset(data=data, mime_type=MIME_GLB, extension=".glb"),
            )
            result.glb.bytes_written = len(data)
        except Exception as exc:  # noqa: BLE001 — capture for the report
            result.glb.error = f"{type(exc).__name__}: {exc}"
    else:
        result.glb.skipped_reason = "no glb_url or glb_bundle in catalog"

    if entry.usdz_url:
        try:
            data = _download(client, entry.usdz_url)
            store.put(
                entry.id,
                Scene3DAsset(data=data, mime_type=MIME_USDZ, extension=".usdz"),
            )
            result.usdz.bytes_written = len(data)
        except Exception as exc:  # noqa: BLE001
            result.usdz.error = f"{type(exc).__name__}: {exc}"
    else:
        result.usdz.skipped_reason = "no usdz_url in catalog"

    return result


def select_entries(
    catalog: AssetCatalog, ids: list[str] | None
) -> list[AssetCatalogEntry]:
    """Resolve ``ids`` against ``catalog``, raising on unknown IDs.

    ``ids=None`` means "all entries, in manifest order". The strict
    behaviour for unknown IDs is intentional — typo'ing an id on the
    CLI should fail loudly, not silently fetch nothing.
    """
    if ids is None:
        return catalog.list()
    missing = [asset_id for asset_id in ids if catalog.get(asset_id) is None]
    if missing:
        raise KeyError(f"unknown catalog id(s): {missing!r}")
    # Preserve the requested order so users see results in the order
    # they asked.
    return [catalog.get(asset_id) for asset_id in ids]  # type: ignore[misc]


def fetch_all(
    catalog: AssetCatalog,
    store: ARStore,
    *,
    ids: list[str] | None = None,
    client: httpx.Client | None = None,
) -> list[FetchResult]:
    """Fetch ``ids`` (or every entry if ``None``) into ``store``."""
    entries = select_entries(catalog, ids)
    owns_client = client is None
    client = client or httpx.Client(timeout=DEFAULT_TIMEOUT_S, follow_redirects=True)
    try:
        return [fetch_entry(entry, store, client=client) for entry in entries]
    finally:
        if owns_client:
            client.close()


def _fmt_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


def format_summary(results: list[FetchResult]) -> str:
    """Render a human-readable per-entry table of outcomes."""
    if not results:
        return "(no entries selected)"
    id_width = max(len(r.asset_id) for r in results)
    lines: list[str] = []
    for r in results:
        parts: list[str] = []
        for label, outcome in (("GLB", r.glb), ("USDZ", r.usdz)):
            if outcome.bytes_written is not None:
                parts.append(f"✓ {label} ({_fmt_bytes(outcome.bytes_written)})")
            elif outcome.error is not None:
                parts.append(f"✗ {label} ({outcome.error})")
            elif outcome.skipped_reason is not None:
                parts.append(f"– {label}")
        lines.append(f"{r.asset_id:<{id_width}}  " + "   ".join(parts))
    return "\n".join(lines)
