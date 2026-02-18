"""CLI module for Manus blog scraper."""

import asyncio
import os

import click
from rich.console import Console

from manus_download.scraper import ManusScraper, ScraperConfig

console = Console()

ARTICLE_SLUGS = [
    "manus-joins-meta-for-next-era-of-innovation",
    "manus-project-skills",
    "manus-beginner-prompts",
    "manus-skills",
    "manus-app-publishing",
    "manus-sandbox",
    "similarweb-manus",
    "manus-meeting-minutes",
    "manus-slack-connector",
    "manus-design-view",
    "manus-academy-launch",
    "projects-connectors",
    "edit-slides-created-on-manus-with-nano-banana-pro",
    "manus-100m-arr",
    "manus-max-release",
    "manus-advanced-seo",
    "manus-google-drive-connector",
    "manus-custom-domains",
    "manus-slides-nano-banana-pro",
    "manus-projects",
    "manus-user-story-noelle-fleur",
    "manus-microsoft-agent365",
    "manus-browser-operator",
    "manus-notion-mcp-use-cases",
    "manus-stripe",
    "manus-pops-event-bts",
    "manus-slack-integration",
    "manus-wide-research-solve-context-problem",
    "manus-1.5-release",
    "introducing-wide-research",
    "Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus",
    "what-we-saw-in-the-past-three-months-and-what-we-see-in-the-future",
    "manus-is-hiring",
    "free-pdf-to-ppt-converters",
    "best-ai-productivity-tools",
    "best-ai-tools-for-code-review",
    "manus-vs-synthesia",
    "best-landing-page-generator",
    "best-b2b-sales-presentations-tools",
    "best-ai-presentation-makers",
    "best-ai-image-generator",
    "best-vibe-coding-tools",
    "email-automation-ai-writing-tools",
    "vibe-coding-tools-non-coder-review",
    "ai-website-builders-professional-sites",
    "best-ai-video-generator",
    "best-ai-text-generator",
    "best-ai-coding-assistant-tools",
    "best-chatgpt-alternatives",
    "best-website-builder",
    "lovable-vs-replit-vs-manus",
    "can-manus-create-slides",
    "presentation-tools-for-education",
    "vs-gamma",
    "vs-canva",
]


@click.command()
@click.argument("base_url", default="https://manus.im/blog")
@click.option(
    "--output",
    "-o",
    default="./manus/blog",
    help="Output directory for downloaded markdown files",
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
    help="Skip downloading existing files",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Enable verbose output",
)
def main(base_url: str, output: str, concurrency: int, skip_existing: bool, verbose: bool):
    """Download articles from Manus blog to markdown files."""
    config = ScraperConfig(
        base_url=base_url,
        output_dir=output,
        concurrency=concurrency,
        skip_existing=skip_existing,
        verbose=verbose,
    )

    scraper = ManusScraper(config)

    try:
        asyncio.run(scraper.run(ARTICLE_SLUGS))
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user[/yellow]")
        raise click.Abort()


if __name__ == "__main__":
    main()
