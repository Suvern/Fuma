.PHONY: setup backend frontend worker scheduler infra-up infra-down infra-logs test-infra-up test-infra-down migrate idl idl-check lint test build check

DEV_COMPOSE = FUMA_DEV_UID=$$(id -u) FUMA_DEV_GID=$$(id -g) docker compose --env-file /dev/null -f deploy/compose.dev.yml

setup:
	uv sync --directory backend --locked
	pnpm --dir frontend install --frozen-lockfile

backend:
	$(DEV_COMPOSE) up -d --build --wait api

frontend:
	pnpm --dir frontend dev:local

worker:
	$(DEV_COMPOSE) up -d --build worker

scheduler:
	$(DEV_COMPOSE) up -d --build scheduler

infra-up:
	$(DEV_COMPOSE) up -d --build --wait

infra-down:
	$(DEV_COMPOSE) down

infra-logs:
	$(DEV_COMPOSE) logs -f --tail=100

test-infra-up:
	docker compose --env-file /dev/null -f deploy/compose.test.yml up -d --wait

test-infra-down:
	docker compose --env-file /dev/null -f deploy/compose.test.yml down

migrate:
	$(DEV_COMPOSE) run --rm migrate

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
	uv run --directory backend ruff check ../scripts
	uv run --directory backend ruff format --check .
	uv run --directory backend ruff format --check ../parser
	uv run --directory backend ruff format --check ../scripts
	pnpm --dir frontend lint

test:
	uv run --directory backend pytest
	pnpm --dir frontend test

build:
	uv build --directory backend
	pnpm --dir frontend build
	uv run --directory backend python ../scripts/check_release_artifacts.py

check: idl-check lint test build
