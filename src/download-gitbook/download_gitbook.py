#!/usr/bin/env python3
"""
Download GitBook documentation and convert to Markdown.
Supports GitBook-powered sites like docs.axiom.trade
"""

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup, NavigableString


class GitBookDownloader:
    """Download and convert GitBook documentation to Markdown."""

    def __init__(self, base_url: str, output_dir: str, rate_limit: float = 0.5):
        self.base_url = base_url.rstrip('/')
        self.output_dir = Path(output_dir)
        self.rate_limit = rate_limit
        self.visited_urls: set[str] = set()
        self.page_queue: list[str] = []

        # Create output directory
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Initialize HTTP client
        self.client = httpx.AsyncClient(
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
            },
            follow_redirects=True,
            timeout=30.0,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.client.aclose()

    async def fetch_page(self, url: str) -> str | None:
        """Fetch a page with rate limiting."""
        try:
            await asyncio.sleep(self.rate_limit)
            response = await self.client.get(url)
            response.raise_for_status()
            return response.text
        except Exception as e:
            print(f"Error fetching {url}: {e}", file=sys.stderr)
            return None

    def extract_sidebar_links(self, soup: BeautifulSoup) -> list[str]:
        """Extract links from GitBook sidebar navigation."""
        links = []

        # Try multiple selectors for GitBook sidebars
        selectors = [
            'nav[role="navigation"] a',
            '.book-sidebar a',
            '.sidebar a',
            '.sidebar-content a',
            '[class*="sidebar"] a',
            '.table-of-contents a',
            '.gitbook-root a',
            'nav a[href^="/"]',
        ]

        seen_urls = set()
        for selector in selectors:
            for link in soup.select(selector):
                href = link.get('href', '')
                if not href or href.startswith('#') or href.startswith('javascript:'):
                    continue

                # Normalize URL
                full_url = urljoin(self.base_url, href)
                parsed = urlparse(full_url)

                # Only include URLs from the same domain and path
                base_parsed = urlparse(self.base_url)
                if parsed.netloc == base_parsed.netloc:
                    # Remove fragment
                    clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                    if clean_url not in seen_urls:
                        seen_urls.add(clean_url)
                        links.append(clean_url)

        return links

    def extract_content(self, soup: BeautifulSoup) -> tuple[str, str]:
        """Extract main content and title from GitBook page."""
        # Try to find the main content area
        content_selectors = [
            'main[role="main"]',
            'article',
            '.book-body .body-inner',
            '.book-body',
            '.content',
            '.main-content',
            '[class*="content"][class*="main"]',
            '.markdown-body',
            '#main-content',
            '.gitbook-root',
        ]

        content_elem = None
        for selector in content_selectors:
            content_elem = soup.select_one(selector)
            if content_elem:
                break

        # Fallback to body if no content found
        if not content_elem:
            content_elem = soup.find('body')

        # Extract title
        title = "Untitled"
        title_elem = soup.find('h1') or soup.find('title')
        if title_elem:
            title = title_elem.get_text(strip=True)

        return title, str(content_elem) if content_elem else ""

    def html_to_markdown(self, html_content: str, base_url: str) -> str:
        """Convert HTML content to Markdown."""
        soup = BeautifulSoup(html_content, 'html.parser')

        # Remove script and style elements
        for elem in soup.find_all(['script', 'style', 'nav', 'footer', 'header']):
            elem.decompose()

        markdown_parts = []

        for elem in soup.descendants:
            if isinstance(elem, NavigableString):
                text = str(elem).strip()
                if text:
                    markdown_parts.append(text)
            elif elem.name == 'h1':
                text = elem.get_text(strip=True)
                if text:
                    markdown_parts.append(f"\n# {text}\n")
            elif elem.name == 'h2':
                text = elem.get_text(strip=True)
                if text:
                    markdown_parts.append(f"\n## {text}\n")
            elif elem.name == 'h3':
                text = elem.get_text(strip=True)
                if text:
                    markdown_parts.append(f"\n### {text}\n")
            elif elem.name == 'h4':
                text = elem.get_text(strip=True)
                if text:
                    markdown_parts.append(f"\n#### {text}\n")
            elif elem.name == 'p':
                text = elem.get_text(strip=True)
                if text:
                    markdown_parts.append(f"{text}\n")
            elif elem.name == 'br':
                markdown_parts.append("\n")
            elif elem.name == 'ul':
                for li in elem.find_all('li', recursive=False):
                    text = li.get_text(strip=True)
                    if text:
                        markdown_parts.append(f"- {text}\n")
                markdown_parts.append("\n")
            elif elem.name == 'ol':
                for idx, li in enumerate(elem.find_all('li', recursive=False), 1):
                    text = li.get_text(strip=True)
                    if text:
                        markdown_parts.append(f"{idx}. {text}\n")
                markdown_parts.append("\n")
            elif elem.name == 'pre':
                code_elem = elem.find('code')
                if code_elem:
                    language = ' '.join(code_elem.get('class', []))
                    language = language.replace('language-', '').strip()
                    code = code_elem.get_text()
                    markdown_parts.append(f"\n```{language}\n{code}\n```\n")
                else:
                    code = elem.get_text()
                    markdown_parts.append(f"\n```\n{code}\n```\n")
            elif elem.name == 'code':
                # Inline code (not inside pre)
                if not elem.find_parent('pre'):
                    text = elem.get_text(strip=True)
                    if text:
                        markdown_parts.append(f"`{text}`")
            elif elem.name == 'a':
                href = elem.get('href', '')
                text = elem.get_text(strip=True)
                if href and text:
                    # Resolve relative URLs
                    full_url = urljoin(base_url, href)
                    markdown_parts.append(f"[{text}]({full_url})")
                elif text:
                    markdown_parts.append(text)
            elif elem.name in ['strong', 'b']:
                text = elem.get_text(strip=True)
                if text:
                    markdown_parts.append(f"**{text}**")
            elif elem.name in ['em', 'i']:
                text = elem.get_text(strip=True)
                if text:
                    markdown_parts.append(f"*{text}*")
            elif elem.name == 'img':
                src = elem.get('src', '')
                alt = elem.get('alt', '')
                if src:
                    full_src = urljoin(base_url, src)
                    markdown_parts.append(f"![{alt}]({full_src})")
            elif elem.name == 'hr':
                markdown_parts.append("\n---\n")
            elif elem.name == 'table':
                markdown = self._table_to_markdown(elem)
                if markdown:
                    markdown_parts.append(markdown)

        # Join and clean up
        markdown = ''.join(markdown_parts)
        # Clean up excessive newlines
        markdown = re.sub(r'\n{4,}', '\n\n\n', markdown)
        return markdown.strip()

    def _table_to_markdown(self, table_elem) -> str:
        """Convert HTML table to Markdown."""
        rows = []
        headers = []

        # Find header row
        thead = table_elem.find('thead')
        if thead:
            ths = thead.find_all('th')
            if ths:
                headers = [th.get_text(strip=True) for th in ths]

        # Find body rows
        tbody = table_elem.find('tbody')
        if tbody:
            trs = tbody.find_all('tr')
        else:
            trs = table_elem.find_all('tr')

        for tr in trs:
            tds = tr.find_all(['td', 'th'])
            row = [td.get_text(strip=True) for td in tds]
            if row:
                rows.append(row)

        # If no explicit headers but rows exist, use first row as header
        if not headers and rows:
            headers = rows[0]
            rows = rows[1:]

        if not headers:
            return ""

        # Build markdown table
        lines = []
        lines.append('| ' + ' | '.join(headers) + ' |')
        lines.append('|' + '|'.join(['---' for _ in headers]) + '|')
        for row in rows:
            # Pad row to match header length
            padded_row = row + [''] * (len(headers) - len(row))
            lines.append('| ' + ' | '.join(padded_row[:len(headers)]) + ' |')

        return '\n'.join(lines) + '\n'

    def url_to_filename(self, url: str) -> str:
        """Convert URL to safe filename."""
        parsed = urlparse(url)
        path = parsed.path.strip('/')
        if not path:
            return 'index'

        # Remove trailing slashes and convert to safe filename
        path = path.replace('/', '-')
        path = re.sub(r'[^\w\-]', '_', path)
        return path.lower()

    async def download_page(self, url: str) -> tuple[str, str] | None:
        """Download and convert a single page."""
        html = await self.fetch_page(url)
        if not html:
            return None

        soup = BeautifulSoup(html, 'html.parser')

        # Extract title and content
        title, content_html = self.extract_content(soup)

        # Convert to markdown
        markdown = self.html_to_markdown(content_html, url)

        # Add frontmatter
        frontmatter = f"---\ntitle: {title}\nsource: {url}\n---\n\n"
        full_markdown = frontmatter + markdown

        return title, full_markdown

    async def run(self, start_url: str | None = None):
        """Run the full download process."""
        start_url = start_url or self.base_url

        print(f"Starting download from: {start_url}")
        print(f"Output directory: {self.output_dir}")

        # Fetch the start page to find all links
        html = await self.fetch_page(start_url)
        if not html:
            print("Failed to fetch start page")
            return

        soup = BeautifulSoup(html, 'html.parser')

        # Extract all page links from sidebar
        links = self.extract_sidebar_links(soup)

        # Always include the start URL
        if start_url not in links:
            links.insert(0, start_url)

        print(f"Found {len(links)} pages to download")

        # Download each page
        for i, url in enumerate(links, 1):
            if url in self.visited_urls:
                continue

            self.visited_urls.add(url)
            print(f"[{i}/{len(links)}] Downloading: {url}")

            result = await self.download_page(url)
            if not result:
                continue

            title, markdown = result

            # Generate filename
            filename = self.url_to_filename(url) + '.md'
            filepath = self.output_dir / filename

            # Write markdown file
            filepath.write_text(markdown, encoding='utf-8')
            print(f"  ✓ Saved: {filepath}")

        print(f"\nDownload complete! Files saved to: {self.output_dir}")


def main():
    parser = argparse.ArgumentParser(
        description='Download GitBook documentation as Markdown'
    )
    parser.add_argument(
        'url',
        help='Base URL of the GitBook documentation'
    )
    parser.add_argument(
        '-o', '--output',
        default='docs',
        help='Output directory (default: docs)'
    )
    parser.add_argument(
        '-r', '--rate-limit',
        type=float,
        default=0.5,
        help='Rate limit between requests in seconds (default: 0.5)'
    )

    args = parser.parse_args()

    async def run():
        async with GitBookDownloader(
            base_url=args.url,
            output_dir=args.output,
            rate_limit=args.rate_limit
        ) as downloader:
            await downloader.run()

    asyncio.run(run())


if __name__ == '__main__':
    main()
