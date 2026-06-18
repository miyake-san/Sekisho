# syntax=docker/dockerfile:1

# ---- Build stage: resolve and install dependencies with uv ----
FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

# Install only production dependencies first (cached unless lockfile changes).
# CONTEXT.md is the package readme referenced by pyproject.toml, so the build
# backend needs it present to build the wheel.
COPY pyproject.toml uv.lock CONTEXT.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

# ---- Runtime stage: minimal image with just the virtual environment ----
FROM python:3.14-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Run as a non-root user.
RUN useradd --create-home --uid 10001 appuser
COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv

USER appuser
EXPOSE 8000

# Sekisho is an ASGI app exposed as sekisho.main:app on port 8000.
CMD ["uvicorn", "sekisho.main:app", "--host", "0.0.0.0", "--port", "8000"]