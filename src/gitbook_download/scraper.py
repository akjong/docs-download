"""Core scraper module for GitBook documentation sites."""

import asyncio
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
    """Configuration for the GitBook scraper."""

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


class HTMLToMarkdownConverter:
    """Convert HTML content to Markdown format."""

    def __init__(self, base_url: str):
        self.base_url = base_url

    def convert(self, element: Tag) -> str:
        """Convert BeautifulSoup element to Markdown."""
        if element is None:
            return ""

        lines = []
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
        if tag_name in ["script", "style", "nav", "aside", "footer", "button", "svg", "img"]:
            if tag_name == "img":
                # Handle images
                src = element.get("src", "")
                alt = element.get("alt", "")
                if src:
                    # Make absolute URL
                    if not src.startswith(("http://", "https://")):
                        src = urljoin(self.base_url, src)
                    lines.append(f"\n![{alt}]({src})\n")
            return

        # Handle different tags
        if tag_name in ["h1", "h2", "h3", "h4", "h5", "h6"]:
            level = int(tag_name[1])
            # Remove anchor links (contain hashtag icon) before getting text
            for anchor in element.find_all("a"):
                anchor.decompose()
            text = self._get_text(element).strip()
            if text:
                # Remove "Direct link to heading" prefix and hashtag
                text = re.sub(r"^Direct link to heading\s*", "", text)
                text = re.sub(r"^hashtag\s*", "", text)
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
                    if cls.startswith("language-"):
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
            href = element.get("href", "")
            text = self._get_text(element).strip()
            # Skip navigation links
            if "Previous" in text or "Next" in text or "chevron" in text.lower():
                return
            # Remove icon text
            text = re.sub(r"(arrow-up-right|arrow-right|external-link)", "", text).strip()
            if href and text:
                if not href.startswith(("http://", "https://", "#", "mailto:")):
                    href = urljoin(self.base_url, href)
                lines.append(f"[{text}]({href})")

        elif tag_name == "br":
            lines.append("\n")

        elif tag_name == "hr":
            lines.append("\n---\n")

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
            href = element.get("href", "")
            text = element.get_text().strip()
            # Remove icon text
            text = re.sub(r"(arrow-up-right|arrow-right|external-link)", "", text).strip()
            if href and text:
                if not href.startswith(("http://", "https://", "#", "mailto:")):
                    href = urljoin(self.base_url, href)
                return f"[{text}]({href})"
            return text
        elif tag_name == "br":
            return "\n"
        else:
            return element.get_text()

    def _process_list_item(self, li: Tag) -> str:
        """Process a list item and return its text content."""
        parts = []
        for child in li.children:
            if isinstance(child, NavigableString):
                parts.append(str(child).strip())
            elif isinstance(child, Tag):
                if child.name in ["ul", "ol"]:
                    # Nested list - skip for now, could implement indentation
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
        headers = [
            th.get_text().strip() for th in header_row.find_all(["th", "td"])
        ]
        if headers:
            lines.append("| " + " | ".join(headers) + " |")
            lines.append("| " + " | ".join(["---"] * len(headers)) + " |")

        # Process data rows
        for row in rows[1:]:
            cells = [td.get_text().strip() for td in row.find_all(["td", "th"])]
            if cells:
                lines.append("| " + " | ".join(cells) + " |")

        lines.append("")


class GitBookScraper:
    """Scraper for GitBook documentation sites."""

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

        # Semaphore for concurrency control
        self.semaphore = asyncio.Semaphore(config.concurrency)

        # HTML to Markdown converter
        self.converter = HTMLToMarkdownConverter(self.base_url)

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

    async def _fetch_sitemap_urls(self, client: httpx.AsyncClient) -> list[str]:
        """Fetch all page URLs from GitBook sitemaps."""
        urls = []

        # Try to fetch main sitemap index
        sitemap_url = f"{self.base_url}/sitemap.xml"

        try:
            response = await client.get(sitemap_url, timeout=self.config.timeout)
            if response.status_code != 200:
                if self.config.verbose:
                    console.print(f"[yellow]Could not fetch sitemap: {sitemap_url}[/yellow]")
                return urls

            # Parse sitemap index
            root = ElementTree.fromstring(response.content)

            # Handle namespace
            ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

            # Check if this is a sitemap index or urlset
            if root.tag.endswith("sitemapindex"):
                # This is a sitemap index, fetch each child sitemap
                sitemap_locs = root.findall(".//sm:loc", ns)
                for loc in sitemap_locs:
                    if loc.text and "sitemap-pages.xml" in loc.text:
                        child_urls = await self._fetch_sitemap_pages(client, loc.text)
                        urls.extend(child_urls)
            else:
                # This is a direct urlset
                loc_elements = root.findall(".//sm:loc", ns)
                for loc in loc_elements:
                    if loc.text:
                        urls.append(loc.text)

        except Exception as e:
            if self.config.verbose:
                console.print(f"[yellow]Error fetching sitemap: {e}[/yellow]")

        return urls

    async def _fetch_sitemap_pages(self, client: httpx.AsyncClient, sitemap_url: str) -> list[str]:
        """Fetch URLs from a sitemap-pages.xml file."""
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
        """Fallback: Extract internal links from HTML page."""
        links = []

        try:
            response = await client.get(url, timeout=self.config.timeout)
            if response.status_code != 200:
                return links

            soup = BeautifulSoup(response.text, "html.parser")

            # Find sidebar navigation
            nav = soup.find("nav") or soup.find("aside") or soup.find("complementary")
            search_area = nav if nav else soup

            for a_tag in search_area.find_all("a", href=True):
                href = a_tag["href"]

                # Skip external links, anchors, and javascript
                if href.startswith(("http://", "https://")):
                    if self.base_host not in href:
                        continue
                    links.append(href)
                elif href.startswith(("#", "javascript:", "mailto:", "tel:")):
                    continue
                elif href.startswith("/"):
                    # Relative URL
                    full_url = f"https://{self.base_host}{href}"
                    if self.base_path in href:
                        links.append(full_url)

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
            title = h1.get_text().strip()
        elif soup.title:
            title = soup.title.get_text().split("|")[0].strip()

        # Find main content
        main = soup.find("main")
        if not main:
            main = soup.find("article")
        if not main:
            main = soup.find("div", {"role": "main"})

        if main:
            # Remove unwanted elements
            for elem in main.find_all(["nav", "aside", "footer", "button"]):
                elem.decompose()

            # Remove "Previous/Next" navigation
            for link in main.find_all("a"):
                link_text = link.get_text()
                if "Previous" in link_text or "Next" in link_text:
                    parent = link.find_parent()
                    if parent:
                        parent.decompose()

            # Remove "Last updated" text
            for elem in main.find_all(["p", "div", "span"]):
                if "Last updated" in elem.get_text():
                    elem.decompose()

            # Remove copy buttons
            for elem in main.find_all(attrs={"aria-label": "Copy"}):
                elem.decompose()
            for elem in main.find_all(string=re.compile(r"^Copy$")):
                if elem.parent:
                    elem.parent.decompose()

        return title, main

    async def _process_url(
        self, client: httpx.AsyncClient, url: str, progress: Progress, task_id
    ) -> bool:
        """Process a single URL: download HTML, convert to Markdown, and save."""
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
                # Convert to Markdown
                markdown = self.converter.convert(content)

                # Add title if not already in content
                if title and not markdown.startswith(f"# {title}"):
                    markdown = f"# {title}\n\n{markdown}"

                # Skip files with minimal content (just a title, no real content)
                # Check if content is just a title (e.g., "# Title" with nothing else)
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
        console.print("[bold blue]GitBook Scraper[/bold blue]")
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
                tasks = [
                    self._process_url(client, url, progress, task_id)
                    for url in urls
                ]

                # Run with concurrency limit (semaphore handles this)
                await asyncio.gather(*tasks)

        # Print summary
        console.print()
        console.print("[bold green]✓ Scraping complete![/bold green]")
        console.print(f"  Discovered: {self.stats.discovered} pages")
        console.print(f"  Downloaded: {self.stats.downloaded} files")
        console.print(f"  Skipped: {self.stats.skipped} files")
        console.print(f"  Failed: {self.stats.failed} pages")

        return self.stats
