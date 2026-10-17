UV ?= $(if $(wildcard .venv/bin/uv),.venv/bin/uv,uv)

.PHONY: setup dev-api dev-web contracts check build

setup:
	$(UV) sync --locked --inexact
	npm --prefix apps/web ci

dev-api:
	$(UV) run --no-sync uvicorn fullfill.main:create_app --factory --reload --host 127.0.0.1 --port 8000

dev-web:
	npm --prefix apps/web run dev

contracts:
	$(UV) run --no-sync python scripts/export_contracts.py
	npm --prefix apps/web run generate:contracts

check:
	$(UV) run --no-sync ruff check apps/api apps/capture packages/contracts scripts
	$(UV) run --no-sync ruff format --check apps/api apps/capture packages/contracts scripts
	$(UV) run --no-sync python -m compileall -q apps/api/fullfill apps/capture/fullfill_capture packages/contracts/fullfill_contracts scripts
	$(MAKE) contracts
	git diff --exit-code -- packages/contracts/generated apps/web/src/api/generated
	npm --prefix apps/web run build

build:
	npm --prefix apps/web run build
