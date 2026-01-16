"""Core scraper module for Mintlify documentation sites."""

import asyncio
import os
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn

console = Console()


@dataclass
class ScraperConfig:
    """Configuration for the Mintlify scraper."""

    base_url: str
    output_dir: str = "./downloaded_docs"
    force_md: bool = False
    concurrency: int = 10
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


class MintlifyScraper:
    """Scraper for Mintlify documentation sites."""

    def __init__(self, config: ScraperConfig):
        self.config = config
        self.stats = ScraperStats()

        # Normalize base URL
        self.base_url = config.base_url.rstrip("/")
        parsed = urlparse(self.base_url)
        self.base_host = parsed.netloc
        self.base_path = parsed.path

        # URL tracking
        self.visited_urls: set[str] = set()
        self.urls_to_visit: asyncio.Queue[str] = asyncio.Queue()
        self.downloaded_paths: set[str] = set()

        # Semaphore for concurrency control
        self.semaphore = asyncio.Semaphore(config.concurrency)

    def _normalize_url(self, url: str) -> str:
        """Normalize URL by removing trailing slashes and fragments."""
        parsed = urlparse(url)
        # Remove fragment and query, normalize path
        normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}"
        return normalized

    def _is_valid_doc_url(self, url: str) -> bool:
        """Check if URL is a valid documentation page under base_url."""
        parsed = urlparse(url)

        # Must be same host
        if parsed.netloc != self.base_host:
            return False

        # Must be under base path
        if not parsed.path.startswith(self.base_path):
            return False

        # Skip common non-doc paths
        skip_patterns = [
            r"/_next/",
            r"/api/",
            r"\.(js|css|png|jpg|jpeg|gif|svg|ico|woff|woff2|ttf|eot)$",
            r"/static/",
            r"#",
        ]
        for pattern in skip_patterns:
            if re.search(pattern, parsed.path):
                return False

        return True

    def _get_local_path(self, url: str, extension: str) -> str:
        """Convert URL to local file path."""
        parsed = urlparse(url)
        path = parsed.path

        # Remove base path prefix to get relative path
        if path.startswith(self.base_path):
            relative_path = path[len(self.base_path) :].lstrip("/")
        else:
            relative_path = path.lstrip("/")

        # Handle empty path (root)
        if not relative_path:
            relative_path = "index"

        # Handle trailing slash
        if relative_path.endswith("/"):
            relative_path = relative_path.rstrip("/") + "/index"

        # Determine file extension
        save_ext = ".md" if self.config.force_md else extension

        # Build full path
        file_path = os.path.join(self.config.output_dir, relative_path)

        # Add extension if not already present
        if not file_path.endswith((".md", ".mdx")):
            file_path += save_ext

        return file_path

    async def _fetch_mint_json(self, client: httpx.AsyncClient) -> list[str]:
        """Try to fetch mint.json to discover all pages."""
        urls_found = []

        # Try different possible locations for mint.json
        mint_json_urls = [
            f"{self.base_url}/mint.json",
            urljoin(self.base_url, "/mint.json"),
        ]

        for mint_url in mint_json_urls:
            try:
                response = await client.get(mint_url, timeout=self.config.timeout)
                if response.status_code == 200:
                    data = response.json()
                    urls_found.extend(self._extract_urls_from_mint_json(data))
                    if urls_found:
                        if self.config.verbose:
                            console.print(
                                f"[green]Found {len(urls_found)} pages from mint.json[/green]"
                            )
                        break
            except Exception as e:
                if self.config.verbose:
                    console.print(f"[dim]Could not fetch {mint_url}: {e}[/dim]")

        return urls_found

    def _extract_urls_from_mint_json(self, data: dict) -> list[str]:
        """Extract page URLs from mint.json navigation structure."""
        urls = []

        def extract_from_navigation(nav_items: list) -> None:
            for item in nav_items:
                if isinstance(item, str):
                    # Direct page reference
                    urls.append(item)
                elif isinstance(item, dict):
                    # Could be a group with pages
                    if "pages" in item:
                        extract_from_navigation(item["pages"])
                    if "group" in item and "pages" in item:
                        extract_from_navigation(item["pages"])
                    # Could be a direct page with href
                    if "href" in item:
                        urls.append(item["href"])

        # Check different navigation structures
        if "navigation" in data:
            extract_from_navigation(data["navigation"])

        if "topbarLinks" in data:
            for link in data["topbarLinks"]:
                if "href" in link and not link["href"].startswith("http"):
                    urls.append(link["href"])

        if "tabs" in data:
            for tab in data["tabs"]:
                if "url" in tab:
                    urls.append(tab["url"])

        return urls

    async def _extract_links_from_html(self, client: httpx.AsyncClient, url: str) -> list[str]:
        """Extract internal links from HTML page."""
        links = []

        try:
            response = await client.get(url, timeout=self.config.timeout)
            if response.status_code != 200:
                return links

            soup = BeautifulSoup(response.text, "html.parser")

            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"]

                # Skip external links, anchors, and javascript
                if href.startswith(("http://", "https://")) and self.base_host not in href:
                    continue
                if href.startswith(("#", "javascript:", "mailto:", "tel:")):
                    continue

                # Convert to absolute URL
                absolute_url = urljoin(url, href)
                normalized = self._normalize_url(absolute_url)

                if self._is_valid_doc_url(normalized):
                    links.append(normalized)

        except Exception as e:
            if self.config.verbose:
                console.print(f"[yellow]Failed to extract links from {url}: {e}[/yellow]")

        return links

    async def _try_download_source(
        self, client: httpx.AsyncClient, url: str
    ) -> tuple[bytes, str] | None:
        """Try to download .mdx or .md source for a URL."""
        url_str = url.rstrip("/")

        # Try both extensions
        candidates = [
            (f"{url_str}.mdx", ".mdx"),
            (f"{url_str}.md", ".md"),
        ]

        for source_url, ext in candidates:
            try:
                async with self.semaphore:
                    response = await client.get(source_url, timeout=self.config.timeout)

                if response.status_code == 200:
                    content = response.content

                    # Verify it's not an HTML error page
                    content_start = content[:500].lower()
                    if b"<!doctype html>" in content_start or b"<html" in content_start:
                        continue

                    # Check content type if available
                    content_type = response.headers.get("content-type", "")
                    if "text/html" in content_type:
                        continue

                    return content, ext

            except Exception as e:
                if self.config.verbose:
                    console.print(f"[dim]Failed to fetch {source_url}: {e}[/dim]")

        return None

    async def _process_url(
        self, client: httpx.AsyncClient, url: str, progress: Progress, task_id
    ) -> None:
        """Process a single URL: download source and discover new links."""
        # Try to download the source
        result = await self._try_download_source(client, url)

        if result:
            content, ext = result
            local_path = self._get_local_path(url, ext)

            # Skip if file exists and skip_existing is enabled
            if self.config.skip_existing and os.path.exists(local_path):
                self.stats.skipped += 1
                if self.config.verbose:
                    console.print(f"[dim]Skipped (exists): {local_path}[/dim]")
            else:
                # Create directory and save file
                os.makedirs(os.path.dirname(local_path), exist_ok=True)

                with open(local_path, "wb") as f:
                    f.write(content)

                self.stats.downloaded += 1
                self.downloaded_paths.add(local_path)

                if self.config.verbose:
                    console.print(f"[green]Downloaded: {local_path}[/green]")
        else:
            self.stats.failed += 1
            if self.config.verbose:
                console.print(f"[yellow]No source found for: {url}[/yellow]")

        # Extract links from HTML page for discovery
        new_links = await self._extract_links_from_html(client, url)

        for link in new_links:
            if link not in self.visited_urls:
                self.visited_urls.add(link)
                await self.urls_to_visit.put(link)
                self.stats.discovered += 1

        progress.update(task_id, advance=1)

    async def _worker(self, client: httpx.AsyncClient, progress: Progress, task_id) -> None:
        """Worker coroutine that processes URLs from the queue."""
        while True:
            try:
                url = await asyncio.wait_for(self.urls_to_visit.get(), timeout=5.0)
            except asyncio.TimeoutError:
                # Queue is empty for 5 seconds, worker can exit
                break

            try:
                await self._process_url(client, url, progress, task_id)
            except Exception as e:
                if self.config.verbose:
                    console.print(f"[red]Error processing {url}: {e}[/red]")
            finally:
                self.urls_to_visit.task_done()

    async def run(self) -> ScraperStats:
        """Run the scraper."""
        console.print("[bold blue]Mintlify Scraper[/bold blue]")
        console.print(f"  Base URL: {self.base_url}")
        console.print(f"  Output: {self.config.output_dir}")
        console.print(f"  Concurrency: {self.config.concurrency}")
        console.print()

        # Create output directory
        os.makedirs(self.config.output_dir, exist_ok=True)

        async with httpx.AsyncClient(
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            },
        ) as client:
            # Try to get pages from mint.json first
            mint_pages = await self._fetch_mint_json(client)

            if mint_pages:
                # Convert relative paths to full URLs
                for page in mint_pages:
                    if page.startswith("/"):
                        full_url = f"https://{self.base_host}{page}"
                    elif page.startswith("http"):
                        full_url = page
                    else:
                        full_url = f"{self.base_url}/{page}"

                    normalized = self._normalize_url(full_url)
                    if normalized not in self.visited_urls and self._is_valid_doc_url(normalized):
                        self.visited_urls.add(normalized)
                        await self.urls_to_visit.put(normalized)
                        self.stats.discovered += 1

            # Always add the base URL to start crawling
            self.visited_urls.add(self.base_url)
            await self.urls_to_visit.put(self.base_url)
            self.stats.discovered += 1

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                console=console,
            ) as progress:
                task_id = progress.add_task("[cyan]Processing pages...", total=None)

                # Create workers
                workers = [
                    asyncio.create_task(self._worker(client, progress, task_id))
                    for _ in range(self.config.concurrency)
                ]

                # Wait for queue to be fully processed
                await self.urls_to_visit.join()

                # Cancel workers
                for worker in workers:
                    worker.cancel()

                # Wait for workers to finish
                await asyncio.gather(*workers, return_exceptions=True)

        # Print summary
        console.print()
        console.print("[bold green]✓ Scraping complete![/bold green]")
        console.print(f"  Discovered: {self.stats.discovered} pages")
        console.print(f"  Downloaded: {self.stats.downloaded} files")
        console.print(f"  Skipped: {self.stats.skipped} files")
        console.print(f"  Failed: {self.stats.failed} pages")

        return self.stats
