# Agent Guidelines for docs-download

Coding guidelines for agentic coding assistants working on the docs-download project.

## Project Overview

A Python CLI tool that scrapes documentation from Mintlify, GitBook, MkDocs, and ReadMe sites to local Markdown files. Uses asyncio for concurrent downloads.

## Build/Lint/Test Commands

### Development Setup

```bash
# Install all dependencies (production + dev)
make dev-install
# or
uv sync --group dev

# Install only production dependencies
make install
# or
uv sync
```

### Code Quality

```bash
# Check for linting issues
make lint                   # or: uv run ruff check .

# Auto-fix linting issues
make lint-fix               # or: uv run ruff check --fix .

# Format code
make format                 # or: uv run ruff format .

# Run comprehensive checks
make check                  # or: uv run ruff check . && uv run ruff format --check .
```

### Testing

```bash
# Run all tests
uv run python -m pytest tests/ -v

# Run a single test file
uv run python -m pytest tests/test_scraper.py -v

# Run a specific test function
uv run python -m pytest tests/test_scraper.py::test_function_name -v

# Run tests matching a pattern
uv run python -m pytest tests/ -v -k "test_name_pattern"
```

### Running the Application

```bash
# Show help for all commands
uv run mintlify-download --help
uv run gitbook-download --help
uv run mkdocs-download --help
uv run readme-download --help

# Example runs
uv run mintlify-download https://docs.example.com/ --output ./docs --verbose
uv run gitbook-download https://docs.example.com/ --concurrency 5 --skip-existing
```

## Code Style Guidelines

### Python Configuration

- **Python**: 3.10+ required
- **Package Manager**: uv (preferred)
- **Line Length**: 100 characters
- **Quote Style**: Double quotes for strings
- **Indent**: 4 spaces

### Import Organization

Group imports with blank lines between:

1. Standard library (alphabetized)
2. Third-party packages (alphabetized)
3. Local imports (alphabetized)

```python
import asyncio
import os
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import click
import httpx
from bs4 import BeautifulSoup
from rich.console import Console

from mintlify_download.scraper import MintlifyScraper, ScraperConfig
```

### Naming Conventions

- **Classes**: PascalCase (`MintlifyScraper`, `ScraperConfig`)
- **Functions/Methods**: snake_case (`download_file`)
- **Variables**: snake_case (`base_url`)
- **Private methods**: Leading underscore (`_normalize_url`)
- **Constants**: UPPER_SNAKE_CASE (`DEFAULT_TIMEOUT`)

### Type Hints

- Use type hints for all function parameters and return values
- Use `dataclasses` for configuration and data structures
- Use `|` union syntax (Python 3.10+) instead of `Optional` or `Union`

```python
@dataclass
class ScraperConfig:
    base_url: str
    output_dir: str = "./downloaded_docs"
    concurrency: int = 10
    timeout: float = 30.0

async def _download(self, url: str) -> tuple[bytes, str] | None:
    ...
```

### Error Handling

```python
try:
    result = await self._download(url)
except httpx.HTTPError as e:
    console.print(f"[red]HTTP error: {e}[/red]")
    raise ScrapingError(f"Failed to download {url}") from e
```

### Async/Await Patterns

```python
async def _worker(self, client: httpx.AsyncClient) -> None:
    while True:
        try:
            url = await asyncio.wait_for(self.urls_to_visit.get(), timeout=5.0)
        except asyncio.TimeoutError:
            break
        async with self.semaphore:
            await self._process_url(client, url)
```

### Docstrings

Use triple-quoted docstrings for all public functions, classes, and modules. Keep docstrings concise but descriptive.

### CLI Interface

- Use Click for CLI
- Provide sensible defaults for all options
- Include help text for all options
- Use Rich for console output
- Handle `KeyboardInterrupt` for graceful shutdown

### File Structure

- Packages: `mintlify_download`, `gitbook_download`, `mkdocs_download`, `readme_download`
- Each package: `__init__.py`, `cli.py`, `scraper.py`, `py.typed`
- Use relative imports within packages

### Linting Rules (Ruff)

Enabled: E, W, F, I, B, C4, UP
Ignored: E501 (line length), B008 (function calls in defaults), C901 (complexity)

## Development Workflow

1. **Before coding**: Run `make check` for clean starting point
2. **During development**: Run `make lint-fix && make format` frequently
3. **Before commit**: Run `make check` to verify code quality
4. **Add tests**: Include tests for new functionality

## Architecture Patterns

### Scraper Classes

- Separate configuration from implementation using dataclasses
- Use composition over inheritance
- Keep scrapers focused on single responsibility

### Data Flow

1. Parse and validate configuration
2. Discover URLs (mint.json, HTML parsing)
3. Filter and deduplicate URLs
4. Download content concurrently
5. Process images and update references
6. Validate and save files
7. Report statistics

### Security

- Validate URLs to prevent directory traversal
- Sanitize and normalize file paths
- Use appropriate timeouts
- Never log sensitive data
