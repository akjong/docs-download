#!/bin/bash
# Download LobeHub self-hosting documentation from GitHub

set -e

OUTPUT_DIR="${1:-/Volumes/akext/src/github.com/akjong/docs-download/lobehub/self-hosting}"
mkdir -p "$OUTPUT_DIR"

BASE_URL="https://raw.githubusercontent.com/lobehub/lobe-chat/main/docs/self-hosting"

echo "==================================="
echo "LobeHub Documentation Downloader"
echo "==================================="
echo ""
echo "Output directory: $OUTPUT_DIR"
echo ""

# Function to download a file
download_file() {
    local path="$1"
    local output="$2"
    local filename=$(basename "$path")

    curl -sL "$BASE_URL/$path" -o "$output/$filename" 2>/dev/null
    if [ $? -eq 0 ] && [ -s "$output/$filename" ]; then
        echo "  ✓ $path"
        return 0
    else
        echo "  ✗ Failed: $path"
        rm -f "$output/$filename"
        return 1
    fi
}

# Track statistics
TOTAL=0
SUCCESS=0

# Main files
echo "[1/8] Downloading main files..."
FILES=(
    "start.mdx"
    "auth.mdx"
    "environment-variables.mdx"
)
for file in "${FILES[@]}"; do
    TOTAL=$((TOTAL + 1))
    if download_file "$file" "$OUTPUT_DIR"; then
        SUCCESS=$((SUCCESS + 1))
    fi
done

# Platform files
echo ""
echo "[2/8] Downloading platform guides..."
mkdir -p "$OUTPUT_DIR/platform"
PLATFORM_FILES=(
    "platform/docker.mdx"
    "platform/docker-compose.mdx"
    "platform/vercel.mdx"
    "platform/sealos.mdx"
    "platform/zeabur.mdx"
    "platform/repocloud.mdx"
    "platform/dokploy.mdx"
)
for file in "${PLATFORM_FILES[@]}"; do
    TOTAL=$((TOTAL + 1))
    if download_file "$file" "$OUTPUT_DIR/platform"; then
        SUCCESS=$((SUCCESS + 1))
    fi
done

# Advanced files
echo ""
echo "[3/8] Downloading advanced guides..."
mkdir -p "$OUTPUT_DIR/advanced"
ADVANCED_FILES=(
    "advanced/upstream-sync.mdx"
    "advanced/desktop.mdx"
    "advanced/model-list.mdx"
    "advanced/feature-flags.mdx"
    "advanced/settings-url-share.mdx"
    "advanced/knowledge-base.mdx"
    "advanced/online-search.mdx"
    "advanced/s3.mdx"
    "advanced/redis.mdx"
    "advanced/analytics.mdx"
)
for file in "${ADVANCED_FILES[@]}"; do
    TOTAL=$((TOTAL + 1))
    if download_file "$file" "$OUTPUT_DIR/advanced"; then
        SUCCESS=$((SUCCESS + 1))
    fi
done

# Auth files
echo ""
echo "[4/8] Downloading auth guides..."
mkdir -p "$OUTPUT_DIR/auth"
AUTH_FILES=(
    "auth/clerk.mdx"
    "auth/email.mdx"
    "auth/legacy.mdx"
)
for file in "${AUTH_FILES[@]}"; do
    TOTAL=$((TOTAL + 1))
    if download_file "$file" "$OUTPUT_DIR/auth"; then
        SUCCESS=$((SUCCESS + 1))
    fi
done

# Examples files
echo ""
echo "[5/8] Downloading examples..."
mkdir -p "$OUTPUT_DIR/examples"
EXAMPLE_FILES=(
    "examples/azure-openai.mdx"
    "examples/ollama.mdx"
)
for file in "${EXAMPLE_FILES[@]}"; do
    TOTAL=$((TOTAL + 1))
    if download_file "$file" "$OUTPUT_DIR/examples"; then
        SUCCESS=$((SUCCESS + 1))
    fi
done

# FAQ files
echo ""
echo "[6/8] Downloading FAQ..."
mkdir -p "$OUTPUT_DIR/faq"
FAQ_FILES=(
    "faq/no-v1-suffix.mdx"
    "faq/proxy-with-unable-to-verify-leaf-signature.mdx"
    "faq/vercel-ai-image-timeout.mdx"
)
for file in "${FAQ_FILES[@]}"; do
    TOTAL=$((TOTAL + 1))
    if download_file "$file" "$OUTPUT_DIR/faq"; then
        SUCCESS=$((SUCCESS + 1))
    fi
done

# Create index file
echo ""
echo "[7/8] Creating index file..."
cat > "$OUTPUT_DIR/index.md" << 'EOF'
# LobeHub Self-Hosting Documentation

This directory contains the complete self-hosting documentation for LobeHub.

## Contents

### Getting Started
- [start.mdx](start.mdx) - Quick start guide
- [environment-variables.mdx](environment-variables.mdx) - Environment variable reference

### Authentication
- [auth.mdx](auth.mdx) - Authentication overview
- [auth/clerk.mdx](auth/clerk.mdx) - Clerk authentication
- [auth/email.mdx](auth/email.mdx) - Email authentication
- [auth/legacy.mdx](auth/legacy.mdx) - Legacy authentication

### Deployment Platforms
- [platform/docker.mdx](platform/docker.mdx) - Docker deployment
- [platform/docker-compose.mdx](platform/docker-compose.mdx) - Docker Compose deployment
- [platform/vercel.mdx](platform/vercel.mdx) - Vercel deployment
- [platform/sealos.mdx](platform/sealos.mdx) - Sealos deployment
- [platform/zeabur.mdx](platform/zeabur.mdx) - Zeabur deployment
- [platform/repocloud.mdx](platform/repocloud.mdx) - RepoCloud deployment
- [platform/dokploy.mdx](platform/dokploy.mdx) - Dokploy deployment

### Advanced Topics
- [advanced/upstream-sync.mdx](advanced/upstream-sync.mdx) - Upstream sync
- [advanced/desktop.mdx](advanced/desktop.mdx) - Desktop app
- [advanced/model-list.mdx](advanced/model-list.mdx) - Model list
- [advanced/feature-flags.mdx](advanced/feature-flags.mdx) - Feature flags
- [advanced/settings-url-share.mdx](advanced/settings-url-share.mdx) - Settings URL share
- [advanced/knowledge-base.mdx](advanced/knowledge-base.mdx) - Knowledge base
- [advanced/online-search.mdx](advanced/online-search.mdx) - Online search
- [advanced/s3.mdx](advanced/s3.mdx) - S3 storage
- [advanced/redis.mdx](advanced/redis.mdx) - Redis
- [advanced/analytics.mdx](advanced/analytics.mdx) - Analytics

### Examples
- [examples/azure-openai.mdx](examples/azure-openai.mdx) - Azure OpenAI
- [examples/ollama.mdx](examples/ollama.mdx) - Ollama

### FAQ
- [faq/no-v1-suffix.mdx](faq/no-v1-suffix.mdx) - No v1 suffix
- [faq/proxy-with-unable-to-verify-leaf-signature.mdx](faq/proxy-with-unable-to-verify-leaf-signature.mdx) - Proxy certificate issue
- [faq/vercel-ai-image-timeout.mdx](faq/vercel-ai-image-timeout.mdx) - Vercel AI image timeout

## File Format

All documentation files are in MDX format (Markdown with JSX), which allows for:
- Standard Markdown formatting
- JSX components for interactive elements
- Frontmatter metadata (title, description, tags)

To view these files:
1. Use a Markdown viewer that supports MDX
2. Open with a code editor (VS Code, etc.)
3. Use the LobeHub documentation site for rendered version

## Source

These files are from the official LobeChat repository:
https://github.com/lobehub/lobe-chat/tree/main/docs/self-hosting
EOF

echo "  ✓ index.md created"

# Summary
echo ""
echo "[8/8] Download Summary"
echo "======================="
echo "Total files: $TOTAL"
echo "Successful: $SUCCESS"
echo "Failed: $((TOTAL - SUCCESS))"
echo ""
echo "Files saved to: $OUTPUT_DIR"
echo ""
echo "Directory structure:"
find "$OUTPUT_DIR" -type f -name "*.mdx" -o -name "*.md" | head -30
echo ""
echo "Download complete!"
