"""Core scraper module for Manus blog."""

import asyncio
import hashlib
import os
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn

console = Console()


@dataclass
class ScraperConfig:
    """Configuration for the Manus blog scraper."""

    base_url: str
    output_dir: str = "./downloaded_docs"
    concurrency: int = 1
    skip_existing: bool = False
    verbose: bool = False
    timeout: float = 60.0


@dataclass
class ScraperStats:
    """Statistics for the scraping process."""

    discovered: int = 0
    downloaded: int = 0
    skipped: int = 0
    failed: int = 0
    images_downloaded: int = 0
    images_failed: int = 0


class ManusScraper:
    """Scraper for Manus blog using Playwright for JS rendering."""

    def __init__(self, config: ScraperConfig):
        self.config = config
        self.stats = ScraperStats()

        self.base_url = config.base_url.rstrip("/")
        parsed = urlparse(self.base_url)
        self.base_host = parsed.netloc
        self.base_path = parsed.path

        self.visited_urls: set[str] = set()
        self.urls_to_visit: asyncio.Queue[str] = asyncio.Queue()
        self.downloaded_images: set[str] = set()
        self.image_lock = asyncio.Lock()

    def _normalize_url(self, url: str) -> str:
        """Normalize URL by removing trailing slashes and fragments."""
        parsed = urlparse(url)
        normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}"
        return normalized

    def _get_local_path(self, url: str) -> str:
        """Convert URL to local file path."""
        parsed = urlparse(url)
        path = parsed.path

        if path.startswith(self.base_path):
            relative_path = path[len(self.base_path) :].lstrip("/")
        else:
            relative_path = path.lstrip("/")

        if not relative_path:
            relative_path = "index"

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
        async with self.image_lock:
            if url in self.downloaded_images:
                return True

        try:
            response = await client.get(url, timeout=self.config.timeout)

            if response.status_code != 200:
                if self.config.verbose:
                    console.print(
                        f"[yellow]Failed to download image ({response.status_code}): {url}[/yellow]"
                    )
                async with self.image_lock:
                    self.stats.images_failed += 1
                return False

            full_path = os.path.join(self.config.output_dir, local_path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)

            with open(full_path, "wb") as f:
                f.write(response.content)

            async with self.image_lock:
                self.downloaded_images.add(url)
                self.stats.images_downloaded += 1

            if self.config.verbose:
                console.print(f"[dim]Downloaded image: {full_path}[/dim]")

            return True

        except Exception as e:
            if self.config.verbose:
                console.print(f"[yellow]Error downloading image {url}: {e}[/yellow]")
            async with self.image_lock:
                self.stats.images_failed += 1
            return False

    def _convert_playwright_content_to_markdown(
        self, client: httpx.AsyncClient, url: str, page_content: str
    ) -> str:
        """Convert Playwright page content to Markdown format."""
        soup = BeautifulSoup(page_content, "html.parser")

        md_lines = []

        main = soup.find("main")

        if not main:
            return ""

        title = main.find("h1")
        if title:
            md_lines.append(f"# {title.get_text(strip=True)}")
            md_lines.append("")

        for div in main.find_all("div"):
            text = div.get_text(strip=True)

            if not text or text == "Less structure,more intelligence.":
                continue

            if text in ["Product", "Resources", "Community", "Compare", "Download", "Company"]:
                continue

            if any(
                skip in text
                for skip in [
                    "Features",
                    "Resources",
                    "Events",
                    "Pricing",
                    "Get started",
                    "English",
                    "Deutsch",
                ]
            ):
                if len(text) < 50:
                    continue

            if text.startswith("Manus is now part of"):
                continue

            if text.startswith("Less structure"):
                continue

            if div.find_previous_sibling("div") and div.find_previous_sibling("div").get_text(
                strip=True
            ) in [
                "Key Capabilities",
                "Why It Matters",
                "How to Get Started",
                "Frequently Asked Questions",
                "Availability",
            ]:
                md_lines.append(f"### {div.find_previous_sibling('div').get_text(strip=True)}")

            lines = text.split("\n")
            for line in lines:
                line = line.strip()
                if line:
                    md_lines.append(line)

            md_lines.append("")

        return "\n".join(md_lines)

    async def _process_url(self, page, client: httpx.AsyncClient, url: str) -> None:
        """Process a single URL: download and convert to markdown."""
        try:
            await page.goto(url, timeout=self.config.timeout * 1000, wait_until="domcontentloaded")

            await asyncio.sleep(8)

            content = await page.content()

            markdown = self._convert_playwright_content_to_markdown(client, url, content)

            local_path = self._get_local_path(url)

            if self.config.skip_existing and os.path.exists(local_path):
                self.stats.skipped += 1
                if self.config.verbose:
                    console.print(f"[dim]Skipped (exists): {local_path}[/dim]")
            else:
                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                with open(local_path, "w", encoding="utf-8") as f:
                    f.write(markdown)

                self.stats.downloaded += 1
                if self.config.verbose:
                    console.print(f"[green]Downloaded: {local_path}[/green]")

        except Exception as e:
            self.stats.failed += 1
            console.print(f"[red]Error processing {url}: {e}[/red]")

    async def run(self, article_slugs: list[str]) -> ScraperStats:
        """Run the scraper."""
        console.print("[bold blue]Manus Blog Scraper[/bold blue]")
        console.print(f"  Base URL: {self.base_url}")
        console.print(f"  Output: {self.config.output_dir}")
        console.print(f"  Articles: {len(article_slugs)}")
        console.print()

        os.makedirs(self.config.output_dir, exist_ok=True)

        async with httpx.AsyncClient(
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            },
        ) as client:
            for slug in article_slugs:
                if slug.startswith("/"):
                    url = f"https://{self.base_host}{slug}"
                else:
                    url = f"https://{self.base_host}/blog/{slug}"

                normalized = self._normalize_url(url)
                if normalized not in self.visited_urls:
                    self.visited_urls.add(normalized)
                    self.stats.discovered += 1

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                console=console,
            ) as progress:
                task_id = progress.add_task(
                    "[cyan]Downloading articles...", total=self.stats.discovered
                )

                async with async_playwright() as p:
                    browser = await p.chromium.launch(headless=True)
                    context = await browser.new_context(
                        viewport={"width": 1920, "height": 1080},
                        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    )
                    page = await context.new_page()

                    page.set_default_timeout(self.config.timeout * 1000)

                    for url in self.visited_urls:
                        await self._process_url(page, client, url)
                        progress.update(task_id, advance=1)

                    await context.close()
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
