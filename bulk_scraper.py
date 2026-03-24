#!/usr/bin/env python3
"""
Bulk Scraper — parallel HTML downloader for TAM analysis.

Scrapes hundreds of websites in parallel using a shared Playwright browser
with per-worker contexts. Saves raw HTML to raw_html/ for technology detection.

Usage:
    python bulk_scraper.py urls.txt
    python bulk_scraper.py urls.txt --concurrency 10 --output-dir raw_html
    cat urls.txt | python bulk_scraper.py -

Input file: one URL per line, # comments ignored, blank lines ignored.
"""

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
except ImportError:
    sys.exit("Missing dep: pip install playwright && playwright install chromium")

sys.path.insert(0, str(Path(__file__).parent))
from html_extractor import sanitize_filename


RAW_HTML_DIR = Path("raw_html")
DEFAULT_CONCURRENCY = 8
TIMEOUT_MS = 30_000
RETRIES = 2


# ---------------------------------------------------------------------------
# Single-URL worker (runs in a thread)
# ---------------------------------------------------------------------------

def scrape_one(url: str, browser, output_dir: Path) -> dict:
    """
    Scrape one URL in its own browser context.
    Returns a result dict: {url, file, html_size, elapsed, error}.
    """
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    filename = sanitize_filename(url).replace(".md", ".html")
    html_path = output_dir / filename
    meta_path = output_dir / (filename + ".meta.json")

    # Skip if already scraped
    if html_path.exists():
        return {"url": url, "file": filename, "status": "skipped",
                "html_size": html_path.stat().st_size}

    t0 = time.time()
    ctx = None
    for attempt in range(1, RETRIES + 1):
        try:
            ctx = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
                ),
                java_script_enabled=True,
                ignore_https_errors=True,
            )
            page = ctx.new_page()
            page.goto(url, wait_until="networkidle", timeout=TIMEOUT_MS)
            html = page.content()
            ctx.close()
            ctx = None

            html_path.write_text(html, encoding="utf-8", errors="replace")
            meta = {
                "url": url,
                "scraped_at": datetime.now(timezone.utc).isoformat(),
                "html_size_bytes": len(html.encode("utf-8")),
                "filename": filename,
            }
            meta_path.write_text(json.dumps(meta, indent=2))

            return {
                "url": url, "file": filename, "status": "ok",
                "html_size": len(html), "elapsed": round(time.time() - t0, 1),
            }

        except PWTimeout:
            if ctx:
                ctx.close()
                ctx = None
            if attempt < RETRIES:
                time.sleep(2 ** (attempt - 1))
                continue
            return {"url": url, "file": filename, "status": "error",
                    "error": f"Timeout after {TIMEOUT_MS/1000:.0f}s"}

        except Exception as e:
            if ctx:
                try:
                    ctx.close()
                except Exception:
                    pass
                ctx = None
            if attempt < RETRIES:
                time.sleep(2 ** (attempt - 1))
                continue
            return {"url": url, "file": filename, "status": "error", "error": str(e)[:200]}

    return {"url": url, "file": filename, "status": "error", "error": "max retries"}


# ---------------------------------------------------------------------------
# Parallel batch scraper
# ---------------------------------------------------------------------------

def scrape_bulk(
    urls: list[str],
    output_dir: Path = RAW_HTML_DIR,
    concurrency: int = DEFAULT_CONCURRENCY,
    on_result=None,          # callback(result_dict) called after each URL
) -> list[dict]:
    """
    Scrape all URLs in parallel. Returns list of result dicts.
    `on_result` is called from worker threads — must be thread-safe.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    results = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                futures = {
                    pool.submit(scrape_one, url, browser, output_dir): url
                    for url in urls
                }
                for future in as_completed(futures):
                    try:
                        result = future.result()
                    except Exception as e:
                        url = futures[future]
                        result = {"url": url, "status": "error", "error": str(e)[:200]}
                    results.append(result)
                    if on_result:
                        on_result(result)
        finally:
            browser.close()

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def load_urls(source: str) -> list[str]:
    """Load URLs from a file path or '-' for stdin."""
    if source == "-":
        lines = sys.stdin.read().splitlines()
    else:
        lines = Path(source).read_text(encoding="utf-8").splitlines()
    return [
        line.strip() for line in lines
        if line.strip() and not line.strip().startswith("#")
    ]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parallel bulk HTML scraper for TAM analysis."
    )
    parser.add_argument("input", help="URL list file (one URL/line) or '-' for stdin")
    parser.add_argument("--concurrency", "-c", type=int, default=DEFAULT_CONCURRENCY,
                        help=f"Parallel workers (default: {DEFAULT_CONCURRENCY})")
    parser.add_argument("--output-dir", "-o", default=str(RAW_HTML_DIR),
                        help=f"Output directory (default: {RAW_HTML_DIR})")
    args = parser.parse_args()

    urls = load_urls(args.input)
    if not urls:
        sys.exit("No URLs found in input.")

    output_dir = Path(args.output_dir)
    print(f"Scraping {len(urls)} URLs with concurrency={args.concurrency} → {output_dir}/")

    done = [0]
    errors = [0]
    t_start = time.time()

    def on_result(r):
        done[0] += 1
        if r["status"] == "error":
            errors[0] += 1
            print(f"  [{done[0]}/{len(urls)}] ✗ {r['url']} — {r.get('error','')}")
        elif r["status"] == "skipped":
            print(f"  [{done[0]}/{len(urls)}] ~ {r['url']} (skipped, already scraped)")
        else:
            kb = r.get("html_size", 0) / 1024
            print(f"  [{done[0]}/{len(urls)}] ✓ {r['url']} ({kb:.0f}KB, {r.get('elapsed',0)}s)")

    scrape_bulk(urls, output_dir=output_dir, concurrency=args.concurrency, on_result=on_result)

    elapsed = time.time() - t_start
    ok = done[0] - errors[0]
    print(f"\nDone in {elapsed:.1f}s — {ok} OK, {errors[0]} failed, {len(urls)} total.")


if __name__ == "__main__":
    main()
