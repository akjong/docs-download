"""Command-line interface for PancakeSwap Infinity docs scraper."""

import asyncio
from urllib.parse import urlparse

import click
from rich.console import Console

from pancakeswap_download.scraper import PancakeSwapScraper, ScraperConfig

console = Console()


def _derive_base_path(url: str) -> str:
    """Derive the base path (section root) from a doc URL.

    Takes the parent directory of the URL path so that all sibling pages
    under the same section are discovered and saved with their sub-paths.
    """
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    # Return the directory part of the path with trailing slash
    idx = path.rfind("/")
    if idx > 0:
        return path[:idx] + "/"
    return path + "/"


@click.command()
@click.option(
    "--base-url",
    "-u",
    default="https://developer.pancakeswap.finance/contracts/infinity/overview",
    help="Base URL of the PancakeSwap Infinity docs to download",
)
@click.option(
    "--output",
    "-o",
    default="./pancakeswap",
    help="Output directory for downloaded files",
)
@click.option(
    "--base-path",
    "-p",
    default=None,
    help="Base path to filter and strip from URLs (auto-detected if not set)",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Enable verbose output",
)
def main(
    base_url: str,
    output: str,
    base_path: str | None,
    verbose: bool,
) -> None:
    """Download PancakeSwap Infinity docs to local Markdown files.

    Examples:

        pancakeswap-download

        pancakeswap-download --output ./my-docs --verbose
    """
    parsed = urlparse(base_url)
    effective_base_path = base_path if base_path else _derive_base_path(base_url)

    config = ScraperConfig(
        base_url=base_url,
        output_dir=output,
        base_host=parsed.netloc,
        base_path=effective_base_path,
        verbose=verbose,
    )

    scraper = PancakeSwapScraper(config)

    try:
        asyncio.run(scraper.run())
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user[/yellow]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise click.Abort() from e


if __name__ == "__main__":
    main()
