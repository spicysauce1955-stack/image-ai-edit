"""Gemini provider — multi-image edit / object insertion.

The POC's insertion engine. Uses ``gemini-2.5-flash-image`` (informally
"Nano Banana") because as of early 2026 it gives the best
quality-per-dollar for reference-conditioned edits and accepts arbitrary
numbers of input images via inline base64.

Why direct REST instead of ``google-genai``
-------------------------------------------
Same reason as the Replicate provider: keeping every provider on
``httpx`` means one set of error-handling primitives, one timeout
strategy, and zero new transitive dependencies. Gemini's
``generateContent`` endpoint is a simple JSON POST, so the SDK wouldn't
buy us anything here.

Auth quirk
----------
Gemini does **not** use a ``Bearer`` token. The key goes in the
``x-goog-api-key`` header — that's why this provider overrides
:meth:`BaseProvider._headers`.

Response shape quirk
--------------------
Gemini returns image data inside ``candidates[].content.parts[]`` under
either ``inline_data`` (snake_case) or ``inlineData`` (camelCase)
depending on which version of the API you hit. We accept either to
shield callers from that churn.
"""

from __future__ import annotations

import base64
from typing import Any

import httpx

from ..config import get_env
from ..models.base import BaseProvider, EditModel, EditResponse

BASE_URL = "https://generativelanguage.googleapis.com"
DEFAULT_EDIT_MODEL = "gemini-2.5-flash-image"


class GeminiImage(EditModel):
    """Gemini 2.5 Flash Image edit handler.

    Translates a list of ``(bytes, mime_type)`` images into Gemini's
    ``parts`` schema, posts a single ``generateContent`` request, and
    extracts the first image part from the response.
    """

    def __init__(self, provider: Gemini) -> None:
        self._provider = provider

    async def edit(
        self,
        instruction: str,
        images: list[tuple[bytes, str]],
        *,
        model: str | None = None,
        **kwargs: Any,
    ) -> EditResponse:
        """Run a multi-image edit.

        Parameters
        ----------
        instruction:
            Free-form prompt. By convention the pipeline appends a
            standard suffix telling Gemini what each image position
            means (see :func:`ai_edit.pipeline.insert.insert_object`).
        images:
            ``(image_bytes, mime_type)`` pairs in the order the prompt
            references them ("Image 1", "Image 2", …).
        model:
            Override the default model name. Useful for trying preview
            variants without editing this file.
        **kwargs:
            Merged into the request body — e.g. pass
            ``generationConfig={"temperature": 0.4}`` to tweak sampling.

        Raises
        ------
        RuntimeError:
            If Gemini's response contains no image part. The error
            includes any text Gemini returned, which is usually a
            policy refusal explaining what to change in the prompt.
        """
        # Order matters: text first by convention, then each image as
        # an inline_data part. Gemini stitches them into one user turn.
        parts: list[dict[str, Any]] = [{"text": instruction}]
        for image_bytes, mime_type in images:
            parts.append(
                {
                    "inline_data": {
                        "mime_type": mime_type,
                        "data": base64.b64encode(image_bytes).decode(),
                    }
                }
            )

        payload: dict[str, Any] = {
            "contents": [{"role": "user", "parts": parts}],
        }
        payload.update(kwargs)

        url = (
            f"{self._provider.base_url}/v1beta/models/"
            f"{model or DEFAULT_EDIT_MODEL}:generateContent"
        )

        # 180 s ceiling: Gemini Flash Image typically returns in 3–6 s
        # but the tail can stretch past 60 s on cold edges.
        async with httpx.AsyncClient(timeout=180) as client:
            resp = await client.post(
                url, headers=self._provider._headers(), json=payload
            )
            resp.raise_for_status()
            data = resp.json()

        out_bytes = b""
        out_mime = "image/png"
        out_text = ""
        for cand in data.get("candidates", []):
            for part in cand.get("content", {}).get("parts", []):
                # Accept both snake_case and camelCase keys — see module
                # docstring for context on why both show up in the wild.
                if "inline_data" in part or "inlineData" in part:
                    inline = part.get("inline_data") or part.get("inlineData")
                    out_bytes = base64.b64decode(inline["data"])
                    out_mime = inline.get("mime_type") or inline.get("mimeType", out_mime)
                elif "text" in part:
                    out_text += part["text"]

        if not out_bytes:
            # Surface Gemini's narration so the caller can see *why* —
            # most no-image responses are policy refusals or "I can
            # describe but not generate" deflections, both fixable from
            # the prompt.
            raise RuntimeError(
                f"Gemini returned no image. Text: {out_text[:200]!r}. "
                f"Raw keys: {list(data.keys())}"
            )

        return EditResponse(
            image_bytes=out_bytes,
            mime_type=out_mime,
            text=out_text,
            raw=data,
        )


class Gemini(BaseProvider):
    """Gemini REST client. Currently exposes image edit only.

    Other capabilities (text chat via ``generateContent``, embeddings)
    can be attached as additional handlers in ``__init__`` if/when the
    pipeline grows beyond image editing.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = BASE_URL,
    ) -> None:
        key = api_key or get_env("GEMINI_API_KEY", required=True)
        super().__init__(api_key=key, base_url=base_url)
        self.image = GeminiImage(self)

    @property
    def name(self) -> str:
        return "gemini"

    def _headers(self) -> dict[str, str]:
        # Override: Gemini uses ``x-goog-api-key`` rather than the
        # ``Authorization: Bearer`` scheme assumed by BaseProvider.
        return {
            "x-goog-api-key": self.api_key,
            "Content-Type": "application/json",
        }
