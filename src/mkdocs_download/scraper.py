"""Core scraper module for MkDocs documentation sites."""

import asyncio
import hashlib
import os
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

import httpx
from bs4 import BeautifulSoup, NavigableString, Tag
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn

console = Console()


@dataclass
class ScraperConfig:
    """Configuration for the MkDocs scraper."""

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
    """Convert HTML content to Markdown format for MkDocs sites."""

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
        if not filename:
            # Generate a filename from URL hash
            url_hash = hashlib.md5(img_url.encode()).hexdigest()[:8]
            filename = f"image_{url_hash}.png"

        # Get the base path from base_url
        base_parsed = urlparse(self.base_url)
        base_path = base_parsed.path.rstrip("/")

        # Try to preserve the original image path structure
        if path.startswith(base_path):
            relative_img_path = path[len(base_path) :].lstrip("/")
        else:
            # Keep the path structure from the URL
            relative_img_path = path.lstrip("/")

        return relative_img_path

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
        if tag_name in ["script", "style", "nav", "footer", "button", "svg"]:
            return

        # Handle images
        if tag_name == "img":
            self._process_image(element, lines)
            return

        # Handle different tags
        if tag_name in ["h1", "h2", "h3", "h4", "h5", "h6"]:
            level = int(tag_name[1])
            # Remove anchor links and headerlink (MkDocs specific)
            for anchor in element.find_all("a", class_="headerlink"):
                anchor.decompose()
            for anchor in element.find_all("a"):
                if anchor.get("class") and "headerlink" in anchor.get("class", []):
                    anchor.decompose()
            text = self._get_text(element).strip()
            # Remove paragraph symbol (¶) commonly used in MkDocs
            text = text.replace("¶", "").strip()
            if text:
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
                    if isinstance(cls, str):
                        if cls.startswith("language-"):
                            lang = cls.replace("language-", "")
                            break
                        # MkDocs/Pygments style
                        if cls.startswith("highlight-"):
                            lang = cls.replace("highlight-", "")
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

        # Handle MkDocs admonitions (note, warning, tip, etc.)
        elif tag_name == "div" and element.get("class"):
            classes = element.get("class", [])
            if isinstance(classes, list) and "admonition" in classes:
                self._process_admonition(element, lines)
            else:
                # Container elements - process children
                for child in element.children:
                    self._process_element(child, lines, depth + 1)

        elif tag_name == "a":
            # Check if this is a glightbox image link (MkDocs image lightbox)
            classes = element.get("class", [])
            if "glightbox" in classes:
                # This is an image lightbox, process the image inside
                img = element.find("img")
                if img:
                    self._process_image(img, lines)
                return

            href = element.get("href", "")
            text = self._get_text(element).strip()
            # Skip navigation links and headerlinks
            if "headerlink" in classes:
                return
            if "¶" in text:
                return

            # Check if there's an image inside the link
            img = element.find("img")
            if img:
                self._process_image(img, lines)
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

        elif tag_name in ["section", "article", "main", "span", "aside"]:
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
            # Check if this is a glightbox image link (MkDocs image lightbox)
            classes = element.get("class", [])
            if isinstance(classes, list) and "glightbox" in classes:
                img = element.find("img")
                if img:
                    return self._inline_image(img)
                return ""

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

    def _process_admonition(self, element: Tag, lines: list) -> None:
        """Process MkDocs admonition (note, warning, tip, etc.)."""
        classes = element.get("class", [])
        admonition_type = "note"

        # Find admonition type from classes
        type_mapping = {
            "note": "Note",
            "warning": "Warning",
            "tip": "Tip",
            "info": "Info",
            "danger": "Danger",
            "success": "Success",
            "question": "Question",
            "abstract": "Abstract",
            "example": "Example",
            "quote": "Quote",
            "bug": "Bug",
            "failure": "Failure",
        }

        for cls in classes:
            if cls in type_mapping:
                admonition_type = type_mapping[cls]
                break

        # Get title
        title_elem = element.find("p", class_="admonition-title")
        title = title_elem.get_text().strip() if title_elem else admonition_type

        # Get content
        content_parts = []
        for child in element.children:
            if isinstance(child, Tag):
                if "admonition-title" not in (child.get("class") or []):
                    content_parts.append(child.get_text().strip())

        content = " ".join(content_parts)

        # Format as blockquote with title
        lines.append(f"\n> **{title}**")
        for line in content.split("\n"):
            if line.strip():
                lines.append(f"> {line.strip()}")
        lines.append("")


class MkDocsScraper:
    """Scraper for MkDocs documentation sites."""

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
            if not relative_path:
                relative_path = "index"

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

    async def _fetch_sitemap_urls(self, client: httpx.AsyncClient) -> list[str]:
        """Fetch all page URLs from MkDocs sitemap."""
        urls = []

        # Try to fetch sitemap.xml
        sitemap_url = f"{self.base_url}/sitemap.xml"

        # Also try parent domain sitemap if base_url has a subpath
        parsed = urlparse(self.base_url)
        parent_sitemap_url = f"{parsed.scheme}://{parsed.netloc}/sitemap.xml"

        sitemap_urls_to_try = [sitemap_url]
        if sitemap_url != parent_sitemap_url:
            sitemap_urls_to_try.append(parent_sitemap_url)

        for smap_url in sitemap_urls_to_try:
            try:
                response = await client.get(smap_url, timeout=self.config.timeout)
                if response.status_code != 200:
                    if self.config.verbose:
                        console.print(f"[dim]Could not fetch sitemap: {smap_url}[/dim]")
                    continue

                # Parse sitemap
                root = ElementTree.fromstring(response.content)

                # Handle namespace
                ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

                # Check if this is a sitemap index or urlset
                if root.tag.endswith("sitemapindex"):
                    # This is a sitemap index, fetch each child sitemap
                    sitemap_locs = root.findall(".//sm:loc", ns)
                    for loc in sitemap_locs:
                        if loc.text:
                            child_urls = await self._fetch_child_sitemap(client, loc.text)
                            urls.extend(child_urls)
                else:
                    # This is a direct urlset
                    loc_elements = root.findall(".//sm:loc", ns)
                    for loc in loc_elements:
                        if loc.text:
                            urls.append(loc.text)

                if urls:
                    if self.config.verbose:
                        console.print(
                            f"[green]Found {len(urls)} URLs from sitemap: {smap_url}[/green]"
                        )
                    break

            except Exception as e:
                if self.config.verbose:
                    console.print(f"[yellow]Error fetching sitemap {smap_url}: {e}[/yellow]")

        return urls

    async def _fetch_child_sitemap(self, client: httpx.AsyncClient, sitemap_url: str) -> list[str]:
        """Fetch URLs from a child sitemap."""
        urls = []

        try:
            response = await client.get(sitemap_url, timeout=self.config.timeout)
            if response.status_code != 200:
                return urls

            root = ElementTree.fromstring(response.content)
            ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

            loc_elements = root.findall(".//sm:loc", ns)
            for loc in loc_elements:
                if loc.text:
                    urls.append(loc.text)

            if self.config.verbose:
                console.print(f"[dim]Found {len(urls)} URLs in {sitemap_url}[/dim]")

        except Exception as e:
            if self.config.verbose:
                console.print(f"[yellow]Error fetching {sitemap_url}: {e}[/yellow]")

        return urls

    async def _extract_links_from_html(self, client: httpx.AsyncClient, url: str) -> list[str]:
        """Fallback: Extract internal links from HTML page navigation."""
        links = []

        try:
            response = await client.get(url, timeout=self.config.timeout)
            if response.status_code != 200:
                return links

            soup = BeautifulSoup(response.text, "html.parser")

            # MkDocs Material theme uses nav with class md-nav for sidebar
            nav = soup.find("nav", class_="md-nav--primary")
            if not nav:
                nav = soup.find("nav", class_="md-nav")
            if not nav:
                nav = soup.find("nav")
            if not nav:
                nav = soup.find("aside")

            search_area = nav if nav else soup

            for a_tag in search_area.find_all("a", href=True):
                href = a_tag["href"]

                # Skip external links, anchors, and javascript
                if href.startswith(("http://", "https://")):
                    if self.base_host not in href:
                        continue
                    # Check if URL is under base path
                    parsed_href = urlparse(href)
                    if not parsed_href.path.startswith(self.base_path):
                        continue
                    links.append(href.split("#")[0])  # Remove fragment
                elif href.startswith(("#", "javascript:", "mailto:", "tel:")):
                    continue
                elif href.startswith("/"):
                    # Absolute path
                    full_url = f"https://{self.base_host}{href}"
                    if self.base_path in href:
                        links.append(full_url.split("#")[0])
                else:
                    # Relative path
                    full_url = urljoin(url, href)
                    if self.base_path in full_url:
                        links.append(full_url.split("#")[0])

        except Exception as e:
            if self.config.verbose:
                console.print(f"[yellow]Failed to extract links from {url}: {e}[/yellow]")

        return list(set(links))

    def _extract_content(self, html: str) -> tuple[str, Tag | None]:
        """Extract title and main content from HTML page."""
        soup = BeautifulSoup(html, "html.parser")

        # Extract title
        title = ""
        h1 = soup.find("h1")
        if h1:
            # Clean up title - remove paragraph mark
            title = h1.get_text().strip().replace("¶", "").strip()
        elif soup.title:
            title = soup.title.get_text().split("|")[0].split("-")[0].strip()

        # Find main content - MkDocs Material theme uses article with class md-content__inner
        main = soup.find("article", class_="md-content__inner")
        if not main:
            main = soup.find("article")
        if not main:
            main = soup.find("div", class_="md-content")
        if not main:
            main = soup.find("main")
        if not main:
            main = soup.find("div", {"role": "main"})

        if main:
            # Remove unwanted elements
            for elem in main.find_all(["nav", "footer", "button"]):
                elem.decompose()

            # Remove edit links (common in MkDocs)
            for elem in main.find_all("a", class_="md-content__button"):
                elem.decompose()

            # Remove "Last updated" metadata
            for elem in main.find_all(["p", "div", "span", "small"]):
                text = elem.get_text().lower()
                if "last updated" in text or "last modified" in text:
                    elem.decompose()

            # Remove navigation footer (prev/next)
            for elem in main.find_all(class_="md-footer-nav"):
                elem.decompose()
            for elem in main.find_all("nav", class_="md-footer__inner"):
                elem.decompose()

            # Remove copy buttons
            for elem in main.find_all(attrs={"data-clipboard-target": True}):
                elem.decompose()
            for elem in main.find_all("button"):
                elem.decompose()

            # Remove source code links
            for elem in main.find_all("a", class_="md-source"):
                elem.decompose()

        return title, main

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
        console.print("[bold blue]MkDocs Scraper[/bold blue]")
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
            # Discover URLs from sitemap
            console.print("[cyan]Discovering pages from sitemap...[/cyan]")
            urls = await self._fetch_sitemap_urls(client)

            # Filter URLs to only include those under base_url
            urls = [u for u in urls if u.startswith(self.base_url)]

            # Fallback to HTML crawling if no URLs found
            if not urls:
                console.print("[yellow]No sitemap found, falling back to HTML crawling...[/yellow]")
                urls = await self._extract_links_from_html(client, self.base_url)
                urls = list(set(urls))

            # Always include base URL
            if self.base_url not in urls and f"{self.base_url}/" not in urls:
                urls.insert(0, self.base_url)

            # Remove duplicates and sort
            urls = sorted(set(urls))

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
