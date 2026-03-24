#!/usr/bin/env python3
"""
TAM Scanner — orchestrates full technology mapping across a TAM.

Workflow:
  1. Point at raw_html/ directory (filled by bulk_scraper.py)
  2. Optionally: provide competitor HTML files → Claude generates custom fingerprints
  3. Scan every HTML file for built-in + custom tech signatures
  4. Output: JSON matrix + CSV + Markdown report

Usage:
    # Scan with built-in signatures only
    python tam_scanner.py

    # Scan with competitor-derived custom fingerprints
    python tam_scanner.py --competitors raw_html/stripe.com.html raw_html/braintree.com.html

    # Custom input/output dirs
    python tam_scanner.py --input-dir raw_html --output-dir tam_results
"""

import argparse
import csv
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from tech_fingerprints import (
    SIGNATURES,
    scan_html_file,
    generate_custom_fingerprints,
    apply_custom_fingerprints,
)

RAW_HTML_DIR   = Path("raw_html")
RESULTS_DIR    = Path("tam_results")
SCAN_WORKERS   = 16  # CPU-bound regex, benefit from parallelism


# ---------------------------------------------------------------------------
# Core scan
# ---------------------------------------------------------------------------

def scan_file_full(
    html_path: Path,
    custom_fingerprints: list[dict],
) -> dict:
    """Scan one HTML file with built-in + custom fingerprints."""
    html = html_path.read_text(encoding="utf-8", errors="replace")
    result = scan_html_file(html_path)

    if custom_fingerprints:
        custom = apply_custom_fingerprints(html, custom_fingerprints)
        result.update(custom)

    # Load metadata if available
    meta_path = html_path.parent / (html_path.name + ".meta.json")
    url = html_path.stem.replace("_", ".")
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text())
            url = meta.get("url", url)
        except Exception:
            pass

    return {
        "url": url,
        "file": html_path.name,
        "technologies": result,
        "tech_count": len(result),
    }


def run_scan(
    input_dir: Path = RAW_HTML_DIR,
    competitor_paths: list[Path] | None = None,
    api_key: str = "",
    on_progress=None,     # callback(done, total, url)
) -> dict:
    """
    Run a full TAM scan. Returns the complete results dict.
    `on_progress` is called from worker threads — must be thread-safe.
    """
    html_files = sorted(input_dir.glob("*.html"))
    if not html_files:
        return {"error": f"No .html files found in {input_dir}"}

    # ── Generate custom fingerprints from competitors ─────────────────────
    custom_fingerprints: list[dict] = []
    if competitor_paths:
        key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        for cp in competitor_paths:
            if not cp.exists():
                continue
            html = cp.read_text(encoding="utf-8", errors="replace")
            fps = generate_custom_fingerprints(html, api_key=key)
            custom_fingerprints.extend(fps)

    # ── Parallel scan ─────────────────────────────────────────────────────
    total = len(html_files)
    done = [0]
    company_results = {}

    with ThreadPoolExecutor(max_workers=SCAN_WORKERS) as pool:
        futures = {
            pool.submit(scan_file_full, f, custom_fingerprints): f
            for f in html_files
        }
        for future in as_completed(futures):
            try:
                r = future.result()
                company_results[r["url"]] = r
            except Exception as e:
                f = futures[future]
                company_results[str(f)] = {"url": str(f), "error": str(e), "technologies": {}}
            done[0] += 1
            if on_progress:
                url = company_results.get(list(company_results.keys())[-1], {}).get("url", "")
                on_progress(done[0], total, url)

    # ── Aggregate statistics ──────────────────────────────────────────────
    tech_stats: dict[str, dict] = {}
    for sig_id, sig in SIGNATURES.items():
        tech_stats[sig_id] = {
            "name": sig["name"],
            "category": sig["category"],
            "homepage": sig.get("homepage", ""),
            "count": 0,
            "companies": [],
        }
    for fp in custom_fingerprints:
        name = fp.get("name", "")
        if name and name not in tech_stats:
            tech_stats[name] = {
                "name": name,
                "category": fp.get("category", "Custom"),
                "homepage": fp.get("homepage", ""),
                "count": 0,
                "companies": [],
                "source": "custom",
            }

    for url, r in company_results.items():
        for tech_id, tech in r.get("technologies", {}).items():
            key = tech.get("name", tech_id)
            if key not in tech_stats:
                tech_stats[key] = {
                    "name": key,
                    "category": tech.get("category", "Other"),
                    "count": 0,
                    "companies": [],
                }
            tech_stats[key]["count"] += 1
            tech_stats[key]["companies"].append(url)

    # Sort by usage count
    tech_stats_sorted = dict(
        sorted(tech_stats.items(), key=lambda x: x[1]["count"], reverse=True)
    )

    return {
        "scan_id": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_companies": total,
        "signatures_checked": len(SIGNATURES) + len(custom_fingerprints),
        "custom_fingerprints": len(custom_fingerprints),
        "company_results": company_results,
        "tech_stats": tech_stats_sorted,
    }


# ---------------------------------------------------------------------------
# Export helpers
# ---------------------------------------------------------------------------

def save_json(scan: dict, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = scan["scan_id"].replace(":", "-").replace("T", "_")[:16]
    path = output_dir / f"scan_{ts}.json"
    path.write_text(json.dumps(scan, indent=2))
    return path


def save_csv(scan: dict, output_dir: Path) -> Path:
    """Save a company × technology matrix CSV."""
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = scan["scan_id"].replace(":", "-").replace("T", "_")[:16]
    path = output_dir / f"matrix_{ts}.csv"

    # Collect all technology names detected at least once
    all_techs = [
        t["name"]
        for t in scan["tech_stats"].values()
        if t["count"] > 0
    ]

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["URL", "Tech Count"] + all_techs)
        for url, r in scan["company_results"].items():
            detected_names = {
                t["name"] for t in r.get("technologies", {}).values()
            }
            row = [url, r.get("tech_count", 0)] + [
                "✓" if tech in detected_names else ""
                for tech in all_techs
            ]
            writer.writerow(row)

    return path


def save_report(scan: dict, output_dir: Path) -> Path:
    """Save a human-readable Markdown report."""
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = scan["scan_id"].replace(":", "-").replace("T", "_")[:16]
    path = output_dir / f"report_{ts}.md"

    total = scan["total_companies"]
    lines = [
        f"# TAM Technology Report",
        f"*Generated {scan['scan_id']} · {total} companies · "
        f"{scan['signatures_checked']} signatures*",
        "",
        "## Technology Coverage",
        "",
        "| Technology | Category | Companies | Coverage |",
        "|---|---|---|---|",
    ]

    for stat in scan["tech_stats"].values():
        if stat["count"] == 0:
            continue
        pct = stat["count"] / total * 100
        lines.append(
            f"| {stat['name']} | {stat['category']} | "
            f"{stat['count']} | {pct:.1f}% |"
        )

    lines += [
        "",
        "## Company Details",
        "",
    ]
    for url, r in sorted(
        scan["company_results"].items(),
        key=lambda x: x[1].get("tech_count", 0),
        reverse=True,
    ):
        techs = ", ".join(
            t["name"] for t in r.get("technologies", {}).values()
        )
        lines.append(f"**{url}** ({r.get('tech_count', 0)} techs): {techs}")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="TAM technology scanner — maps the tech stack of every company in your TAM."
    )
    parser.add_argument("--input-dir", "-i", default=str(RAW_HTML_DIR),
                        help=f"Directory of raw HTML files (default: {RAW_HTML_DIR})")
    parser.add_argument("--output-dir", "-o", default=str(RESULTS_DIR),
                        help=f"Output directory for results (default: {RESULTS_DIR})")
    parser.add_argument("--competitors", "-c", nargs="+", metavar="HTML_FILE",
                        help="Raw HTML files of competitor sites for custom fingerprinting")
    parser.add_argument("--workers", type=int, default=SCAN_WORKERS,
                        help=f"Parallel scan workers (default: {SCAN_WORKERS})")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    if not input_dir.is_dir():
        sys.exit(f"Error: {input_dir} is not a directory.")

    html_files = list(input_dir.glob("*.html"))
    if not html_files:
        sys.exit(f"No .html files found in {input_dir}. Run bulk_scraper.py first.")

    competitor_paths = [Path(c) for c in (args.competitors or [])]
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")

    if competitor_paths:
        print(f"Generating custom fingerprints from {len(competitor_paths)} competitor(s)...")
        if not api_key:
            print("  Warning: ANTHROPIC_API_KEY not set — skipping custom fingerprinting.")
            competitor_paths = []

    print(f"\nScanning {len(html_files)} companies with {args.workers} workers...")
    t0 = time.time()

    done = [0]
    def on_progress(d, total, url):
        done[0] = d
        if d % 10 == 0 or d == total:
            print(f"  [{d}/{total}]", flush=True)

    global SCAN_WORKERS
    SCAN_WORKERS = args.workers

    scan = run_scan(
        input_dir=input_dir,
        competitor_paths=competitor_paths if competitor_paths else None,
        api_key=api_key,
        on_progress=on_progress,
    )

    if "error" in scan:
        sys.exit(scan["error"])

    output_dir = Path(args.output_dir)
    json_path = save_json(scan, output_dir)
    csv_path  = save_csv(scan, output_dir)
    md_path   = save_report(scan, output_dir)

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed:.1f}s")
    print(f"  JSON   → {json_path}")
    print(f"  CSV    → {csv_path}")
    print(f"  Report → {md_path}")

    # Top 10 techs
    print("\nTop technologies detected:")
    stats = scan["tech_stats"]
    top = [(v["name"], v["count"], v["category"])
           for v in stats.values() if v["count"] > 0]
    for name, count, cat in top[:15]:
        pct = count / scan["total_companies"] * 100
        print(f"  {pct:5.1f}%  {count:4d}  {name} ({cat})")


if __name__ == "__main__":
    main()
