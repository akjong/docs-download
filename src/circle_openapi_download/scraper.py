import os

import click
import httpx
from rich.console import Console

console = Console()


def fetch_openapi_json(url: str) -> dict:
    response = httpx.get(url, timeout=30.0)
    response.raise_for_status()
    return response.json()


def download_products(
    data: dict,
    output_dir: str,
    base_url: str,
    skip_existing: bool = False,
) -> None:
    downloaded = 0
    failed = 0

    for product_name, config in data.items():
        console.print(f"[cyan]Processing {product_name}...[/cyan]")

        product_dir = os.path.join(output_dir, product_name)
        if skip_existing and os.path.exists(product_dir):
            console.print(f"  [yellow]Skipping {product_name} (already exists)[/yellow]")
            continue

        files = config.get("files", [])

        for file_name in files:
            file_url = f"{base_url.rstrip('/')}/{file_name}"
            dst_path = os.path.join(product_dir, file_name)

            try:
                response = httpx.get(file_url, timeout=30.0)
                if response.status_code == 200:
                    os.makedirs(os.path.dirname(dst_path), exist_ok=True)
                    with open(dst_path, "wb") as f:
                        f.write(response.content)
                    console.print(f"  [green]Downloaded {file_name}[/green]")
                    downloaded += 1
                else:
                    console.print(
                        f"  [red]Failed to download {file_name}: HTTP {response.status_code}[/red]"
                    )
                    failed += 1
            except Exception as e:
                console.print(f"  [red]Error downloading {file_name}: {e}[/red]")
                failed += 1

    console.print(f"\n[bold green]Done! Downloaded: {downloaded}, Failed: {failed}[/bold green]")


@click.command()
@click.option(
    "--url",
    default="https://developers.circle.com/openapi.json",
    help="URL to openapi.json",
)
@click.option(
    "--output",
    default="./circle-openapi",
    help="Output directory",
)
@click.option(
    "--base-url",
    default="https://developers.circle.com/openapi",
    help="Base URL for downloading OpenAPI files",
)
@click.option(
    "--skip-existing",
    is_flag=True,
    help="Skip products that already exist",
)
def main(url: str, output: str, base_url: str, skip_existing: bool) -> None:
    console.print(f"[bold]Fetching {url}...[/bold]")
    data = fetch_openapi_json(url)

    total_files = sum(len(config.get("files", [])) for config in data.values())
    console.print(f"[bold]Found {len(data)} products with {total_files} files total[/bold]")
    for name, config in data.items():
        console.print(f"  - {name}: {len(config.get('files', []))} files")

    download_products(data, output, base_url, skip_existing)


if __name__ == "__main__":
    main()
