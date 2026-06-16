"""Core scraper module for HTX API documentation sites."""

import asyncio
import re
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from markdownify import MarkdownConverter
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn

console = Console()

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

CATEGORY_API = "https://www.htx.com/oplt/api/open_api/category"
INTERFACE_DETAIL_API = "https://www.htx.com/oplt/api/open_api/interface/detail"


class HTXMarkdownConverter(MarkdownConverter):
    """Custom Markdown converter for HTX API docs."""

    def convert_pre(self, el, text, convert_as_inline=False, **kwargs):
        """Handle code blocks with language detection."""
        code_el = el.find("code")
        lang = ""
        if code_el:
            for cls in code_el.get("class", []):
                if cls.startswith("language-"):
                    lang = cls.replace("language-", "")
                    break
        return f"\n\n```{lang}\n{text.strip()}\n```\n\n"

    def convert_table(self, el, text, convert_as_inline=False, **kwargs):
        """Ensure tables have proper spacing."""
        return f"\n\n{text}\n\n"


@dataclass
class ScraperConfig:
    """Configuration for the HTX documentation scraper."""

    output_dir: str = "./htx/docs"
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


@dataclass
class CategoryNode:
    """A node in the HTX API category tree."""

    id: int
    label: str
    pid: str
    node_type: int | None  # 1=group, 2=page, None=endpoint
    children: list["CategoryNode"] = field(default_factory=list)
    desc: str | None = None  # HTML content for type=2 nodes
    interface_id: str | None = None  # For API endpoint nodes
    interface_path: str | None = None
    interface_name: str | None = None


class HtxScraper:
    """Scraper for HTX API documentation."""

    def __init__(self, config: ScraperConfig):
        self.config = config
        self.stats = ScraperStats()
        self.semaphore = asyncio.Semaphore(config.concurrency)

    def _build_category_tree(self, data: list[dict]) -> list[CategoryNode]:
        """Recursively build category tree from API response."""

        def _parse_node(item: dict) -> CategoryNode:
            children = [_parse_node(c) for c in item.get("children", [])]
            return CategoryNode(
                id=item["id"],
                label=item.get("label", ""),
                pid=item.get("pid", "0"),
                node_type=item.get("type"),
                children=children,
                desc=item.get("desc"),
                interface_id=item.get("interface_id"),
                interface_path=item.get("interface_path"),
                interface_name=item.get("interface_name"),
            )

        return [_parse_node(item) for item in data]

    def _collect_pages(
        self,
        nodes: list[CategoryNode],
        path_parts: list[str] | None = None,
        seen_paths: dict[str, int] | None = None,
    ) -> list[tuple[list[str], CategoryNode]]:
        """Collect all downloadable pages (type=2 with desc, or endpoints)."""
        if path_parts is None:
            path_parts = []
        if seen_paths is None:
            seen_paths = {}

        pages: list[tuple[list[str], CategoryNode]] = []

        for node in nodes:
            current_path = path_parts + [node.label] if node.label else path_parts

            # Type 2 nodes with desc content
            if node.node_type == 2 and node.desc:
                base = "/".join(self._sanitize_path(current_path).split("/"))
                count = seen_paths.get(base, 0)
                if count > 0:
                    pages.append((current_path + [str(count)], node))
                else:
                    pages.append((current_path, node))
                seen_paths[base] = count + 1

            # API endpoint nodes (interface_id present) - add unique endpoint name to path
            if node.interface_id:
                endpoint_name = (node.interface_name or "").strip()
                if endpoint_name:
                    pages.append((current_path + [endpoint_name], node))
                else:
                    pages.append((current_path, node))

            # Recurse into children
            if node.children:
                pages.extend(self._collect_pages(node.children, current_path, seen_paths))

        return pages

    def _sanitize_path(self, parts: list[str]) -> str:
        """Convert path parts to a safe file path."""
        sanitized = []
        for part in parts:
            # Remove or replace unsafe characters
            s = re.sub(r'[<>:"/\\|?*]', "", part).strip()
            s = re.sub(r"\s+", "-", s)
            s = s.strip("-")
            if s:
                sanitized.append(s)
        return "/".join(sanitized)

    def _html_to_markdown(self, html: str) -> str:
        """Convert HTML content to Markdown."""
        converter = HTXMarkdownConverter(
            heading_style="atx",
            bullets="-",
            strip=["script", "style", "svg"],
        )
        md = converter.convert(html)
        md = re.sub(r"\n{4,}", "\n\n\n", md)
        return md.strip()

    def _build_endpoint_markdown(
        self, node: CategoryNode, detail: dict, path_parts: list[str]
    ) -> str:
        """Build markdown content from endpoint detail data."""
        lines: list[str] = []

        # Title
        name = (node.interface_name or "").strip()
        lines.append(f"# {name}\n")

        # Path
        if node.interface_path:
            lines.append(f"`{node.interface_path}`\n")

        # Metadata
        if detail.get("req_type"):
            lines.append(f"**Request Type:** `{detail['req_type']}`")
        if detail.get("req_limit"):
            lines.append(f"**Rate Limit:** {detail['req_limit']}")
        if detail.get("permission"):
            lines.append(f"**Permission:** `{detail['permission']}`")
        if detail.get("signature_required"):
            lines.append("**Signature Required:** Yes")
        lines.append("")

        # Description
        desc = (detail.get("desc") or "").strip()
        if desc:
            lines.append(f"{desc}\n")

        # Environments
        env_list = detail.get("env_list", [])
        if env_list:
            lines.append("## Environments\n")
            lines.append("| Environment | Address |")
            lines.append("|---|---|")
            for env in env_list:
                lines.append(f"| {env.get('env_name', '')} | `{env.get('env_address', '')}` |")
            lines.append("")

        # Request Parameters
        req_params = detail.get("req_param", [])
        if req_params:
            lines.append("## Request Parameters\n")
            lines.append("| Name | Type | Required | Description | Default |")
            lines.append("|---|---|---|---|---|")
            for p in req_params:
                required = "Yes" if p.get("required") else "No"
                desc_text = (p.get("desc") or "").replace("|", "\\|")
                default = p.get("default_value", "")
                lines.append(
                    f"| `{p.get('param_name', '')}` | `{p.get('data_type', '')}` "
                    f"| {required} | {desc_text} | `{default}` |"
                )
            lines.append("")

        # Request Example
        req_example = detail.get("req_example")
        if req_example:
            lines.append("## Request Example\n")
            lines.append(f"```json\n{req_example}\n```\n")

        # Response Parameters
        res_params = detail.get("res_param", [])
        if res_params:
            lines.append("## Response Parameters\n")
            lines.append("| Name | Type | Description |")
            lines.append("|---|---|---|")
            for p in res_params:
                desc_text = (p.get("desc") or "").replace("|", "\\|")
                lines.append(
                    f"| `{p.get('param_name', '')}` | `{p.get('data_type', '')}` | {desc_text} |"
                )
            lines.append("")

        # Response Example
        res_example = detail.get("res_example")
        if res_example:
            lines.append("## Response Example\n")
            lines.append(f"```json\n{res_example}\n```\n")

        # Response Failure Example
        res_fail = detail.get("res_fail_example")
        if res_fail:
            lines.append("## Failure Example\n")
            lines.append(f"```json\n{res_fail}\n```\n")

        # Response Remark
        res_remark = (detail.get("res_param_remark") or "").strip()
        if res_remark:
            remark_md = self._html_to_markdown(res_remark)
            lines.append("## Notes\n")
            lines.append(f"{remark_md}\n")

        # SDK URLs
        sdk_urls = detail.get("sdkUrl", [])
        if sdk_urls:
            lines.append("## SDKs\n")
            for sdk in sdk_urls:
                lines.append(f"- [{sdk.get('title', '')}]({sdk.get('url', '')})")
            lines.append("")

        return "\n".join(lines)

    def _build_page_markdown(self, node: CategoryNode, path_parts: list[str]) -> str:
        """Build markdown content from a type=2 page node."""
        lines: list[str] = []
        lines.append(f"# {node.label}\n")
        if node.desc:
            lines.append(self._html_to_markdown(node.desc))
        return "\n".join(lines)

    async def _fetch(self, client: httpx.AsyncClient, url: str, retries: int = 3) -> dict | None:
        """Fetch a URL with retries and rate-limit handling."""
        for attempt in range(retries):
            try:
                resp = await client.get(url, follow_redirects=True)
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 429:
                    wait = 2 ** (attempt + 1)
                    if self.config.verbose:
                        console.print(f"  [yellow]Rate limited, waiting {wait}s...[/yellow]")
                    await asyncio.sleep(wait)
                    continue
                if self.config.verbose:
                    console.print(f"  [red]HTTP {exc.response.status_code}: {url}[/red]")
                return None
            except httpx.HTTPError:
                if attempt < retries - 1:
                    await asyncio.sleep(1)
                    continue
                return None
        return None

    async def _fetch_text(
        self, client: httpx.AsyncClient, url: str, retries: int = 3
    ) -> str | None:
        """Fetch raw text with retries."""
        for attempt in range(retries):
            try:
                resp = await client.get(url, follow_redirects=True)
                resp.raise_for_status()
                return resp.text
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 429:
                    wait = 2 ** (attempt + 1)
                    if self.config.verbose:
                        console.print(f"  [yellow]Rate limited, waiting {wait}s...[/yellow]")
                    await asyncio.sleep(wait)
                    continue
                if self.config.verbose:
                    console.print(f"  [red]HTTP {exc.response.status_code}: {url}[/red]")
                return None
            except httpx.HTTPError:
                if attempt < retries - 1:
                    await asyncio.sleep(1)
                    continue
                return None
        return None

    async def _process_endpoint(
        self,
        client: httpx.AsyncClient,
        path_parts: list[str],
        node: CategoryNode,
        output_dir: str,
        progress: Progress,
        task_id: int,
    ) -> None:
        """Fetch endpoint detail and save as markdown."""
        async with self.semaphore:
            await asyncio.sleep(0.2)

            detail_url = f"{INTERFACE_DETAIL_API}?interface_id={node.interface_id}"
            detail = await self._fetch(client, detail_url)

            if detail is None or detail.get("code") != 200:
                self.stats.failed += 1
                if self.config.verbose:
                    console.print(f"  [red]Failed: {node.interface_name}[/red]")
                progress.advance(task_id)
                return

            try:
                content = self._build_endpoint_markdown(node, detail.get("data", {}), path_parts)
            except Exception as exc:
                self.stats.failed += 1
                if self.config.verbose:
                    console.print(f"  [red]Parse error: {node.interface_name}: {exc}[/red]")
                progress.advance(task_id)
                return

            rel_path = self._sanitize_path(path_parts)
            filepath = f"{output_dir}/{rel_path}.md"

            if self.config.skip_existing and Path(filepath).exists():
                self.stats.skipped += 1
                progress.advance(task_id)
                return

            # Add YAML frontmatter
            title = (node.interface_name or "").strip()
            source_url = f"https://www.htx.com/en-us/opend/newApiPages/?id={node.interface_id}"
            meta = f'---\ntitle: "{title}"\nsource: "{source_url}"\n---\n\n'
            full_content = meta + content

            Path(filepath).parent.mkdir(parents=True, exist_ok=True)
            Path(filepath).write_text(full_content, encoding="utf-8")

            self.stats.downloaded += 1
            progress.advance(task_id)

            if self.config.verbose:
                console.print(f"  [green]Saved[/green] {rel_path}.md")

    async def _process_page(
        self,
        path_parts: list[str],
        node: CategoryNode,
        output_dir: str,
    ) -> None:
        """Save a type=2 page node as markdown."""
        content = self._build_page_markdown(node, path_parts)
        rel_path = self._sanitize_path(path_parts)
        filepath = f"{output_dir}/{rel_path}.md"

        if self.config.skip_existing and Path(filepath).exists():
            self.stats.skipped += 1
            return

        meta = f'---\ntitle: "{node.label}"\n---\n\n'
        full_content = meta + content

        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        Path(filepath).write_text(full_content, encoding="utf-8")

        self.stats.downloaded += 1

        if self.config.verbose:
            console.print(f"  [green]Saved[/green] {rel_path}.md")

    async def run(self) -> ScraperStats:
        """Execute the full scraping pipeline."""
        console.print(
            f"[bold blue]HTX API Documentation Scraper[/bold blue]\n"
            f"  Output: {self.config.output_dir}\n"
            f"  Concurrency: {self.config.concurrency}\n"
        )

        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/html,application/xhtml+xml,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

        async with httpx.AsyncClient(headers=headers, timeout=self.config.timeout) as client:
            # Step 1: Fetch category tree
            with console.status("[bold green]Fetching category tree..."):
                category_data = await self._fetch(client, CATEGORY_API)

            if not category_data or category_data.get("code") != 200:
                console.print("[red]Failed to fetch category tree[/red]")
                return self.stats

            tree = self._build_category_tree(category_data.get("data", []))
            pages = self._collect_pages(tree)

            endpoint_pages = [(parts, node) for parts, node in pages if node.interface_id]
            content_pages = [
                (parts, node)
                for parts, node in pages
                if node.node_type == 2 and node.desc and not node.interface_id
            ]

            self.stats.discovered = len(endpoint_pages) + len(content_pages)
            console.print(
                f"  Found [bold]{len(endpoint_pages)}[/bold] API endpoints, "
                f"[bold]{len(content_pages)}[/bold] content pages\n"
            )

            # Step 2: Save content pages (no API call needed)
            for path_parts, node in content_pages:
                await self._process_page(path_parts, node, self.config.output_dir)

            # Step 3: Fetch endpoint details concurrently
            if endpoint_pages:
                with Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    BarColumn(),
                    TaskProgressColumn(),
                    console=console,
                ) as progress:
                    task_id = progress.add_task(
                        "Downloading endpoints...", total=len(endpoint_pages)
                    )
                    await asyncio.gather(
                        *[
                            self._process_endpoint(
                                client, parts, node, self.config.output_dir, progress, task_id
                            )
                            for parts, node in endpoint_pages
                        ]
                    )

        # Step 4: Print summary
        failed_str = (
            f"[red]{self.stats.failed}[/red]" if self.stats.failed else str(self.stats.failed)
        )
        console.print(
            f"\n[bold]Summary[/bold]\n"
            f"  Discovered:  {self.stats.discovered}\n"
            f"  Downloaded:  [green]{self.stats.downloaded}[/green]\n"
            f"  Skipped:     {self.stats.skipped}\n"
            f"  Failed:      {failed_str}"
        )

        return self.stats
