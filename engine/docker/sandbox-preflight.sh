#!/bin/sh
# Require a working backend before escape tests: launch failure would make denials falsely
# pass.
set -e

BACKEND=$(python -c 'from co_scientist.sandbox import sandbox_backend; print(sandbox_backend() or "")')

if [ -z "$BACKEND" ]; then
  echo "PREFLIGHT FAILED: no usable sandbox backend in this container." >&2
  echo "" >&2
  echo "landlock needs Linux 5.13+ with the LSM enabled." >&2
  echo "Without it, the escape tests would pass because nothing ran --" >&2
  echo "not because anything was confined." >&2
  exit 1
fi

echo "preflight ok: sandbox backend = $BACKEND"
exec "$@"
