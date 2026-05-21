# syntax=docker/dockerfile:1.7
#
# Container image for customer-hosted Azure Container Apps deployment.
# Built and published to ghcr.io/amitagl27/opentext-pa-mcp by
# .github/workflows/publish-image.yml on tag pushes and main pushes.
#
# Multi-stage: builder stage runs `uv build` from repo source so the image
# is reproducible from this repo without a PyPI release prerequisite.

# ---------- builder ----------
FROM python:3.12-slim AS builder

RUN pip install --no-cache-dir uv

WORKDIR /build
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv build --wheel --out-dir /build/dist

# ---------- runtime ----------
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH

WORKDIR $HOME/app

COPY --from=builder --chown=user:user /build/dist/*.whl ./
RUN pip install --user --no-cache-dir ./*.whl \
    && rm ./*.whl

# HTTP transport (DEC-015): credentials arrive on each request as HTTP headers.
# Bind to 0.0.0.0 inside the container; Container Apps routes external traffic
# to whatever port we declare as the ingress targetPort (7860 in the ARM template).
ENV PA_TRANSPORT=http \
    PA_HTTP_HOST=0.0.0.0 \
    PA_HTTP_PORT=7860 \
    PA_LOG_LEVEL=INFO

EXPOSE 7860

CMD ["python", "-m", "opentext_pa_mcp"]
