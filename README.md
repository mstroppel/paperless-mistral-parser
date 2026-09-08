# Paperless Mistral Parser

`paperless-mistral-parser` is a document parser plugin for Paperless-ngx. It
uses Mistral Document AI OCR for scan-based PDFs and images while keeping
born-digital PDFs local.

The plugin requires **Paperless-ngx 3.1 or newer**. Version 3.1 introduced the
remote-service flag used to enable or deny external processing per document.

## How It Works

With Paperless OCR and archive generation set to `auto`, Paperless first
decides whether a PDF already contains enough native text:

- Born-digital PDF: Paperless extracts its embedded text locally. No document
  data is sent to Mistral.
- Scan-based PDF or supported image: the plugin sends the file to Mistral OCR.
- Office files and email: existing Tika and Gotenberg parsers remain in use.

Mistral returns Markdown and positioned text blocks. The plugin passes the
Markdown to Paperless as searchable content and overlays an invisible Unicode
text layer on locally rendered page images. Paperless retains the original
document unchanged and stores the generated searchable PDF as its archive
copy.

Supported input types are PDF, PNG, JPEG, TIFF, BMP, GIF, and WebP. Mixed PDFs
are classified as a whole by Paperless; page-by-page OCR selection is not
currently implemented.

## Installation

Building a custom Paperless image is the recommended, reproducible method.

### 1. Build the image

Clone this repository on the Docker host and build it:

```bash
git clone https://github.com/mstroppel/paperless-mistral-parser.git
cd paperless-mistral-parser
docker build \
  --build-arg PAPERLESS_VERSION=3.1.3 \
  --tag paperless-mistral-parser:3.1.3 .
```

Use a tested Paperless version instead of `3.1.3` when upgrading. Do not use
an unpinned `latest` tag in production.

### 2. Create the API-key secret

```bash
mkdir -p secrets
printf '%s' 'YOUR_MISTRAL_API_KEY' > secrets/mistral_api_key
chmod 600 secrets/mistral_api_key
```

The `secrets/` directory and API key must never be committed.

### 3. Update Docker Compose

Apply these additions to the existing Paperless Compose file. Preserve its
current volumes, database, broker, Tika, Gotenberg, network, and other
settings.

```yaml
services:
  paperless:
    image: paperless-mistral-parser:3.1.3
    environment:
      PAPERLESS_OCR_MODE: auto
      PAPERLESS_ARCHIVE_FILE_GENERATION: auto
      PAPERLESS_REMOTE_OCR_BY_DEFAULT: "true"
      MISTRAL_API_KEY_FILE: /run/secrets/mistral_api_key
    secrets:
      - mistral_api_key

secrets:
  mistral_api_key:
    file: ./secrets/mistral_api_key
```

Alternatively, adapt `compose.override.example.yml` and merge it with the
existing Compose file:

```bash
docker compose \
  -f /path/to/paperless/docker-compose.yml \
  -f compose.override.example.yml \
  up -d --build
```

All Paperless processes using the parser must run from the custom image. If
the deployment has separate webserver, consumer, or task-worker services,
set the custom image on each of them.

### 4. Restart and verify

```bash
docker compose up -d
docker compose logs paperless | grep "Loaded third-party parser"
```

Expected startup message includes:

```text
Loaded third-party parser 'Mistral OCR' v0.1.0
```

Import one born-digital PDF and one scan before enabling the plugin for a
large archive. Logs should report that Mistral was skipped for the digital PDF
and completed for the scan.

## Selective Remote OCR

The example enables Mistral for every eligible document:

```env
PAPERLESS_REMOTE_OCR_BY_DEFAULT=true
```

To opt in only selected documents, set it to `false` and create a Paperless
workflow that enables remote OCR for matching documents. The parser declares
`uses_remote_service = True`, so Paperless will not select it unless remote
processing is allowed for that ingestion.

## Configuration

All plugin settings are environment variables.

| Variable | Default | Description |
| --- | --- | --- |
| `MISTRAL_API_KEY` | none | Mistral API key. Prefer the file variant. |
| `MISTRAL_API_KEY_FILE` | none | Path to a file containing the API key. |
| `MISTRAL_OCR_ENDPOINT` | `https://api.mistral.ai` | API base URL without `/v1/ocr`. |
| `MISTRAL_OCR_MODEL` | `mistral-ocr-latest` | Mistral OCR model. Pin a model if reproducibility is required. |
| `MISTRAL_OCR_TIMEOUT` | `600` | Request timeout in seconds. |
| `MISTRAL_OCR_RETRIES` | `3` | Attempts for network errors, HTTP 429, and HTTP 5xx. |
| `MISTRAL_OCR_MAX_BYTES` | `52428800` | Maximum input size in bytes (50 MiB). |
| `MISTRAL_OCR_MAX_PAGES` | `100` | Maximum document page count. |
| `MISTRAL_OCR_RENDER_DPI` | `200` | Resolution used for archive pages. |
| `MISTRAL_OCR_FONT_PATH` | auto-detected | Unicode TTF used for the invisible text layer. |
| `MISTRAL_OCR_ALLOW_HTTP` | `false` | Permit a non-TLS custom endpoint. Use only on a trusted private network. |

`MISTRAL_API_KEY` and `MISTRAL_API_KEY_FILE` are mutually exclusive. The
plugin refuses invalid configuration and remains unselected when no key is
available.

## Failure Behavior

The plugin retries temporary network failures, rate limits, and server errors
with exponential backoff. Permanent API errors, invalid responses, empty OCR
results, page-count mismatches, and local PDF generation errors fail the
Paperless import with a `ParseError`. It never silently imports an empty
document or falls back to Tesseract.

Document content and API keys are not logged. Mistral request IDs and page
counts are logged for diagnostics.

## PDF/A

Generated archives are searchable PDFs, but are **not guaranteed to conform
to PDF/A**. If formal PDF/A compliance is required, add a post-processing step
using OCRmyPDF/Ghostscript without re-running OCR and validate the output with
veraPDF. Always test this against the exact Paperless and plugin versions used
in production.

## Direct Python Installation

For non-Docker Paperless installations, install the wheel into the same Python
environment as Paperless and restart every Paperless process:

```bash
python -m pip install \
  "git+https://github.com/mstroppel/paperless-mistral-parser.git@v0.1.0"
```

For an unreleased checkout:

```bash
python -m pip install /path/to/paperless-mistral-parser
```

## Development

Python 3.11 or newer and Poppler (`pdftoppm`) are required. Create an isolated
environment and install runtime plus development dependencies:

```bash
python -m venv .venv
.venv/bin/python -m pip install --group dev -e .
```

Run all checks:

```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy
.venv/bin/pytest
.venv/bin/python -m build
```

Tests use mocked HTTP responses and never contact Mistral. CI runs on Python
3.11, 3.12, and 3.13.

## Security and Privacy

OCR sends complete eligible documents to the configured endpoint. Confirm
that this complies with data-protection, retention, and contractual
requirements before enabling remote OCR. Keep TLS enabled, use Docker secrets
or an equivalent secret store, restrict access to the secret file, and review
Mistral's current processing terms.

## License

MIT. See `LICENSE`.
