#!/bin/sh
# ---------------------------------------------------------------------
# Runtime secrets materialisation — THE single configuration layer.
#
# AWS injects credentials as environment variables (ECS "secrets" from
# Secrets Manager, or `docker run -e`); this script renders them into
# .streamlit/secrets.toml at container start so the application runs
# completely unchanged.
#
# Variables:
#   APP_PASSWORD     REQUIRED. The access-gate password analysts type.
#                    Without it this script REFUSES TO START — client
#                    programme data is commercially sensitive and an
#                    unconfigured container must never serve open.
#                    (ALLOW_PUBLIC=true overrides, for demos only.)
#   GEMINI_API_KEY   the Gemini credential — the app's ZERO-CLICK
#                    MANAGED DEFAULT. GOOGLE_API_KEY works too.
#                    Analysts never see, type or handle the key.
#   ANTHROPIC_API_KEY / OPENAI_API_KEY
#                    optional: pre-fill for analysts who switch to
#                    their own provider. Normally unset.
# ---------------------------------------------------------------------
set -eu

if [ -z "${APP_PASSWORD:-}" ] && [ "${ALLOW_PUBLIC:-}" != "true" ]; then
    echo "FATAL: APP_PASSWORD is not set and ALLOW_PUBLIC != true." >&2
    echo "Refusing to serve an open instance. Set APP_PASSWORD in the" >&2
    echo "task's secrets (see README_DEPLOY.md, step 3)." >&2
    exit 1
fi

mkdir -p /app/.streamlit
SECRETS=/app/.streamlit/secrets.toml
: > "$SECRETS"
chmod 600 "$SECRETS"

if [ -n "${APP_PASSWORD:-}" ]; then
    printf 'APP_PASSWORD = "%s"\n' "$APP_PASSWORD" >> "$SECRETS"
fi
if [ "${ALLOW_PUBLIC:-}" = "true" ]; then
    printf 'ALLOW_PUBLIC = "true"\n' >> "$SECRETS"
fi
for VAR in GEMINI_API_KEY GOOGLE_API_KEY ANTHROPIC_API_KEY \
           OPENAI_API_KEY; do
    VAL=$(printenv "$VAR" || true)
    if [ -n "$VAL" ]; then
        printf '%s = "%s"\n' "$VAR" "$VAL" >> "$SECRETS"
    fi
done

# Either Google name works; honour whichever was set.
if [ -n "${GEMINI_API_KEY:-}" ] && [ -z "${GOOGLE_API_KEY:-}" ]; then
    export GOOGLE_API_KEY="$GEMINI_API_KEY"
    printf 'GOOGLE_API_KEY = "%s"\n' "$GEMINI_API_KEY" >> "$SECRETS"
fi

echo "secrets.toml rendered ($(grep -c '=' "$SECRETS") entries)."
exec python -m streamlit run app.py \
    --server.port "${PORT:-8501}" \
    --server.address 0.0.0.0
