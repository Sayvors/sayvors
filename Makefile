.PHONY: help api-dev api-migrate api-new-module

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

api-dev: ## Start API dev server (port 8000)
	cd services/api && uv run uvicorn app.main:app --reload --port 8000

api-migrate: ## Run alembic migrations
	cd services/api && uv run alembic upgrade head

api-new-module: ## Create new module (usage: make api-new-module name=notifications)
	cd services/api && powershell -ExecutionPolicy Bypass -File scripts/new-module.ps1 -Name $(name)
