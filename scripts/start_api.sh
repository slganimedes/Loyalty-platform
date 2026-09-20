#!/bin/sh
set -eu
cd "/source/$SOURCE_REF/api"
runtime="/python-env/$SOURCE_REF"
if [ ! -f "$runtime/.ready" ]; then
    python -m venv "$runtime"
    "$runtime/bin/pip" install --no-cache-dir -r requirements.txt
    touch "$runtime/.ready"
fi
export PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
exec "$runtime/bin/python" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-access-log
