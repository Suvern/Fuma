.PHONY: setup backend frontend worker scheduler infra-up infra-down migrate idl idl-check lint test build check

setup:
	uv sync --directory backend --locked
	pnpm --dir frontend install --frozen-lockfile

backend:
	uv run --directory backend uvicorn app.main:app --reload --host 127.0.0.1 --port 8000 --no-access-log

frontend:
	pnpm --dir frontend dev:local

worker:
	uv run --directory backend celery -A app.workers.celery_app:celery_app worker -Q general,files --loglevel=INFO

scheduler:
	uv run --directory backend python -m app.workers.scheduler

infra-up:
	docker compose --env-file /dev/null -f deploy/compose.dev.yml up -d --wait

infra-down:
	docker compose --env-file /dev/null -f deploy/compose.dev.yml down

migrate:
	uv run --directory backend alembic upgrade head

idl:
	uv run --directory backend python -m app.cli.export_openapi
	uv run --directory backend python -m app.cli.generate_contract_models
	pnpm --dir frontend generate:api

idl-check:
	uv run --directory backend python -m app.cli.export_openapi --check
	uv run --directory backend python -m app.cli.generate_contract_models --check
	pnpm --dir frontend check:api

lint:
	uv run --directory backend ruff check .
	uv run --directory backend ruff check ../parser
	uv run --directory backend ruff format --check .
	uv run --directory backend ruff format --check ../parser
	pnpm --dir frontend lint

test:
	uv run --directory backend pytest
	pnpm --dir frontend test

build:
	uv build --directory backend
	pnpm --dir frontend build

check: idl-check lint test build
