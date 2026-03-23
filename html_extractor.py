#!/usr/bin/env python3
"""
HTML Extractor - Fetches and saves the full HTML of a list of websites.

Usage:
    python html_extractor.py <url1> [url2 ...]
    python html_extractor.py --file urls.txt
    python html_extractor.py --file urls.txt --output-dir ./output
"""

import argparse
import os
import re
import sys
import time
import urllib.request
import urllib.error
from urllib.parse import urlparse


def sanitize_filename(url: str) -> str:
    """Convert a URL into a safe filename."""
    parsed = urlparse(url)
    name = parsed.netloc + parsed.path
    name = re.sub(r'[^\w\-.]', '_', name).strip('_')
    return name[:200] + ".html"


def fetch_html(url: str, timeout: int = 10, retries: int = 3) -> tuple[str, str | None]:
    """
    Fetch the HTML content of a URL.
    Returns (html_content, error_message). On failure, html_content is empty.
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        )
    }
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as response:
                charset = "utf-8"
                content_type = response.headers.get_content_charset()
                if content_type:
                    charset = content_type
                return response.read().decode(charset, errors="replace"), None
        except urllib.error.HTTPError as e:
            return "", f"HTTP {e.code}: {e.reason}"
        except urllib.error.URLError as e:
            if attempt < retries:
                time.sleep(2 ** (attempt - 1))
                continue
            return "", f"URL error: {e.reason}"
        except Exception as e:
            if attempt < retries:
                time.sleep(2 ** (attempt - 1))
                continue
            return "", str(e)
    return "", "Max retries exceeded"


def extract_urls_from_file(path: str) -> list[str]:
    """Read URLs from a text file (one per line, # comments ignored)."""
    with open(path, "r") as f:
        return [
            line.strip()
            for line in f
            if line.strip() and not line.startswith("#")
        ]


def process_urls(urls: list[str], output_dir: str) -> None:
    os.makedirs(output_dir, exist_ok=True)
    results = {"success": 0, "failure": 0}

    for url in urls:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        print(f"Fetching: {url} ... ", end="", flush=True)
        html, error = fetch_html(url)

        if error:
            print(f"FAILED ({error})")
            results["failure"] += 1
            continue

        filename = sanitize_filename(url)
        filepath = os.path.join(output_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"OK -> {filepath} ({len(html):,} bytes)")
        results["success"] += 1

    print(f"\nDone: {results['success']} succeeded, {results['failure']} failed.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract the full HTML of one or more websites."
    )
    parser.add_argument(
        "urls",
        nargs="*",
        metavar="URL",
        help="One or more URLs to fetch.",
    )
    parser.add_argument(
        "--file", "-f",
        metavar="FILE",
        help="Path to a text file with one URL per line.",
    )
    parser.add_argument(
        "--output-dir", "-o",
        default="html_output",
        metavar="DIR",
        help="Directory to save HTML files (default: html_output).",
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
