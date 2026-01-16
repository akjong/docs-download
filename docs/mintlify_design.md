# Mintlify Documentation Scraper - Design Document

## Overview

This is a tool for scraping Mintlify documentation websites. Mintlify documentation sites have the characteristic that adding `.md` or `.mdx` suffix to the URL can directly obtain the Markdown source code. This tool utilizes this feature to automatically discover and download all documentation pages.

## Core Features

- **Automatic URL Discovery**: Starting from base_url, automatically crawl all subpage links
- **Intelligent Source Acquisition**: Automatically try `.mdx` and `.md` suffixes to obtain source code
- **Directory Structure Preservation**: Local file structure matches URL paths
- **Forced Suffix Conversion**: Optional conversion of all `.mdx` files to `.md`
- **High Concurrency Download**: Use asyncio for efficient asynchronous downloads
- **Incremental Download**: Support skipping existing files

## Architecture Design

### Module Structure

```
mintlify_download/
├── __init__.py
├── scraper.py      # Core crawler logic
├── downloader.py   # File downloader
├── utils.py        # Utility functions
└── cli.py          # Command-line entry point
```

### Core Components

#### 1. URL Discoverer (Crawler)

**Responsibilities**: Recursively discover all documentation pages starting from the initial URL

**Strategy**:
1. Parse `<a>` tags in HTML pages
2. Filter and retain links belonging to base_url subpaths
3. Use Set for deduplication, Queue for managing pending URLs
4. Support obtaining page lists from sitemap.xml and mint.json (alternative solutions)

**Key Improvements**:
- Prioritize parsing `mint.json` configuration file to obtain complete page list
- Support sitemap.xml as alternative discovery mechanism
- Intelligent filtering of non-documentation links (external links, anchor links, etc.)

#### 2. Source Downloader (Downloader)

**Responsibilities**: Obtain Markdown/MDX source code and save locally

**Detection Strategy**:
1. First try `{url}.mdx`
2. If failed, try `{url}.md`
3. Verify response content is valid Markdown (not HTML error page)

**Path Mapping Rules**:
- `https://docs.site.com/api/users` → `./output/api/users.md`
- `https://docs.site.com/guide/` → `./output/guide/index.md`
- `https://docs.site.com/` → `./output/index.md`

#### 3. File Saver (File Saver)

**Responsibilities**: Write downloaded content to local file system

**Features**:
- Automatically create directory structure
- Support forced suffix conversion (`.mdx` → `.md`)
- Support incremental mode (skip existing files)

### Data Flow

```
┌─────────────┐
│  base_url   │
└──────┬──────┘
       │
       ▼
┌─────────────────┐     ┌─────────────────┐
│  mint.json or   │────▶│   URL Queue     │
│  HTML Crawler   │     │   (asyncio)     │
└─────────────────┘     └────────┬────────┘
                                 │
                    ┌────────────┼────────────┐
                    ▼            ▼            ▼
              ┌──────────┐┌──────────┐┌──────────┐
              │ Worker 1 ││ Worker 2 ││ Worker N │
              └────┬─────┘└────┬─────┘└────┬─────┘
                   │           │           │
                   ▼           ▼           ▼
              ┌─────────────────────────────────┐
              │       Try .mdx / .md            │
              │       Download & Save           │
              └─────────────────────────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │    Local File System    │
                    │    (Preserve Structure) │
                    └─────────────────────────┘
```

## Technology Stack

- **Python 3.10+**
- **httpx**: Modern asynchronous HTTP client (more concise than aiohttp)
- **BeautifulSoup4**: HTML parsing
- **rich**: Beautiful terminal output and progress bars
- **click**: Command-line argument parsing

## Usage

### Basic Usage

```bash
# Download documentation to default directory
mintlify-download https://docs.example.com/

# Specify output directory
mintlify-download https://docs.example.com/ -o ./my-docs

# Force saving as .md suffix
mintlify-download https://docs.example.com/ --force-md

# Set concurrency
mintlify-download https://docs.example.com/ --concurrency 20

# Incremental download (skip existing files)
mintlify-download https://docs.example.com/ --skip-existing
```

### Command-line Parameters

| Parameter | Short | Description | Default |
|-----------|-------|-------------|---------|
| `url` | - | Base URL of Mintlify documentation | (required) |
| `--output` | `-o` | Output directory | `./downloaded_docs` |
| `--force-md` | `-f` | Force saving as .md suffix | `False` |
| `--concurrency` | `-c` | Number of concurrent downloads | `10` |
| `--skip-existing` | `-s` | Skip existing files | `False` |
| `--verbose` | `-v` | Verbose logging output | `False` |

## Notes

### Mintlify Features

1. **mint.json**: Mintlify sites usually have a `mint.json` configuration file containing complete navigation structure
2. **Source Access**: Add `.md` or `.mdx` after page URL to obtain source code
3. **Static Resources**: Images and other resources are usually in `/images/` or CDN

### Known Limitations

1. **SPA Rendering**: If site is completely client-side rendered, HTML crawler may not discover all links
2. **Anti-crawling Mechanisms**: Some sites may have rate limits, need to appropriately reduce concurrency
3. **Dynamic Content**: Some pages may contain dynamically generated content that cannot be fully obtained

### Best Practices

1. First visit target site to confirm support for `.md`/`.mdx` suffix access
2. Start from specific documentation root directory to avoid crawling irrelevant pages
3. Use appropriate concurrency (recommended 5-20)
4. For large sites, use incremental mode for batch downloads

## Examples

### Download Orderly Network Documentation

```bash
mintlify-download https://orderly.network/docs/build-on-omnichain -o ./orderly-docs --force-md
```

### Download Structure Example

```
orderly-docs/
├── build-on-omnichain/
│   ├── index.md
│   ├── getting-started/
│   │   ├── overview.md
│   │   └── quickstart.md
│   ├── api/
│   │   ├── rest-api.md
│   │   └── websocket.md
│   └── ...
```

