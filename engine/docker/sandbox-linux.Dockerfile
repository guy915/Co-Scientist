# Production bubblewrap differs from macOS seatbelt and needs Linux escape coverage.
# Privileged namespace preflight avoids false-green denials when no sandbox can launch.
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

# Abort before escape tests when bubblewrap cannot create a namespace.
ENTRYPOINT ["/usr/local/bin/preflight"]

CMD ["python", "-m", "pytest", "-q", \
     "tests/test_sandbox.py", "tests/test_sandbox_runner.py", \
     "tests/test_workspace.py", "tests/test_workspace_output.py", \
     "tests/test_workspace_snapshot.py", \
     "tests/test_command_safety.py", \
     "tests/test_sandbox_landlock.py"]
