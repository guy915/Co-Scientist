#!/usr/bin/env bash
# Run API + UI side-by-side with prefixed output. Ctrl-C kills both.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cleanup() { kill 0 2>/dev/null || true; }
trap cleanup EXIT INT TERM

(cd "$ROOT" && make dev-api 2>&1 | sed 's/^/[api] /') &
(cd "$ROOT" && make dev-ui 2>&1 | sed 's/^/[ui]  /') &
wait
