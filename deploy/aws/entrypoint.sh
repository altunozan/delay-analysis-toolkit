#!/bin/sh
# ---------------------------------------------------------------------
# Runtime secrets materialisation — THE single configuration layer.
#
# The app reads credentials through st.secrets (.streamlit/secrets.toml)
# and the process environment. AWS injects everything as environment
# variables (ECS "secrets" from Secrets Manager, or `docker run -e`);
# this script renders them into secrets.toml at container start so the
# application code runs COMPLETELY UNCHANGED.
#
# Recognised variables (all optional except APP_PASSWORD):
#   APP_PASSWORD     access-gate password. WITHOUT IT THE APP SERVES
#                    OPEN: the fail-closed guard in app.py keys off
#                    Streamlit Cloud's filesystem and does not trip on
#                    AWS, so this script refuses to start without a
#                    password unless ALLOW_PUBLIC=true is set on
#                    purpose.
#   GEMINI_API_KEY   the COAIR Gemini credential (single layer). Also
#                    exported as GOOGLE_API_KEY — the app accepts
#                    either name and PRE-FILLS the Gemini key field
#                    from the environment, so analysts never handle
#                    the key.
#   ANTHROPIC_API_KEY / OPENAI_API_KEY / NVIDIA_API_KEY
#                    optional additional providers. NVIDIA_API_KEY, if
#                    set, becomes the zero-click managed default —
#                    leave it UNSET in COAIR per the no-NVIDIA policy.
#   ALLOW_PUBLIC     "true" to run without a password (demo only).
# ---------------------------------------------------------------------
set -eu

if [ -z "${APP_PASSWORD:-}" ] && [ "${ALLOW_PUBLIC:-}" != "true" ]; then
    echo "FATAL: APP_PASSWORD is not set and ALLOW_PUBLIC != true." >&2
    echo "Client programmes are commercially sensitive; refusing to" >&2
    echo "serve an open instance. Set APP_PASSWORD in the task's" >&2
    echo "secrets (see deploy/aws/DEPLOYMENT_GUIDE.md, step 3)." >&2
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
           OPENAI_API_KEY NVIDIA_API_KEY; do
    VAL=$(printenv "$VAR" || true)
    if [ -n "$VAL" ]; then
        printf '%s = "%s"\n' "$VAR" "$VAL" >> "$SECRETS"
    fi
done

# The app's Gemini field falls back to GOOGLE_API_KEY — honour a
# deployment that set only GEMINI_API_KEY, and vice versa.
if [ -n "${GEMINI_API_KEY:-}" ] && [ -z "${GOOGLE_API_KEY:-}" ]; then
    export GOOGLE_API_KEY="$GEMINI_API_KEY"
    printf 'GOOGLE_API_KEY = "%s"\n' "$GEMINI_API_KEY" >> "$SECRETS"
fi

echo "secrets.toml rendered ($(grep -c '=' "$SECRETS") entries)."
exec python -m streamlit run app.py \
    --server.port "${PORT:-8501}" \
    --server.address 0.0.0.0
