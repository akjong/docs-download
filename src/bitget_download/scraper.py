"""Core scraper module for Bitget API documentation sites (Docusaurus-based)."""

import asyncio
import hashlib
import os
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskID, TaskProgressColumn, TextColumn

console = Console()


@dataclass
class ScraperConfig:
    """Configuration for the Bitget scraper."""

    base_url: str
    output_dir: str = "./downloaded_docs"
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
    images_downloaded: int = 0
    images_failed: int = 0


class BitgetScraper:
    """Scraper for Bitget API documentation with collapsible sidebar discovery."""

    MAX_EXPAND_ROUNDS = 8

    # Landing page slugs that are stripped to derive the section root path
    LANDING_SLUGS = {"intro", "introduction", "overview", "index", "guide", "getting-started"}

    def __init__(self, config: ScraperConfig):
        self.config = config

        # Normalize base URL (keep trailing slash for correct urljoin resolution)
        self.base_url = config.base_url.rstrip("/") + "/"
        parsed = urlparse(self.base_url)
        self.base_host = parsed.netloc
        self.origin = f"{parsed.scheme}://{parsed.netloc}"

        # Section root path used for filtering and local path mapping.
        # A trailing landing slug (e.g. /intro) is stripped so that passing a
        # landing page URL still captures the whole docs section.
        base_path = parsed.path.rstrip("/")
        segments = base_path.rsplit("/", 1)
        if len(segments) == 2 and segments[1].lower() in self.LANDING_SLUGS:
            self.section_path = segments[0]
        else:
            self.section_path = base_path

        # URL tracking
        self.visited_urls: set[str] = set()
        self.downloaded_paths: set[str] = set()
        self.downloaded_images: set[str] = set()

        # Semaphore for concurrency control
        self.semaphore = asyncio.Semaphore(config.concurrency)

    def _normalize_url(self, url: str) -> str:
        """Normalize URL by removing trailing slashes and fragments."""
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}"

    def _is_valid_doc_url(self, url: str) -> bool:
        """Check if URL is a valid documentation page under the section root."""
        parsed = urlparse(url)

        # Must be same host
        if parsed.netloc != self.base_host:
            return False

        # Must be under the section root path
        if self.section_path and not parsed.path.startswith(self.section_path + "/"):
            return False

        # Skip non-doc paths
        skip_patterns = [
            r"/api/",
            r"/_next/",
            r"/assets/",
            r"\.(js|css|png|jpg|jpeg|gif|svg|ico|woff|woff2|ttf|eot)$",
            r"/static/",
        ]
        return not any(re.search(pattern, parsed.path) for pattern in skip_patterns)

    def _get_local_path(self, url: str) -> str:
        """Convert URL to local file path."""
        parsed = urlparse(url)
        path = parsed.path

        # Remove section root prefix
        if self.section_path and path.startswith(self.section_path):
            relative_path = path[len(self.section_path) :].lstrip("/")
        else:
            relative_path = path.lstrip("/")

        # Handle empty path (root)
        if not relative_path:
            relative_path = "index"

        # Handle trailing slash
        if relative_path.endswith("/"):
            relative_path = relative_path.rstrip("/") + "/index"

        # Build full path
        file_path = os.path.join(self.config.output_dir, relative_path)

        # Add extension if not already present
        if not file_path.endswith(".md"):
            file_path += ".md"

        return file_path

    def _get_image_local_path(self, img_url: str) -> str:
        """Get local path for an image URL."""
        parsed = urlparse(img_url)
        path = parsed.path

        filename = os.path.basename(path)
        if not filename or "." not in filename:
            url_hash = hashlib.md5(img_url.encode()).hexdigest()[:8]
            ext = ".png"
            if "." in path:
                ext = os.path.splitext(path)[1] or ".png"
            filename = f"image_{url_hash}{ext}"

        return f"img/{filename}"

    async def _download_image(self, client: httpx.AsyncClient, url: str, local_path: str) -> bool:
        """Download an image to local path."""
        if url in self.downloaded_images:
            return True

        try:
            async with self.semaphore:
                response = await client.get(url, timeout=self.config.timeout)

            if response.status_code != 200:
                if self.config.verbose:
                    console.print(
                        f"[yellow]Failed to download image ({response.status_code}): {url}[/yellow]"
                    )
                self.stats.images_failed += 1
                return False

            full_path = os.path.join(self.config.output_dir, local_path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)

            with open(full_path, "wb") as f:
                f.write(response.content)

            self.downloaded_images.add(url)
            self.stats.images_downloaded += 1

            if self.config.verbose:
                console.print(f"[dim]Downloaded image: {full_path}[/dim]")

            return True

        except Exception as e:
            if self.config.verbose:
                console.print(f"[yellow]Error downloading image {url}: {e}[/yellow]")
            self.stats.images_failed += 1
            return False

    async def _expand_sidebar(self, page) -> None:
        """Expand all collapsed sidebar categories until none remain.

        Only collapsed items are clicked each round: the caret acts as a toggle,
        so re-clicking expanded categories would collapse them again. Nested
        categories rendered after expansion are handled by subsequent rounds.
        """
        for _ in range(self.MAX_EXPAND_ROUNDS):
            collapsibles = await page.query_selector_all(
                "li.menu__list-item--collapsed .menu__list-item-collapsible"
            )
            if not collapsibles:
                break

            for item in collapsibles:
                try:
                    await item.click(timeout=1000)
                except Exception:
                    pass

            await asyncio.sleep(1)

    def _filter_doc_urls(self, hrefs: list[str | None]) -> set[str]:
        """Filter raw hrefs into a set of valid normalized doc URLs."""
        urls = set()
        for href in hrefs:
            if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue
            if href.startswith(("http://", "https://")):
                absolute_url = href
            else:
                absolute_url = urljoin(self.base_url, href)

            normalized = self._normalize_url(absolute_url)
            if self._is_valid_doc_url(normalized):
                urls.add(normalized)
        return urls

    async def _collect_links(self, page) -> set[str]:
        """Expand the sidebar on the current page and collect all doc URLs."""
        await asyncio.sleep(3)
        await self._expand_sidebar(page)

        hrefs = await page.evaluate(
            "() => Array.from(document.querySelectorAll('a[href]'))"
            ".map(a => a.getAttribute('href'))"
        )
        return self._filter_doc_urls(hrefs)

    async def _discover_urls(self, browser) -> list[str]:
        """Load the docs section landing page, expand the sidebar, and collect all doc URLs."""
        page = await browser.new_page()
        try:
            candidate_urls: list[str] = [self.base_url]
            # Fallback landing page in case the section root itself has no page (404 shell)
            fallback = f"{self.origin}{self.section_path}/intro/"
            if fallback.rstrip("/") != self.base_url.rstrip("/"):
                candidate_urls.append(fallback)

            urls: set[str] = set()
            for candidate in candidate_urls:
                try:
                    await page.goto(
                        candidate,
                        wait_until="domcontentloaded",
                        timeout=self.config.timeout * 1000,
                    )
                except Exception as e:
                    if self.config.verbose:
                        console.print(f"[yellow]Failed to load {candidate}: {e}[/yellow]")
                    continue

                urls = await self._collect_links(page)
                if len(urls) >= 5:
                    break

                if self.config.verbose:
                    console.print(
                        f"[yellow]Only {len(urls)} links found at {candidate}, "
                        "trying fallback landing page[/yellow]"
                    )

            if self.config.verbose:
                console.print(f"[green]Discovered {len(urls)} documentation pages[/green]")

            return sorted(urls)
        finally:
            await page.close()

    async def _extract_content_from_page(self, page) -> str | None:
        """Extract markdown content from a Playwright page."""
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=20000)
            await asyncio.sleep(2)

            content_html = await page.evaluate("""() => {
                return document.documentElement.outerHTML;
            }""")

            if not content_html:
                if self.config.verbose:
                    console.print("[yellow]No content returned from evaluate[/yellow]")
                return None

            soup = BeautifulSoup(content_html, "html.parser")

            # Remove navigation and sidebar elements
            for tag in soup.find_all(["nav", "aside", "footer", "header"]):
                tag.decompose()

            # Find the main content area - Docusaurus uses article or main
            article = soup.find("article")
            main = soup.find("main")

            content_elem = article or main or soup.find("body") or soup

            # Remove UI artifacts (copy page / copy code buttons)
            for tag in content_elem.find_all("button"):
                tag.decompose()

            # Convert to markdown using html2text
            try:
                import html2text

                h = html2text.HTML2Text()
                h.body_width = 0
                markdown = h.handle(str(content_elem))
                if len(markdown.strip()) < 100:
                    return content_elem.get_text(separator="\n", strip=True)
                return self._clean_markdown(markdown)
            except Exception:
                return content_elem.get_text(separator="\n", strip=True)

        except Exception as e:
            if self.config.verbose:
                console.print(f"[yellow]Error extracting content: {e}[/yellow]")
            return None

    @staticmethod
    def _clean_markdown(markdown: str) -> str:
        """Clean up common extraction artifacts from the markdown output."""
        # Remove zero-width spaces that pollute headings and text
        markdown = markdown.replace("\u200b", "")
        # Drop leftover "Copy Page" action labels
        lines = [line for line in markdown.splitlines() if line.strip() != "Copy Page"]
        return "\n".join(lines)

    async def _process_page(
        self,
        page,
        client: httpx.AsyncClient,
        url: str,
        progress: Progress,
        task_id: TaskID,
    ) -> None:
        """Process a single URL: extract content and save as markdown."""
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=self.config.timeout * 1000)
        except Exception as e:
            self.stats.failed += 1
            if self.config.verbose:
                console.print(f"[yellow]Failed to load {url}: {e}[/yellow]")
            progress.update(task_id, advance=1)
            return

        try:
            content = await self._extract_content_from_page(page)
        except Exception as e:
            if self.config.verbose:
                console.print(f"[yellow]Error extracting content from {url}: {e}[/yellow]")
            content = None

        if content:
            local_path = self._get_local_path(url)

            content_str = content

            img_pattern = r"!\[([^\]]*)\]\(([^)]+)\)"
            matches = re.findall(img_pattern, content_str)

            for alt, img_url in matches:
                if not img_url or img_url.startswith(("data:", "blob:")):
                    continue

                if not img_url.startswith(("http://", "https://")):
                    img_url_abs = urljoin(url, img_url)
                else:
                    img_url_abs = img_url

                if img_url_abs.startswith("blob:"):
                    continue

                local_img_path = self._get_image_local_path(img_url_abs)
                await self._download_image(client, img_url_abs, local_img_path)
                content_str = content_str.replace(
                    f"![{alt}]({img_url})", f"![{alt}]({local_img_path})"
                )

            if self.config.skip_existing and os.path.exists(local_path):
                self.stats.skipped += 1
                if self.config.verbose:
                    console.print(f"[dim]Skipped (exists): {local_path}[/dim]")
            else:
                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                with open(local_path, "w", encoding="utf-8") as f:
                    f.write(content_str)

                self.stats.downloaded += 1
                self.downloaded_paths.add(local_path)

                if self.config.verbose:
                    console.print(f"[green]Downloaded: {local_path}[/green]")
        else:
            self.stats.failed += 1
            if self.config.verbose:
                console.print(f"[yellow]No content found for: {url}[/yellow]")

        progress.update(task_id, advance=1)

    async def _worker(
        self,
        browser,
        client: httpx.AsyncClient,
        queue: asyncio.Queue[str],
        progress: Progress,
        task_id: TaskID,
    ) -> None:
        """Worker coroutine that processes URLs from the queue with its own page."""
        page = await browser.new_page()
        try:
            while True:
                try:
                    url = await asyncio.wait_for(queue.get(), timeout=5.0)
                except asyncio.TimeoutError:
                    break

                try:
                    await self._process_page(page, client, url, progress, task_id)
                except Exception as e:
                    if self.config.verbose:
                        console.print(f"[red]Error processing {url}: {e}[/red]")
                finally:
                    queue.task_done()
        finally:
            await page.close()

    async def run(self) -> ScraperStats:
        """Run the scraper."""
        self.stats = ScraperStats()

        console.print("[bold blue]Bitget Docs Scraper[/bold blue]")
        console.print(f"  Base URL: {self.base_url}")
        console.print(f"  Output: {self.config.output_dir}")
        console.print(f"  Concurrency: {self.config.concurrency}")
        console.print()

        os.makedirs(self.config.output_dir, exist_ok=True)

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)

            discovered = await self._discover_urls(browser)

            for url in discovered:
                self.visited_urls.add(url)
                self.stats.discovered += 1

            async with httpx.AsyncClient(
                follow_redirects=True,
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
                },
            ) as client:
                queue: asyncio.Queue[str] = asyncio.Queue()
                for url in discovered:
                    queue.put_nowait(url)

                with Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    BarColumn(),
                    TaskProgressColumn(),
                    console=console,
                ) as progress:
                    task_id: TaskID = progress.add_task(
                        "[cyan]Processing pages...", total=len(discovered)
                    )

                    workers = [
                        asyncio.create_task(self._worker(browser, client, queue, progress, task_id))
                        for _ in range(self.config.concurrency)
                    ]

                    await queue.join()

                    for worker in workers:
                        worker.cancel()

                    await asyncio.gather(*workers, return_exceptions=True)

            await browser.close()

        console.print()
        console.print("[bold green]✓ Scraping complete![/bold green]")
        console.print(f"  Discovered: {self.stats.discovered} pages")
        console.print(f"  Downloaded: {self.stats.downloaded} files")
        console.print(f"  Skipped: {self.stats.skipped} files")
        console.print(f"  Failed: {self.stats.failed} pages")
        console.print(f"  Images downloaded: {self.stats.images_downloaded}")
        console.print(f"  Images failed: {self.stats.images_failed}")

        return self.stats
