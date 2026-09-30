# Documentation Scraper

A powerful tool to scrape and download documentation sites (Mintlify, GitBook, MkDocs, ReadMe.com, Docusaurus, Stoplight, and more) to local Markdown files. This tool automatically discovers all documentation pages and downloads their source code while preserving the directory structure.

## Features

- **� Automatic URL Discovery**: Starts from a base URL and recursively crawls all documentation pages
- **📁 Structure Preservation**: Maintains the exact directory structure from the website
- **⚡ High Performance**: Asynchronous downloads with configurable concurrency
- **� Smart Source Detection**: Automatically tries `.mdx` and `.md` suffixes to get source code (Mintlify), or parses HTML for GitBook, MkDocs, ReadMe.com, and others
- **� Flexible Output**: Force all files to `.md` extension or keep original extensions
- **📈 Incremental Downloads**: Skip existing files to resume interrupted downloads
- **🛡️ Content Validation**: Verifies downloaded content is valid Markdown (not HTML error pages)
- **🌐 Proxy Support**: Works with system proxy settings (HTTP, HTTPS, SOCKS)
- **📊 Rich Progress**: Beautiful progress bars and detailed statistics
- **🖥️ SPA Support**: Uses Playwright for JavaScript-rendered documentation sites (Bitget, Docusaurus, Stoplight)

## Supported Platforms

| Platform | Command | Discovery Method |
|----------|---------|-----------------|
| Mintlify | `mintlify-download` | mint.json / sitemap / HTML crawling |
| GitBook | `gitbook-download` | sitemap / HTML navigation |
| MkDocs | `mkdocs-download` | sitemap / HTML navigation |
| ReadMe.com | `readme-download` | Recursive navigation crawling |
| Docusaurus | `docusaurus-download` | sitemap + Playwright rendering |
| Stoplight | `stoplight-download` | sitemap + Playwright rendering |
| Nextra / Webshare | `webshare-download` | HTML crawling + html2text |
| Arc Blog | `arc-blog-download` | JSON-LD + HTML parsing |
| Circle OpenAPI | `circle-openapi-download` | OpenAPI JSON manifest |
| CoinW | `coinw-download` | sitemap + markdownify |
| HTX | `htx-download` | API category tree + endpoint details |
| Bitget | `bitget-download` | Playwright sidebar expansion |
| PancakeSwap | `pancakeswap-download` | Vocs framework sidebar extraction |

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

# All CLI commands are now available
```

### Install with pip

```bash
# Clone the repository
git clone https://github.com/akjong/docs-download.git
cd docs-download

# Install the package in editable mode
pip install -e .
```

### Verify Installation

```bash
mintlify-download --help
gitbook-download --help
mkdocs-download --help
readme-download --help
stoplight-download --help
docusaurus-download --help
webshare-download --help
arc-blog-download --help
circle-openapi-download --help
coinw-download --help
htx-download --help
bitget-download --help
pancakeswap-download --help
```

## Usage

### Mintlify Documentation

```bash
# Download with force .md conversion and verbose output
uv run mintlify-download https://orderly.network/docs/build-on-omnichain \
  --output ./orderly-docs \
  --force-md \
  --verbose

# Skip existing files to resume download
uv run mintlify-download https://docs.example.com/ --output ./docs --skip-existing

# Use more workers for faster download
uv run mintlify-download https://docs.example.com/ --concurrency 20 --output ./fast-download
```

**Options:**

| Parameter | Short | Description | Default |
|-----------|-------|-------------|---------|
| `url` | - | **Required.** Base URL of the Mintlify documentation site | - |
| `--output` | `-o` | Output directory for downloaded files | `./downloaded_docs` |
| `--force-md` | `-f` | Force all files to be saved with `.md` extension | `False` |
| `--concurrency` | `-c` | Number of concurrent download workers | `10` |
| `--skip-existing` | `-s` | Skip downloading files that already exist | `False` |
| `--verbose` | `-v` | Enable verbose logging output | `False` |

### GitBook Documentation

```bash
# Download with verbose output
uv run gitbook-download https://hyperliquid.gitbook.io/hyperliquid-docs \
  --output ./hyperliquid-docs --verbose

# Skip existing files to resume download
uv run gitbook-download https://docs.example.com/ --output ./docs --skip-existing
```

**Options:**

| Parameter | Short | Description | Default |
|-----------|-------|-------------|---------|
| `url` | - | **Required.** Base URL of the GitBook documentation site | - |
| `--output` | `-o` | Output directory for downloaded files | `./downloaded_docs` |
| `--concurrency` | `-c` | Number of concurrent download workers | `5` |
| `--skip-existing` | `-s` | Skip downloading files that already exist | `False` |
| `--verbose` | `-v` | Enable verbose logging output | `False` |

### MkDocs Documentation

```bash
# Download MkDocs Material documentation
uv run mkdocs-download https://squidfunk.github.io/mkdocs-material/ \
  --output ./mkdocs-docs --verbose

# Download custom MkDocs site
uv run mkdocs-download https://docs.example.com/guide -o ./my-docs
```

**Options:** Same as GitBook (without `--force-md`).

### ReadMe.com Documentation

```bash
# Download API reference documentation
uv run readme-download https://developer.rise.trade/reference/ \
  --output ./rises-api --verbose
```

**Options:** Same as GitBook.

### Docusaurus Documentation

```bash
# Download Docusaurus-based documentation (uses Playwright for SPA rendering)
uv run docusaurus-download https://docs.example.com/ --output ./docs
```

**Options:** Same as GitBook.

### Stoplight Documentation

```bash
# Download Stoplight documentation (uses Playwright for SPA rendering)
uv run stoplight-download https://docs.stoplight.io/docs/prism/ --output ./prism-docs
```

**Options:** Same as GitBook, but concurrency defaults to `10`.

### Webshare / Nextra Documentation

```bash
# Download Nextra-based documentation
uv run webshare-download https://apidocs.webshare.io/ --output ./webshare-docs
```

**Options:** Same as GitBook, but concurrency defaults to `10`.

### Arc Blog

```bash
# Download all Arc blog articles
uv run arc-blog-download --output ./arc-blog --verbose

# Custom blog URL
uv run arc-blog-download --base-url https://www.arc.network/blog -o ./arc-blog
```

**Options:**

| Parameter | Short | Description | Default |
|-----------|-------|-------------|---------|
| `--base-url` | `-u` | Base URL of the Arc blog | `https://www.arc.network/blog` |
| `--output` | `-o` | Output directory | `arc/blog` |
| `--verbose` | `-v` | Enable verbose output | `False` |

### Circle OpenAPI

```bash
# Download Circle OpenAPI files
uv run circle-openapi-download --output ./circle-openapi
```

**Options:**

| Parameter | Description | Default |
|-----------|-------------|---------|
| `--url` | URL to openapi.json | `https://developers.circle.com/openapi.json` |
| `--output` | Output directory | `./circle-openapi` |
| `--base-url` | Base URL for downloading OpenAPI files | `https://developers.circle.com/openapi` |
| `--skip-existing` | Skip products that already exist | `False` |

### CoinW API Documentation

```bash
# Download CoinW API docs
uv run coinw-download https://www.coinw.com/api-doc/en/common/introduction \
  --output ./coinw-docs -c 10
```

**Options:**

| Parameter | Short | Description | Default |
|-----------|-------|-------------|---------|
| `url` | - | **Required.** Base URL of CoinW API docs | - |
| `--output` | `-o` | Output directory | `./downloaded_docs` |
| `--concurrency` | `-c` | Number of concurrent downloads | `5` |
| `--skip-existing` | `-s` | Skip existing files | `False` |
| `--verbose` | `-v` | Enable verbose output | `False` |

### HTX API Documentation

```bash
# Download HTX API docs (fetches category tree from HTX API)
uv run htx-download --output ./htx-docs
```

**Options:**

| Parameter | Short | Description | Default |
|-----------|-------|-------------|---------|
| `--output` | `-o` | Output directory | `./htx/docs` |
| `--concurrency` | `-c` | Number of concurrent downloads | `5` |
| `--skip-existing` | `-s` | Skip existing files | `False` |
| `--verbose` | `-v` | Enable verbose output | `False` |

### Bitget API Documentation

```bash
# Download Bitget API docs (uses Playwright for sidebar discovery)
uv run bitget-download https://www.bitget.com/api-doc/uta -o ./bitget

# Download contract API docs
uv run bitget-download https://www.bitget.com/api-doc/contract -o ./bitget-contract
```

**Options:**

| Parameter | Short | Description | Default |
|-----------|-------|-------------|---------|
| `url` | - | **Required.** Base URL of the documentation section | - |
| `--output` | `-o` | Output directory | `./downloaded_docs` |
| `--concurrency` | `-c` | Number of concurrent downloads | `10` |
| `--skip-existing` | `-s` | Skip existing files | `False` |
| `--verbose` | `-v` | Enable verbose output | `False` |

### PancakeSwap Infinity Documentation

```bash
# Download PancakeSwap Infinity docs (Vocs framework)
uv run pancakeswap-download --output ./pancakeswap-docs
```

**Options:**

| Parameter | Short | Description | Default |
|-----------|-------|-------------|---------|
| `--base-url` | `-u` | Base URL of PancakeSwap Infinity docs | `https://developer.pancakeswap.finance/contracts/infinity/overview` |
| `--output` | `-o` | Output directory | `./pancakeswap` |
| `--base-path` | `-p` | Base path to filter URLs (auto-detected) | `None` |
| `--verbose` | `-v` | Enable verbose output | `False` |

## How It Works

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

1. **Try Source Access**: For Mintlify, try `{url}.mdx` first, then `{url}.md`; for GitBook/MkDocs/ReadMe, parse HTML content
2. **Content Validation**: Check that the response contains valid content
3. **Path Mapping**: Convert URL path to local file path
4. **File Saving**: Write content to appropriate location with correct extension

### Concurrency Model

- **AsyncIO Queue**: Manages URLs to be processed
- **Semaphore**: Limits concurrent downloads to prevent overwhelming servers
- **Worker Pool**: Multiple async workers process URLs from the queue
- **Progress Tracking**: Real-time progress bars show download status

### Playwright-based Scraping

For SPA (Single Page Application) documentation sites like Bitget, Docusaurus, and Stoplight:

1. Launch headless Chromium browser
2. Expand sidebar navigation to discover all links
3. Navigate to each page and extract rendered HTML
4. Convert HTML to Markdown using html2text

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
- **beautifulsoup4**: HTML parsing and link extraction
- **rich**: Beautiful terminal UI and progress bars
- **click**: Command-line interface framework
- **playwright**: Headless browser for SPA documentation sites
- **markdownify / html2text**: HTML to Markdown conversion
- **uv**: Fast Python package manager

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

### Project Structure

```
src/
├── mintlify_download/      # Mintlify documentation scraper
├── gitbook_download/       # GitBook documentation scraper
├── mkdocs_download/        # MkDocs documentation scraper
├── readme_download/        # ReadMe.com documentation scraper
├── stoplight_download/     # Stoplight documentation scraper (Playwright)
├── docusaurus_download/    # Docusaurus documentation scraper (Playwright)
├── webshare_download/      # Nextra/Webshare documentation scraper
├── arc_blog_download/      # Arc blog scraper
├── circle_openapi_download/# Circle OpenAPI files downloader
├── coinw_download/         # CoinW API documentation scraper
├── htx_download/           # HTX API documentation scraper
├── bitget_download/        # Bitget API documentation scraper (Playwright)
├── pancakeswap_download/   # PancakeSwap Infinity docs scraper
├── docs_download/          # Core documentation utilities
├── download-gitbook/       # Legacy GitBook download script
└── download-lobehub/       # Legacy LobeHub blog download script
```

## Troubleshooting

### Common Issues

**"No source found" for some pages**
- Some pages might be dynamically generated or not have source files
- For SPA sites, try using the Playwright-based scrapers

**Rate limiting**
- Reduce `--concurrency` value
- CoinW and HTX scrapers have built-in rate-limit handling with retries

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

## License

MIT License - see LICENSE file for details.

## Author

Bob Liu (akagi201@gmail.com)
