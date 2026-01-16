# GitBook Documentation Scraper - Design Document

## Overview

This is a tool for scraping GitBook documentation websites. Unlike Mintlify which allows direct `.md`/`.mdx` access, GitBook renders content as HTML through a Single Page Application (SPA). This tool extracts content from GitBook pages, converts HTML to Markdown, and saves files while preserving the URL path structure.

## Core Features

- **Sitemap-based URL Discovery**: Uses GitBook's `sitemap.xml` and `sitemap-pages.xml` for reliable page discovery
- **HTML to Markdown Conversion**: Extracts main content from HTML and converts to clean Markdown
- **Directory Structure Preservation**: Local file structure matches URL paths
- **High Concurrency Download**: Uses asyncio for efficient asynchronous downloads
- **Incremental Download**: Support skipping existing files
- **Multiple Variant Support**: Handles GitBook's section variants (e.g., `/builder-tools/`, `/support/`)

## GitBook Characteristics

### URL Structure

GitBook documentation sites follow this pattern:
```
https://{org}.gitbook.io/{space-name}
https://{org}.gitbook.io/{space-name}/{section}/{page}
```

Examples:
- `https://hyperliquid.gitbook.io/hyperliquid-docs`
- `https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees`

### Sitemap Structure

GitBook provides structured sitemaps:
1. **Main Sitemap Index**: `{base_url}/sitemap.xml` - Contains links to section sitemaps
2. **Section Sitemaps**: `{base_url}/sitemap-pages.xml` - Contains actual page URLs

Example sitemap-pages.xml structure:
```xml
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://hyperliquid.gitbook.io/hyperliquid-docs</loc>
    <priority>1</priority>
    <lastmod>2025-03-09T08:12:07.658Z</lastmod>
  </url>
  ...
</urlset>
```

### Page Structure

GitBook pages have a consistent HTML structure:
- Main content is in `<main>` element
- Headings use standard `<h1>`, `<h2>`, `<h3>` tags
- Code blocks use `<pre><code>` tags
- Images use `<img>` tags with GitBook CDN URLs

## Architecture Design

### Module Structure

```
gitbook_download/
├── __init__.py
├── scraper.py      # Core scraper logic
└── cli.py          # Command-line entry point
```

### Core Components

#### 1. URL Discoverer

**Responsibilities**: Discover all documentation pages via sitemaps

**Strategy**:
1. Fetch main `sitemap.xml` to get all sitemap index URLs
2. Parse each `sitemap-pages.xml` to extract page URLs
3. Filter URLs to only include those under base_url
4. Fallback to HTML link crawling if sitemap is unavailable

#### 2. Content Extractor

**Responsibilities**: Extract main content from HTML pages

**Strategy**:
1. Fetch HTML page
2. Parse with BeautifulSoup
3. Extract `<main>` content section
4. Remove navigation, sidebar, and footer elements
5. Extract page title from `<h1>` or `<title>`

#### 3. HTML to Markdown Converter

**Responsibilities**: Convert extracted HTML to clean Markdown

**Conversion Rules**:
- `<h1>` → `# Heading`
- `<h2>` → `## Heading`
- `<h3>` → `### Heading`
- `<p>` → Plain text with blank lines
- `<a>` → `[text](url)` (convert relative URLs to absolute)
- `<code>` → `` `code` ``
- `<pre><code>` → Fenced code blocks with language detection
- `<ul>/<ol>` → Markdown lists
- `<img>` → `![alt](src)`
- `<table>` → Markdown tables
- `<strong>/<b>` → `**bold**`
- `<em>/<i>` → `*italic*`

#### 4. File Saver

**Responsibilities**: Save Markdown files with proper directory structure

**Path Mapping Rules**:
- `https://org.gitbook.io/docs/api/users` → `./output/api/users.md`
- `https://org.gitbook.io/docs/guide/` → `./output/guide.md`
- `https://org.gitbook.io/docs/` → `./output/index.md`

### Data Flow

```
┌─────────────┐
│  base_url   │
└──────┬──────┘
       │
       ▼
┌─────────────────┐     ┌─────────────────┐
│  sitemap.xml    │────▶│   URL List      │
│  Parser         │     │                 │
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
              │       Fetch HTML Page           │
              │       Extract Content           │
              │       Convert to Markdown       │
              │       Save to File              │
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
- **httpx**: Modern asynchronous HTTP client
- **BeautifulSoup4**: HTML parsing
- **markdownify**: HTML to Markdown conversion (or custom converter)
- **rich**: Beautiful terminal output and progress bars
- **click**: Command-line argument parsing

## Usage

### Basic Usage

```bash
# Download documentation to default directory
gitbook-download https://hyperliquid.gitbook.io/hyperliquid-docs

# Specify output directory
gitbook-download https://hyperliquid.gitbook.io/hyperliquid-docs -o ./my-docs

# Set concurrency
gitbook-download https://hyperliquid.gitbook.io/hyperliquid-docs --concurrency 5

# Incremental download (skip existing files)
gitbook-download https://hyperliquid.gitbook.io/hyperliquid-docs --skip-existing
```

### Command-line Parameters

| Parameter | Short | Description | Default |
|-----------|-------|-------------|---------|
| `url` | - | Base URL of GitBook documentation | (required) |
| `--output` | `-o` | Output directory | `./downloaded_docs` |
| `--concurrency` | `-c` | Number of concurrent downloads | `5` |
| `--skip-existing` | `-s` | Skip existing files | `False` |
| `--verbose` | `-v` | Verbose logging output | `False` |
| `--include-images` | `-i` | Download and save images locally | `False` |

## Implementation Details

### Sitemap Parsing

```python
async def fetch_sitemap_urls(client, base_url):
    # Try sitemap index first
    sitemap_url = f"{base_url}/sitemap.xml"
    response = await client.get(sitemap_url)
    
    # Parse sitemap index to get all sitemap-pages.xml URLs
    soup = BeautifulSoup(response.text, "xml")
    sitemap_locs = [loc.text for loc in soup.find_all("loc")]
    
    # Fetch each sitemap-pages.xml
    all_urls = []
    for sitemap_loc in sitemap_locs:
        if "sitemap-pages.xml" in sitemap_loc:
            pages_response = await client.get(sitemap_loc)
            pages_soup = BeautifulSoup(pages_response.text, "xml")
            all_urls.extend([loc.text for loc in pages_soup.find_all("loc")])
    
    return all_urls
```

### Content Extraction

```python
def extract_content(html):
    soup = BeautifulSoup(html, "html.parser")
    
    # Find main content area
    main = soup.find("main")
    if not main:
        main = soup.find("article") or soup.find("div", class_="content")
    
    # Remove navigation elements
    for nav in main.find_all(["nav", "aside", "footer"]):
        nav.decompose()
    
    # Remove "Previous/Next" navigation links
    for link in main.find_all("a"):
        if "Previous" in link.text or "Next" in link.text:
            parent = link.find_parent()
            if parent:
                parent.decompose()
    
    return main
```

### HTML to Markdown Conversion

Using a combination of markdownify library with custom filters:

```python
from markdownify import markdownify as md

def html_to_markdown(html_content, base_url):
    # Convert HTML to Markdown
    markdown = md(
        str(html_content),
        heading_style="ATX",
        code_language_callback=detect_code_language,
    )
    
    # Clean up extra whitespace
    markdown = re.sub(r'\n{3,}', '\n\n', markdown)
    
    return markdown.strip()
```

## Notes

### GitBook Characteristics

1. **SPA Architecture**: GitBook uses client-side rendering, but content is also server-rendered for SEO
2. **Sitemap Availability**: Most GitBook sites have sitemaps enabled
3. **Content Structure**: Main content is consistently placed in `<main>` element
4. **Image Hosting**: Images are hosted on GitBook's CDN with special URL patterns

### Known Limitations

1. **Dynamic Content**: Some interactive elements may not convert properly
2. **Embedded Widgets**: External embeds (YouTube, Codepen, etc.) become plain links
3. **Custom Styling**: Special formatting may be lost in conversion
4. **Private Documentation**: Requires authentication for private GitBook spaces

### Best Practices

1. Start with a specific documentation base URL
2. Use moderate concurrency (5-10) to avoid rate limiting
3. Run with `--verbose` first to verify URL discovery
4. Use `--skip-existing` for incremental updates

## Examples

### Download Hyperliquid Documentation

```bash
gitbook-download https://hyperliquid.gitbook.io/hyperliquid-docs -o ./hyperliquid-docs -v
```

### Expected Output Structure

```
hyperliquid-docs/
├── index.md
├── about-hyperliquid/
│   ├── hyperliquid-101-for-non-crypto-audiences.md
│   └── core-contributors.md
├── onboarding/
│   ├── how-to-start-trading.md
│   ├── how-to-use-the-hyperevm.md
│   └── ...
├── trading/
│   ├── fees.md
│   ├── margining.md
│   └── ...
└── for-developers/
    ├── api/
    │   ├── notation.md
    │   ├── websocket/
    │   │   ├── subscriptions.md
    │   │   └── ...
    │   └── ...
    └── ...
```
