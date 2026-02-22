"""Core scraper module for Nextra documentation sites."""

import asyncio
import hashlib
import os
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskID, TaskProgressColumn, TextColumn

console = Console()


@dataclass
class ScraperConfig:
    """Configuration for the Nextra scraper."""

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


class NextraScraper:
    """Scraper for Nextra documentation sites."""

    def __init__(self, config: ScraperConfig):
        self.config = config
        self.stats = ScraperStats()

        self.base_url = config.base_url.rstrip("/")
        if not self.base_url.endswith("/"):
            self.base_url += "/"
        parsed = urlparse(self.base_url)
        self.base_host = parsed.netloc
        self.base_path = parsed.path.rstrip("/")

        self.visited_urls: set[str] = set()
        self.urls_to_visit: asyncio.Queue[str] = asyncio.Queue()
        self.downloaded_paths: set[str] = set()
        self.downloaded_images: set[str] = set()

        self.semaphore = asyncio.Semaphore(config.concurrency)

    def _normalize_url(self, url: str) -> str:
        """Normalize URL by removing trailing slashes and fragments."""
        parsed = urlparse(url)
        normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}"
        return normalized

    def _is_valid_doc_url(self, url: str) -> bool:
        """Check if URL is a valid documentation page under base_url."""
        parsed = urlparse(url)

        if parsed.netloc != self.base_host:
            return False

        if self.base_path and not parsed.path.startswith(self.base_path):
            return False

        skip_patterns = [
            r"/api/",
            r"/_next/",
            r"/assets/",
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

        if self.base_path and path.startswith(self.base_path):
            relative_path = path[len(self.base_path) :].lstrip("/")
        else:
            relative_path = path.lstrip("/")

        if not relative_path:
            relative_path = "index"

        if relative_path.endswith("/"):
            relative_path = relative_path.rstrip("/") + "/index"

        file_path = os.path.join(self.config.output_dir, relative_path)

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

    def _extract_title(self, soup: BeautifulSoup) -> str:
        """Extract the page title from the HTML."""
        title = soup.find("title")
        if title:
            return title.get_text(strip=True)

        h1 = soup.find("h1")
        if h1:
            return h1.get_text(strip=True)

        return "Untitled"

    def _extract_content_from_soup(self, soup: BeautifulSoup, url: str) -> str:
        """Extract markdown content from BeautifulSoup."""
        for tag in soup.find_all(["nav", "aside", "footer", "header", "script", "style"]):
            tag.decompose()

        content_elem = (
            soup.find("article")
            or soup.find("main")
            or soup.find("div", class_="nextra-content")
            or soup.find("div", class_="content")
            or soup.find("body")
        )

        if not content_elem:
            content_elem = soup

        for tag in content_elem.find_all(["nav", "aside", "footer", "script", "style"]):
            tag.decompose()

        try:
            import html2text

            h = html2text.HTML2Text()
            h.body_width = 0
            markdown = h.handle(str(content_elem))
            if len(markdown.strip()) < 100:
                return content_elem.get_text(separator="\n", strip=True)
            return markdown
        except Exception:
            return content_elem.get_text(separator="\n", strip=True)

    def _extract_links_from_html(self, html_content: str, base_url: str) -> list[str]:
        """Extract internal links from HTML content."""
        links = []
        soup = BeautifulSoup(html_content, "html.parser")
        all_links = soup.find_all("a", href=True)

        for a_tag in all_links:
            href = str(a_tag.get("href", ""))

            if href.startswith(("http://", "https://")) and self.base_host not in href:
                continue
            if href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue

            if not href.startswith(("http://", "https://")):
                absolute_url = urljoin(base_url, href)
            else:
                absolute_url = href

            normalized = self._normalize_url(absolute_url)

            if self._is_valid_doc_url(normalized):
                links.append(normalized)

        return list(set(links))

    async def _process_url(
        self,
        client: httpx.AsyncClient,
        url: str,
        progress: Progress,
        task_id: TaskID,
    ) -> None:
        """Process a single URL: download content and discover new links."""
        try:
            response = await client.get(url, timeout=self.config.timeout, follow_redirects=True)

            if response.status_code != 200:
                self.stats.failed += 1
                if self.config.verbose:
                    console.print(f"[yellow]Failed to load {url}: {response.status_code}[/yellow]")
                progress.update(task_id, advance=1)
                return

            html_content = response.text
            soup = BeautifulSoup(html_content, "html.parser")
            content = self._extract_content_from_soup(soup, url)

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

            new_links = self._extract_links_from_html(html_content, url)

            for link in new_links:
                if link not in self.visited_urls:
                    self.visited_urls.add(link)
                    await self.urls_to_visit.put(link)
                    self.stats.discovered += 1

            progress.update(task_id, advance=1)

        except Exception as e:
            self.stats.failed += 1
            if self.config.verbose:
                console.print(f"[red]Error processing {url}: {e}[/red]")
            progress.update(task_id, advance=1)

    async def _worker(
        self,
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
                await self._process_url(client, url, progress, task_id)
            except Exception as e:
                if self.config.verbose:
                    console.print(f"[red]Error processing {url}: {e}[/red]")
            finally:
                self.urls_to_visit.task_done()

    async def run(self) -> ScraperStats:
        """Run the scraper."""
        console.print("[bold blue]Nextra Scraper[/bold blue]")
        console.print(f"  Base URL: {self.base_url}")
        console.print(f"  Output: {self.config.output_dir}")
        console.print(f"  Concurrency: {self.config.concurrency}")
        console.print()

        os.makedirs(self.config.output_dir, exist_ok=True)

        async with httpx.AsyncClient(
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            },
        ) as client:
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
                    asyncio.create_task(self._worker(client, progress, task_id))
                    for _ in range(self.config.concurrency)
                ]

                await self.urls_to_visit.join()

                for worker in workers:
                    worker.cancel()

                await asyncio.gather(*workers, return_exceptions=True)

        console.print()
        console.print("[bold green]✓ Scraping complete![/bold green]")
        console.print(f"  Discovered: {self.stats.discovered} pages")
        console.print(f"  Downloaded: {self.stats.downloaded} files")
        console.print(f"  Skipped: {self.stats.skipped} files")
        console.print(f"  Failed: {self.stats.failed} pages")
        console.print(f"  Images downloaded: {self.stats.images_downloaded}")
        console.print(f"  Images failed: {self.stats.images_failed}")

        return self.stats
