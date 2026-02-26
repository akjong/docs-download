"""Command-line interface for Arc Blog scraper."""

import asyncio

import click
from rich.console import Console

from arc_blog_download.scraper import ArcBlogScraper, ScraperConfig

console = Console()


@click.command()
@click.option(
    "--base-url",
    "-u",
    default="https://www.arc.network/blog",
    help="Base URL of the Arc blog to download",
)
@click.option(
    "--output",
    "-o",
    default="arc/blog",
    help="Output directory for downloaded files",
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
    verbose: bool,
) -> None:
    """Download Arc blog articles to local Markdown files.

    Examples:

        arc-blog-download

        arc-blog-download --output ./arc-blog --verbose
    """
    config = ScraperConfig(
        base_url=base_url,
        output_dir=output,
        verbose=verbose,
    )

    scraper = ArcBlogScraper(config)

    try:
        asyncio.run(scraper.run())
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user[/yellow]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise click.Abort() from e


if __name__ == "__main__":
    main()
