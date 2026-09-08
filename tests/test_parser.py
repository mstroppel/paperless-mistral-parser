from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from paperless_mistral_parser.config import Config
from paperless_mistral_parser.parser import MistralOcrParser


def test_score_requires_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    assert MistralOcrParser.score("application/pdf", "scan.pdf") is None
    monkeypatch.setenv("MISTRAL_API_KEY", "secret")
    assert MistralOcrParser.score("application/pdf", "scan.pdf") == 30
    assert MistralOcrParser.score("text/plain", "note.txt") is None


def test_protocol_surface() -> None:
    expected = {
        "supported_mime_types",
        "score",
        "can_produce_archive",
        "requires_pdf_rendition",
        "configure",
        "parse",
        "get_text",
        "get_date",
        "get_archive_path",
        "get_thumbnail",
        "get_page_count",
        "extract_metadata",
        "__enter__",
        "__exit__",
    }
    assert all(hasattr(MistralOcrParser, name) for name in expected)
    assert MistralOcrParser.uses_remote_service is True


def test_born_digital_pdf_skips_remote(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    paperless_modules: SimpleNamespace,
) -> None:
    monkeypatch.setenv("MISTRAL_API_KEY", "secret")
    path = tmp_path / "digital.pdf"
    path.write_bytes(b"pdf")

    with MistralOcrParser() as parser:
        parser.parse(path, "application/pdf", produce_archive=False)
        assert parser.get_text() == "native text"
        assert parser.get_archive_path() is None


def test_scan_calls_mistral_and_builds_archive(
    monkeypatch: pytest.MonkeyPatch,
    image_path: Path,
    paperless_modules: SimpleNamespace,
) -> None:
    monkeypatch.setenv("MISTRAL_API_KEY", "secret")
    pages = [{"markdown": "recognized"}]

    class FakeClient:
        def __init__(self, _config: Config) -> None:
            pass

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *_args: object) -> None:
            pass

        def process(self, _path: Path, _mime: str) -> list[dict[str, str]]:
            return pages

    def fake_build(*args: object, **kwargs: object) -> None:
        Path(args[3]).write_bytes(b"archive")

    monkeypatch.setattr("paperless_mistral_parser.parser.MistralClient", FakeClient)
    monkeypatch.setattr("paperless_mistral_parser.parser.build_searchable_pdf", fake_build)

    with MistralOcrParser() as parser:
        parser.parse(image_path, "image/png")
        assert parser.get_text() == "recognized"
        assert parser.get_archive_path().read_bytes() == b"archive"  # type: ignore[union-attr]


def test_errors_become_parse_error(
    monkeypatch: pytest.MonkeyPatch,
    image_path: Path,
    paperless_modules: SimpleNamespace,
) -> None:
    monkeypatch.setenv("MISTRAL_API_KEY", "secret")

    class FailingClient:
        def __init__(self, _config: Config) -> None:
            raise ValueError("broken")

    monkeypatch.setattr("paperless_mistral_parser.parser.MistralClient", FailingClient)
    with (
        MistralOcrParser() as parser,
        pytest.raises(
            paperless_modules.parse_error,
            match="Mistral OCR parsing failed",
        ),
    ):
        parser.parse(image_path, "image/png")


def test_image_thumbnail_and_page_count(image_path: Path) -> None:
    with MistralOcrParser() as parser:
        thumbnail = parser.get_thumbnail(image_path, "image/png")
        assert thumbnail.is_file()
        assert parser.get_page_count(image_path, "image/png") == 1


def test_unsupported_mime_raises_parse_error(
    image_path: Path,
    paperless_modules: SimpleNamespace,
) -> None:
    with (
        MistralOcrParser() as parser,
        pytest.raises(
            paperless_modules.parse_error,
            match="Unsupported MIME type",
        ),
    ):
        parser.parse(image_path, "text/plain")


def test_page_limit_fails_before_remote_call(
    monkeypatch: pytest.MonkeyPatch,
    image_path: Path,
    paperless_modules: SimpleNamespace,
) -> None:
    monkeypatch.setenv("MISTRAL_API_KEY", "secret")
    monkeypatch.setenv("MISTRAL_OCR_MAX_PAGES", "1")
    monkeypatch.setattr(MistralOcrParser, "get_page_count", lambda *_args: 2)

    with (
        MistralOcrParser() as parser,
        pytest.raises(
            paperless_modules.parse_error,
            match="MAX_PAGES",
        ),
    ):
        parser.parse(image_path, "image/png")


def test_metadata_failure_is_nonfatal(
    monkeypatch: pytest.MonkeyPatch,
    image_path: Path,
    paperless_modules: SimpleNamespace,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> list[object]:
        raise ValueError("bad PDF")

    monkeypatch.setattr(paperless_modules.utils, "extract_pdf_metadata", fail)
    with MistralOcrParser() as parser:
        assert parser.extract_metadata(image_path, "image/png") == []
        assert parser.extract_metadata(image_path, "application/pdf") == []
