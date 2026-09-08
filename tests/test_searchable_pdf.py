from pathlib import Path

import pytest
from pypdf import PdfReader

from paperless_mistral_parser.searchable_pdf import PdfBuildError, build_searchable_pdf, find_font


def test_builds_searchable_unicode_pdf(image_path: Path, tmp_path: Path) -> None:
    output = tmp_path / "archive.pdf"
    pages = [
        {
            "markdown": "Invoice number 12345 - Grüße",
            "dimensions": {"width": 200, "height": 100},
            "blocks": [
                {
                    "content": "Invoice number 12345 - Grüße",
                    "top_left_x": 10,
                    "top_left_y": 10,
                    "bottom_right_x": 190,
                    "bottom_right_y": 40,
                },
            ],
        },
    ]

    build_searchable_pdf(image_path, "image/png", pages, output, dpi=100)

    reader = PdfReader(output)
    assert len(reader.pages) == 1
    assert "Invoice number 12345" in reader.pages[0].extract_text()
    assert not list(tmp_path.glob("mistral-page-*.png"))


def test_rejects_page_count_mismatch(image_path: Path, tmp_path: Path) -> None:
    with pytest.raises(PdfBuildError, match="Mistral returned 0"):
        build_searchable_pdf(image_path, "image/png", [], tmp_path / "out.pdf", dpi=100)


def test_falls_back_to_page_markdown(image_path: Path, tmp_path: Path) -> None:
    output = tmp_path / "archive.pdf"
    pages = [
        {
            "markdown": "Fallback text",
            "dimensions": {"width": None, "height": 0},
            "blocks": [None, {"content": "missing coordinates"}],
        },
    ]

    build_searchable_pdf(image_path, "image/png", pages, output, dpi=100)

    assert "Fallback text" in PdfReader(output).pages[0].extract_text()


def test_builds_archive_from_pdf_source(image_path: Path, tmp_path: Path) -> None:
    source_pdf = tmp_path / "source.pdf"
    build_searchable_pdf(
        image_path,
        "image/png",
        [{"markdown": "first pass"}],
        source_pdf,
        dpi=100,
    )
    output = tmp_path / "second.pdf"

    build_searchable_pdf(
        source_pdf,
        "application/pdf",
        [{"markdown": "PDF scan text"}],
        output,
        dpi=100,
    )

    assert "PDF scan text" in PdfReader(output).pages[0].extract_text()


def test_find_font_rejects_missing_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "is_file", lambda _path: False)

    with pytest.raises(PdfBuildError, match="No Unicode font"):
        find_font()
