# Linux harness for exercising the sandbox on the platform production
# actually runs on.
#
# Why this exists: development happens on macOS, where seatbelt is
# exercised by real escape attempts. The bubblewrap backend had no
# equivalent and was shipping unverified — and Linux is production, so
# that was the wrong way round. This image runs the same escape tests
# against bwrap.
#
# It must be run --privileged. That is not a shortcut: an unprivileged
# container cannot create the user namespace bwrap needs, and bwrap then
# fails to start. A failed launch denies the write, which looks exactly
# like successful confinement — so without --privileged this harness
# reports false passes.
#
# The same restriction is why bwrap inside the app container is very
# likely not the production answer; see references/harness/PLAN.md.
FROM python:3.12-slim

RUN apt-get update -qq \
 && apt-get install -y -qq --no-install-recommends \
      bubblewrap git curl coreutils \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /engine
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --quiet --no-cache-dir -e '.[dev]'
COPY tests/ ./tests/
COPY docker/sandbox-preflight.sh /usr/local/bin/preflight
RUN chmod +x /usr/local/bin/preflight

# The preflight refuses to run when bwrap cannot create a namespace,
# because in that state the escape tests pass for the wrong reason.
ENTRYPOINT ["/usr/local/bin/preflight"]

# Default to the suites that are platform-dependent. The rest of the
# engine suite is platform-neutral and runs on the host.
CMD ["python", "-m", "pytest", "-q", \
     "tests/test_sandbox.py", "tests/test_sandbox_runner.py", \
     "tests/test_workspace.py", "tests/test_workspace_output.py", \
     "tests/test_workspace_snapshot.py", \
     "tests/test_command_safety.py", "tests/test_code_eval.py", \
     "tests/test_sandbox_landlock.py", \
     "tests/test_code_evolve.py"]
