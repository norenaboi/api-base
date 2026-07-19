FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

COPY pyproject.toml README.md ./
COPY api_base ./api_base

RUN python -m pip wheel --wheel-dir /wheels .

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    API_BASE_HOST=0.0.0.0 \
    API_BASE_PORT=8765 \
    API_BASE_DATABASE=/data/vault.sqlite3

RUN groupadd --gid 10001 api-base \
    && useradd --uid 10001 --gid api-base --home-dir /home/api-base --create-home api-base \
    && mkdir -p /data \
    && chown api-base:api-base /data

COPY --from=builder /wheels /wheels
RUN python -m pip install --no-cache-dir /wheels/* \
    && rm -rf /wheels

USER api-base
WORKDIR /home/api-base

EXPOSE 8765
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('API_BASE_PORT', '8765') + '/healthz', timeout=3).read()"]

CMD ["api-base"]
