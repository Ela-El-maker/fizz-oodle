.PHONY: help up down build logs validate test lint frontend-install frontend-dev frontend-build

help:
	@echo "Available targets:"
	@echo "  up              Start full container stack"
	@echo "  down            Stop container stack"
	@echo "  build           Rebuild and start stack"
	@echo "  logs            Tail gateway logs"
	@echo "  validate        Validate YAML/JSON config contracts"
	@echo "  test            Run backend tests"
	@echo "  frontend-install Install frontend dependencies"
	@echo "  frontend-dev    Run frontend dev server"
	@echo "  frontend-build  Build frontend production bundle"

up:
	docker compose up -d

down:
	docker compose down

build:
	docker compose up -d --build

logs:
	docker compose logs -f gateway-service

validate:
	python scripts/validate_configs.py

test:
	pytest -q

frontend-install:
	cd dashboard && npm install

frontend-dev:
	cd dashboard && npm run dev

frontend-build:
	cd dashboard && npm run build
