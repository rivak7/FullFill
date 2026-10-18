UV ?= $(if $(wildcard .venv/bin/uv),.venv/bin/uv,uv)

.PHONY: setup dev-api dev-web dev-order dev-fulfill contracts check build

setup:
	$(UV) sync --locked --inexact
	npm --prefix apps/web ci

dev-api:
	$(UV) run --no-sync uvicorn fullfill.main:create_app --factory --reload $(if $(wildcard .env),--env-file .env,) --host 127.0.0.1 --port 8000

dev-web:
	npm --prefix apps/web run dev

dev-order:
	npm --prefix apps/web run dev:order

dev-fulfill:
	npm --prefix apps/web run dev:fulfill

contracts:
	$(UV) run --no-sync python scripts/export_contracts.py
	npm --prefix apps/web run generate:contracts

check:
	$(UV) run --no-sync ruff check app.py apps/api apps/capture packages/contracts scripts tests
	$(UV) run --no-sync ruff format --check app.py apps/api apps/capture packages/contracts scripts tests
	$(UV) run --no-sync python -m compileall -q app.py apps/api/fullfill apps/capture/fullfill_capture packages/contracts/fullfill_contracts scripts
	$(UV) run --no-sync pytest -q tests
	$(MAKE) contracts
	git diff --exit-code -- packages/contracts/generated apps/web/src/api/generated
	npm --prefix apps/web run build
	VITE_API_BASE_URL=https://api.example.invalid npm --prefix apps/web run build:order
	VITE_API_BASE_URL=https://api.example.invalid npm --prefix apps/web run build:fulfill

build:
	npm --prefix apps/web run build
