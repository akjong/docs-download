# Documentation Scraper

A powerful tool to scrape and download documentation sites (Mintlify and GitBook) to local Markdown files. This tool automatically discovers all documentation pages and downloads their source code while preserving the directory structure.

## Features

- **🔍 Automatic URL Discovery**: Starts from a base URL and recursively crawls all documentation pages
- **📁 Structure Preservation**: Maintains the exact directory structure from the website
- **⚡ High Performance**: Asynchronous downloads with configurable concurrency
- **🔄 Smart Source Detection**: Automatically tries `.mdx` and `.md` suffixes to get source code (Mintlify), or parses HTML for GitBook
- **🎯 Flexible Output**: Force all files to `.md` extension or keep original extensions
- **📈 Incremental Downloads**: Skip existing files to resume interrupted downloads
- **🛡️ Content Validation**: Verifies downloaded content is valid Markdown (not HTML error pages)
- **🌐 Proxy Support**: Works with system proxy settings (HTTP, HTTPS, SOCKS)
- **📊 Rich Progress**: Beautiful progress bars and detailed statistics

## How It Works

Documentation sites like Mintlify and GitBook have features to access raw Markdown source. This tool leverages these features to:

1. **Discover Pages**: Parse HTML pages and configuration files to find all documentation links
2. **Download Sources**: For Mintlify, try `{url}.mdx` first, then `{url}.md` if that fails; for GitBook, parse HTML to extract content
3. **Validate Content**: Ensure downloaded content is actual Markdown, not HTML error pages
4. **Preserve Structure**: Map URL paths to local directory structure
5. **Handle Concurrency**: Use asyncio for efficient parallel downloads

## Installation

### Prerequisites

- Python 3.10 or higher
- uv package manager (recommended) or pip

### Install with uv (Recommended)

```bash
# Clone the repository
git clone https://github.com/akjong/docs-download.git
cd docs-download

# Install dependencies and the package
uv sync

# The commands mintlify-download and gitbook-download are now available system-wide
```

### Install with pip

```bash
# Clone the repository
git clone https://github.com/akjong/docs-download.git
cd docs-download

# Install the package in editable mode
pip install -e .

# The commands mintlify-download and gitbook-download are now available system-wide
```

### Verify Installation

After installation, verify the tools are available:

```bash
mintlify-download --help
gitbook-download --help
```

## Usage

### Mintlify Documentation

#### Basic Usage

```bash
# Download documentation to default directory
uv run mintlify-download https://docs.example.com/

# Or with pip
python -m mintlify_download.cli https://docs.example.com/
```

#### Command Line Options

| Parameter | Short | Description | Default | Example |
|-----------|-------|-------------|---------|---------|
| `url` | - | **Required.** Base URL of the Mintlify documentation site | - | `https://docs.example.com/guide/` |
| `--output` | `-o` | Output directory for downloaded files | `./downloaded_docs` | `-o ./my-docs` |
| `--force-md` | `-f` | Force all files to be saved with `.md` extension (converts `.mdx` to `.md`) | `False` | `--force-md` |
| `--concurrency` | `-c` | Number of concurrent download workers | `10` | `--concurrency 20` |
| `--skip-existing` | `-s` | Skip downloading files that already exist in output directory | `False` | `--skip-existing` |
| `--verbose` | `-v` | Enable verbose logging output | `False` | `--verbose` |

### GitBook Documentation

#### Basic Usage

```bash
# Download documentation to default directory
uv run gitbook-download https://docs.example.com/

# Or with pip
python -m gitbook_download.cli https://docs.example.com/
```

#### Command Line Options

| Parameter | Short | Description | Default | Example |
|-----------|-------|-------------|---------|---------|
| `url` | - | **Required.** Base URL of the GitBook documentation site | - | `https://docs.example.com/guide/` |
| `--output` | `-o` | Output directory for downloaded files | `./downloaded_docs` | `-o ./my-docs` |
| `--concurrency` | `-c` | Number of concurrent download workers | `5` | `--concurrency 10` |
| `--skip-existing` | `-s` | Skip downloading files that already exist in output directory | `False` | `--skip-existing` |
| `--verbose` | `-v` | Enable verbose logging output | `False` | `--verbose` |

### Parameter Explanations

#### `url` (Required)
The base URL of the Mintlify documentation site. This should be the root URL of the documentation section you want to download. The tool will automatically discover and download all pages under this path.

**Examples:**
- `https://docs.example.com/` - Downloads entire documentation
- `https://docs.example.com/api/` - Downloads only API documentation
- `https://orderly.network/docs/build-on-omnichain/` - Specific section

#### `--output` / `-o`
Directory where downloaded files will be saved. The tool creates this directory if it doesn't exist. The directory structure from the website URLs will be preserved under this path.

**Default:** `./downloaded_docs`

#### `--force-md` / `-f`
When enabled, all downloaded files (including `.mdx` files) will be saved with `.md` extension. This is useful if your Markdown editor or note-taking app doesn't support `.mdx` files.

**Default:** `False` (keeps original extensions)

#### `--concurrency` / `-c`
Number of concurrent download workers. Higher values download faster but may be rate-limited by the server. For large documentation sites, values between 5-20 are recommended.

**Default:** `10`

#### `--skip-existing` / `-s`
When enabled, skips downloading files that already exist in the output directory. This is useful for resuming interrupted downloads or updating documentation incrementally.

**Default:** `False`

#### `--verbose` / `-v`
Enables detailed logging output, showing which URLs are being processed, download successes/failures, and other debugging information.

**Default:** `False`

## Examples

### Download Mintlify Documentation

#### Download Orderly Network Documentation

```bash
# Download with force .md conversion and verbose output
uv run mintlify-download https://orderly.network/docs/build-on-omnichain \
  --output ./orderly-docs \
  --force-md \
  --verbose
```

#### Resume Interrupted Download

```bash
# Skip existing files to resume download
uv run mintlify-download https://docs.example.com/ \
  --output ./docs \
  --skip-existing
```

#### High-Speed Download

```bash
# Use more workers for faster download
uv run mintlify-download https://docs.example.com/ \
  --concurrency 20 \
  --output ./fast-download
```

### Download GitBook Documentation

#### Download Hyperliquid Documentation

```bash
# Download with verbose output
uv run gitbook-download https://hyperliquid.gitbook.io/hyperliquid-docs \
  --output ./hyperliquid-docs \
  --verbose
```

#### Resume Interrupted Download

```bash
# Skip existing files to resume download
uv run gitbook-download https://docs.example.com/ \
  --output ./docs \
  --skip-existing
```

## Project Logic

### URL Discovery Process

1. **Start with Base URL**: Add the provided base URL to the processing queue
2. **Parse Configuration/HTML**: Attempt to fetch and parse configuration files (mint.json for Mintlify) or HTML pages to find all documentation links
3. **Link Filtering**: Only keep links that:
   - Belong to the same domain
   - Are under the base URL path
   - Don't match excluded patterns (images, API routes, etc.)
4. **Deduplication**: Use a set to avoid processing the same URL multiple times

### Source Download Strategy

For each discovered URL, the tool:

1. **Try Source Access**: For Mintlify, try `{url}.mdx` first, then `{url}.md`; for GitBook, parse HTML content
2. **Content Validation**: Check that the response:
   - Has HTTP 200 status
   - Contains valid Markdown content (not HTML error pages)
   - Has appropriate content-type headers
3. **Path Mapping**: Convert URL path to local file path
4. **File Saving**: Write content to appropriate location with correct extension

### Concurrency Model

- **AsyncIO Queue**: Manages URLs to be processed
- **Semaphore**: Limits concurrent downloads to prevent overwhelming servers
- **Worker Pool**: Multiple async workers process URLs from the queue
- **Progress Tracking**: Real-time progress bars show download status

## Output Structure

The tool preserves the URL structure in the local filesystem:

```
# URL Structure
https://docs.example.com/
├── guide/
│   ├── getting-started.md
│   └── advanced/
│       └── configuration.md
└── api/
    ├── rest-api.md
    └── websocket.md

# Becomes Local Structure
./downloaded_docs/
├── guide/
│   ├── getting-started.md
│   └── advanced/
│       └── configuration.md
└── api/
    ├── rest-api.md
    └── websocket.md
```

## Technology Stack

- **Python 3.10+**: Modern Python with advanced async features
- **httpx[socks]**: Asynchronous HTTP client with proxy support
- **BeautifulSoup4**: HTML parsing and link extraction
- **rich**: Beautiful terminal UI and progress bars
- **click**: Command-line interface framework
- **uv**: Fast Python package manager

## Troubleshooting

### Common Issues

**"No source found" for some pages**
- Some pages might be dynamically generated or not have source files
- Check if the site supports `.md`/`.mdx` access by manually testing URLs

**Rate limiting**
- Reduce `--concurrency` value
- Add delays between requests (not currently implemented)

**Proxy issues**
- The tool automatically uses system proxy settings
- For SOCKS proxies, ensure `socksio` package is installed

**Large documentation sites**
- Use `--skip-existing` for resumable downloads
- Increase `--concurrency` for faster downloads (if allowed by server)

### Verbose Mode

Use `--verbose` flag to see detailed information about:
- URLs being discovered
- Download attempts and results
- Content validation decisions
- File saving operations

## Development

### Code Quality

This project uses [Ruff](https://github.com/astral-sh/ruff) for linting and formatting.

```bash
# Check for linting issues
uv run ruff check .

# Auto-fix linting issues
uv run ruff check --fix .

# Format code
uv run ruff format .

# Run both linting and formatting
uv run ruff check --fix . && uv run ruff format .
```

## License

MIT License - see LICENSE file for details.

## Author

Bob Liu (akagi201@gmail.com)</content>
<parameter name="filePath">/Users/akagi201/src/github.com/akjong/mintlify-download/README.md
