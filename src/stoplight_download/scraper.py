"""Core scraper module for Stoplight documentation sites."""

import asyncio
import hashlib
import os
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

import httpx
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskID, TaskProgressColumn, TextColumn

console = Console()


@dataclass
class ScraperConfig:
    """Configuration for the Stoplight scraper."""

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


class StoplightScraper:
    """Scraper for Stoplight documentation sites."""

    def __init__(self, config: ScraperConfig):
        self.config = config
        self.stats = ScraperStats()

        # Normalize base URL
        self.base_url = config.base_url.rstrip("/")
        # Ensure base_url ends with / for proper path handling
        if not self.base_url.endswith("/"):
            self.base_url += "/"
        parsed = urlparse(self.base_url)
        self.base_host = parsed.netloc

        # Extract project name from URL (e.g., "prism" from /docs/prism/)
        path_match = re.match(r"/docs/([^/]+)", parsed.path)
        self.project_name = path_match.group(1) if path_match else "docs"

        # URL tracking
        self.visited_urls: set[str] = set()
        self.urls_to_visit: asyncio.Queue[str] = asyncio.Queue()
        self.downloaded_paths: set[str] = set()
        self.downloaded_images: set[str] = set()

        # Semaphore for concurrency control
        self.semaphore = asyncio.Semaphore(config.concurrency)

    def _normalize_url(self, url: str) -> str:
        """Normalize URL by removing trailing slashes and fragments."""
        parsed = urlparse(url)
        normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}"
        return normalized

    def _is_valid_doc_url(self, url: str) -> bool:
        """Check if URL is a valid documentation page under base_url."""
        parsed = urlparse(url)

        # Must be same host
        if parsed.netloc != self.base_host:
            return False

        # Must start with /docs/{project}/
        if not re.match(rf"/docs/{re.escape(self.project_name)}/", parsed.path):
            return False

        # Skip non-doc paths
        skip_patterns = [
            r"/api/",
            r"\.(js|css|png|jpg|jpeg|gif|svg|ico|woff|woff2|ttf|eot)$",
            r"/static/",
        ]
        for pattern in skip_patterns:
            if re.search(pattern, parsed.path):
                return False

        return True

    def _get_local_path(self, url: str) -> str:
        """Convert URL to local file path."""
        parsed = urlparse(url)
        path = parsed.path

        # Remove /docs/{project}/ prefix
        match = re.match(rf"/docs/{re.escape(self.project_name)}/?(.*)", path)
        if match:
            relative_path = match.group(1)
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

    async def _extract_content_from_page(self, page) -> str | None:
        """Extract markdown content from a Playwright page."""
        try:
            # Wait for page to be mostly loaded
            await page.wait_for_load_state("domcontentloaded", timeout=20000)

            # Wait for JS to render content
            await asyncio.sleep(3)

            # Use Playwright's evaluate to get the rendered content
            # This is more reliable for SPAs
            content_html = await page.evaluate("""() => {
                // Get the entire document HTML
                return document.documentElement.outerHTML;
            }""")

            if not content_html:
                if self.config.verbose:
                    console.print("[yellow]No content returned from evaluate[/yellow]")
                return None

            # Debug: check content length
            if self.config.verbose:
                console.print(f"[dim]Content length from evaluate: {len(content_html)}[/dim]")

            # Parse with BeautifulSoup
            soup = BeautifulSoup(content_html, "html.parser")

            # Remove navigation and sidebar elements
            for tag in soup.find_all(["nav", "aside", "footer", "header"]):
                tag.decompose()

            # Find the body or main content
            body = soup.find("body")
            if body:
                main = body
            else:
                main = soup

            # Convert to markdown using html2text
            try:
                import html2text

                h = html2text.HTML2Text()
                h.body_width = 0
                markdown = h.handle(str(main))
                # If markdown is very short, try getting text directly
                if len(markdown.strip()) < 100:
                    return main.get_text(separator="\n", strip=True)
                return markdown
            except Exception:
                # Fallback: extract text
                return main.get_text(separator="\n", strip=True)

        except Exception as e:
            if self.config.verbose:
                console.print(f"[yellow]Error extracting content: {e}[/yellow]")
            return None

    async def _extract_links_from_page(self, page) -> list[str]:
        """Extract internal links from the page sidebar."""
        links = []

        try:
            # Get all links from the page
            html_content = await page.content()
            soup = BeautifulSoup(html_content, "html.parser")

            # Debug: print number of links found
            all_links = soup.find_all("a", href=True)
            if self.config.verbose:
                console.print(f"[dim]Found {len(all_links)} total links[/dim]")

            # Find all anchor tags with href
            for a_tag in all_links:
                href = str(a_tag.get("href", ""))

                # Skip external links, anchors, and javascript
                if href.startswith(("http://", "https://")) and self.base_host not in href:
                    continue
                if href.startswith(("#", "javascript:", "mailto:", "tel:")):
                    continue

                # Convert to absolute URL
                if not href.startswith(("http://", "https://")):
                    absolute_url = urljoin(self.base_url, href)
                else:
                    absolute_url = href

                normalized = self._normalize_url(absolute_url)

                if self._is_valid_doc_url(normalized):
                    links.append(normalized)

        except Exception as e:
            if self.config.verbose:
                console.print(f"[yellow]Error extracting links: {e}[/yellow]")

        return list(set(links))

    async def _fetch_sitemap_urls(self, client: httpx.AsyncClient) -> list[str]:
        """Fetch all page URLs from sitemap.xml."""
        urls = []

        parsed_base = urlparse(self.base_url)
        sitemap_url = f"{parsed_base.scheme}://{parsed_base.netloc}/sitemap.xml"

        try:
            response = await client.get(sitemap_url, timeout=self.config.timeout)
            if response.status_code != 200:
                return urls

            root = ElementTree.fromstring(response.content)

            for elem in root.iter():
                if elem.tag.endswith("loc"):
                    if elem.text:
                        urls.append(elem.text)

            if self.config.verbose and urls:
                console.print(f"[green]Found {len(urls)} URLs in sitemap[/green]")

        except Exception as e:
            if self.config.verbose:
                console.print(f"[dim]Could not fetch sitemap {sitemap_url}: {e}[/dim]")

        return urls

    async def _process_url(
        self,
        browser,
        page,
        client: httpx.AsyncClient,
        url: str,
        progress: Progress,
        task_id: TaskID,
    ) -> None:
        """Process a single URL: download content and discover new links."""
        # Navigate to the page
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=self.config.timeout * 1000)
        except Exception as e:
            self.stats.failed += 1
            if self.config.verbose:
                console.print(f"[yellow]Failed to load {url}: {e}[/yellow]")
            progress.update(task_id, advance=1)
            return

        # Extract content with its own timeout handling
        try:
            content = await self._extract_content_from_page(page)
        except Exception as e:
            if self.config.verbose:
                console.print(f"[yellow]Error extracting content from {url}: {e}[/yellow]")
            content = None

        if content:
            local_path = self._get_local_path(url)

            # Process images in content
            content_str = content

            # Find image references
            img_pattern = r"!\[([^\]]*)\]\(([^)]+)\)"
            matches = re.findall(img_pattern, content_str)

            for alt, img_url in matches:
                # Skip data URLs and blob URLs
                if not img_url or img_url.startswith(("data:", "blob:")):
                    continue

                if not img_url.startswith(("http://", "https://")):
                    img_url_abs = urljoin(url, img_url)
                else:
                    img_url_abs = img_url

                # Skip blob URLs after join
                if img_url_abs.startswith("blob:"):
                    continue

                local_img_path = self._get_image_local_path(img_url_abs)
                await self._download_image(client, img_url_abs, local_img_path)
                content_str = content_str.replace(
                    f"![{alt}]({img_url})", f"![{alt}]({local_img_path})"
                )

            # Skip if file exists
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

        # Extract links for discovery
        new_links = await self._extract_links_from_page(page)

        for link in new_links:
            if link not in self.visited_urls:
                self.visited_urls.add(link)
                await self.urls_to_visit.put(link)
                self.stats.discovered += 1

        progress.update(task_id, advance=1)

    async def _worker(
        self,
        browser,
        page,
        client: httpx.AsyncClient,
        progress: Progress,
        task_id: TaskID,
    ) -> None:
        """Worker coroutine that processes URLs from the queue."""
        while True:
            try:
                url = await asyncio.wait_for(self.urls_to_visit.get(), timeout=5.0)
            except asyncio.TimeoutError:
                break

            try:
                await self._process_url(browser, page, client, url, progress, task_id)
            except Exception as e:
                if self.config.verbose:
                    console.print(f"[red]Error processing {url}: {e}[/red]")
            finally:
                self.urls_to_visit.task_done()

    async def run(self) -> ScraperStats:
        """Run the scraper."""
        console.print("[bold blue]Stoplight Scraper[/bold blue]")
        console.print(f"  Base URL: {self.base_url}")
        console.print(f"  Output: {self.config.output_dir}")
        console.print(f"  Concurrency: {self.config.concurrency}")
        console.print()

        os.makedirs(self.config.output_dir, exist_ok=True)

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            async with httpx.AsyncClient(
                follow_redirects=True,
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
                },
            ) as client:
                # Try sitemap first
                sitemap_urls = await self._fetch_sitemap_urls(client)
                project_urls = [
                    url
                    for url in sitemap_urls
                    if re.search(rf"/docs/{re.escape(self.project_name)}/", url)
                ]

                if project_urls:
                    for url in project_urls:
                        normalized = self._normalize_url(url)
                        if normalized not in self.visited_urls and self._is_valid_doc_url(
                            normalized
                        ):
                            self.visited_urls.add(normalized)
                            await self.urls_to_visit.put(normalized)
                            self.stats.discovered += 1
                else:
                    # Fallback: start with base URL
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
                    task_id: TaskID = progress.add_task("[cyan]Processing pages...", total=None)

                    workers = [
                        asyncio.create_task(self._worker(browser, page, client, progress, task_id))
                        for _ in range(self.config.concurrency)
                    ]

                    await self.urls_to_visit.join()

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
