#!/bin/sh
# Refuses to run the sandbox suite in a container where bwrap cannot
# create a namespace.
#
# This guard exists because the failure is silent and inverted: when
# bwrap cannot start, every command it wraps fails — including the ones
# the tests expect to fail. The denial tests then pass for the wrong
# reason and the suite reports green while confining nothing. That is
# the exact false-pass this whole area keeps producing, so it is checked
# rather than trusted.
set -e

if ! bwrap --unshare-user --unshare-pid --ro-bind / / --proc /proc --dev /dev \
      -- /bin/true 2>/dev/null; then
  echo "PREFLIGHT FAILED: bwrap cannot create a namespace here." >&2
  echo "" >&2
  echo "Run this image with --privileged. An unprivileged container" >&2
  echo "blocks unprivileged user namespaces, bwrap fails to launch, and" >&2
  echo "the escape tests then pass because nothing ran — not because" >&2
  echo "anything was confined." >&2
  exit 1
fi

echo "preflight ok: bwrap can create namespaces"
exec "$@"
