#!/bin/bash
set -e

WORKSPACE=/workspace/open-coscientist
REPO=${OPEN_COSCIENTIST_REPO:-}
REF=${OPEN_COSCIENTIST_REF:-main}

if [ -f "$WORKSPACE/pyproject.toml" ]; then
    echo "Found engine checkout at $WORKSPACE, installing..."
else
    echo "No checkout found at $WORKSPACE, cloning $REPO@$REF..."
    git clone --depth 1 --branch "$REF" "$REPO" "$WORKSPACE"
fi

pip install --no-cache-dir -q -e "$WORKSPACE"

exec python -m uvicorn app.main:app \
    --host 0.0.0.0 \
    --port 8008 \
    --reload \
    --reload-dir app
