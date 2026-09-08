ARG PAPERLESS_VERSION=3.1.3
FROM ghcr.io/paperless-ngx/paperless-ngx:${PAPERLESS_VERSION}

COPY . /tmp/paperless-mistral-parser
RUN pip install --no-cache-dir /tmp/paperless-mistral-parser \
    && rm -rf /tmp/paperless-mistral-parser
