# @summary
# Shared console service helpers for UI serving, static asset resolution, log snapshots, source previews, and rendering.
# Exports: CONSOLE_HTML_PATH, USER_CONSOLE_HTML_PATH, CONSOLE_STATIC_DIR, USER_CONSOLE_STATIC_DIR, resolve_console_html_path, resolve_user_console_html_path, resolve_console_static_asset, resolve_user_console_static_asset, is_ollama_reachable, tail_log_lines, resolve_console_source_path, build_source_preview_payload, render_source_document_html
# Deps: config.settings, server.schemas, fastapi
# @end-summary
"""Console service helpers."""

from __future__ import annotations

from collections import deque
from html import escape
from pathlib import Path
from urllib.parse import unquote, urlparse

from fastapi import HTTPException

from config.settings import DOCUMENTS_DIR, OLLAMA_BASE_URL
from server.schemas import ConsoleLogsResponse

_CONSOLE_DIR = Path(__file__).resolve().parent

# --- Admin Console (existing tabbed debug/ops interface) ---
_CONSOLE_HTML_CANDIDATES = (
    _CONSOLE_DIR / "static" / "console.html",
    _CONSOLE_DIR.parent / "console.html",  # Backward-compat for older local checkouts.
)
CONSOLE_STATIC_DIR = _CONSOLE_DIR / "static"

# --- User Console (modern chat interface) ---
USER_CONSOLE_STATIC_DIR = _CONSOLE_DIR / "static" / "user"
_USER_CONSOLE_HTML_PATH = USER_CONSOLE_STATIC_DIR / "index.html"


def resolve_console_html_path() -> Path:
    """Resolve admin console HTML path with fallback for legacy locations."""
    for candidate in _CONSOLE_HTML_CANDIDATES:
        if candidate.exists():
            return candidate
    return _CONSOLE_HTML_CANDIDATES[0]


CONSOLE_HTML_PATH = resolve_console_html_path()


def resolve_user_console_html_path() -> Path:
    """Resolve User Console HTML path."""
    return _USER_CONSOLE_HTML_PATH


USER_CONSOLE_HTML_PATH = resolve_user_console_html_path()


def resolve_console_static_asset(asset_path: str) -> Path:
    """Resolve and validate static console asset path (admin console)."""
    candidate = (CONSOLE_STATIC_DIR / asset_path).resolve()
    static_root = CONSOLE_STATIC_DIR.resolve()
    if not str(candidate).startswith(str(static_root)):
        raise HTTPException(status_code=404, detail="Console asset not found")
    if not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="Console asset not found")
    return candidate


def resolve_user_console_static_asset(asset_path: str) -> Path:
    """Resolve and validate static asset path for the User Console."""
    candidate = (USER_CONSOLE_STATIC_DIR / asset_path).resolve()
    static_root = USER_CONSOLE_STATIC_DIR.resolve()
    if not str(candidate).startswith(str(static_root)):
        raise HTTPException(status_code=404, detail="User console asset not found")
    if not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="User console asset not found")
    return candidate


def is_ollama_reachable() -> bool:
    """Best-effort Ollama reachability probe from API process."""
    from urllib.request import Request, urlopen

    req = Request(f"{OLLAMA_BASE_URL.rstrip('/')}/api/tags", method="GET")
    try:
        with urlopen(req, timeout=3):
            return True
    except Exception:
        return False


def tail_log_lines(lines: int = 120) -> ConsoleLogsResponse:
    """Return a tail snapshot across common local log files."""
    logs_dir = Path(__file__).resolve().parent.parent.parent / "logs"
    log_files = [
        logs_dir / "query_processing.log",
        logs_dir / "ingest.log",
        logs_dir / "server.log",
    ]
    out_lines: deque[str] = deque(maxlen=max(10, lines))
    found_files: list[str] = []
    for candidate in log_files:
        if not candidate.exists():
            continue
        found_files.append(str(candidate))
        try:
            text = candidate.read_text(encoding="utf-8", errors="replace")
            for line in text.splitlines()[-lines:]:
                out_lines.append(f"[{candidate.name}] {line}")
        except Exception as exc:
            out_lines.append(f"[{candidate.name}] <read_error> {exc}")
    if not found_files:
        out_lines.append("No log files found in ./logs")
    return ConsoleLogsResponse(files=found_files, lines=list(out_lines))


def resolve_console_source_path(source: str | None, source_uri: str | None) -> Path:
    """Resolve console source reference to a local file under DOCUMENTS_DIR."""
    if source_uri:
        parsed = urlparse(source_uri)
        if parsed.scheme and parsed.scheme != "file":
            raise HTTPException(status_code=404, detail="Source URI is not a local file")
        candidate = Path(unquote(parsed.path)) if parsed.scheme == "file" else Path(source_uri)
    elif source:
        candidate = DOCUMENTS_DIR / Path(source).name
    else:
        raise HTTPException(status_code=400, detail="source or source_uri is required")

    try:
        resolved = candidate.resolve()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid source path") from exc

    documents_root = DOCUMENTS_DIR.resolve()
    if not str(resolved).startswith(str(documents_root)):
        raise HTTPException(status_code=400, detail="Invalid source path")
    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(status_code=404, detail="Source document not found")
    return resolved


def build_source_preview_payload(
    *,
    target: Path,
    source_uri: str | None,
    text: str,
    start: int | None,
    end: int | None,
    context_chars: int,
    max_chars: int,
) -> dict:
    """Build payload for `/console/source-document` preview endpoint."""
    total_chars = len(text)
    effective_max_chars = max(200, min(max_chars, 20000))
    preview_start = 0
    preview_end = min(total_chars, effective_max_chars)
    highlight_start = None
    highlight_end = None

    if start is not None and end is not None and end > start:
        safe_start = max(0, min(start, total_chars))
        safe_end = max(safe_start, min(end, total_chars))
        context = max(100, min(context_chars, 5000))
        preview_start = max(0, safe_start - context)
        preview_end = min(total_chars, safe_end + context)
        if preview_end - preview_start > effective_max_chars:
            preview_end = min(total_chars, preview_start + effective_max_chars)
            if preview_end < safe_end:
                preview_end = safe_end
                preview_start = max(0, preview_end - effective_max_chars)
        highlight_start = safe_start
        highlight_end = safe_end

    clipped = text[preview_start:preview_end]
    return {
        "source": target.name,
        "path": str(target),
        "source_uri": source_uri or target.as_uri(),
        "preview": clipped,
        "truncated": preview_start > 0 or preview_end < total_chars,
        "total_chars": total_chars,
        "preview_start": preview_start,
        "preview_end": preview_end,
        "highlight_start": highlight_start,
        "highlight_end": highlight_end,
    }


def render_source_document_html(
    *,
    target: Path,
    text: str,
    start: int | None,
    end: int | None,
    chunk: int | None,
) -> str:
    """Render HTML document with optional highlighted source range."""
    total_chars = len(text)
    safe_start = 0
    safe_end = 0
    has_range = start is not None and end is not None and end > start
    if has_range:
        safe_start = max(0, min(start, total_chars))
        safe_end = max(safe_start, min(end, total_chars))

    if has_range:
        before = escape(text[:safe_start])
        highlighted = escape(text[safe_start:safe_end]) or "&nbsp;"
        after = escape(text[safe_end:])
        body = f"{before}<mark>{highlighted}</mark>{after}"
    else:
        body = escape(text)

    chunk_label = f"Chunk {chunk}" if chunk is not None and chunk > 0 else "Document View"
    range_label = f"chars {safe_start}..{safe_end}" if has_range else "no highlight range provided"
    return (
        "<!doctype html><html><head><meta charset='utf-8' />"
        f"<title>{escape(target.name)} - {escape(chunk_label)}</title>"
        "<style>"
        "body{font-family:ui-sans-serif,system-ui;background:#0f1115;color:#e7ecf3;margin:0;padding:16px;}"
        ".meta{margin-bottom:10px;padding:10px;border:1px solid #2a3040;border-radius:8px;background:#171a21;}"
        ".mono{white-space:pre-wrap;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;"
        "line-height:1.45;border:1px solid #2a3040;border-radius:8px;padding:12px;background:#111522;}"
        "mark{background:#ffe08a;color:#111;}"
        "a{color:#4da3ff;}"
        "</style></head><body>"
        f"<div class='meta'><strong>{escape(target.name)}</strong><br/>"
        f"<span>{escape(str(target))}</span><br/>"
        f"<span>{escape(chunk_label)} | {escape(range_label)}</span><br/>"
        f"<span>total chars: {total_chars}</span></div>"
        f"<div class='mono'>{body}</div>"
        "</body></html>"
    )

