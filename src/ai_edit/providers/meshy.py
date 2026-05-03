"""Meshy provider — image-to-3D for the AR phase.

Wraps the ``Multi-Image-to-3D`` endpoint, which takes 1–N reference
photos of an object and returns a textured 3D asset. Picked over Tripo,
Hunyuan3D, and Stable Fast 3D because Meshy is the only vendor in the
survey that exposes **GLB + USDZ in the same call** with **commercial
ownership for paid tiers** — exactly what we need for cross-platform
WebAR (USDZ for iOS Quick Look, GLB for Android Scene Viewer).

Async by submission + polling
-----------------------------
Meshy generations take **minutes**, not seconds. The endpoint is
strictly asynchronous: POST creates a task, then we poll a separate
``GET /<task_id>`` until ``status == "SUCCEEDED"`` and the response
includes ``model_urls`` for every requested format. Polling cadence is
4 s (vs 2 s for fal.ai) because Meshy charges per request and there's
no benefit to polling tighter than the model can finish.

Auth
----
Standard ``Authorization: Bearer msy_…``.
"""

from __future__ import annotations

import asyncio
import base64
from typing import Any

import httpx

from ..config import get_env
from ..models.base import BaseProvider, Image3DModel, Image3DResponse

BASE_URL = "https://api.meshy.ai"
MULTI_IMAGE_PATH = "/openapi/v1/multi-image-to-3d"
POLL_INTERVAL_S = 4.0
POLL_TIMEOUT_S = 900.0  # 15 min — Meshy can take a while for textured assets

# Meshy returns model_urls keyed by lower-case format names.
SUPPORTED_FORMATS = ("glb", "usdz", "fbx", "obj")


def _data_uri(image_bytes: bytes, mime_type: str) -> str:
    """Encode a local image as a ``data:`` URI for inline upload."""
    return f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode()}"


class MeshyMultiImage3D(Image3DModel):
    """Multi-Image-to-3D handler.

    Submits all reference images in one task, polls the task to
    completion, then downloads each requested asset format.
    """

    def __init__(self, provider: Meshy) -> None:
        self._provider = provider

    async def generate(
        self,
        images: list[tuple[bytes, str]],
        *,
        target_formats: list[str] | None = None,
        target_polycount: int = 30000,
        model: str | None = None,
        **kwargs: Any,
    ) -> Image3DResponse:
        """Build a 3D asset from one or more reference photos.

        Parameters
        ----------
        images:
            ``(image_bytes, mime_type)`` tuples. Meshy works best with
            3–8 well-lit views of the same object from different angles.
            One image works in a pinch but quality degrades fast.
        target_formats:
            Subset of ``("glb", "usdz", "fbx", "obj")``. Defaults to
            GLB + USDZ which is what the WebAR delivery path needs.
        target_polycount:
            Max triangles in the output mesh. 30k is a good balance for
            web/mobile delivery.
        model:
            Override the Meshy model identifier (default chosen by their
            backend at submission time).
        **kwargs:
            Forwarded into the request body. Useful for ``topology``,
            ``texture_richness``, ``ai_model``, etc.

        Raises
        ------
        TimeoutError, RuntimeError:
            On polling timeout or upstream failure.
        """
        if not images:
            raise ValueError("MeshyMultiImage3D.generate requires at least one image.")

        formats = [f.lower() for f in (target_formats or ["glb", "usdz"])]
        for f in formats:
            if f not in SUPPORTED_FORMATS:
                raise ValueError(f"Unsupported target format: {f}")

        payload: dict[str, Any] = {
            "image_urls": [_data_uri(b, m) for b, m in images],
            "target_polycount": target_polycount,
            "should_remesh": True,
            "should_texture": True,
        }
        if model:
            payload["ai_model"] = model
        payload.update(kwargs)

        submit_url = f"{self._provider.base_url}{MULTI_IMAGE_PATH}"

        async with httpx.AsyncClient(timeout=60) as client:
            # 1. Submit. Returns {"result": "<task_id>"}.
            submit = await client.post(
                submit_url, headers=self._provider._headers(), json=payload
            )
            submit.raise_for_status()
            sub = submit.json()
            task_id = sub.get("result") or sub.get("id")
            if not task_id:
                raise RuntimeError(f"Meshy submit returned no task id: {sub}")

            # 2. Poll. Status flow: PENDING → IN_PROGRESS → SUCCEEDED / FAILED.
            poll_url = f"{submit_url}/{task_id}"
            elapsed = 0.0
            task: dict[str, Any] = {}
            while True:
                if elapsed >= POLL_TIMEOUT_S:
                    raise TimeoutError(
                        f"Meshy task {task_id} timed out after {POLL_TIMEOUT_S}s"
                    )
                await asyncio.sleep(POLL_INTERVAL_S)
                elapsed += POLL_INTERVAL_S
                poll = await client.get(poll_url, headers=self._provider._headers())
                poll.raise_for_status()
                task = poll.json()
                status = task.get("status")
                if status == "SUCCEEDED":
                    break
                if status in ("FAILED", "CANCELED", "EXPIRED"):
                    raise RuntimeError(f"Meshy task {status}: {task}")

            # 3. Download requested asset formats.
            model_urls = task.get("model_urls") or {}
            assets: dict[str, bytes] = {}
            for fmt in formats:
                url = model_urls.get(fmt)
                if not url:
                    # Vendor returned the task as SUCCEEDED but didn't
                    # produce this format. Skip rather than fail —
                    # callers can branch on whether the bytes are empty.
                    continue
                resp = await client.get(url)
                resp.raise_for_status()
                assets[fmt] = resp.content

        return Image3DResponse(
            glb_bytes=assets.get("glb", b""),
            usdz_bytes=assets.get("usdz", b""),
            fbx_bytes=assets.get("fbx", b""),
            obj_bytes=assets.get("obj", b""),
            raw=task,
        )


class Meshy(BaseProvider):
    """Meshy REST client. Currently exposes Multi-Image-to-3D only.

    Add Text-to-3D, retopology, etc. as additional handlers attached in
    ``__init__`` if/when the AR pipeline grows.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = BASE_URL,
    ) -> None:
        key = api_key or get_env("MESHY_API_KEY", required=True)
        super().__init__(api_key=key, base_url=base_url)
        self.image_3d = MeshyMultiImage3D(self)

    @property
    def name(self) -> str:
        return "meshy"

    def _headers(self) -> dict[str, str]:
        # Meshy uses Bearer auth with a key prefixed `msy_`.
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
