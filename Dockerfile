# ABOUTME: Multi-stage Dockerfile for BehindBars web application.
# ABOUTME: Uses uv for dependency management, runs uvicorn on Cloud Run.

# Build stage
FROM python:3.13-slim AS builder

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Set working directory
WORKDIR /app

# Copy dependency files
COPY pyproject.toml uv.lock README.md ./

# Install dependencies
RUN uv sync --frozen --no-dev --no-install-project

# Copy application code
COPY src/ ./src/
COPY alembic.ini ./

# Install the project itself
RUN uv sync --frozen --no-dev

# Runtime stage
FROM python:3.13-slim AS runtime

# Create non-root user
RUN useradd --create-home --shell /bin/bash app

# Set working directory
WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Copy application code
COPY --from=builder /app/src ./src
COPY --from=builder /app/alembic.ini ./

# Create data directories (writable by app user)
RUN mkdir -p /app/data /app/previous_issues && chown -R app:app /app/data /app/previous_issues

# Set environment variables
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Switch to non-root user
USER app

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/', timeout=5)" || exit 1

# Run uvicorn
CMD ["uvicorn", "behind_bars_pulse.web.app:app", "--host", "0.0.0.0", "--port", "8000"]
