#!/bin/sh
# Require a working namespace before escape tests: launch failure would make denials falsely
# pass.
set -e

BACKEND=$(python -c 'from co_scientist.sandbox import sandbox_backend; print(sandbox_backend() or "")')

if [ -z "$BACKEND" ]; then
  echo "PREFLIGHT FAILED: no usable sandbox backend in this container." >&2
  echo "" >&2
  echo "bubblewrap needs unprivileged user namespaces, which a default" >&2
  echo "container seccomp profile blocks; landlock needs Linux 5.13+." >&2
  echo "With neither, the escape tests would pass because nothing ran --" >&2
  echo "not because anything was confined." >&2
  exit 1
fi

echo "preflight ok: sandbox backend = $BACKEND"
exec "$@"
