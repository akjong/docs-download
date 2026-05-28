"""Core scraper module for CoinW API documentation sites."""

import asyncio
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from markdownify import MarkdownConverter
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
)

console = Console()

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class CoinWMarkdownConverter(MarkdownConverter):
    """Custom Markdown converter for CoinW Docusaurus docs."""

    def convert_pre(self, el, text, convert_as_inline=False, **kwargs):
        """Handle code blocks with language detection."""
        code_el = el.find("code")
        lang = ""
        if code_el:
            for cls in code_el.get("class", []):
                if cls.startswith("language-"):
                    lang = cls.replace("language-", "")
                    break
        return f"\n\n```{lang}\n{text.strip()}\n```\n\n"

    def convert_table(self, el, text, convert_as_inline=False, **kwargs):
        """Ensure tables have proper spacing."""
        return f"\n\n{text}\n\n"


@dataclass
class ScraperConfig:
    """Configuration for the CoinW documentation scraper."""

    base_url: str
    output_dir: str = "./downloaded_docs"
    concurrency: int = 5
    skip_existing: bool = False
    verbose: bool = False
    timeout: float = 30.0


@dataclass
class ScraperStats:
    """Statistics for the scraping process."""

    discovered: int = 0
    downloaded: int = 0
    skipped: int = 0
    failed: int = 0


class CoinwScraper:
    """Scraper for CoinW API documentation (Docusaurus v3)."""

    def __init__(self, config: ScraperConfig):
        self.config = config
        self.stats = ScraperStats()

        self.base_url = config.base_url.rstrip("/")
        parsed = urlparse(self.base_url)
        self.base_host = parsed.netloc

        self.semaphore = asyncio.Semaphore(config.concurrency)

    def _url_to_filepath(self, url: str) -> str:
        """Convert a documentation URL to a local file path."""
        parsed = urlparse(url)
        path = parsed.path.strip("/")

        # Remove the "api-doc/en" prefix
        path = re.sub(r"^api-doc/en/", "", path)

        parts = path.split("/")
        if len(parts) <= 1:
            return f"{parts[0]}/index.md" if parts else "index.md"

        # Group by first segment (category), then nested path
        category = parts[0]
        subpath = "/".join(parts[1:])
        return f"{category}/{subpath}.md"

    def _extract_article_content(self, html: str) -> tuple[str, str]:
        """Extract the main article content from a Docusaurus page.

        Returns (title, markdown_content).
        """
        soup = BeautifulSoup(html, "html.parser")

        title = ""
        h1 = soup.select_one("article h1, .theme-doc-markdown h1")
        if h1:
            title = h1.get_text(strip=True)

        article = soup.select_one("article .theme-doc-markdown, main .theme-doc-markdown")
        if not article:
            article = soup.select_one("article")
        if not article:
            return title, ""

        # Remove navigation elements, TOC, breadcrumbs
        for tag in article.select(
            "nav, .pagination-nav, .table-of-contents, "
            ".tocCollapsible_ETCw, .breadcrumbsContainer_Z_bl"
        ):
            tag.decompose()

        # Remove anchor hash links from headings
        for anchor in article.select("a.hash-link"):
            anchor.decompose()

        converter = CoinWMarkdownConverter(
            heading_style="atx",
            bullets="-",
            strip=["script", "style", "svg"],
        )
        md = converter.convert(str(article))

        # Clean up excessive blank lines
        md = re.sub(r"\n{4,}", "\n\n\n", md)
        return title, md.strip()

    def _discover_urls_from_sitemap(self, sitemap_xml: str) -> list[str]:
        """Parse sitemap.xml and return all English documentation URLs."""
        from xml.etree import ElementTree

        root = ElementTree.fromstring(sitemap_xml)
        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

        # Pages to skip (non-documentation)
        skip_paths = {"/versions", "/home-doc", "/"}

        urls = []
        for url_el in root.findall("sm:url", ns):
            loc = url_el.find("sm:loc", ns)
            if loc is not None and loc.text:
                url = loc.text.strip()
                if "/api-doc/en/" not in url:
                    continue
                # Check if it's a non-doc page
                from urllib.parse import urlparse

                path = urlparse(url).path.rstrip("/")
                # Remove the /api-doc/en prefix to get the doc path
                doc_path = re.sub(r"^/api-doc/en", "", path)
                if doc_path in skip_paths or doc_path == "":
                    continue
                urls.append(url)

        return urls

    async def _fetch(self, client: httpx.AsyncClient, url: str, retries: int = 3) -> str | None:
        """Fetch a URL with retries and rate-limit handling."""
        for attempt in range(retries):
            try:
                resp = await client.get(url, follow_redirects=True)
                resp.raise_for_status()
                return resp.text
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 429:
                    wait = 2 ** (attempt + 1)
                    if self.config.verbose:
                        console.print(f"  [yellow]Rate limited, waiting {wait}s...[/yellow]")
                    await asyncio.sleep(wait)
                    continue
                if self.config.verbose:
                    console.print(f"  [red]HTTP {exc.response.status_code}: {url}[/red]")
                return None
            except httpx.HTTPError:
                if attempt < retries - 1:
                    await asyncio.sleep(1)
                    continue
                return None
        return None

    async def _process_url(
        self,
        client: httpx.AsyncClient,
        url: str,
        output_dir: str,
        progress: Progress,
        task_id: int,
    ) -> None:
        """Fetch, parse, and save a single documentation page."""
        async with self.semaphore:
            # Rate limit
            await asyncio.sleep(0.3)

            html = await self._fetch(client, url)
            if html is None:
                self.stats.failed += 1
                if self.config.verbose:
                    console.print(f"  [red]Failed: {url}[/red]")
                progress.advance(task_id)
                return

            try:
                title, content = self._extract_article_content(html)
            except Exception as exc:
                self.stats.failed += 1
                if self.config.verbose:
                    console.print(f"  [red]Parse error: {url}: {exc}[/red]")
                progress.advance(task_id)
                return

            rel_path = self._url_to_filepath(url)
            filepath = f"{output_dir}/{rel_path}"

            # Skip if exists
            if self.config.skip_existing:
                from pathlib import Path

                if Path(filepath).exists():
                    self.stats.skipped += 1
                    progress.advance(task_id)
                    return

            # Add YAML frontmatter
            meta = f'---\ntitle: "{title}"\nsource: "{url}"\n---\n\n'
            full_content = meta + content

            from pathlib import Path

            Path(filepath).parent.mkdir(parents=True, exist_ok=True)
            Path(filepath).write_text(full_content, encoding="utf-8")

            self.stats.downloaded += 1
            progress.advance(task_id)

            if self.config.verbose:
                console.print(f"  [green]Saved[/green] {rel_path}")

    async def run(self) -> ScraperStats:
        """Execute the full scraping pipeline."""
        console.print(
            f"[bold blue]CoinW API Documentation Scraper[/bold blue]\n"
            f"  URL: {self.base_url}\n"
            f"  Output: {self.config.output_dir}\n"
            f"  Concurrency: {self.config.concurrency}\n"
        )

        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

        async with httpx.AsyncClient(headers=headers, timeout=self.config.timeout) as client:
            # Step 1: Discover URLs from sitemap
            with console.status("[bold green]Discovering pages from sitemap..."):
                sitemap_url = f"{self.base_url.rstrip('/')}/sitemap.xml"
                sitemap_xml = await self._fetch(client, sitemap_url)
                if sitemap_xml:
                    urls = self._discover_urls_from_sitemap(sitemap_xml)
                else:
                    urls = []

            self.stats.discovered = len(urls)

            if not urls:
                console.print("[yellow]No pages found in sitemap.[/yellow]")
                return self.stats

            console.print(f"  Found [bold]{len(urls)}[/bold] pages to download\n")

            # Step 2: Download all pages concurrently
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                console=console,
            ) as progress:
                task_id = progress.add_task("Downloading...", total=len(urls))
                await asyncio.gather(
                    *[
                        self._process_url(client, url, self.config.output_dir, progress, task_id)
                        for url in urls
                    ]
                )

        # Step 3: Print summary
        failed_str = (
            f"[red]{self.stats.failed}[/red]" if self.stats.failed else str(self.stats.failed)
        )
        console.print(
            f"\n[bold]Summary[/bold]\n"
            f"  Discovered:  {self.stats.discovered}\n"
            f"  Downloaded:  [green]{self.stats.downloaded}[/green]\n"
            f"  Skipped:     {self.stats.skipped}\n"
            f"  Failed:      {failed_str}"
        )

        return self.stats
