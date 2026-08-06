# Forensic Delay Analysis Toolkit — AWS build (Gemini-only edition).
# Build from THIS folder:
#
#   docker build -t delay-toolkit:v1 .
#
# The application in this package is complete and self-contained; all
# deployment concerns (password, Gemini key, server settings) are
# injected at runtime by entrypoint.sh — nothing sensitive is ever
# baked into an image layer.

FROM python:3.11-slim

# curl: container/ALB health checks hit Streamlit's /_stcore/health
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /app/.streamlit && cp config.toml /app/.streamlit/config.toml \
    && chmod +x /app/entrypoint.sh

RUN useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fs http://localhost:8501/_stcore/health || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
