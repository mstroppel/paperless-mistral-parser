"""Environment-based plugin configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


class ConfigurationError(ValueError):
    """Raised for invalid plugin configuration."""


def _positive_number(name: str, default: str, converter: type[int] | type[float]) -> int | float:
    raw = os.getenv(name, default)
    try:
        value = converter(raw)
    except ValueError as error:
        raise ConfigurationError(f"{name} must be a number") from error
    if value <= 0:
        raise ConfigurationError(f"{name} must be greater than zero")
    return value


def _read_secret(name: str) -> str | None:
    value = os.getenv(name)
    file_name = os.getenv(f"{name}_FILE")
    if value and file_name:
        raise ConfigurationError(f"Set only one of {name} and {name}_FILE")
    if file_name:
        try:
            value = Path(file_name).read_text(encoding="utf-8")
        except OSError as error:
            raise ConfigurationError(f"Unable to read {name}_FILE") from error
    return value.strip() if value and value.strip() else None


def _endpoint() -> str:
    endpoint = os.getenv("MISTRAL_OCR_ENDPOINT", "https://api.mistral.ai").rstrip("/")
    parsed = urlsplit(endpoint)
    allow_http = os.getenv("MISTRAL_OCR_ALLOW_HTTP", "false").lower() in {"1", "true", "yes"}
    if parsed.scheme not in ({"https", "http"} if allow_http else {"https"}):
        raise ConfigurationError("MISTRAL_OCR_ENDPOINT must use HTTPS")
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ConfigurationError("MISTRAL_OCR_ENDPOINT is not a valid base URL")
    return endpoint


@dataclass(frozen=True, slots=True)
class Config:
    """Validated runtime settings."""

    api_key: str
    endpoint: str
    model: str
    timeout: float
    retries: int
    max_bytes: int
    max_pages: int
    render_dpi: int
    font_path: Path | None

    @classmethod
    def load(cls) -> Config:
        api_key = _read_secret("MISTRAL_API_KEY")
        if not api_key:
            raise ConfigurationError("MISTRAL_API_KEY or MISTRAL_API_KEY_FILE is required")
        font = os.getenv("MISTRAL_OCR_FONT_PATH")
        return cls(
            api_key=api_key,
            endpoint=_endpoint(),
            model=os.getenv("MISTRAL_OCR_MODEL", "mistral-ocr-latest"),
            timeout=float(_positive_number("MISTRAL_OCR_TIMEOUT", "600", float)),
            retries=int(_positive_number("MISTRAL_OCR_RETRIES", "3", int)),
            max_bytes=int(_positive_number("MISTRAL_OCR_MAX_BYTES", "52428800", int)),
            max_pages=int(_positive_number("MISTRAL_OCR_MAX_PAGES", "100", int)),
            render_dpi=int(_positive_number("MISTRAL_OCR_RENDER_DPI", "200", int)),
            font_path=Path(font) if font else None,
        )

    @classmethod
    def is_enabled(cls) -> bool:
        try:
            cls.load()
        except ConfigurationError:
            return False
        return True
