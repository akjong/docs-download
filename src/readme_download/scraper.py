"""Core scraper module for ReadMe.com documentation sites."""

import asyncio
import hashlib
import os
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup, NavigableString, Tag
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn

console = Console()


@dataclass
class ScraperConfig:
    """Configuration for the ReadMe.com scraper."""

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
    images_downloaded: int = 0
    images_failed: int = 0


class HTMLToMarkdownConverter:
    """Convert HTML content to Markdown format."""

    def __init__(self, base_url: str, output_dir: str):
        self.base_url = base_url
        self.output_dir = output_dir
        self.images_to_download: list[tuple[str, str]] = []  # (url, local_path)
        self.current_page_url = ""

    def convert(self, element: Tag, page_url: str) -> str:
        """Convert BeautifulSoup element to Markdown."""
        if element is None:
            return ""

        self.images_to_download = []
        self.current_page_url = page_url

        lines: list[str] = []
        self._process_element(element, lines, depth=0)

        # Join lines and clean up
        markdown = "\n".join(lines)

        # Clean up excessive newlines
        markdown = re.sub(r"\n{4,}", "\n\n\n", markdown)

        # Remove trailing whitespace from each line
        markdown = "\n".join(line.rstrip() for line in markdown.split("\n"))

        return markdown.strip()

    def _get_text(self, element: Tag | NavigableString) -> str:
        """Get text content from element."""
        if isinstance(element, NavigableString):
            return str(element)
        return element.get_text()

    def _get_image_local_path(self, img_url: str) -> str:
        """Get local path for an image URL."""
        parsed = urlparse(img_url)
        path = parsed.path

        # Get the filename from the path
        filename = os.path.basename(path)
        if not filename or "." not in filename:
            # Generate a filename from URL hash
            url_hash = hashlib.md5(img_url.encode()).hexdigest()[:8]
            ext = ".png"
            # Try to get extension from content-type or URL
            if "." in path:
                ext = os.path.splitext(path)[1] or ".png"
            filename = f"image_{url_hash}{ext}"

        # Put images in an 'img' subdirectory
        return f"img/{filename}"

    def _process_image(self, element: Tag, lines: list) -> None:
        """Process an image element."""
        src = element.get("src", "")
        alt = element.get("alt", "")

        if not src:
            return

        # Make absolute URL
        if not src.startswith(("http://", "https://", "data:")):
            src = urljoin(self.current_page_url, src)

        # Skip data URLs
        if src.startswith("data:"):
            return

        # Get local path for the image
        local_img_path = self._get_image_local_path(src)
        full_local_path = os.path.join(self.output_dir, local_img_path)

        # Add to download queue
        self.images_to_download.append((src, full_local_path))

        # Use the relative path from output_dir
        lines.append(f"\n![{alt}]({local_img_path})\n")

    def _process_element(self, element: Tag | NavigableString, lines: list, depth: int = 0) -> None:
        """Process an HTML element and convert to Markdown."""
        if isinstance(element, NavigableString):
            text = str(element).strip()
            if text:
                if lines and not lines[-1].endswith("\n"):
                    lines.append(text)
                else:
                    lines.append(text)
            return

        if not isinstance(element, Tag):
            return

        tag_name = element.name.lower() if element.name else ""

        # Skip unwanted elements
        if tag_name in ["script", "style", "nav", "aside", "footer", "svg"]:
            return

        # Skip button elements but preserve code inside them
        if tag_name == "button":
            # Check if button contains useful text (not just icons)
            text = self._get_text(element).strip()
            if text and text not in [
                "Copy",
                "Copy to clipboard",
                "Copy Code",
                "Try It!",
                "Show full URL",
                "Yes",
                "No",
            ]:
                lines.append(text)
            return

        # Handle images
        if tag_name == "img":
            self._process_image(element, lines)
            return

        # Handle different tags
        if tag_name in ["h1", "h2", "h3", "h4", "h5", "h6"]:
            level = int(tag_name[1])
            # Remove anchor links before getting text
            for anchor in element.find_all("a"):
                anchor.decompose()
            text = self._get_text(element).strip()
            if text:
                # Remove "Skip link to" prefix
                text = re.sub(r"^Skip link to\s*", "", text)
                lines.append(f"\n{'#' * level} {text}\n")

        elif tag_name == "p":
            text_parts = []
            for child in element.children:
                if isinstance(child, NavigableString):
                    text_parts.append(str(child))
                elif isinstance(child, Tag):
                    text_parts.append(self._inline_element(child))
            text = "".join(text_parts).strip()
            if text:
                lines.append(f"\n{text}\n")

        elif tag_name == "pre":
            # Code block
            code_elem = element.find("code")
            if code_elem:
                code_text = code_elem.get_text()
                # Try to detect language from class
                classes = code_elem.get("class", [])
                lang = ""
                for cls in classes:
                    if isinstance(cls, str) and cls.startswith("language-"):
                        lang = cls.replace("language-", "")
                        break
                lines.append(f"\n```{lang}\n{code_text}\n```\n")
            else:
                lines.append(f"\n```\n{element.get_text()}\n```\n")

        elif tag_name == "code":
            # Inline code (not in pre)
            parent = element.parent
            if parent and parent.name != "pre":
                text = element.get_text()
                lines.append(f"`{text}`")

        elif tag_name == "ul":
            lines.append("")
            for li in element.find_all("li", recursive=False):
                li_text = self._process_list_item(li)
                lines.append(f"- {li_text}")
            lines.append("")

        elif tag_name == "ol":
            lines.append("")
            for i, li in enumerate(element.find_all("li", recursive=False), 1):
                li_text = self._process_list_item(li)
                lines.append(f"{i}. {li_text}")
            lines.append("")

        elif tag_name == "blockquote":
            text = self._get_text(element).strip()
            if text:
                quoted = "\n".join(f"> {line}" for line in text.split("\n"))
                lines.append(f"\n{quoted}\n")

        elif tag_name == "table":
            self._process_table(element, lines)

        elif tag_name == "a":
            # Check if there's an image inside the link
            img = element.find("img")
            if img:
                self._process_image(img, lines)
                return

            href = element.get("href", "")
            text = self._get_text(element).strip()
            # Skip navigation links
            if "Previous" in text or "Next" in text:
                return
            if href and text:
                if not href.startswith(("http://", "https://", "#", "mailto:")):
                    href = urljoin(self.base_url, href)
                lines.append(f"[{text}]({href})")

        elif tag_name == "br":
            lines.append("\n")

        elif tag_name == "hr":
            lines.append("\n---\n")

        elif tag_name == "figure":
            # Handle figure elements which often contain images
            img = element.find("img")
            if img:
                self._process_image(img, lines)
            figcaption = element.find("figcaption")
            if figcaption:
                caption = figcaption.get_text().strip()
                if caption:
                    lines.append(f"*{caption}*\n")

        elif tag_name in ["div", "section", "article", "main", "span"]:
            # Container elements - process children
            for child in element.children:
                self._process_element(child, lines, depth + 1)

        elif tag_name in ["strong", "b"]:
            text = self._get_text(element).strip()
            if text:
                lines.append(f"**{text}**")

        elif tag_name in ["em", "i"]:
            text = self._get_text(element).strip()
            if text:
                lines.append(f"*{text}*")

        else:
            # Process children for unknown elements
            for child in element.children:
                self._process_element(child, lines, depth + 1)

    def _inline_element(self, element: Tag) -> str:
        """Convert inline element to Markdown string."""
        if isinstance(element, NavigableString):
            return str(element)

        tag_name = element.name.lower() if element.name else ""

        if tag_name == "code":
            return f"`{element.get_text()}`"
        elif tag_name in ["strong", "b"]:
            return f"**{element.get_text()}**"
        elif tag_name in ["em", "i"]:
            return f"*{element.get_text()}*"
        elif tag_name == "a":
            # Check if there's an image inside the link
            img = element.find("img")
            if img:
                return self._inline_image(img)

            href = element.get("href", "")
            text = element.get_text().strip()
            if href and text:
                if not href.startswith(("http://", "https://", "#", "mailto:")):
                    href = urljoin(self.base_url, href)
                return f"[{text}]({href})"
            return text
        elif tag_name == "br":
            return "\n"
        elif tag_name == "img":
            return self._inline_image(element)
        else:
            return element.get_text()

    def _inline_image(self, element: Tag) -> str:
        """Process an image element and return Markdown string."""
        src = element.get("src", "")
        alt = element.get("alt", "")
        if src:
            if not src.startswith(("http://", "https://", "data:")):
                src = urljoin(self.current_page_url, src)
            if not src.startswith("data:"):
                local_img_path = self._get_image_local_path(src)
                full_local_path = os.path.join(self.output_dir, local_img_path)
                self.images_to_download.append((src, full_local_path))
                return f"![{alt}]({local_img_path})"
        return ""

    def _process_list_item(self, li: Tag) -> str:
        """Process a list item and return its text content."""
        parts = []
        for child in li.children:
            if isinstance(child, NavigableString):
                parts.append(str(child).strip())
            elif isinstance(child, Tag):
                if child.name in ["ul", "ol"]:
                    # Nested list - skip for now
                    continue
                parts.append(self._inline_element(child))
        return " ".join(parts).strip()

    def _process_table(self, table: Tag, lines: list) -> None:
        """Convert HTML table to Markdown table."""
        lines.append("")

        rows = table.find_all("tr")
        if not rows:
            return

        # Process header row
        header_row = rows[0]
        headers = [th.get_text().strip() for th in header_row.find_all(["th", "td"])]
        if headers:
            lines.append("| " + " | ".join(headers) + " |")
            lines.append("| " + " | ".join(["---"] * len(headers)) + " |")

        # Process data rows
        for row in rows[1:]:
            cells = [td.get_text().strip() for td in row.find_all(["td", "th"])]
            if cells:
                lines.append("| " + " | ".join(cells) + " |")

        lines.append("")


class ReadMeScraper:
    """Scraper for ReadMe.com documentation sites."""

    def __init__(self, config: ScraperConfig):
        self.config = config
        self.stats = ScraperStats()

        # Normalize base URL
        self.base_url = config.base_url.rstrip("/")
        parsed = urlparse(self.base_url)
        self.base_host = parsed.netloc
        self.base_path = parsed.path

        # URL tracking
        self.urls_to_process: list[str] = []
        self.downloaded_images: set[str] = set()
        self.discovered_urls: set[str] = set()

        # Semaphore for concurrency control
        self.semaphore = asyncio.Semaphore(config.concurrency)

        # HTML to Markdown converter
        self.converter = HTMLToMarkdownConverter(self.base_url, config.output_dir)

    def _get_local_path(self, url: str) -> str:
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
            relative_path = relative_path.rstrip("/")

        # Build full path
        file_path = os.path.join(self.config.output_dir, relative_path)

        # Add .md extension
        if not file_path.endswith(".md"):
            file_path += ".md"

        return file_path

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

            # Create directory if needed
            os.makedirs(os.path.dirname(local_path), exist_ok=True)

            # Save image
            with open(local_path, "wb") as f:
                f.write(response.content)

            self.downloaded_images.add(url)
            self.stats.images_downloaded += 1

            if self.config.verbose:
                console.print(f"[dim]Downloaded image: {local_path}[/dim]")

            return True

        except Exception as e:
            if self.config.verbose:
                console.print(f"[yellow]Error downloading image {url}: {e}[/yellow]")
            self.stats.images_failed += 1
            return False

    async def _extract_links_from_html(self, client: httpx.AsyncClient, url: str) -> list[str]:
        """Extract all documentation links from ReadMe.com HTML page."""
        links = []

        try:
            response = await client.get(url, timeout=self.config.timeout)
            if response.status_code != 200:
                return links

            soup = BeautifulSoup(response.text, "html.parser")

            # Find sidebar navigation (ReadMe uses nav elements with specific structure)
            nav_elements = soup.find_all("nav")

            for nav in nav_elements:
                for a_tag in nav.find_all("a", href=True):
                    href = a_tag["href"]

                    # Skip external links, anchors, and non-doc links
                    if href.startswith(("http://", "https://")):
                        if self.base_host not in href:
                            continue
                        # Check if it's under the same reference path
                        parsed_href = urlparse(href)
                        if self.base_path in parsed_href.path or "/reference" in parsed_href.path:
                            links.append(href)
                    elif href.startswith(("#", "javascript:", "mailto:", "tel:")):
                        continue
                    elif href.startswith("/"):
                        # Only include paths that are reference docs
                        if "/reference" in href or self.base_path in href:
                            full_url = f"https://{self.base_host}{href}"
                            links.append(full_url)

            # Also check for links in the main content area
            main = soup.find("main")
            if main:
                for a_tag in main.find_all("a", href=True):
                    href = a_tag["href"]
                    if href.startswith("/reference"):
                        full_url = f"https://{self.base_host}{href}"
                        if full_url not in links:
                            links.append(full_url)

        except Exception as e:
            if self.config.verbose:
                console.print(f"[yellow]Failed to extract links from {url}: {e}[/yellow]")

        return list(set(links))

    async def _discover_all_links(self, client: httpx.AsyncClient) -> list[str]:
        """Recursively discover all links from the documentation site."""
        urls_to_visit = [self.base_url]
        all_urls = set()

        while urls_to_visit:
            current_url = urls_to_visit.pop(0)

            if current_url in self.discovered_urls:
                continue

            self.discovered_urls.add(current_url)
            all_urls.add(current_url)

            if self.config.verbose:
                console.print(f"[dim]Discovering links from: {current_url}[/dim]")

            # Extract links from current page
            links = await self._extract_links_from_html(client, current_url)

            for link in links:
                # Normalize URL (remove trailing slashes, anchors)
                parsed = urlparse(link)
                normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                normalized = normalized.rstrip("/")

                # Filter to only include URLs under base path
                if normalized not in self.discovered_urls and self.base_host in normalized:
                    urls_to_visit.append(normalized)
                    all_urls.add(normalized)

        return list(all_urls)

    def _extract_content(self, html: str) -> tuple[str, Tag | None]:
        """Extract title and main content from HTML page."""
        soup = BeautifulSoup(html, "html.parser")

        # Extract title
        title = ""
        h1 = soup.find("h1")
        if h1:
            title = h1.get_text().strip()
        elif soup.title:
            title = soup.title.get_text().split("|")[0].strip()

        # Find main content - ReadMe uses article elements inside main
        article = soup.find("article")
        if not article:
            article = soup.find("main")
        if not article:
            article = soup.find("div", {"role": "main"})

        if article:
            # Remove unwanted elements
            for elem in article.find_all(["nav", "aside", "footer"]):
                elem.decompose()

            # Remove buttons but keep their text if relevant
            for btn in article.find_all("button"):
                btn_text = btn.get_text().strip()
                # Keep meaningful button text as plain text
                if btn_text and btn_text not in [
                    "Copy",
                    "Copy to clipboard",
                    "Copy Code",
                    "Try It!",
                    "Show full URL",
                    "Yes",
                    "No",
                    "RESPONSE",
                ]:
                    btn.replace_with(btn_text + " ")
                else:
                    btn.decompose()

            # Remove "Previous/Next" navigation
            for nav in article.find_all("nav", {"aria-label": "Pagination Controls"}):
                nav.decompose()

            # Remove "Did this page help you?" section
            for elem in article.find_all(string=re.compile(r"Did this page help you")):
                parent = elem.find_parent()
                if parent:
                    # Go up to find the layout table containing this
                    for _ in range(5):
                        if parent.name in ["table", "div"] and "help" in parent.get_text().lower():
                            parent.decompose()
                            break
                        parent = parent.find_parent()
                        if not parent:
                            break

            # Remove "Updated X ago" text
            for elem in article.find_all(string=re.compile(r"Updated\s+.*ago")):
                parent = elem.find_parent()
                if parent:
                    parent.decompose()

            # Remove table of contents nav on the right
            for elem in article.find_all("nav", {"aria-label": "Table of contents"}):
                elem.decompose()

            # Remove recent requests section
            for elem in article.find_all(string=re.compile(r"Recent Requests")):
                parent = elem.find_parent()
                if parent:
                    # Find the section containing this
                    for _ in range(5):
                        if parent.name == "section" or (
                            hasattr(parent, "get") and "Recent" in parent.get_text()[:50]
                        ):
                            parent.decompose()
                            break
                        parent = parent.find_parent()
                        if not parent:
                            break

            # Remove language selector and code sample sections (right panel)
            for elem in article.find_all(string=re.compile(r"^LANGUAGE$")):
                parent = elem.find_parent()
                if parent:
                    # Find the container div
                    for _ in range(10):
                        parent = parent.find_parent()
                        if not parent:
                            break
                        # Check if this is the right panel container
                        if parent.name == "div" and parent.find(string=re.compile(r"Try It!")):
                            parent.decompose()
                            break

            # Remove Log in prompts
            for elem in article.find_all(string=re.compile(r"Log in to see")):
                parent = elem.find_parent()
                if parent:
                    for _ in range(3):
                        parent = parent.find_parent()
                        if not parent:
                            break
                    if parent:
                        parent.decompose()

        return title, article

    async def _process_url(
        self, client: httpx.AsyncClient, url: str, progress: Progress, task_id
    ) -> bool:
        """Process a single URL: download HTML, convert to Markdown, download images, and save."""
        local_path = self._get_local_path(url)

        # Skip if file exists and skip_existing is enabled
        if self.config.skip_existing and os.path.exists(local_path):
            self.stats.skipped += 1
            if self.config.verbose:
                console.print(f"[dim]Skipped (exists): {local_path}[/dim]")
            progress.update(task_id, advance=1)
            return True

        try:
            async with self.semaphore:
                response = await client.get(url, timeout=self.config.timeout)

            if response.status_code != 200:
                self.stats.failed += 1
                if self.config.verbose:
                    console.print(f"[yellow]Failed ({response.status_code}): {url}[/yellow]")
                progress.update(task_id, advance=1)
                return False

            # Extract content
            title, content = self._extract_content(response.text)

            if content:
                # Convert to Markdown (this also collects images to download)
                markdown = self.converter.convert(content, url)

                # Download images
                for img_url, img_local_path in self.converter.images_to_download:
                    await self._download_image(client, img_url, img_local_path)

                # Add title if not already in content
                if title and not markdown.startswith(f"# {title}"):
                    markdown = f"# {title}\n\n{markdown}"

                # Skip files with minimal content (just a title, no real content)
                content_without_title = re.sub(r"^#\s+[^\n]+\n*", "", markdown).strip()
                if len(content_without_title) < 10:
                    self.stats.skipped += 1
                    if self.config.verbose:
                        console.print(f"[dim]Skipped (no content): {local_path}[/dim]")
                    progress.update(task_id, advance=1)
                    return True

                # Create directory and save file
                os.makedirs(os.path.dirname(local_path), exist_ok=True)

                with open(local_path, "w", encoding="utf-8") as f:
                    f.write(markdown)

                self.stats.downloaded += 1
                if self.config.verbose:
                    console.print(f"[green]Downloaded: {local_path}[/green]")
            else:
                self.stats.failed += 1
                if self.config.verbose:
                    console.print(f"[yellow]No content found: {url}[/yellow]")

        except Exception as e:
            self.stats.failed += 1
            if self.config.verbose:
                console.print(f"[red]Error processing {url}: {e}[/red]")

        progress.update(task_id, advance=1)
        return True

    async def run(self) -> ScraperStats:
        """Run the scraper."""
        console.print("[bold blue]ReadMe.com Scraper[/bold blue]")
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
            # Discover all URLs by crawling the navigation
            console.print("[cyan]Discovering pages from navigation...[/cyan]")
            urls = await self._discover_all_links(client)

            # Filter URLs to only include those under base_url or /reference path
            urls = [u for u in urls if "/reference" in u or u.startswith(self.base_url)]

            # Deduplicate and sort
            urls = sorted(set(urls))

            # Always include base URL
            if self.base_url not in urls:
                urls.insert(0, self.base_url)

            self.stats.discovered = len(urls)
            console.print(f"[green]Found {len(urls)} pages to download[/green]")
            console.print()

            if not urls:
                console.print("[yellow]No pages found to download[/yellow]")
                return self.stats

            # Process all URLs
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                console=console,
            ) as progress:
                task_id = progress.add_task("[cyan]Downloading pages...", total=len(urls))

                # Create tasks for all URLs
                tasks = [self._process_url(client, url, progress, task_id) for url in urls]

                # Run with concurrency limit (semaphore handles this)
                await asyncio.gather(*tasks)

        # Print summary
        console.print()
        console.print("[bold green]✓ Scraping complete![/bold green]")
        console.print(f"  Discovered: {self.stats.discovered} pages")
        console.print(f"  Downloaded: {self.stats.downloaded} files")
        console.print(f"  Skipped: {self.stats.skipped} files")
        console.print(f"  Failed: {self.stats.failed} pages")
        console.print(f"  Images downloaded: {self.stats.images_downloaded}")
        console.print(f"  Images failed: {self.stats.images_failed}")

        return self.stats
