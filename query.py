#!/usr/bin/env python3
# @summary
# Core RAG query logic: logging setup, filter parsing, result display, output suppression.
# Main exports: parse_filters, display_results, _quiet_output, _detect_vector_backend, _setup_logging.
# Deps: re, sys, os, contextlib, logging, pathlib, src.retrieval.rag_chain, src.platform.validation
# @end-summary
"""Core query logic for the RAG system — logging, filters, display, output suppression."""

import contextlib
import logging
import os
import re
import sys
from pathlib import Path

# Allow imports from project root
sys.path.insert(0, str(Path(__file__).parent))

from src.platform.validation import validate_filter_value

# ── ANSI colors ──────────────────────────────────────────────────────────────
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
RED = "\033[31m"
WHITE = "\033[97m"

B_CYAN = f"{BOLD}{CYAN}"
B_GREEN = f"{BOLD}{GREEN}"
B_YELLOW = f"{BOLD}{YELLOW}"
B_BLUE = f"{BOLD}{BLUE}"
B_MAGENTA = f"{BOLD}{MAGENTA}"
B_RED = f"{BOLD}{RED}"
B_WHITE = f"{BOLD}{WHITE}"

# ── Logging setup ────────────────────────────────────────────────────────────
LOG_DIR = Path(__file__).parent / "logs"
LOG_FILE = LOG_DIR / "rag_query.log"
_verbose_mode = False

# Icons and colors for each rag.* sub-logger
_LOGGER_STYLE = {
    "rag.query_processor": (f"{B_MAGENTA}⟡ Query{RESET}", MAGENTA),
    "rag.rag_chain":       (f"{B_CYAN}⟡ Chain{RESET}", CYAN),
    "rag.vector_store":    (f"{B_BLUE}⟡ Store{RESET}", BLUE),
    "rag.generator":       (f"{B_GREEN}⟡ Gen{RESET}", GREEN),
    "rag.knowledge_graph": (f"{B_YELLOW}⟡ KG{RESET}", YELLOW),
    "rag.query_cli":       (f"{B_WHITE}⟡ CLI{RESET}", WHITE),
}

_LEVEL_BADGE = {
    "DEBUG":    f"{DIM}DBG{RESET}",
    "INFO":     f"{B_CYAN}ℹ{RESET}",
    "WARNING":  f"{B_YELLOW}⚠{RESET}",
    "ERROR":    f"{B_RED}✗{RESET}",
    "CRITICAL": f"{B_RED}✗✗{RESET}",
}


class StyledConsoleHandler(logging.Handler):
    """Pretty-prints rag.* logs to the console. Silences everything else."""

    def emit(self, record):
        # Only show rag.* namespace on console (unless verbose)
        if not record.name.startswith("rag.") and not _verbose_mode:
            return
        # In non-verbose mode, skip DEBUG
        if not _verbose_mode and record.levelno < logging.INFO:
            return

        badge = _LEVEL_BADGE.get(record.levelname, f"{DIM}?{RESET}")
        label, color = _LOGGER_STYLE.get(
            record.name, (f"{DIM}⟡ {record.name}{RESET}", "")
        )
        msg = record.getMessage()

        # Parse out useful info for common patterns
        if record.name == "rag.query_processor":
            msg = _style_query_processor_msg(msg, color)

        print(f"    {badge}  {label}  {DIM}{msg}{RESET}")

    def _verbose_emit(self, record):
        """Show all loggers in verbose mode."""
        badge = _LEVEL_BADGE.get(record.levelname, f"{DIM}?{RESET}")
        msg = record.getMessage()
        print(f"    {badge}  {DIM}{record.name}{RESET}  {msg}")


def _style_query_processor_msg(msg: str, color: str) -> str:
    """Make query processor messages more readable."""
    # "Iteration 1: reformulated 'x' -> 'y'"
    m = re.match(r"Iteration (\d+): reformulated '(.+)' -> '(.+)'", msg)
    if m:
        return f"Reformulation #{m.group(1)}: {RESET}{m.group(3)}"

    # "Iteration 1: confidence=0.45 reasoning='...'"
    m = re.match(r"Iteration (\d+): confidence=([\d.]+) reasoning='(.+)'", msg)
    if m:
        conf = float(m.group(2))
        if conf >= 0.7:
            cc = B_GREEN
        elif conf >= 0.4:
            cc = B_YELLOW
        else:
            cc = B_RED
        return f"Confidence: {cc}{conf:.0%}{RESET}  {DIM}{m.group(3)}{RESET}"

    # "Query processing complete: action=search confidence=0.70 ..."
    m = re.match(r"Query processing complete: action=(\w+) confidence=([\d.]+) iterations=(\d+) query='(.+)'", msg)
    if m:
        return f"Final: {RESET}{B_WHITE}{m.group(4)}{RESET} {DIM}({m.group(1)}, {m.group(3)} iters){RESET}"

    # "Processing query: '...'"
    m = re.match(r"Processing query: '(.+)'", msg)
    if m:
        return f"Processing: {RESET}{m.group(1)}"

    return msg


def _setup_logging():
    """Configure logging: file gets everything, console gets styled rag.* only."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    # Root logger captures all
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # Remove any existing handlers (from basicConfig etc.)
    root.handlers.clear()

    # File handler — captures everything for debugging
    file_handler = logging.FileHandler(LOG_FILE, mode="a", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(name)s | %(levelname)s | %(message)s"
    ))
    root.addHandler(file_handler)

    # Styled console handler — only rag.* namespace by default
    console_handler = StyledConsoleHandler()
    console_handler.setLevel(logging.DEBUG)
    root.addHandler(console_handler)


_setup_logging()
logger = logging.getLogger("rag.query_cli")


@contextlib.contextmanager
def _quiet_output():
    """Suppress stdout/stderr at OS fd level to catch subprocess output (Weaviate Go JSON, tqdm).

    Python-level sys.stderr redirect does NOT catch output from child processes
    that write directly to inherited file descriptors. os.dup2 redirects the
    underlying fd so even Go/C subprocesses writing to fd 1/2 are silenced.
    Python's own sys.stdout is re-pointed to a copy of the original fd so our
    print() calls still reach the terminal.
    """
    import warnings

    # Save original OS-level file descriptors
    saved_stdout_fd = os.dup(1)
    saved_stderr_fd = os.dup(2)
    devnull_fd = os.open(os.devnull, os.O_WRONLY)

    # Create a Python file object from the saved stdout fd for our own output
    saved_stdout = os.fdopen(os.dup(saved_stdout_fd), "w")
    old_sys_stdout = sys.stdout
    old_sys_stderr = sys.stderr

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            # Redirect OS-level fds to /dev/null — catches subprocess output
            os.dup2(devnull_fd, 1)
            os.dup2(devnull_fd, 2)
            # Point Python's sys.stdout to the saved copy so print() still works
            sys.stdout = saved_stdout
            sys.stderr = open(os.devnull, "w")
            yield
        finally:
            # Restore OS-level fds
            os.dup2(saved_stdout_fd, 1)
            os.dup2(saved_stderr_fd, 2)
            sys.stdout = old_sys_stdout
            sys.stderr = old_sys_stderr
            os.close(saved_stdout_fd)
            os.close(saved_stderr_fd)
            os.close(devnull_fd)
            saved_stdout.close()


def _detect_vector_backend() -> str:
    """Auto-detect the vector store backend from installed packages."""
    try:
        import weaviate
        return "Weaviate"
    except ImportError:
        pass
    try:
        import chromadb
        return "ChromaDB"
    except ImportError:
        pass
    try:
        import qdrant_client
        return "Qdrant"
    except ImportError:
        pass
    try:
        import pinecone
        return "Pinecone"
    except ImportError:
        pass
    return "Vector DB"


# ── Filter parsing ───────────────────────────────────────────────────────────

# Filter prefix patterns: "source:filename.txt" or "section:Heading"
_FILTER_PAT = re.compile(
    r"\b(source|section):(\S+)\s*", re.IGNORECASE
)


def parse_filters(raw_query: str) -> tuple:
    """Extract filter prefixes from query, return (clean_query, filters_dict).

    Supported filters:
        source:<filename>   — filter by source document
        section:<heading>   — filter by section heading

    Example:
        "source:sample_doc_3.txt what is RAG?"
        → ("what is RAG?", {"source_filter": "sample_doc_3.txt"})
    """
    filters = {}
    def _replace(m):
        key = m.group(1).lower()
        value = m.group(2)
        if key == "source":
            filters["source_filter"] = value
        elif key == "section":
            filters["heading_filter"] = value
        return ""

    clean = _FILTER_PAT.sub(_replace, raw_query).strip()
    if "source_filter" in filters:
        filters["source_filter"] = validate_filter_value("source_filter", filters["source_filter"])
    if "heading_filter" in filters:
        filters["heading_filter"] = validate_filter_value("heading_filter", filters["heading_filter"])
    return clean, filters


def _truncate(text: str, max_len: int) -> str:
    """Truncate text for display."""
    text = text.replace("\n", " ")
    if len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text


def display_results(response, elapsed: float) -> None:
    """Pretty-print RAG results."""
    print()
    print(f"  {DIM}{'─' * 72}{RESET}")

    # Query metadata
    print(f"  {B_WHITE}Query{RESET}         {response.query}")
    print(f"  {DIM}Processed{RESET}     {response.processed_query}")

    # Confidence with color coding
    conf = response.query_confidence
    if conf >= 0.7:
        conf_color = B_GREEN
    elif conf >= 0.4:
        conf_color = B_YELLOW
    else:
        conf_color = B_RED
    print(f"  {DIM}Confidence{RESET}    {conf_color}{conf:.0%}{RESET}")

    # Action badge
    action_colors = {
        "answer": B_GREEN,
        "ask_user": B_YELLOW,
        "search": B_CYAN,
    }
    ac = action_colors.get(response.action, DIM)
    print(f"  {DIM}Action{RESET}        {ac}{response.action}{RESET}")

    if response.kg_expanded_terms:
        terms = ", ".join(response.kg_expanded_terms[:5])
        print(f"  {DIM}KG expansion{RESET}  {B_BLUE}{terms}{RESET}")

    print(f"  {DIM}{'─' * 72}{RESET}")

    if response.action == "ask_user":
        print(f"\n  {B_YELLOW}?{RESET} {response.clarification_message}")
        return

    # Show generated answer prominently
    if response.generated_answer:
        print()
        print(f"  {B_GREEN}✦ Answer{RESET} {DIM}({elapsed:.1f}s){RESET}\n")
        # Indent each line of the answer
        for line in response.generated_answer.split("\n"):
            print(f"  {line}")
        print()
        print(f"  {DIM}{'─' * 72}{RESET}")

    if not response.results:
        print(f"\n  {B_YELLOW}⚠{RESET} No results found.\n")
        return

    # Retrieved chunks
    print(f"\n  {B_WHITE}Top {len(response.results)} retrieved chunks{RESET}\n")
    for i, result in enumerate(response.results, 1):
        score_color = B_GREEN if result.score >= 0.5 else (B_YELLOW if result.score >= 0.2 else DIM)
        print(f"  {B_CYAN}#{i}{RESET}  {score_color}score: {result.score:.4f}{RESET}  {DIM}│{RESET}  {B_MAGENTA}{result.metadata.get('source', 'unknown')}{RESET}")
        section = result.metadata.get("section_path", "")
        if section:
            print(f"      {DIM}section:{RESET} {section}")
        print(f"      {DIM}{_truncate(result.text, 200)}{RESET}")
        print()
