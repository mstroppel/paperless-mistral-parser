"""Small, retrying Mistral OCR HTTP client."""

from __future__ import annotations

import base64
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from paperless_mistral_parser.config import Config

logger = logging.getLogger("paperless_mistral_parser.client")


class OcrError(RuntimeError):
    """Raised when Mistral OCR cannot produce a valid result."""


class MistralClient:
    """Call Mistral OCR without logging document data or credentials."""

    def __init__(
        self,
        config: Config,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        self._sleep = sleep
        self._client = httpx.Client(
            timeout=config.timeout,
            follow_redirects=False,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> MistralClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def process(self, path: Path, mime_type: str) -> list[dict[str, Any]]:
        size = path.stat().st_size
        if size > self.config.max_bytes:
            raise OcrError(f"Document exceeds MISTRAL_OCR_MAX_BYTES ({size} bytes)")

        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        uri = f"data:{mime_type};base64,{encoded}"
        if mime_type == "application/pdf":
            document = {"type": "document_url", "document_url": uri}
        else:
            document = {"type": "image_url", "image_url": uri}
        payload = {
            "model": self.config.model,
            "document": document,
            "include_blocks": True,
        }

        response = self._post_with_retries(payload)
        try:
            body = response.json()
        except ValueError as error:
            raise OcrError("Mistral OCR returned invalid JSON") from error
        pages = body.get("pages") if isinstance(body, dict) else None
        if not isinstance(pages, list) or not all(isinstance(page, dict) for page in pages):
            raise OcrError("Mistral OCR response has no valid pages array")
        if not pages:
            raise OcrError("Mistral OCR returned no pages")
        if len(pages) > self.config.max_pages:
            raise OcrError("Mistral OCR response exceeds MISTRAL_OCR_MAX_PAGES")
        request_id = response.headers.get("x-request-id", "unknown")
        logger.info("Mistral OCR completed pages=%d request_id=%s", len(pages), request_id)
        return pages

    def _post_with_retries(self, payload: dict[str, Any]) -> httpx.Response:
        url = f"{self.config.endpoint}/v1/ocr"
        headers = {"Authorization": f"Bearer {self.config.api_key}"}
        last_error: Exception | None = None
        for attempt in range(1, self.config.retries + 1):
            try:
                response = self._client.post(url, json=payload, headers=headers)
                if response.status_code == 429 or response.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        "retryable Mistral OCR response",
                        request=response.request,
                        response=response,
                    )
                response.raise_for_status()
                return response
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as error:
                last_error = error
                retryable = not isinstance(error, httpx.HTTPStatusError) or (
                    error.response.status_code == 429 or error.response.status_code >= 500
                )
                if not retryable or attempt == self.config.retries:
                    break
                logger.warning("Mistral OCR attempt %d failed; retrying", attempt)
                self._sleep(2 ** (attempt - 1))
        status = (
            last_error.response.status_code
            if isinstance(last_error, httpx.HTTPStatusError)
            else None
        )
        detail = f"HTTP {status}" if status else type(last_error).__name__
        message = f"Mistral OCR request failed after {attempt} attempt(s): {detail}"
        raise OcrError(message) from last_error


def pages_to_text(pages: list[dict[str, Any]]) -> str:
    """Join page Markdown in source order."""
    parts = [str(page.get("markdown", "")).strip() for page in pages]
    return "\n\n".join(part for part in parts if part)
