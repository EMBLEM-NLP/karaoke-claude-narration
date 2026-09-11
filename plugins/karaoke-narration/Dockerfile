# karaoke-narration MCP server — deployable container
#
# Builds the auth-wrapped HTTP server (server_http_authed.py), not the bare
# mcp/server.py, because the bare one has no auth layer and SECURITY.md is
# explicit that it needs one before going public.
#
# Build:  docker build -t karaoke-mcp .
# Run:    docker run -p 8787:8787 -e KARAOKE_MCP_TOKEN=<secret> karaoke-mcp
#
# Then point a tunnel or your host's public URL at container port 8787,
# and add https://<that-host>/mcp as a custom connector (see DEPLOY.md).

FROM python:3.12-slim

# ffmpeg/ffprobe: required by build_karaoke.py for mastering/QC, not bundled
# by any pip package - confirmed missing from python:3.12-slim by default.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app

# Pinned per DEPLOY_NOTES.md: mcp[cli] unpinned resolves to 2.0.0, which
# renamed FastMCP -> MCPServer and broke this plugin's import. Verified
# working at 1.29.0 in a live test session before this Dockerfile was written.
RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 8787

# No default for KARAOKE_MCP_TOKEN on purpose - server_http_authed.py exits
# non-zero immediately if it's unset, rather than starting unauthenticated.
# Fail loud at container start, not silently at request time.
CMD ["python3", "mcp/server_http_authed.py", "--host", "0.0.0.0", "--port", "8787"]
