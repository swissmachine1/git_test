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
from html_analyzer import (
    EXTRACTION_SYSTEM, EXTRACTION_PROMPT,
    ANALYSIS_SYSTEM, ANALYSIS_PROMPT,
    PROFILE_SYSTEM, PROFILE_PROMPT,
    SCORING_SYSTEM, SCORING_PROMPT,
    MAX_CONTENT_CHARS,
)

OUTPUT_DIR = Path("html_output")
CANDS_DIR  = Path("candidates_output")
STATIC_DIR = Path(__file__).parent / "static"
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
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    STATIC_DIR.mkdir(exist_ok=True)
    OUTPUT_DIR.mkdir(exist_ok=True)
    port = int(os.environ.get("PORT", 8000))
    print(f"Starting HTML Analyzer UI → http://localhost:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
