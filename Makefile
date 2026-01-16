# Makefile for Mintlify Download

.PHONY: help install dev-install lint lint-fix format check test clean

help: ## Show this help message
	@echo "Available commands:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-15s %s\n", $$1, $$2}'

install: ## Install production dependencies
	uv sync

dev-install: ## Install development dependencies
	uv sync --group dev

lint: ## Check for linting issues
	uv run ruff check .

lint-fix: ## Auto-fix linting issues
	uv run ruff check --fix .

format: ## Format code
	uv run ruff format .

check: ## Run linting and formatting checks
	uv run ruff check . && uv run ruff format --check .

test: ## Run tests (placeholder)
	@echo "No tests implemented yet"

clean: ## Clean up generated files
	rm -rf dist/
	rm -rf *.egg-info/
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

run: ## Run the CLI with example
	uv run mintlify-download --help