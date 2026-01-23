# Agent Guidelines for docs-download

This document provides coding guidelines and development commands for agentic coding assistants working on the docs-download project.

## Project Overview

docs-download is a Python CLI tool that scrapes and downloads documentation from Mintlify, GitBook, and MkDocs sites to local Markdown files. It uses asyncio for concurrent downloads and preserves directory structure.

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
make lint
# or
uv run ruff check .

# Auto-fix linting issues
make lint-fix
# or
uv run ruff check --fix .

# Format code
make format
# or
uv run ruff format .

# Run comprehensive checks
make check
# or
uv run ruff check . && uv run ruff format --check .
```

### Testing

```bash
# Run all tests
make test
# or
uv run python -m pytest tests/ -v

# Run specific test file
uv run python -m pytest tests/test_scraper.py -v

# Run specific test function
uv run python -m pytest tests/test_scraper.py::TestMintlifyScraper::test_download_file -v

# Run tests with coverage
uv run python -m pytest tests/ --cov=src/ --cov-report=html
```

### Running the Application

```bash
# Show help for all commands
uv run mintlify-download --help
uv run gitbook-download --help
uv run mkdocs-download --help

# Example runs
uv run mintlify-download https://docs.example.com/ --output ./docs --verbose
uv run gitbook-download https://docs.example.com/ --concurrency 5 --skip-existing
```

## Code Style Guidelines

### Python Version & Dependencies

- **Python**: 3.10+ required
- **Package Manager**: uv (preferred) or pip
- **Dependencies**: httpx[socks], beautifulsoup4, rich, click
- **Dev Dependencies**: ruff, pytest, mypy (planned)

### Import Organization

- Standard library imports first (alphabetized)
- Third-party imports second (alphabetized)
- Local imports third (alphabetized)

### Naming Conventions

- **Classes**: PascalCase (e.g., `MintlifyScraper`)
- **Functions/Methods**: snake_case (e.g., `download_file`)
- **Variables**: snake_case (e.g., `base_url`)
- **Private methods**: Leading underscore (e.g., `_normalize_url`)

### Type Hints

- Use type hints for all function parameters and return values
- Use `dataclasses` for configuration and data structures
- Include type hints for complex data structures and async functions

```python
@dataclass
class ScraperConfig:
    base_url: str
    output_dir: str = "./downloaded_docs"
    concurrency: int = 10
    timeout: float = 30.0
```

### Error Handling

- Use try/except blocks for expected errors
- Handle `KeyboardInterrupt` specially for graceful shutdown
- Use Rich console for user-facing error messages with colors
- Re-raise exceptions with `from` for proper traceback

### Async/Await Patterns

- Use asyncio for all I/O operations
- Use asyncio.Semaphore for concurrency control
- Use asyncio.Queue for work distribution

```python
async def _download_with_semaphore(self, client: httpx.AsyncClient, url: str) -> bytes:
    async with self.semaphore:
        async with client.get(url, timeout=self.config.timeout) as response:
            response.raise_for_status()
            return await response.aread()
```

### Docstrings

- Use triple-quoted docstrings for all public functions, classes, and modules
- Follow Google-style docstring format
- Include parameter descriptions, return types, and examples

### CLI Interface

- Use Click for command-line interfaces
- Provide sensible defaults for all options
- Include comprehensive help text for all options
- Use Rich for console output and progress bars

### File Structure

- Organize code into packages: `mintlify_download`, `gitbook_download`, `mkdocs_download`
- Each package should have: `__init__.py`, `cli.py`, `scraper.py`, `py.typed`
- Use relative imports within packages
- Keep CLI entry points separate from core logic

### Security Considerations

- Validate URLs to prevent directory traversal attacks
- Sanitize file paths and normalize them
- Use appropriate timeouts to prevent hanging

## Development Workflow

1. **Before coding**: Run `make check` to ensure clean starting point
2. **During development**: Use `make lint-fix` and `make format` frequently
3. **Before commit**: Run `make check` and ensure all tests pass
4. **Testing**: Add comprehensive tests for new functionality

## Architecture Patterns

### Scraper Classes

- Separate configuration from implementation using dataclasses
- Use composition over inheritance
- Keep scrapers focused on single responsibility (Mintlify vs GitBook vs MkDocs)

### Async Patterns

- Use asyncio.Queue for work distribution
- Use asyncio.Semaphore for rate limiting
- Use asyncio.gather for concurrent operations

### Data Flow

1. Parse and validate configuration
2. Discover URLs from starting point (mint.json, HTML parsing)
3. Filter and deduplicate URLs
4. Download content concurrently with proper error handling
5. Process images and update references
6. Validate and save files with correct extensions
7. Report comprehensive statistics</content>
<parameter name="filePath">AGENTS.md
