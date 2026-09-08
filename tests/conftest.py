from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from PIL import Image


class ParseError(RuntimeError):
    pass


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "MISTRAL_API_KEY",
        "MISTRAL_API_KEY_FILE",
        "MISTRAL_OCR_ENDPOINT",
        "MISTRAL_OCR_ALLOW_HTTP",
        "MISTRAL_OCR_MODEL",
        "MISTRAL_OCR_TIMEOUT",
        "MISTRAL_OCR_RETRIES",
        "MISTRAL_OCR_MAX_BYTES",
        "MISTRAL_OCR_MAX_PAGES",
        "MISTRAL_OCR_RENDER_DPI",
        "MISTRAL_OCR_FONT_PATH",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def image_path(tmp_path: Path) -> Path:
    path = tmp_path / "scan.png"
    Image.new("RGB", (200, 100), "white").save(path)
    return path


@pytest.fixture
def paperless_modules(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> SimpleNamespace:
    documents = ModuleType("documents")
    document_parsers = ModuleType("documents.parsers")
    document_parsers.ParseError = ParseError
    document_parsers.make_thumbnail_from_pdf = lambda *_args: tmp_path / "thumbnail.webp"

    paperless = ModuleType("paperless")
    parsers = ModuleType("paperless.parsers")
    utils = ModuleType("paperless.parsers.utils")
    utils.pdf_born_digital_text = lambda *_args, **_kwargs: (" native text ", True)
    utils.post_process_text = lambda value: value.strip()
    utils.get_page_count_for_pdf = lambda *_args, **_kwargs: 1
    utils.extract_pdf_metadata = lambda *_args, **_kwargs: []

    monkeypatch.setitem(sys.modules, "documents", documents)
    monkeypatch.setitem(sys.modules, "documents.parsers", document_parsers)
    monkeypatch.setitem(sys.modules, "paperless", paperless)
    monkeypatch.setitem(sys.modules, "paperless.parsers", parsers)
    monkeypatch.setitem(sys.modules, "paperless.parsers.utils", utils)
    return SimpleNamespace(utils=utils, parse_error=ParseError)
