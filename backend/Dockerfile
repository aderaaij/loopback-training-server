# Build context is the REPO ROOT (see docker-compose.yml) so this image can
# bake in the React dashboard from ../frontend alongside the backend.

# --platform=$BUILDPLATFORM: the frontend output is static files, so this stage
# always runs on the build host's native arch (no QEMU emulation of npm when
# cross-building the multi-arch image in CI).
FROM --platform=$BUILDPLATFORM node:22-slim AS frontend
WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build

FROM python:3.13-slim AS builder

RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential libpq-dev && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

ENV VIRTUAL_ENV=/opt/venv
RUN uv venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

COPY backend/pyproject.toml backend/uv.lock ./
# Exactly what uv.lock pins, installed into /opt/venv. Resolving the pyproject
# ranges instead is how an upstream release (fastmcp 4.0) broke CI with no
# change here. --locked fails the build if the lock has drifted from
# pyproject. The app isn't installed as a package (and isn't copied yet),
# hence --no-install-project.
ENV UV_PROJECT_ENVIRONMENT=$VIRTUAL_ENV
RUN uv sync --locked --no-install-project --extra test

COPY backend/ .

FROM python:3.13-slim

# postgresql-client provides pg_dump for server-managed backups (app/backup.py).
# Trixie ships client 17, which dumps servers up to Postgres 17 — fine for the
# compose default of postgres:16.
RUN apt-get update && \
    apt-get install -y --no-install-recommends libpq5 postgresql-client && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app /app
COPY --from=frontend /fe/dist /app/static
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="/opt/venv/bin:$PATH"

EXPOSE 8001

CMD ["bash", "scripts/start.sh"]
