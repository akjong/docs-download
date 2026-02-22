# Justfile for docs-download

help:
    @echo "Available commands:"
    @just --list --unsorted

install:
    uv sync

dev-install:
    uv sync --group dev

lint:
    uv run ruff check .

lint-fix:
    uv run ruff check --fix .

format:
    uv run ruff format .

check:
    uv run ruff check . && uv run ruff format --check .

test:
    uv run python -m pytest tests/ -v

clean:
    rm -rf dist/
    rm -rf *.egg-info/
    find . -type d -name __pycache__ -exec rm -rf {} +
    find . -type f -name "*.pyc" -delete

run:
    uv run mintlify-download --help
