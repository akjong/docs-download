import asyncio
import os
import re
from pathlib import Path

import httpx


async def download_blogs(urls: list[str], output_dir: str) -> None:
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    semaphore = asyncio.Semaphore(10)

    async def download(url: str) -> None:
        async with semaphore:
            async with httpx.AsyncClient(headers={"Accept": "text/markdown"}, follow_redirects=True) as client:
                try:
                    response = await client.get(url)
                    response.raise_for_status()

                    md_content = response.text

                    # Extract slug from URL
                    # e.g., https://lobehub.com/blog/5-ollama-web-ui-recommendation -> 5-ollama-web-ui-recommendation
                    slug = url.replace("https://lobehub.com/blog/", "").rstrip("/")

                    filepath = Path(output_dir) / f"{slug}.md"
                    filepath.parent.mkdir(parents=True, exist_ok=True)

                    filepath.write_text(md_content)
                    print(f"Downloaded: {slug}")
                except Exception as e:
                    print(f"Failed: {url} - {e}")

    await asyncio.gather(*[download(url) for url in urls])


async def main():
    # Read URLs from file
    urls_file = "/tmp/blog_urls.txt"
    if not Path(urls_file).exists():
        print(f"URLs file not found: {urls_file}")
        return

    with open(urls_file) as f:
        urls = [line.strip() for line in f if line.strip()]

    print(f"Found {len(urls)} URLs")

    await download_blogs(urls, "./lobehub/blog")


if __name__ == "__main__":
    asyncio.run(main())
