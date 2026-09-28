"""Core scraper module for Vocs-based documentation (PancakeSwap Infinity)."""

import asyncio
import os
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from bs4.element import NavigableString, Tag
from rich.console import Console

console = Console()


@dataclass
class ScraperConfig:
    """Configuration for the Vocs scraper."""

    base_url: str = "https://developer.pancakeswap.finance/contracts/infinity/overview"
    output_dir: str = "./pancakeswap"
    base_host: str = "developer.pancakeswap.finance"
    base_path: str = "/contracts/infinity/"
    verbose: bool = False
    timeout: float = 30.0


def _normalize_text(text: str) -> str:
    """Normalize whitespace in text."""
    return re.sub(r"\s+", " ", text).strip()


def _tag_to_markdown(element: Tag, base_url: str) -> str:
    """Convert a BeautifulSoup Tag to markdown text."""
    result: list[str] = []

    for child in element.children:
        if isinstance(child, NavigableString):
            text = _normalize_text(str(child))
            if text:
                result.append(text)
        elif isinstance(child, Tag):
            tag_name = child.name.lower()

            if tag_name == "h1":
                text = child.get_text(strip=True)
                if text:
                    result.append(f"\n# {text}\n")
            elif tag_name == "h2":
                text = child.get_text(strip=True)
                if text:
                    result.append(f"\n## {text}\n")
            elif tag_name == "h3":
                text = child.get_text(strip=True)
                if text:
                    result.append(f"\n### {text}\n")
            elif tag_name == "h4":
                text = child.get_text(strip=True)
                if text:
                    result.append(f"\n#### {text}\n")
            elif tag_name == "h5":
                text = child.get_text(strip=True)
                if text:
                    result.append(f"\n##### {text}\n")
            elif tag_name == "p":
                inner = _tag_to_markdown(child, base_url)
                if inner.strip():
                    result.append(f"\n{inner}\n")
            elif tag_name == "a":
                href = child.get("href", "")
                text = child.get_text(strip=True)
                if text and href:
                    if href.startswith("/"):
                        href = urljoin(f"https://{urlparse(base_url).netloc}", href)
                    result.append(f"[{text}]({href})")
                elif text:
                    result.append(text)
            elif tag_name == "img":
                src = child.get("src", "")
                alt = child.get("alt", "")
                if src:
                    if src.startswith("/"):
                        src = urljoin(f"https://{urlparse(base_url).netloc}", src)
                    result.append(f"\n![{alt}]({src})\n")
            elif tag_name in ("strong", "b"):
                text = child.get_text(strip=True)
                if text:
                    result.append(f"**{text}**")
            elif tag_name in ("em", "i"):
                text = child.get_text(strip=True)
                if text:
                    result.append(f"*{text}*")
            elif tag_name == "code":
                text = child.get_text()
                if text:
                    result.append(f"`{text}`")
            elif tag_name == "pre":
                code = child.find("code")
                if code:
                    text = code.get_text()
                    lang = ""
                    classes = code.get("class", [])
                    for cls in classes:
                        if isinstance(cls, str) and cls.startswith("language-"):
                            lang = cls[9:]
                            break
                    result.append(f"\n```{lang}\n{text}\n```\n")
                else:
                    text = child.get_text()
                    result.append(f"\n```\n{text}\n```\n")
            elif tag_name in ("ul", "ol"):
                items = child.find_all("li", recursive=False)
                for i, li in enumerate(items, 1):
                    li_text = _tag_to_markdown(li, base_url).strip()
                    prefix = "- " if tag_name == "ul" else f"{i}. "
                    result.append(f"\n{prefix}{li_text}")
                result.append("\n")
            elif tag_name == "li":
                inner = _tag_to_markdown(child, base_url)
                result.append(inner)
            elif tag_name == "br":
                result.append("\n")
            elif tag_name == "hr":
                result.append("\n---\n")
            elif tag_name == "blockquote":
                text = _tag_to_markdown(child, base_url).strip()
                result.append(f"\n> {text}\n")
            elif tag_name == "aside":
                text = _tag_to_markdown(child, base_url).strip()
                if text:
                    result.append(f"\n> **Note:** {text}\n")
            else:
                inner = _tag_to_markdown(child, base_url)
                if inner.strip():
                    result.append(inner)

    return " ".join(result)


class PancakeSwapScraper:
    """Scraper for Vocs-based documentation (PancakeSwap Infinity)."""

    def __init__(self, config: ScraperConfig) -> None:
        self.config = config
        self.base_url = config.base_url.rstrip("/")
        self.visited_urls: set[str] = set()
        self.urls_to_download: list[str] = []

    async def _fetch_page(self, client: httpx.AsyncClient, url: str) -> str | None:
        """Fetch a page and return its HTML content."""
        try:
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36"
                )
            }
            resp = await client.get(
                url, headers=headers, timeout=self.config.timeout, follow_redirects=True
            )
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            console.print(f"[yellow]  Error fetching {url}: {e}[/yellow]")
            return None

    def _extract_article_content(self, html: str, url: str) -> str | None:
        """Extract article content and convert to markdown."""
        soup = BeautifulSoup(html, "html.parser")

        # Vocs uses <article class="vocs_Content"> for main content
        article = soup.find("article", class_="vocs_Content")
        if not article:
            article = soup.find("article")

        if not article:
            return None

        return _tag_to_markdown(article, url)

    def _extract_sidebar_links(self, html: str) -> list[str]:
        """Extract all doc links from the sidebar navigation."""
        soup = BeautifulSoup(html, "html.parser")
        base_host = self.config.base_host
        base_path = self.config.base_path

        links: set[str] = set()
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            if href.startswith("/"):
                full_url = f"https://{base_host}{href}"
            elif href.startswith("http"):
                full_url = href
            else:
                full_url = urljoin(self.base_url + "/", href)

            parsed = urlparse(full_url)
            if parsed.netloc != base_host:
                continue
            if not parsed.path.startswith(base_path):
                continue

            # Strip anchor fragments
            if "#" in full_url:
                full_url = full_url.split("#")[0]

            path = parsed.path.rstrip("/")
            if path and path != base_path.rstrip("/"):
                links.add(full_url)

        return sorted(links)

    def _get_local_path(self, url: str) -> str:
        """Convert URL to local file path."""
        parsed = urlparse(url)
        path = parsed.path
        base_path = self.config.base_path

        if path.startswith(base_path):
            relative = path[len(base_path):].strip("/")
        else:
            relative = path.strip("/")

        if not relative:
            relative = "index"

        if relative.endswith("/"):
            relative = relative.rstrip("/") + "/index"

        return os.path.join(self.config.output_dir, relative + ".md")

    async def run(self) -> None:
        """Run the scraper."""
        console.print("[bold blue]PancakeSwap Infinity Docs Scraper[/bold blue]")
        console.print(f"  Base URL: {self.base_url}")
        console.print(f"  Output: {self.config.output_dir}")
        console.print()

        os.makedirs(self.config.output_dir, exist_ok=True)

        async with httpx.AsyncClient() as client:
            # Fetch the base page to discover all links from sidebar
            console.print("[cyan]Fetching base page...[/cyan]")
            html = await self._fetch_page(client, self.base_url)
            if not html:
                console.print("[red]Failed to fetch base page![/red]")
                return

            # Extract all links from sidebar
            links = self._extract_sidebar_links(html)
            all_urls: list[str] = [self.base_url]
            for link in links:
                if link not in all_urls:
                    all_urls.append(link)

            console.print(f"[green]Found {len(all_urls)} pages to download[/green]\n")

            # Download each page
            downloaded = 0
            failed = 0

            for i, url in enumerate(all_urls, 1):
                console.print(
                    f"[cyan][{i}/{len(all_urls)}][/cyan] {url}"
                )
                page_html = await self._fetch_page(client, url)
                if not page_html:
                    failed += 1
                    continue

                content = self._extract_article_content(page_html, url)
                if not content:
                    console.print(
                        "  [yellow]Warning: No article content found[/yellow]"
                    )
                    failed += 1
                    continue

                # Save file
                local_path = self._get_local_path(url)
                os.makedirs(os.path.dirname(local_path), exist_ok=True)

                with open(local_path, "w", encoding="utf-8") as f:
                    f.write(content)

                console.print(f"  [green]Saved:[/green] {local_path}")
                downloaded += 1

            console.print()
            console.print(
                f"[bold green]Done![/bold green] "
                f"Downloaded: {downloaded}, Failed: {failed}"
            )
