from pathlib import Path

import pytest

from paperless_mistral_parser.config import Config, ConfigurationError


def test_loads_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MISTRAL_API_KEY", "secret")

    config = Config.load()

    assert config.api_key == "secret"
    assert config.endpoint == "https://api.mistral.ai"
    assert config.model == "mistral-ocr-latest"
    assert config.retries == 3
    assert config.max_pages == 100


def test_reads_key_from_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    secret = tmp_path / "key"
    secret.write_text("secret\n", encoding="utf-8")
    monkeypatch.setenv("MISTRAL_API_KEY_FILE", str(secret))

    assert Config.load().api_key == "secret"


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("MISTRAL_OCR_TIMEOUT", "zero", "must be a number"),
        ("MISTRAL_OCR_RETRIES", "0", "must be greater than zero"),
        ("MISTRAL_OCR_ENDPOINT", "http://example.com", "must use HTTPS"),
        ("MISTRAL_OCR_ENDPOINT", "https://user@example.com", "not a valid base URL"),
    ],
)
def test_rejects_invalid_config(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
    message: str,
) -> None:
    monkeypatch.setenv("MISTRAL_API_KEY", "secret")
    monkeypatch.setenv(name, value)

    with pytest.raises(ConfigurationError, match=message):
        Config.load()


def test_key_and_key_file_are_mutually_exclusive(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    secret = tmp_path / "key"
    secret.write_text("secret", encoding="utf-8")
    monkeypatch.setenv("MISTRAL_API_KEY", "secret")
    monkeypatch.setenv("MISTRAL_API_KEY_FILE", str(secret))

    with pytest.raises(ConfigurationError, match="Set only one"):
        Config.load()


def test_is_disabled_without_key() -> None:
    assert Config.is_enabled() is False


def test_missing_key_file_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MISTRAL_API_KEY_FILE", "/does/not/exist")

    with pytest.raises(ConfigurationError, match="Unable to read"):
        Config.load()
