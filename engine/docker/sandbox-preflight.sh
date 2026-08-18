#!/bin/sh
# Refuses to run the suite when nothing here can actually confine.
#
# The failure this prevents: when the selected backend cannot start,
# every command it wraps fails -- including the ones the escape tests
# expect to fail. The denial tests then pass for the wrong reason and the
# suite reports green while confining nothing. That is the exact
# false-pass this whole area keeps producing, so it is checked rather
# than trusted. A probe once printed "OUTSIDE: denied (good)" when bwrap
# had never started.
#
# It also prints which backend was selected, because that is the point of
# running this image twice: privileged selects bubblewrap, unprivileged
# falls back to landlock, and a run that silently used the other one
# would prove nothing about the platform it claims to cover.
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
