"""Build searchable image PDFs from Mistral block coordinates."""

from __future__ import annotations

from collections.abc import Generator, Iterable
from pathlib import Path
from typing import Any

from PIL import Image, ImageSequence


class PdfBuildError(RuntimeError):
    """Raised when a searchable archive cannot be built."""


def find_font(configured: Path | None = None) -> Path:
    candidates = [
        configured,
        Path("/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
    ]
    for candidate in candidates:
        if candidate and candidate.is_file():
            return candidate
    raise PdfBuildError("No Unicode font found; set MISTRAL_OCR_FONT_PATH")


def _source_page_count(source: Path, mime_type: str) -> int:
    if mime_type == "application/pdf":
        from pdf2image import pdfinfo_from_path

        return int(pdfinfo_from_path(str(source))["Pages"])
    with Image.open(source) as image:
        return int(getattr(image, "n_frames", 1))


def _page_images(
    source: Path,
    mime_type: str,
    dpi: int,
    workdir: Path,
) -> Generator[tuple[Image.Image, float]]:
    if mime_type == "application/pdf":
        from pdf2image import convert_from_path

        rendered = convert_from_path(
            source,
            dpi=dpi,
            fmt="png",
            output_folder=str(workdir),
            paths_only=True,
        )
        try:
            for rendered_page in rendered:
                page_path = Path(str(rendered_page))
                with Image.open(page_path) as image:
                    converted = image.convert("RGB")
                    try:
                        yield converted, float(dpi)
                    finally:
                        converted.close()
        finally:
            for rendered_page in rendered:
                Path(str(rendered_page)).unlink(missing_ok=True)
        return

    with Image.open(source) as image:
        for frame in ImageSequence.Iterator(image):
            embedded = frame.info.get("dpi")
            page_dpi = float(embedded[0]) if embedded and embedded[0] else float(dpi)
            converted = frame.convert("RGB")
            try:
                yield converted, page_dpi
            finally:
                converted.close()


def _block_box(block: dict[str, Any]) -> tuple[float, float, float, float] | None:
    keys = ("top_left_x", "top_left_y", "bottom_right_x", "bottom_right_y")
    try:
        left, top, right, bottom = (float(block[key]) for key in keys)
    except (KeyError, TypeError, ValueError):
        return None
    return (left, top, right, bottom) if right > left and bottom > top else None


def _dimension(value: object, fallback: int) -> float:
    try:
        result = float(value)  # type: ignore[arg-type]
        return result if result > 0 else float(fallback)
    except (TypeError, ValueError):
        return float(fallback)


def _text_regions(page: dict[str, Any]) -> Iterable[tuple[str, tuple[float, float, float, float]]]:
    blocks = page.get("blocks")
    if isinstance(blocks, list):
        for block in blocks:
            if not isinstance(block, dict):
                continue
            text = block.get("content")
            box = _block_box(block)
            if isinstance(text, str) and text.strip() and box:
                yield text.strip(), box


def build_searchable_pdf(
    source: Path,
    mime_type: str,
    pages: list[dict[str, Any]],
    output: Path,
    *,
    dpi: int,
    font_path: Path | None = None,
) -> None:
    """Rasterize source and overlay invisible, positioned Unicode text."""
    import pikepdf
    from fpdf import FPDF

    source_page_count = _source_page_count(source, mime_type)
    if source_page_count != len(pages):
        raise PdfBuildError(
            f"Source has {source_page_count} page(s), Mistral returned {len(pages)} page(s)",
        )

    font = find_font(font_path)
    temp_images: list[Path] = []
    merged = pikepdf.Pdf.new()
    try:
        page_images = _page_images(source, mime_type, dpi, output.parent)
        for index, ((image, page_dpi), page) in enumerate(zip(page_images, pages, strict=True)):
            pdf = FPDF(unit="pt")
            pdf.set_auto_page_break(False)
            pdf.add_font("OCR", fname=str(font))
            width_pt = image.width * 72 / page_dpi
            height_pt = image.height * 72 / page_dpi
            image_path = output.parent / f"mistral-page-{index}.png"
            image.save(image_path, format="PNG")
            temp_images.append(image_path)
            pdf.add_page(format=(width_pt, height_pt))
            pdf.image(image_path, x=0, y=0, w=width_pt, h=height_pt)
            image_path.unlink()
            temp_images.remove(image_path)

            dimensions = page.get("dimensions")
            source_width = _dimension(
                dimensions.get("width") if isinstance(dimensions, dict) else None,
                image.width,
            )
            source_height = _dimension(
                dimensions.get("height") if isinstance(dimensions, dict) else None,
                image.height,
            )
            scale_x = width_pt / source_width
            scale_y = height_pt / source_height

            regions = list(_text_regions(page))
            if not regions and str(page.get("markdown", "")).strip():
                regions = [
                    (
                        str(page["markdown"]).strip(),
                        (0, 0, source_width, source_height),
                    ),
                ]
            with pdf.local_context(text_mode="INVISIBLE"):
                for text, (left, top, right, bottom) in regions:
                    lines = [line.strip() for line in text.splitlines() if line.strip()]
                    if not lines:
                        continue
                    line_height = max(4.0, min(72.0, (bottom - top) * scale_y / len(lines)))
                    pdf.set_font("OCR", size=line_height * 0.8)
                    for line_index, line in enumerate(lines):
                        x = max(0.0, left * scale_x)
                        y = max(line_height, (top * scale_y) + ((line_index + 0.8) * line_height))
                        available = max(1.0, (right - left) * scale_x)
                        natural = pdf.get_string_width(line)
                        stretching = min(100.0, available / natural * 100) if natural else 100
                        pdf.set_stretching(stretching)
                        pdf.text(x=x, y=min(y, height_pt), text=line)
                    pdf.set_stretching(100)
            page_pdf_path = output.parent / f"mistral-page-{index}.pdf"
            temp_images.append(page_pdf_path)
            pdf.output(page_pdf_path)
            with pikepdf.open(page_pdf_path) as page_pdf:
                merged.pages.extend(page_pdf.pages)
            page_pdf_path.unlink()
            temp_images.remove(page_pdf_path)
        merged.save(output)
    finally:
        page_images.close()
        merged.close()
        for temp_image in temp_images:
            temp_image.unlink(missing_ok=True)
