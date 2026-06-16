#!/bin/bash
#
# Container entrypoint for the Co-Scientist API service. Makes the
# co-scientist-engine package available (using a mounted checkout at
# $WORKSPACE if present, otherwise cloning COSCIENTIST_ENGINE_REPO at
# COSCIENTIST_ENGINE_REF), installs it, then launches the FastAPI app
# under uvicorn.
set -e

WORKSPACE=/workspace/co-scientist-engine
REPO=${COSCIENTIST_ENGINE_REPO:-}
REF=${COSCIENTIST_ENGINE_REF:-main}

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
