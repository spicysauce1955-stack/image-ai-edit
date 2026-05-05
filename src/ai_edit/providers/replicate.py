"""Replicate provider — open-vocabulary segmentation via Grounded-SAM.

Why direct ``httpx`` instead of the official ``replicate`` SDK
--------------------------------------------------------------
Three reasons:

1. The whole codebase already speaks ``httpx`` (see ``minimax.py`` /
   ``zhipuai.py``), so adding an SDK would split the patterns.
2. Replicate's REST surface is small enough that polling + downloading
   one URL is shorter than learning the SDK's iterator semantics.
3. We avoid an extra runtime dependency that would ship transitively
   into anything that imports :mod:`ai_edit`.

How Grounded-SAM is invoked
---------------------------
The ``schananas/grounded_sam`` model takes a single ``image`` (URL or
data URI) and a comma-separated ``mask_prompt`` string. We encode the
caller's local image as a ``data:`` URI so they never have to upload to
S3 first. The model returns one or more PNG mask URLs which we fetch
and hand back as :class:`SegmentationMask` objects — labelled in the
order the prompts came in, with a trailing ``"combined"`` mask if the
model emits one (Grounded-SAM's behavior here is mildly unstable across
versions, so the zip is intentionally tolerant of length mismatches).

Polling
-------
Replicate predictions are async — POST creates a job, then we poll the
``urls.get`` endpoint until status leaves ``starting``/``processing``.
A 120 s ceiling keeps a hung job from blocking the CLI forever.
"""

from __future__ import annotations

import asyncio
import base64
from typing import Any

import httpx

from ..config import get_env
from ..models.base import (
    BaseProvider,
    EditResponse,
    SegmentationMask,
    SegmentationModel,
    SegmentationResponse,
)

BASE_URL = "https://api.replicate.com"
GROUNDED_SAM_MODEL = "schananas/grounded_sam"
GROUNDED_SAM_VERSION = "ee871c19efb1941f55f66a3d7d960428c8a5afcb77449547fe8e5a3ab9ebc21c"
ANYDOOR_VERSION = "542c963129c4661ab53a875b1b9a84b2102ca784cf872ef2752a468721c0eb2a"
POLL_INTERVAL_S = 1.0
POLL_TIMEOUT_S = 300.0


def _data_uri(image_bytes: bytes, mime_type: str) -> str:
    """Encode a local image as a ``data:`` URI for inline upload.

    Avoids the round-trip of pre-uploading to object storage just to get
    a URL Replicate will accept.
    """
    return f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode()}"


class ReplicateGroundedSAM(SegmentationModel):
    """Grounded-SAM client.

    Combines Grounding DINO (text → bounding box) with SAM (box → mask)
    to produce open-vocabulary segmentation. Cheaper and faster than
    SAM 2 alone for our use case because we drive it from text labels
    rather than user-clicked points.
    """

    def __init__(self, provider: Replicate) -> None:
        self._provider = provider

    async def segment(
        self,
        image: bytes,
        prompts: list[str],
        *,
        mime_type: str = "image/jpeg",
        **kwargs: Any,
    ) -> SegmentationResponse:
        """Run segmentation for one or more text labels.

        Parameters
        ----------
        image:
            Raw bytes of the source image (JPEG/PNG).
        prompts:
            One label per region of interest, e.g. ``["ground", "trees"]``.
            Grounded-SAM concatenates them comma-separated under the
            hood and emits one mask per matched label.
        mime_type:
            MIME type of ``image`` for the data URI envelope.
        **kwargs:
            Forwarded into the model ``input`` dict — useful for
            ``adjustment_factor`` or ``negative_mask_prompt``.
        """
        image_uri = _data_uri(image, mime_type)
        prompt_str = ",".join(p.strip() for p in prompts)

        payload: dict[str, Any] = {
            "version": GROUNDED_SAM_VERSION,
            "input": {
                "image": image_uri,
                "mask_prompt": prompt_str,
                # Negative prompt subtracts regions; default empty to
                # keep behavior predictable for the POC.
                "negative_mask_prompt": kwargs.pop("negative_mask_prompt", ""),
                # 0 = use the model's default mask threshold.
                "adjustment_factor": kwargs.pop("adjustment_factor", 0),
            },
        }
        payload["input"].update(kwargs)

        async with httpx.AsyncClient(timeout=POLL_TIMEOUT_S) as client:
            # Versioned /v1/predictions endpoint — the model-aliased
            # /v1/models/{owner}/{name}/predictions form 404s on
            # models without a "default" version.
            create = await client.post(
                f"{self._provider.base_url}/v1/predictions",
                headers=self._provider._headers(),
                json=payload,
            )
            create.raise_for_status()
            prediction = create.json()

            prediction = await self._wait(client, prediction)

            output = prediction.get("output") or []
            mask_urls = output if isinstance(output, list) else [output]

            # schananas/grounded_sam returns 4 outputs in this order:
            #   [0] annotated_picture_mask.jpg   — visualization with red bboxes
            #   [1] neg_annotated_picture_mask  — negative-prompt visualization
            #   [2] mask.jpg                    — the actual binary mask we want
            #   [3] inverted_mask.jpg           — inverse of [2]
            # The previous code zipped prompts vs URLs and grabbed [0],
            # which is the *visualization*, not a binary mask. AnyDoor
            # silently treated that as if the whole image were the
            # object. Now we label by filename so callers can pick.
            label_for_filename = {
                "annotated_picture_mask": "visualization",
                "neg_annotated_picture_mask": "neg_visualization",
                "mask": prompts[0] if prompts else "binary",  # the canonical binary mask
                "inverted_mask": "inverted",
            }
            masks: list[SegmentationMask] = []
            for url in mask_urls:
                if not url:
                    continue
                # filename without extension: ".../mask.jpg" → "mask"
                fname = url.rsplit("/", 1)[-1].rsplit(".", 1)[0]
                label = label_for_filename.get(fname, fname)
                resp = await client.get(url)
                resp.raise_for_status()
                masks.append(
                    SegmentationMask(
                        label=label,
                        image_bytes=resp.content,
                        mime_type="image/png",
                    )
                )

        return SegmentationResponse(masks=masks, raw=prediction)

    async def _wait(
        self, client: httpx.AsyncClient, prediction: dict[str, Any]
    ) -> dict[str, Any]:
        """Poll a Replicate prediction to completion.

        Replicate returns a job descriptor on creation; the actual
        output URLs only show up once ``status == "succeeded"``. We poll
        the ``urls.get`` endpoint at ``POLL_INTERVAL_S`` and bail with a
        :class:`TimeoutError` after ``POLL_TIMEOUT_S`` to keep the CLI
        responsive when something goes sideways upstream.
        """
        get_url = prediction.get("urls", {}).get("get")
        if not get_url:
            return prediction
        elapsed = 0.0
        while prediction.get("status") in ("starting", "processing"):
            if elapsed >= POLL_TIMEOUT_S:
                raise TimeoutError(
                    f"Replicate prediction timed out after {POLL_TIMEOUT_S}s"
                )
            await asyncio.sleep(POLL_INTERVAL_S)
            elapsed += POLL_INTERVAL_S
            poll = await client.get(get_url, headers=self._provider._headers())
            poll.raise_for_status()
            prediction = poll.json()
        if prediction.get("status") != "succeeded":
            raise RuntimeError(
                f"Replicate prediction failed: {prediction.get('error') or prediction}"
            )
        return prediction


class ReplicateAnyDoor:
    """AnyDoor — zero-shot reference-conditioned object insertion.

    Replicate model: ``ali-vilab/anydoor`` (CVPR 2024 paper). AnyDoor
    takes a target image + binary mask (where the object should go)
    and a reference image + reference mask (which part of the
    reference IS the object), and *re-renders* the reference inside
    the target mask in the target's perspective. This is the textbook
    primitive for our use case — it's precisely the "identity +
    detail" feature design that fixes the "model regenerates beyond
    the polygon" problem we hit with gpt-image-1.

    Native fields (per ``ali-vilab/anydoor`` schema):

    - ``bg_image_path``        : target scene
    - ``bg_mask_path``         : where the object goes (white = inpaint)
    - ``reference_image_path`` : the reference object photo
    - ``reference_image_mask`` : which part of the reference IS the
                                 object (white = object, black = bg)
    - ``steps``                : default 50
    - ``guidance_scale``       : default 4.5
    - ``control_strength``     : default 1.0
    - ``enable_shape_control`` : default False

    The reference_image_mask is REQUIRED — if the caller doesn't have
    one we auto-segment it via Grounded-SAM in the pipeline before
    calling here. AnyDoor without a clean reference mask pulls in
    sky/grass background from the reference photo.
    """

    def __init__(self, provider: Replicate) -> None:
        self._provider = provider

    async def edit(
        self,
        scene: tuple[bytes, str],
        scene_mask: tuple[bytes, str],
        reference: tuple[bytes, str],
        reference_mask: tuple[bytes, str],
        *,
        steps: int = 50,
        guidance_scale: float = 4.5,
        control_strength: float = 1.0,
        enable_shape_control: bool = False,
        **kwargs: Any,
    ) -> EditResponse:
        """Run AnyDoor object teleportation.

        All four inputs are ``(bytes, mime)`` tuples. The two masks
        must be PNGs whose dimensions match their respective images.
        """
        sb, sm = scene
        smb, smm = scene_mask
        rb, rm = reference
        rmb, rmm = reference_mask

        payload = {
            "version": ANYDOOR_VERSION,
            "input": {
                "bg_image_path":        _data_uri(sb, sm),
                "bg_mask_path":         _data_uri(smb, smm),
                "reference_image_path": _data_uri(rb, rm),
                "reference_image_mask": _data_uri(rmb, rmm),
                "steps": steps,
                "guidance_scale": guidance_scale,
                "control_strength": control_strength,
                "enable_shape_control": enable_shape_control,
            },
        }
        payload["input"].update(kwargs)

        async with httpx.AsyncClient(timeout=POLL_TIMEOUT_S) as client:
            create = await client.post(
                f"{self._provider.base_url}/v1/predictions",
                headers=self._provider._headers(),
                json=payload,
            )
            create.raise_for_status()
            prediction = create.json()

            # Reuse the polling helper from the segmentation handler.
            seg = self._provider.segmentation
            prediction = await seg._wait(client, prediction)  # type: ignore[attr-defined]

            output = prediction.get("output")
            url = output if isinstance(output, str) else (output[0] if output else None)
            if not url:
                raise RuntimeError(f"AnyDoor returned no image. Raw: {prediction}")
            r = await client.get(url)
            r.raise_for_status()

        return EditResponse(image_bytes=r.content, mime_type="image/png", raw=prediction)


class Replicate(BaseProvider):
    """Replicate REST client. Exposes Grounded-SAM segmentation + AnyDoor."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = BASE_URL,
    ) -> None:
        key = api_key or get_env("REPLICATE_API_TOKEN", required=True)
        super().__init__(api_key=key, base_url=base_url)
        self.segmentation = ReplicateGroundedSAM(self)
        self.anydoor = ReplicateAnyDoor(self)

    @property
    def name(self) -> str:
        return "replicate"

    def _headers(self) -> dict[str, str]:
        # Replicate uses standard Bearer auth; this override exists only
        # so the inheritance is explicit and easy to swap if Replicate
        # ever ships a v2 auth scheme.
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
