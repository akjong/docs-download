"""Arc Blog scraper implementation."""

import json
import os
import re
from dataclasses import dataclass
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from bs4.element import NavigableString, Tag


@dataclass
class ScraperConfig:
    base_url: str = "https://www.arc.network/blog"
    output_dir: str = "arc/blog"
    concurrency: int = 10
    verbose: bool = False


def normalize_text(text: str | None) -> str:
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def tag_to_markdown(element: Tag, base_url: str) -> str:
    result = []

    for child in element.children:
        if isinstance(child, NavigableString):
            text = normalize_text(str(child))
            if text:
                result.append(text)
        elif isinstance(child, Tag):
            tag_name = child.name.lower()

            if tag_name in ("p", "div"):
                if child.get("class"):
                    classes = " ".join(child.get("class", []))
                    if "w-richtext" in classes:
                        result.append(tag_to_markdown(child, base_url))
                        result.append("\n")
                    else:
                        inner = tag_to_markdown(child, base_url)
                        if inner.strip():
                            result.append(inner)
                else:
                    inner = tag_to_markdown(child, base_url)
                    if inner.strip():
                        result.append(inner)

            elif tag_name == "h1":
                text = normalize_text(child.get_text())
                if text:
                    result.append(f"\n# {text}\n\n")

            elif tag_name == "h2":
                text = normalize_text(child.get_text())
                if text:
                    result.append(f"\n## {text}\n\n")

            elif tag_name == "h3":
                text = normalize_text(child.get_text())
                if text:
                    result.append(f"\n### {text}\n\n")

            elif tag_name == "h4":
                text = normalize_text(child.get_text())
                if text:
                    result.append(f"\n#### {text}\n\n")

            elif tag_name == "strong":
                text = normalize_text(child.get_text())
                if text:
                    result.append(f"**{text}**")

            elif tag_name == "em":
                text = normalize_text(child.get_text())
                if text:
                    result.append(f"*{text}*")

            elif tag_name == "a":
                href = child.get("href", "")
                text = normalize_text(child.get_text())
                if text and href:
                    if href.startswith("/"):
                        href = urljoin(base_url, href)
                    elif not href.startswith("http"):
                        href = urljoin(base_url, href)
                    result.append(f"[{text}]({href})")
                elif text:
                    result.append(text)

            elif tag_name == "img":
                src = child.get("src", "")
                alt = child.get("alt", "")
                if src:
                    if src.startswith("/"):
                        src = urljoin(base_url, src)
                    if alt:
                        result.append(f"![{alt}]({src})")
                    else:
                        result.append(f"![]({src})")

            elif tag_name in ("ul", "ol"):
                items = child.find_all("li", recursive=False)
                if items:
                    for i, li in enumerate(items):
                        li_text = normalize_text(li.get_text())
                        if tag_name == "ul":
                            result.append(f"- {li_text}")
                        else:
                            result.append(f"{i + 1}. {li_text}")
                    result.append("\n")

            elif tag_name == "li":
                text = normalize_text(child.get_text())
                if text:
                    result.append(f"- {text}\n")

            elif tag_name == "blockquote":
                text = normalize_text(child.get_text())
                if text:
                    result.append(f"\n> {text}\n")

            elif tag_name == "code":
                text = child.get_text()
                if text:
                    result.append(f"`{text}`")

            elif tag_name == "pre":
                code = child.find("code")
                if code:
                    text = code.get_text()
                else:
                    text = child.get_text()
                if text:
                    result.append(f"\n```\n{text}\n```\n")

            elif tag_name == "br":
                result.append("\n")

            elif tag_name == "hr":
                result.append("\n---\n")

            elif tag_name == "span":
                inner = tag_to_markdown(child, base_url)
                if inner.strip():
                    result.append(inner)

            elif tag_name == "section":
                inner = tag_to_markdown(child, base_url)
                if inner.strip():
                    result.append(inner)

            else:
                inner = tag_to_markdown(child, base_url)
                if inner.strip():
                    result.append(inner)

    return " ".join(result)


async def fetch_page(session: httpx.AsyncClient, url: str) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    response = await session.get(url, headers=headers, timeout=30.0, follow_redirects=True)
    response.raise_for_status()
    return response.text


def extract_article_urls(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    urls = set()

    json_ld = soup.find("script", type="application/ld+json")
    if json_ld:
        try:
            data = json.loads(json_ld.string or "")
            if isinstance(data, dict) and "blogPost" in data:
                for post in data["blogPost"]:
                    if "mainEntityOfPage" in post:
                        url = post["mainEntityOfPage"].get("@id", "")
                        if url:
                            if url.startswith("https://arc.network"):
                                url = url.replace("https://arc.network", "https://www.arc.network")
                            urls.add(url)
        except (json.JSONDecodeError, AttributeError):
            pass

    for link in soup.find_all("a", href=True):
        href: str | None = link.get("href")
        if not href:
            continue
        if "/blog/" in href and href != "/blog" and href != "/blog/":
            if href.startswith("/"):
                href = f"https://www.arc.network{href}"
            if href not in urls and not href.endswith("/blog/"):
                urls.add(href)

    return sorted(urls)


async def download_article(session: httpx.AsyncClient, url: str) -> tuple[str, str]:
    html = await fetch_page(session, url)
    soup = BeautifulSoup(html, "html.parser")

    title = ""
    title_elem = soup.find("h1")
    if title_elem:
        title = normalize_text(title_elem.get_text())

    if not title:
        og_title = soup.find("meta", property="og:title")
        if og_title:
            title = og_title.get("content", "") or ""

    article_content = None

    content_selectors = [
        ("div", {"class": "post"}),
        ("div", {"class": "article"}),
        ("section", {}),
        ("article", {}),
    ]

    for tag, attrs in content_selectors:
        elements = soup.find_all(tag, attrs)
        for elem in elements:
            text = elem.get_text()
            if len(text) > 1000 and "min read" in text:
                article_content = elem
                break
        if article_content:
            break

    if not article_content:
        article_content = soup.find("main")

    markdown_content = []
    if title:
        markdown_content.append(f"# {title}\n")

    if article_content:
        content_md = tag_to_markdown(article_content, url)

        lines = content_md.split("\n")
        cleaned_lines = []
        skip_patterns = [
            "Home",
            "Build",
            "Ecosystem",
            "Litepaper",
            "Blog",
            "Start building",
            "Documentation",
            "Explorer",
            "Faucet",
            "Discord",
            "X",
            "Twitter",
            "Subscribe",
            "Terms",
            "Privacy",
            "Brand Kit",
            "Copyright",
            "Back to blog",
            "min read",
            "©",
            "All rights reserved",
            "/* ----- Custom Dropdown",
            "function openDropdown",
            "function closeDropdown",
            "const dropdowns",
            "data-wf-",
            "data-wf-",
            "w-",
            "Contents",
            "//Build",
            "//Explore",
            "//connect",
            "//Subscribe",
            "Share",
            "Arc testnet is offered",
        ]

        prev_line = ""
        for line in lines:
            line = line.strip()

            if not line and not prev_line:
                continue

            if line in ("Home", "Build", "Ecosystem", "Litepaper", "Blog", "Start building"):
                continue

            skip = False
            for pattern in skip_patterns:
                if pattern in line and len(line) < 100:
                    skip = True
                    break

            if skip:
                continue

            cleaned_lines.append(line)
            prev_line = line

        markdown_content.append("\n".join(cleaned_lines))

    return "\n\n".join(markdown_content), title


def sanitize_filename(title: str) -> str:
    if not title:
        return "untitled"
    filename = re.sub(r"[^\w\s-]", "", title)
    filename = re.sub(r"\s+", "-", filename)
    filename = filename.lower()
    return filename[:100]


class ArcBlogScraper:
    def __init__(self, config: ScraperConfig) -> None:
        self.config = config

    async def run(self) -> None:
        async with httpx.AsyncClient() as session:
            print(f"Fetching blog page: {self.config.base_url}")
            html = await fetch_page(session, self.config.base_url)
            urls = extract_article_urls(html)

            print(f"Found {len(urls)} articles")

            os.makedirs(self.config.output_dir, exist_ok=True)

            for i, url in enumerate(urls, 1):
                print(f"[{i}/{len(urls)}] Downloading: {url}")
                try:
                    content, title = await download_article(session, url)
                    filename = sanitize_filename(title)
                    filepath = os.path.join(self.config.output_dir, f"{filename}.md")

                    counter = 1
                    while os.path.exists(filepath):
                        filepath = os.path.join(self.config.output_dir, f"{filename}-{counter}.md")
                        counter += 1

                    with open(filepath, "w", encoding="utf-8") as f:
                        f.write(content)

                    print(f"  Saved: {filepath}")
                except Exception as e:
                    print(f"  Error: {e}")

            print(f"\nDownloaded {len(urls)} articles to {self.config.output_dir}")
