#!/usr/bin/env python3
"""
Web UI server for the HTML Analyzer pipeline.

Run:
    python app.py
    open http://localhost:8000

Set ANTHROPIC_API_KEY as an environment variable, or paste it into the UI.
"""

import asyncio
import json
import os
import sys
import threading
from pathlib import Path

try:
    import uvicorn
    from fastapi import FastAPI, Query
    from fastapi.responses import StreamingResponse, HTMLResponse
    from fastapi.staticfiles import StaticFiles
except ImportError:
    sys.exit("Missing deps: pip install fastapi uvicorn")

try:
    import anthropic
except ImportError:
    sys.exit("Missing dep: pip install anthropic")

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sys.exit("Missing dep: pip install playwright && playwright install chromium")

sys.path.insert(0, str(Path(__file__).parent))
from html_extractor import sanitize_filename, html_to_markdown
from bulk_scraper import scrape_bulk, RAW_HTML_DIR
from tech_fingerprints import (
    SIGNATURES, scan_html, scan_html_file,
    generate_custom_fingerprints, apply_custom_fingerprints,
)
from tam_scanner import run_scan, save_json, save_csv, save_report, RESULTS_DIR
from html_analyzer import (
    EXTRACTION_SYSTEM, EXTRACTION_PROMPT,
    ANALYSIS_SYSTEM, ANALYSIS_PROMPT,
    PROFILE_SYSTEM, PROFILE_PROMPT,
    SCORING_SYSTEM, SCORING_PROMPT,
    MAX_CONTENT_CHARS,
)

OUTPUT_DIR   = Path("html_output")
CANDS_DIR    = Path("candidates_output")
STATIC_DIR   = Path(__file__).parent / "static"
PROFILE_PATH = Path("lookalike_profile.json")

app = FastAPI(title="HTML Analyzer")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def sse(event_type: str, **data) -> str:
    return f"data: {json.dumps({'type': event_type, **data})}\n\n"


def make_streamer():
    """Return (emit_fn, async_generator). Call emit() from threads."""
    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue()

    def emit(item):
        loop.call_soon_threadsafe(q.put_nowait, item)

    async def stream():
        while (msg := await q.get()) is not None:
            yield msg

    return emit, stream


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse((STATIC_DIR / "index.html").read_text())


@app.get("/api/files")
async def list_files():
    OUTPUT_DIR.mkdir(exist_ok=True)
    result = []
    for f in sorted(OUTPUT_DIR.glob("*.md")):
        try:
            chars = len(f.read_text(encoding="utf-8"))
        except Exception:
            chars = 0
        result.append({"name": f.name, "size": f.stat().st_size, "chars": chars})
    return result


@app.delete("/api/files/{name}")
async def delete_file(name: str):
    p = OUTPUT_DIR / Path(name).name  # prevent path traversal
    if p.exists() and p.suffix == ".md":
        p.unlink()
        return {"ok": True}
    return {"ok": False}


@app.get("/api/profile")
async def get_profile():
    if PROFILE_PATH.exists():
        return json.loads(PROFILE_PATH.read_text())
    return {}


# ---------------------------------------------------------------------------
# SSE: Extract
# ---------------------------------------------------------------------------

@app.get("/api/extract")
async def extract_urls(urls: str = Query(...)):
    url_list = [u.strip() for u in urls.split(",") if u.strip()]
    OUTPUT_DIR.mkdir(exist_ok=True)

    emit, stream = make_streamer()

    def worker():
        emit(sse("log", text=f"Launching browser for {len(url_list)} URL(s)..."))
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                ctx = browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
                    ),
                    java_script_enabled=True,
                )
                page = ctx.new_page()

                for url in url_list:
                    if not url.startswith(("http://", "https://")):
                        url = "https://" + url
                    emit(sse("log", text=f"Fetching {url}..."))
                    try:
                        page.goto(url, wait_until="networkidle", timeout=30_000)
                        html = page.content()
                        md = html_to_markdown(html, base_url=url)
                        if len(md) > MAX_CONTENT_CHARS:
                            md = md[:MAX_CONTENT_CHARS] + "\n\n[truncated]"
                        filename = sanitize_filename(url)
                        (OUTPUT_DIR / filename).write_text(
                            f"<!-- source: {url} -->\n\n{md}", encoding="utf-8"
                        )
                        emit(sse("file", url=url, file=filename, chars=len(md)))
                    except Exception as e:
                        emit(sse("error", text=f"Failed {url}: {e}"))

                ctx.close()
                browser.close()
        except Exception as e:
            emit(sse("error", text=f"Browser error: {e}"))

        emit(sse("done"))
        emit(None)  # terminate async stream

    threading.Thread(target=worker, daemon=True).start()

    async def generate():
        async for chunk in stream():
            yield chunk

    return StreamingResponse(
        generate(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# SSE: Analyze (phases 1-3)
# ---------------------------------------------------------------------------

@app.get("/api/analyze")
async def analyze(
    files: str = Query(...),
    api_key: str = Query(default=""),
):
    file_list = [f.strip() for f in files.split(",") if f.strip()]
    key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")

    emit, stream = make_streamer()

    def worker():
        if not key:
            emit(sse("error", text="ANTHROPIC_API_KEY is not set."))
            emit(None)
            return

        client = anthropic.Anthropic(api_key=key)
        all_data = []

        # ── Phase 1: structured extraction ──────────────────────────────
        emit(sse("phase", n=1, text="Extracting business intelligence..."))

        for fname in file_list:
            p = OUTPUT_DIR / Path(fname).name
            if not p.exists():
                emit(sse("error", text=f"File not found: {fname}"))
                continue

            content = p.read_text(encoding="utf-8")
            emit(sse("log", text=f"Analyzing {fname}..."))
            try:
                with client.messages.stream(
                    model="claude-opus-4-6",
                    max_tokens=4096,
                    system=EXTRACTION_SYSTEM,
                    messages=[{
                        "role": "user",
                        "content": EXTRACTION_PROMPT.format(content=content),
                    }],
                    output_config={"format": {"type": "json_object"}},
                ) as s:
                    final = s.get_final_message()
                text = next((b.text for b in final.content if b.type == "text"), "{}")
                data = json.loads(text)
                data["_source"] = fname
                all_data.append(data)
                emit(sse("extracted", file=fname, name=data.get("business_name", fname)))
            except Exception as e:
                emit(sse("error", text=f"Extraction failed for {fname}: {e}"))

        if not all_data:
            emit(sse("error", text="No data could be extracted. Check your files."))
            emit(None)
            return

        data_block = "\n\n".join(
            f"### {d.get('_source', f'site_{i+1}')}\n"
            f"```json\n{json.dumps({k: v for k, v in d.items() if k != '_source'}, indent=2)}\n```"
            for i, d in enumerate(all_data)
        )

        # ── Phase 2: deep analysis (streaming text) ──────────────────────
        emit(sse("phase", n=2, text="Running deep comparative analysis..."))
        analysis_parts = []
        try:
            with client.messages.stream(
                model="claude-opus-4-6",
                max_tokens=16000,
                thinking={"type": "adaptive"},
                system=ANALYSIS_SYSTEM,
                messages=[{
                    "role": "user",
                    "content": ANALYSIS_PROMPT.format(n=len(all_data), data=data_block),
                }],
            ) as s:
                for event in s:
                    if (
                        event.type == "content_block_delta"
                        and event.delta.type == "text_delta"
                    ):
                        chunk = event.delta.text
                        analysis_parts.append(chunk)
                        emit(sse("analysis", text=chunk))
        except Exception as e:
            emit(sse("error", text=f"Analysis failed: {e}"))

        analysis = "".join(analysis_parts)

        # ── Phase 3: build lookalike profile ─────────────────────────────
        emit(sse("phase", n=3, text="Building lookalike profile..."))
        try:
            with client.messages.stream(
                model="claude-opus-4-6",
                max_tokens=8192,
                system=PROFILE_SYSTEM,
                messages=[{
                    "role": "user",
                    "content": PROFILE_PROMPT.format(
                        n=len(all_data), analysis=analysis, data=data_block
                    ),
                }],
                output_config={"format": {"type": "json_object"}},
            ) as s:
                final = s.get_final_message()
            text = next((b.text for b in final.content if b.type == "text"), "{}")
            profile = json.loads(text)
            PROFILE_PATH.write_text(json.dumps(profile, indent=2))
            emit(sse("profile", data=profile))
        except Exception as e:
            emit(sse("error", text=f"Profile build failed: {e}"))

        emit(sse("done"))
        emit(None)

    threading.Thread(target=worker, daemon=True).start()

    async def generate():
        async for chunk in stream():
            yield chunk

    return StreamingResponse(
        generate(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# SSE: Score candidates
# ---------------------------------------------------------------------------

@app.get("/api/score")
async def score_candidates(
    urls: str = Query(...),
    api_key: str = Query(default=""),
):
    url_list = [u.strip() for u in urls.split(",") if u.strip()]
    key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    CANDS_DIR.mkdir(exist_ok=True)

    emit, stream = make_streamer()

    def worker():
        if not key:
            emit(sse("error", text="ANTHROPIC_API_KEY is not set."))
            emit(None)
            return
        if not PROFILE_PATH.exists():
            emit(sse("error", text="No lookalike profile found — run analysis first."))
            emit(None)
            return

        profile = json.loads(PROFILE_PATH.read_text())
        profile_str = json.dumps(profile, indent=2)
        client = anthropic.Anthropic(api_key=key)

        # Extract candidates
        emit(sse("log", text=f"Extracting {len(url_list)} candidate site(s)..."))
        candidates = []
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                ctx = browser.new_context(java_script_enabled=True)
                page = ctx.new_page()
                for url in url_list:
                    if not url.startswith(("http://", "https://")):
                        url = "https://" + url
                    emit(sse("log", text=f"Fetching {url}..."))
                    try:
                        page.goto(url, wait_until="networkidle", timeout=30_000)
                        md = html_to_markdown(page.content(), base_url=url)
                        candidates.append({"url": url, "content": md[:MAX_CONTENT_CHARS]})
                    except Exception as e:
                        emit(sse("error", text=f"Failed {url}: {e}"))
                ctx.close()
                browser.close()
        except Exception as e:
            emit(sse("error", text=f"Browser error: {e}"))
            emit(None)
            return

        # Score each candidate
        emit(sse("log", text="Scoring candidates..."))
        scores = []
        for cand in candidates:
            emit(sse("log", text=f"Scoring {cand['url']}..."))
            try:
                with client.messages.stream(
                    model="claude-opus-4-6",
                    max_tokens=4096,
                    system=SCORING_SYSTEM,
                    messages=[{
                        "role": "user",
                        "content": SCORING_PROMPT.format(
                            profile=profile_str, content=cand["content"]
                        ),
                    }],
                    output_config={"format": {"type": "json_object"}},
                ) as s:
                    final = s.get_final_message()
                text = next((b.text for b in final.content if b.type == "text"), "{}")
                result = json.loads(text)
                result["url"] = cand["url"]
                scores.append(result)
                emit(sse("score", data=result))
            except Exception as e:
                emit(sse("error", text=f"Scoring failed for {cand['url']}: {e}"))

        scores.sort(key=lambda x: x.get("overall_score", 0), reverse=True)
        emit(sse("scores_done", data=scores))
        emit(None)

    threading.Thread(target=worker, daemon=True).start()

    async def generate():
        async for chunk in stream():
            yield chunk

    return StreamingResponse(
        generate(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# TAM endpoints
# ---------------------------------------------------------------------------

@app.get("/api/tam/raw-files")
async def list_raw_files():
    """List all scraped raw HTML files."""
    RAW_HTML_DIR.mkdir(exist_ok=True)
    files = []
    for f in sorted(RAW_HTML_DIR.glob("*.html")):
        meta_path = RAW_HTML_DIR / (f.name + ".meta.json")
        url = f.stem
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text())
                url = meta.get("url", url)
            except Exception:
                pass
        files.append({"name": f.name, "url": url, "size": f.stat().st_size})
    return files


@app.delete("/api/tam/raw-files/{name}")
async def delete_raw_file(name: str):
    p = RAW_HTML_DIR / Path(name).name
    if p.exists() and p.suffix == ".html":
        p.unlink()
        meta = RAW_HTML_DIR / (p.name + ".meta.json")
        if meta.exists():
            meta.unlink()
        return {"ok": True}
    return {"ok": False}


@app.get("/api/tam/scrape")
async def tam_scrape(
    urls: str = Query(...),
    concurrency: int = Query(default=8),
):
    """SSE: parallel bulk scrape URLs into raw_html/."""
    url_list = [u.strip() for u in urls.split(",") if u.strip()]
    RAW_HTML_DIR.mkdir(exist_ok=True)

    emit, stream = make_streamer()

    def worker():
        emit(sse("log", text=f"Starting bulk scrape of {len(url_list)} URL(s) "
                             f"with concurrency={concurrency}..."))
        ok = [0]
        err = [0]

        def on_result(r):
            if r["status"] == "ok":
                ok[0] += 1
                emit(sse("scraped", url=r["url"], file=r["file"],
                         html_size=r.get("html_size", 0),
                         elapsed=r.get("elapsed", 0)))
            elif r["status"] == "skipped":
                ok[0] += 1
                emit(sse("scraped", url=r["url"], file=r["file"],
                         html_size=r.get("html_size", 0), skipped=True))
            else:
                err[0] += 1
                emit(sse("error", text=f"Failed {r['url']}: {r.get('error','')}"))

        try:
            scrape_bulk(url_list, output_dir=RAW_HTML_DIR,
                        concurrency=concurrency, on_result=on_result)
        except Exception as e:
            emit(sse("error", text=f"Scrape error: {e}"))

        emit(sse("done", ok=ok[0], err=err[0], total=len(url_list)))
        emit(None)

    threading.Thread(target=worker, daemon=True).start()

    async def generate():
        async for chunk in stream():
            yield chunk

    return StreamingResponse(
        generate(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/tam/fingerprint")
async def tam_fingerprint(
    files: str = Query(...),
    api_key: str = Query(default=""),
):
    """SSE: generate custom fingerprints from competitor HTML files in raw_html/."""
    file_list = [f.strip() for f in files.split(",") if f.strip()]
    key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")

    emit, stream = make_streamer()

    def worker():
        if not key:
            emit(sse("error", text="ANTHROPIC_API_KEY not set."))
            emit(None)
            return

        all_fps = []
        for fname in file_list:
            p = RAW_HTML_DIR / Path(fname).name
            if not p.exists():
                emit(sse("error", text=f"File not found: {fname}"))
                continue
            emit(sse("log", text=f"Extracting fingerprints from {fname}..."))
            html = p.read_text(encoding="utf-8", errors="replace")
            fps = generate_custom_fingerprints(html, api_key=key)
            all_fps.extend(fps)
            emit(sse("fingerprints", file=fname, count=len(fps), data=fps))

        # Save fingerprints for later use
        fp_path = Path("custom_fingerprints.json")
        fp_path.write_text(json.dumps(all_fps, indent=2))
        emit(sse("done", total=len(all_fps)))
        emit(None)

    threading.Thread(target=worker, daemon=True).start()

    async def generate():
        async for chunk in stream():
            yield chunk

    return StreamingResponse(
        generate(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/tam/scan")
async def tam_scan(
    competitors: str = Query(default=""),
    api_key: str = Query(default=""),
):
    """SSE: scan all raw_html/ files for technologies."""
    key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    competitor_names = [f.strip() for f in competitors.split(",") if f.strip()]

    emit, stream = make_streamer()

    def worker():
        html_files = list(RAW_HTML_DIR.glob("*.html"))
        if not html_files:
            emit(sse("error", text="No HTML files found. Run TAM scrape first."))
            emit(None)
            return

        emit(sse("log", text=f"Scanning {len(html_files)} companies..."))

        competitor_paths = [
            RAW_HTML_DIR / Path(n).name
            for n in competitor_names
            if (RAW_HTML_DIR / Path(n).name).exists()
        ]

        # Load previously saved custom fingerprints if no competitors specified live
        custom_fingerprints: list[dict] = []
        fp_path = Path("custom_fingerprints.json")
        if not competitor_paths and fp_path.exists():
            try:
                custom_fingerprints = json.loads(fp_path.read_text())
                emit(sse("log", text=f"Using {len(custom_fingerprints)} saved custom fingerprints."))
            except Exception:
                pass

        if competitor_paths and key:
            emit(sse("log", text=f"Generating custom fingerprints from {len(competitor_paths)} competitor(s)..."))
            for cp in competitor_paths:
                html = cp.read_text(encoding="utf-8", errors="replace")
                fps = generate_custom_fingerprints(html, api_key=key)
                custom_fingerprints.extend(fps)
                emit(sse("log", text=f"  {cp.name}: {len(fps)} custom fingerprints found"))

        def on_progress(done, total, url):
            if done % max(1, total // 20) == 0 or done == total:
                emit(sse("progress", done=done, total=total))

        try:
            scan = run_scan(
                input_dir=RAW_HTML_DIR,
                competitor_paths=None,  # already handled above
                api_key=key,
                on_progress=on_progress,
            )
            # Inject custom fingerprints into results manually if we generated them
            if custom_fingerprints and "company_results" in scan:
                for url, r in scan["company_results"].items():
                    html_path = RAW_HTML_DIR / r.get("file", "")
                    if html_path.exists():
                        html = html_path.read_text(encoding="utf-8", errors="replace")
                        custom = apply_custom_fingerprints(html, custom_fingerprints)
                        r["technologies"].update(custom)
                        r["tech_count"] = len(r["technologies"])
        except Exception as e:
            emit(sse("error", text=f"Scan error: {e}"))
            emit(None)
            return

        RESULTS_DIR.mkdir(exist_ok=True)
        save_json(scan, RESULTS_DIR)
        save_csv(scan, RESULTS_DIR)
        save_report(scan, RESULTS_DIR)

        # Send summary
        top_techs = [
            {"name": v["name"], "category": v["category"],
             "count": v["count"], "pct": round(v["count"] / scan["total_companies"] * 100, 1)}
            for v in scan["tech_stats"].values()
            if v["count"] > 0
        ][:50]

        emit(sse("scan_done",
                 total=scan["total_companies"],
                 signatures=scan["signatures_checked"],
                 top_techs=top_techs,
                 full_results=scan["company_results"]))
        emit(None)

    threading.Thread(target=worker, daemon=True).start()

    async def generate():
        async for chunk in stream():
            yield chunk

    return StreamingResponse(
        generate(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/tam/results")
async def get_tam_results():
    """Return latest scan results if available."""
    RESULTS_DIR.mkdir(exist_ok=True)
    jsons = sorted(RESULTS_DIR.glob("scan_*.json"), reverse=True)
    if not jsons:
        return {}
    try:
        return json.loads(jsons[0].read_text())
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    STATIC_DIR.mkdir(exist_ok=True)
    OUTPUT_DIR.mkdir(exist_ok=True)
    port = int(os.environ.get("PORT", 8000))
    print(f"Starting HTML Analyzer UI → http://localhost:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
