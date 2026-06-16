"""Command-line interface for HTX documentation scraper."""

import asyncio

import click
from rich.console import Console
from rich.markup import escape

from htx_download.scraper import HtxScraper, ScraperConfig

console = Console()


@click.command()
@click.option(
    "--output",
    "-o",
    default="./htx/docs",
    help="Output directory for downloaded files",
)
@click.option(
    "--concurrency",
    "-c",
    default=5,
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
    output: str,
    concurrency: int,
    skip_existing: bool,
    verbose: bool,
) -> None:
    """Download HTX API documentation to local Markdown files.

    Fetches the full category tree from the HTX API, then downloads
    detailed documentation for every API endpoint and saves each as
    a Markdown file under the output directory.
    """

    config = ScraperConfig(
        output_dir=output,
        concurrency=concurrency,
        skip_existing=skip_existing,
        verbose=verbose,
    )

    scraper = HtxScraper(config)

    try:
        asyncio.run(scraper.run())
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user[/yellow]")
    except Exception as e:
        console.print(f"[red]Error: {escape(e)}[/red]")
        raise click.Abort() from e


if __name__ == "__main__":
    main()
