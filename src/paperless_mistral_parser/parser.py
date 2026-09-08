"""Paperless-ngx parser entry point."""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Self, cast

from PIL import Image, ImageSequence

from paperless_mistral_parser import __version__
from paperless_mistral_parser.client import MistralClient, OcrError, pages_to_text
from paperless_mistral_parser.config import Config, ConfigurationError
from paperless_mistral_parser.searchable_pdf import PdfBuildError, build_searchable_pdf

if TYPE_CHECKING:
    import datetime
    from types import TracebackType

    from paperless.parsers import MetadataEntry, ParserContext

logger = logging.getLogger("paperless_mistral_parser")

SUPPORTED_MIME_TYPES = {
    "application/pdf": ".pdf",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/tiff": ".tiff",
    "image/bmp": ".bmp",
    "image/gif": ".gif",
    "image/webp": ".webp",
}


class MistralOcrParser:
    """OCR scan-based PDFs and images with Mistral Document AI."""

    name = "Mistral OCR"
    version = __version__
    author = "Marco Stroppel"
    url = "https://github.com/mstroppel/paperless-mistral-parser"
    uses_remote_service = True

    @classmethod
    def supported_mime_types(cls) -> dict[str, str]:
        return SUPPORTED_MIME_TYPES.copy()

    @classmethod
    def score(cls, mime_type: str, filename: str, path: Path | None = None) -> int | None:
        del filename, path
        return 30 if mime_type in SUPPORTED_MIME_TYPES and Config.is_enabled() else None

    @property
    def can_produce_archive(self) -> bool:
        return True

    @property
    def requires_pdf_rendition(self) -> bool:
        return False

    def __init__(self, logging_group: object = None) -> None:
        try:
            from django.conf import settings

            scratch = settings.SCRATCH_DIR
        except (ImportError, AttributeError):
            scratch = None
        self._tempdir = Path(tempfile.mkdtemp(prefix="paperless-mistral-", dir=scratch))
        self._logging_group = logging_group
        self._text = ""
        self._archive_path: Path | None = None

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        shutil.rmtree(self._tempdir, ignore_errors=True)

    def configure(self, context: ParserContext) -> None:
        del context

    def parse(self, document_path: Path, mime_type: str, *, produce_archive: bool = True) -> None:
        from documents.parsers import ParseError

        self._text = ""
        self._archive_path = None
        if mime_type not in SUPPORTED_MIME_TYPES:
            raise ParseError(f"Unsupported MIME type: {mime_type}")

        try:
            config = Config.load()
            if mime_type == "application/pdf" and not produce_archive:
                from paperless.parsers.utils import extract_pdf_text, post_process_text

                self._text = post_process_text(extract_pdf_text(document_path, log=logger)) or ""
                logger.info("Mistral OCR skipped for born-digital PDF")
                return
            self._validate_page_count(document_path, mime_type, config.max_pages)
            with MistralClient(config) as client:
                pages = client.process(document_path, mime_type)
            self._text = pages_to_text(pages)
            if not self._text:
                raise OcrError("Mistral OCR returned no text")
            if produce_archive:
                self._archive_path = self._tempdir / "archive.pdf"
                build_searchable_pdf(
                    document_path,
                    mime_type,
                    pages,
                    self._archive_path,
                    dpi=config.render_dpi,
                    font_path=config.font_path,
                )
        except (ConfigurationError, OcrError, PdfBuildError, OSError, ValueError) as error:
            logger.exception("Mistral OCR parsing failed: %s", error)
            raise ParseError(f"Mistral OCR parsing failed: {error}") from error

    def _validate_page_count(self, path: Path, mime_type: str, limit: int) -> None:
        count = self.get_page_count(path, mime_type)
        if count is not None and count > limit:
            raise OcrError(f"Document exceeds MISTRAL_OCR_MAX_PAGES ({count} pages)")

    def get_text(self) -> str:
        return self._text

    def get_date(self) -> datetime.datetime | None:
        return None

    def get_archive_path(self) -> Path | None:
        return self._archive_path

    def get_thumbnail(self, document_path: Path, mime_type: str) -> Path:
        if mime_type == "application/pdf" or self._archive_path:
            from documents.parsers import make_thumbnail_from_pdf

            return cast(
                Path,
                make_thumbnail_from_pdf(
                    self._archive_path or document_path,
                    self._tempdir,
                    self._logging_group,
                ),
            )
        output = self._tempdir / "thumbnail.webp"
        with Image.open(document_path) as image:
            image.seek(0)
            thumbnail = image.convert("RGB")
            thumbnail.thumbnail((500, 700))
            thumbnail.save(output, "WEBP")
        return output

    def get_page_count(self, document_path: Path, mime_type: str) -> int | None:
        if mime_type == "application/pdf":
            from paperless.parsers.utils import get_page_count_for_pdf

            return cast(int | None, get_page_count_for_pdf(document_path, log=logger))
        if mime_type.startswith("image/"):
            with Image.open(document_path) as image:
                return sum(1 for _ in ImageSequence.Iterator(image))
        return None

    def extract_metadata(self, document_path: Path, mime_type: str) -> list[MetadataEntry]:
        if mime_type != "application/pdf":
            return []
        try:
            from paperless.parsers.utils import extract_pdf_metadata

            return cast(list[MetadataEntry], extract_pdf_metadata(document_path, log=logger))
        except Exception as error:
            logger.warning("Could not extract PDF metadata: %s", error)
            return []
