#!/bin/sh
set -eu
case "${PAN_HASH_SECRET:-}" in
    ""|REPLACE_*) echo "Set a persistent PAN_HASH_SECRET before starting." >&2; exit 1 ;;
esac
case "${AUTH_ENABLED:-false}" in
    true|True|TRUE|1)
        case "${BOOTSTRAP_ADMIN_PASSWORD:-}" in
            ""|REPLACE_*) echo "Set BOOTSTRAP_ADMIN_PASSWORD before starting." >&2; exit 1 ;;
        esac ;;
esac
cd "/source/$SOURCE_REF/api"
runtime="/python-env/$SOURCE_REF"
if [ ! -f "$runtime/.ready" ]; then
    python -m venv "$runtime"
    "$runtime/bin/pip" install --no-cache-dir -r requirements.txt
    touch "$runtime/.ready"
fi
export PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
exec "$runtime/bin/python" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-access-log
