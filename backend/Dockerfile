FROM python:3.13-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.12.7 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY backend/app ./app
COPY backend/alembic.ini ./
COPY backend/migrations ./migrations
RUN uv sync --locked --no-dev --no-editable

FROM python:3.13-slim AS runtime
ENV PATH="/app/backend/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app/backend
RUN groupadd --gid 10001 fuma && useradd --uid 10001 --gid fuma --no-create-home fuma \
    && mkdir -p /data/cache /data/state && chown fuma:fuma /data/cache /data/state \
    && chmod 700 /data/state
COPY --from=build /app/backend /app/backend
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--no-proxy-headers"]
