"""Command-line interface for MkDocs scraper."""

import asyncio

import click
from rich.console import Console

from mkdocs_download.scraper import MkDocsScraper, ScraperConfig

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
    url: str,
    output: str,
    concurrency: int,
    skip_existing: bool,
    verbose: bool,
) -> None:
    """Download MkDocs documentation from URL to local Markdown files.

    URL: The base URL of the MkDocs documentation site to download.

    Examples:

        mkdocs-download https://squidfunk.github.io/mkdocs-material/

        mkdocs-download https://docs.example.com/guide -o ./my-docs
    """
    config = ScraperConfig(
        base_url=url,
        output_dir=output,
        concurrency=concurrency,
        skip_existing=skip_existing,
        verbose=verbose,
    )

    scraper = MkDocsScraper(config)

    try:
        asyncio.run(scraper.run())
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user[/yellow]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise click.Abort() from e


if __name__ == "__main__":
    main()
