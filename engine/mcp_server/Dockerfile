# mcp server dockerfile (local/compose build from engine/)
#
# Sibling: repo-root Dockerfile.mcp (Railway). The two are deliberately
# divergent -- this one builds from engine/ and binds 0.0.0.0, while the
# Railway file builds from the repo root and binds IPv6 (`--host ::`) with an
# [::1] healthcheck for Railway's IPv6 private network. A change to the
# server install, bind host, or healthcheck here usually needs a mirrored
# change there.
# Pinned by digest so the same source always builds the same base
# image (N18) -- python:3.12-slim is a mutable tag that moves under
# it on rebuild. Update deliberately: `docker pull python:3.12-slim`
# then `docker inspect --format='{{index .RepoDigests 0}}' python:3.12-slim`.
FROM python:3.12-slim@sha256:646fb0bca3dd3ea1bcc6feb72c17ed16eed6e10cffc732fcc1478bd3e7f02d7b

# set working directory
WORKDIR /app

# install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# copy dependency files
COPY mcp_server/pyproject.toml ./mcp_server/

# The editable build maps the `mcp_server` package onto this directory
# (pyproject.toml's `package-dir`) and lists its subpackages explicitly, so
# setuptools' egg_info step needs those subpackage directories to exist even
# though their contents arrive in the source COPY below.
RUN mkdir -p ./mcp_server/tools/indra_cogex ./mcp_server/tools/lit_review \
    ./mcp_server/tools/web

# install python dependencies
RUN pip install --no-cache-dir -e ./mcp_server

# copy application code
COPY mcp_server/ ./mcp_server/

# expose port
EXPOSE 8888

# environment variables (can be overridden via docker compose or -e flags)
ENV COSCIENTIST_MCP_PORT=8888
ENV PYTHONUNBUFFERED=1

# health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8888', timeout=5.0)" || exit 1

# run server
CMD ["uvicorn", "mcp_server.server:app", "--host", "0.0.0.0", "--port", "8888"]
