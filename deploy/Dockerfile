# CHIMERA gateway. Build from the repo root: docker build -f deploy/Dockerfile -t chimera-gateway .
# Add the local embedding model for the semantic cache (large): --build-arg EXTRAS=gateway,embed
FROM python:3.12-slim

ARG EXTRAS=gateway
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app \
    CHIMERA_CONFIG=/etc/chimera/chimera.toml

WORKDIR /app
COPY pyproject.toml README.md ./
RUN pip install ".[${EXTRAS}]"

COPY conftest.py ./
COPY packages/chimera-core ./packages/chimera-core
COPY apps/gateway ./apps/gateway
COPY apps/kiro-trimmer ./apps/kiro-trimmer
COPY deploy/chimera.docker.toml /etc/chimera/chimera.toml

# Non-root user. /data holds the key store, audit log, caches and telemetry; mount a volume there.
RUN useradd --system --uid 10001 --no-create-home chimera \
    && mkdir /data && chown chimera /data
USER chimera
VOLUME /data
EXPOSE 8088

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
    CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8088/healthz', timeout=2)"

# 0.0.0.0 is the address inside the container only. Publish the port on 127.0.0.1 or behind a proxy.
CMD ["python", "-m", "apps.gateway", "--host", "0.0.0.0", "--port", "8088"]
