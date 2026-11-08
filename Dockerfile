# syntax=docker/dockerfile:1.7@sha256:a57df69d0ea827fb7266491f2813635de6f17269be881f696fbfdf2d83dda33e
FROM ghcr.io/astral-sh/uv:0.9.21@sha256:15f68a476b768083505fe1dbfcc998344d0135f0ca1b8465c4760b323904f05a AS uv
FROM python:3.13.18-alpine3.23@sha256:e4aeaca9081549f19bd5bc8605ed5ab257ba34f97e0471f8e09161f45b4b08b8 AS base
# sqlite-libs comes from Alpine edge until Alpine 3.23 ships a patched release.
RUN apk add --no-cache zlib=1.4-r0 musl=1.2.5-r24 musl-utils=1.2.5-r24 \
    && apk add --no-cache --repository=https://dl-cdn.alpinelinux.org/alpine/edge/main sqlite-libs=3.54.1-r0
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY pyproject.toml uv.lock ./
COPY LICENSE NOTICE.md README.md ./
COPY src ./src
COPY servers ./servers
RUN uv sync --frozen --no-dev
ENV PATH="/app/.venv/bin:$PATH"

FROM base AS test
RUN apk add --no-cache bash=5.3.3-r1 git=2.52.0-r0 procps-ng=4.0.5-r0
COPY tests ./tests
COPY scripts ./scripts
COPY docs ./docs
COPY .github ./.github
COPY README.md CONTRIBUTING.md server.json ./
COPY Dockerfile .dockerignore .gitignore CHANGELOG.md ./
RUN uv sync --frozen --group dev
CMD ["uv", "run", "--frozen", "--no-sync", "pytest", "tests", "-q"]

FROM base AS runtime
LABEL org.opencontainers.image.source="https://github.com/unibio-intelligence/biomedmcp" \
      org.opencontainers.image.licenses="Apache-2.0" \
      io.modelcontextprotocol.server.name="io.github.unibio-intelligence/biomedmcp"
RUN adduser -D -u 10001 ubi
USER ubi
ENV UBI_PROFILE=local UBI_LOCAL_CONTAINER=1 MCP_TRANSPORT=http FASTMCP_SERVER_HOST=0.0.0.0 FASTMCP_SERVER_PORT=8000
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/readyz',timeout=3)"
CMD ["biomedmcp-server", "--transport", "http"]
