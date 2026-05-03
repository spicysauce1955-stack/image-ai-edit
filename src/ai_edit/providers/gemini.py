from __future__ import annotations

import base64
from typing import Any

import httpx

from ..config import get_env
from ..models.base import BaseProvider, EditModel, EditResponse

BASE_URL = "https://generativelanguage.googleapis.com"
DEFAULT_EDIT_MODEL = "gemini-2.5-flash-image"


class GeminiImage(EditModel):
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
                if "inline_data" in part or "inlineData" in part:
                    inline = part.get("inline_data") or part.get("inlineData")
                    out_bytes = base64.b64decode(inline["data"])
                    out_mime = inline.get("mime_type") or inline.get("mimeType", out_mime)
                elif "text" in part:
                    out_text += part["text"]

        if not out_bytes:
            raise RuntimeError(
                f"Gemini returned no image. Text: {out_text[:200]!r}. Raw keys: {list(data.keys())}"
            )

        return EditResponse(
            image_bytes=out_bytes,
            mime_type=out_mime,
            text=out_text,
            raw=data,
        )


class Gemini(BaseProvider):
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
        return {
            "x-goog-api-key": self.api_key,
            "Content-Type": "application/json",
        }
