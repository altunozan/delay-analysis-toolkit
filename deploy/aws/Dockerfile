# Forensic Delay Analysis Toolkit — production image.
#
# Build FROM THE REPOSITORY ROOT (the build context must see the whole
# app, this file only lives in deploy/aws/):
#
#   docker build -f deploy/aws/Dockerfile -t delay-toolkit:latest .
#
# The app code is copied UNCHANGED — every feature, chart and module is
# exactly the repository. All deployment concerns (secrets, Streamlit
# server settings) are injected at runtime by entrypoint.sh.

FROM python:3.11-slim

# curl: container/ALB health checks hit Streamlit's /_stcore/health
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Dependencies first so code edits do not bust the pip layer cache.
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# The application — unchanged. (.dockerignore trims repo baggage that
# the app never imports: tests, dev tooling, the graph cache, deckforge.)
COPY . .

# Server settings live in config.toml (upload limit, headless, address);
# secrets.toml is WRITTEN AT RUNTIME by the entrypoint from environment
# variables, so no credential is ever baked into an image layer.
COPY deploy/aws/config.toml /app/.streamlit/config.toml
COPY deploy/aws/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Run as a non-root user; the entrypoint writes /app/.streamlit at start.
RUN useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fs http://localhost:8501/_stcore/health || exit 1

ENTRYPOINT ["/entrypoint.sh"]
