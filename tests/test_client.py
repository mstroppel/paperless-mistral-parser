from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from paperless_mistral_parser.client import MistralClient, OcrError, pages_to_text
from paperless_mistral_parser.config import Config


def config(**overrides: object) -> Config:
    values = {
        "api_key": "secret",
        "endpoint": "https://api.mistral.ai",
        "model": "mistral-ocr-latest",
        "timeout": 10.0,
        "retries": 3,
        "max_bytes": 1_000_000,
        "max_pages": 10,
        "render_dpi": 200,
        "font_path": None,
    }
    values.update(overrides)
    return Config(**values)  # type: ignore[arg-type]


def test_sends_image_and_parses_pages(image_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert request.headers["authorization"] == "Bearer secret"
        assert body["document"]["type"] == "image_url"
        assert body["document"]["image_url"].startswith("data:image/png;base64,")
        assert body["include_blocks"] is True
        return httpx.Response(
            200,
            json={"pages": [{"markdown": "hello"}]},
            headers={"x-request-id": "id"},
        )

    with MistralClient(config(), transport=httpx.MockTransport(handler)) as client:
        assert client.process(image_path, "image/png") == [{"markdown": "hello"}]


def test_retries_retryable_responses(image_path: Path) -> None:
    attempts = 0
    sleeps: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(503)
        return httpx.Response(200, json={"pages": [{"markdown": "ok"}]})

    with MistralClient(
        config(),
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
    ) as client:
        client.process(image_path, "image/png")

    assert attempts == 3
    assert sleeps == [1, 2]


def test_does_not_retry_client_error(image_path: Path) -> None:
    with (
        MistralClient(
            config(),
            transport=httpx.MockTransport(lambda _request: httpx.Response(400)),
            sleep=lambda _: None,
        ) as client,
        pytest.raises(OcrError, match="HTTP 400"),
    ):
        client.process(image_path, "image/png")


def test_rejects_oversized_file(image_path: Path) -> None:
    with MistralClient(config(max_bytes=1)) as client, pytest.raises(OcrError, match="MAX_BYTES"):
        client.process(image_path, "image/png")


@pytest.mark.parametrize("body", [{}, {"pages": []}, {"pages": ["invalid"]}])
def test_rejects_invalid_response(image_path: Path, body: dict[str, object]) -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json=body))
    with MistralClient(config(), transport=transport) as client, pytest.raises(OcrError):
        client.process(image_path, "image/png")


def test_pages_to_text_drops_blank_pages() -> None:
    assert pages_to_text([{"markdown": "one"}, {}, {"markdown": " two "}]) == "one\n\ntwo"


def test_rejects_invalid_json(image_path: Path) -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, content=b"not-json"))
    with (
        MistralClient(config(), transport=transport) as client,
        pytest.raises(
            OcrError,
            match="invalid JSON",
        ),
    ):
        client.process(image_path, "image/png")


def test_rejects_too_many_pages(image_path: Path) -> None:
    body = {"pages": [{"markdown": "one"}, {"markdown": "two"}]}
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json=body))
    with (
        MistralClient(
            config(max_pages=1),
            transport=transport,
        ) as client,
        pytest.raises(OcrError, match="MAX_PAGES"),
    ):
        client.process(image_path, "image/png")
