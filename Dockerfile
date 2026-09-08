ARG PAPERLESS_VERSION=3.1.3
FROM ghcr.io/paperless-ngx/paperless-ngx:${PAPERLESS_VERSION}

COPY . /tmp/paperless-mistral-parser
RUN apt-get update \
    && apt-get install --yes --no-install-recommends fonts-noto-core \
    && pip install --no-cache-dir /tmp/paperless-mistral-parser \
    && rm -rf /var/lib/apt/lists/* \
    && rm -rf /tmp/paperless-mistral-parser
