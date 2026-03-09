#!/bin/bash
# Download GitBook documentation as Markdown
# Usage: ./download-gitbook.sh <url> [output_dir]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Default values
URL="${1:-}"
OUTPUT_DIR="${2:-axiom/docs}"
RATE_LIMIT="${3:-0.5}"

if [ -z "$URL" ]; then
    echo "Usage: $0 <url> [output_dir] [rate_limit]"
    echo "Example: $0 https://docs.axiom.trade axiom/docs"
    exit 1
fi

# Change to project root for uv run
cd "$PROJECT_ROOT"

echo "📚 Downloading GitBook documentation"
echo "   URL: $URL"
echo "   Output: $OUTPUT_DIR"
echo ""

# Run the Python script using uv
uv run python "$SCRIPT_DIR/download_gitbook.py" "$URL" -o "$OUTPUT_DIR" -r "$RATE_LIMIT"

echo ""
echo "✅ Download complete! Files saved to: $OUTPUT_DIR"
