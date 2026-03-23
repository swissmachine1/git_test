#!/usr/bin/env python3
"""
HTML Extractor - Fetches websites (including JS-rendered pages) and saves
their content as clean Markdown, optimised for reading by LLMs.

Usage:
    python html_extractor.py <url1> [url2 ...]
    python html_extractor.py --file urls.txt
    python html_extractor.py --file urls.txt --output-dir ./output

Requirements:
    pip install -r requirements.txt
    playwright install chromium
"""

import argparse
import os
import re
import sys
import time
from urllib.parse import urlparse

try:
    import html2text
except ImportError:
    sys.exit("Missing dependency: pip install html2text")

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
except ImportError:
    sys.exit("Missing dependency: pip install playwright && playwright install chromium")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def sanitize_filename(url: str) -> str:
    """Convert a URL into a safe filename."""
    parsed = urlparse(url)
    name = parsed.netloc + parsed.path
    name = re.sub(r"[^\w\-.]", "_", name).strip("_")
    return name[:200] + ".md"


def html_to_markdown(html: str, base_url: str = "") -> str:
    """Convert raw HTML to clean Markdown suited for LLM consumption."""
    converter = html2text.HTML2Text()
    converter.baseurl = base_url
    converter.ignore_images = False      # keep image alt-text as context
    converter.ignore_links = False       # keep links
    converter.body_width = 0            # no hard line-wrapping
    converter.mark_code = True          # wrap <code> blocks in backticks
    converter.ignore_tables = False
    converter.unicode_snob = True
    return converter.handle(html).strip()


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

def fetch_with_playwright(
    url: str,
    page,
    wait_until: str = "networkidle",
    timeout_ms: int = 30_000,
    retries: int = 3,
) -> tuple[str, str | None]:
    """
    Navigate to *url* using an existing Playwright page and return
    (html_content, error_message). On failure html_content is empty.
    """
    for attempt in range(1, retries + 1):
        try:
            page.goto(url, wait_until=wait_until, timeout=timeout_ms)
            return page.content(), None
        except PWTimeout:
            if attempt < retries:
                time.sleep(2 ** (attempt - 1))
                continue
            return "", f"Timeout after {timeout_ms / 1000:.0f}s"
        except Exception as e:
            if attempt < retries:
                time.sleep(2 ** (attempt - 1))
                continue
            return "", str(e)
    return "", "Max retries exceeded"


# ---------------------------------------------------------------------------
# Core processing
# ---------------------------------------------------------------------------

def process_urls(urls: list[str], output_dir: str) -> None:
    os.makedirs(output_dir, exist_ok=True)
    results = {"success": 0, "failure": 0}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
            ),
            java_script_enabled=True,
        )
        page = context.new_page()

        for url in urls:
            if not url.startswith(("http://", "https://")):
                url = "https://" + url

            print(f"Fetching: {url} ... ", end="", flush=True)
            html, error = fetch_with_playwright(url, page)

            if error:
                print(f"FAILED ({error})")
                results["failure"] += 1
                continue

            markdown = html_to_markdown(html, base_url=url)
            filename = sanitize_filename(url)
            filepath = os.path.join(output_dir, filename)

            with open(filepath, "w", encoding="utf-8") as f:
                f.write(f"<!-- source: {url} -->\n\n")
                f.write(markdown)

            print(f"OK -> {filepath} ({len(markdown):,} chars)")
            results["success"] += 1

        context.close()
        browser.close()

    print(f"\nDone: {results['success']} succeeded, {results['failure']} failed.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def extract_urls_from_file(path: str) -> list[str]:
    with open(path) as f:
        return [
            line.strip()
            for line in f
            if line.strip() and not line.startswith("#")
        ]


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch websites (including JS-rendered pages) and save their "
            "content as clean Markdown for LLM consumption."
        )
    )
    parser.add_argument("urls", nargs="*", metavar="URL", help="URLs to fetch.")
    parser.add_argument("--file", "-f", metavar="FILE", help="File with one URL per line.")
    parser.add_argument(
        "--output-dir", "-o",
        default="html_output",
        metavar="DIR",
        help="Directory to save Markdown files (default: html_output).",
    )
    args = parser.parse_args()

    urls = list(args.urls)
    if args.file:
        urls += extract_urls_from_file(args.file)

    if not urls:
        parser.print_help()
        sys.exit(1)

    process_urls(urls, args.output_dir)


if __name__ == "__main__":
    main()
