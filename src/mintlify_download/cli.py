"""Command-line interface for Mintlify scraper."""

import asyncio

import click
from rich.console import Console

from mintlify_download.scraper import MintlifyScraper, ScraperConfig

console = Console()


@click.command()
@click.argument("url")
@click.option(
    "--output",
    "-o",
    default="./downloaded_docs",
    help="Output directory for downloaded files",
)
@click.option(
    "--force-md",
    "-f",
    is_flag=True,
    help="Force saving all files as .md even if source is .mdx",
)
@click.option(
    "--concurrency",
    "-c",
    default=10,
    type=int,
    help="Number of concurrent downloads",
)
@click.option(
    "--skip-existing",
    "-s",
    is_flag=True,
    help="Skip downloading files that already exist",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Enable verbose output",
)
def main(
    url: str,
    output: str,
    force_md: bool,
    concurrency: int,
    skip_existing: bool,
    verbose: bool,
) -> None:
    """Download Mintlify documentation from URL to local Markdown files.

    URL: The base URL of the Mintlify documentation site to download.

    Examples:

        mintlify-download https://docs.example.com/

        mintlify-download https://docs.example.com/guide -o ./my-docs --force-md
    """
    config = ScraperConfig(
        base_url=url,
        output_dir=output,
        force_md=force_md,
        concurrency=concurrency,
        skip_existing=skip_existing,
        verbose=verbose,
    )

    scraper = MintlifyScraper(config)

    try:
        asyncio.run(scraper.run())
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user[/yellow]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise click.Abort() from e


if __name__ == "__main__":
    main()
