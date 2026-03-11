#!/usr/bin/env python3
# @summary
# Thin CLI client that connects to the RAG API server. Same REPL experience
# as cli.py, but no model loading — queries go over HTTP to the server.
# Exports: main
# Deps: urllib.request, json, sys
# @end-summary
"""CLI client for the RAG API server.

Same interactive experience as the local CLI, but queries are sent over
HTTP to the FastAPI server → Temporal → preloaded worker. No torch,
no transformers, no GPU needed in this process. Starts instantly.

Usage:
    python -m server.cli_client
    python -m server.cli_client --server http://localhost:8000
"""

import json
import logging
import os
import re
import readline
import sys
import termios
import time
import tty
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
_LOG_DIR.mkdir(exist_ok=True)

logger = logging.getLogger("rag.cli_client")
logger.setLevel(logging.DEBUG)
_fh = logging.FileHandler(_LOG_DIR / "cli_client.log")
_fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
logger.addHandler(_fh)

# ANSI colors
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
_BG_SEL = "\033[48;5;237m"


DEFAULT_SERVER = os.environ.get("RAG_API_URL", "http://localhost:8000")
_FILTER_PAT = re.compile(r"\b(source|section):(\S+)\s*", re.IGNORECASE)
_CURRENT_SERVER = DEFAULT_SERVER
_verbose_mode = False

# Command registry for parity with cli.py UX
_COMMANDS: dict[str, tuple] = {}


def _register_command(name: str, description: str):
    def decorator(func):
        _COMMANDS[name] = (func, description)
        return func
    return decorator


_BOX_W = 50


def _get_menu_items(filter_text: str = "") -> list[tuple[str, str]]:
    ft = filter_text.lower()
    return [
        (name, desc)
        for name, (_, desc) in _COMMANDS.items()
        if name.lower().startswith(ft)
    ]


def _redraw_menu(prompt: str, buf: str, items: list, sel: int) -> None:
    w = _BOX_W
    sys.stdout.write(f"\r\033[J{prompt}{buf}")
    sys.stdout.write("\033[s")
    if items:
        sys.stdout.write(f"\n  {DIM}┌{'─' * w}┐{RESET}")
        for i, (name, desc) in enumerate(items):
            tag = f"/{name}"
            desc_w = w - 17
            cell_name = tag.ljust(14)
            cell_desc = desc[:desc_w].ljust(desc_w)
            if i == sel:
                sys.stdout.write(
                    f"\n  {DIM}│{_BG_SEL} {B_CYAN}{cell_name}"
                    f"{RESET}{_BG_SEL} {cell_desc} {RESET}{DIM}│{RESET}"
                )
            else:
                sys.stdout.write(
                    f"\n  {DIM}│{RESET} {B_CYAN}{cell_name}"
                    f"{RESET} {DIM}{cell_desc}{RESET} {DIM}│{RESET}"
                )
        sys.stdout.write(f"\n  {DIM}└{'─' * w}┘{RESET}")
    else:
        sys.stdout.write(f"\n    {DIM}No matching commands{RESET}")
    sys.stdout.write("\033[u")
    sys.stdout.flush()


def _read_key(fd: int) -> str:
    ch = sys.stdin.read(1)
    if ch == "\x1b":
        old_flags = termios.tcgetattr(fd)
        try:
            import fcntl
            flags = fcntl.fcntl(fd, fcntl.F_GETFL)
            fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
            try:
                seq = os.read(fd, 10).decode("utf-8", errors="replace")
            except (BlockingIOError, OSError):
                seq = ""
            finally:
                fcntl.fcntl(fd, fcntl.F_SETFL, flags)
        except Exception:
            seq = ""

        if seq.startswith("[A"):
            return "UP"
        if seq.startswith("[B"):
            return "DOWN"
        if seq.startswith("[C"):
            return "RIGHT"
        if seq.startswith("[D"):
            return "LEFT"
        return "ESC"
    return ch


def _interactive_command_select(prompt: str) -> str | None:
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    buf = "/"
    sel = 0
    items = _get_menu_items()
    try:
        tty.setcbreak(fd)
        _redraw_menu(prompt, buf, items, sel)
        while True:
            key = _read_key(fd)
            if key in ("\r", "\n"):
                sys.stdout.write("\r\033[J")
                if items:
                    chosen = items[sel][0]
                    sys.stdout.write(f"{prompt}/{chosen}\n")
                    sys.stdout.flush()
                    return chosen
                sys.stdout.flush()
                return None
            elif key == "ESC":
                sys.stdout.write("\r\033[J")
                sys.stdout.flush()
                return None
            elif key == "UP":
                sel = max(0, sel - 1)
            elif key == "DOWN":
                sel = min(len(items) - 1, sel + 1) if items else 0
            elif key in ("\x7f", "\x08"):
                if len(buf) > 1:
                    buf = buf[:-1]
                    sel = 0
                else:
                    sys.stdout.write("\r\033[J")
                    sys.stdout.flush()
                    return None
            elif key == "\x03":
                sys.stdout.write("\r\033[J")
                sys.stdout.flush()
                raise KeyboardInterrupt
            elif key == "\x04":
                sys.stdout.write("\r\033[J")
                sys.stdout.flush()
                raise EOFError
            elif len(key) == 1 and key.isprintable():
                buf += key
                sel = 0
            else:
                continue

            items = _get_menu_items(buf[1:])
            if sel >= len(items):
                sel = max(0, len(items) - 1)
            _redraw_menu(prompt, buf, items, sel)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _get_input(prompt: str) -> str:
    if not sys.stdin.isatty():
        return input(prompt)

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    sys.stdout.write(prompt)
    sys.stdout.flush()

    try:
        tty.setcbreak(fd)
        first = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)

    if first == "/":
        cmd = _interactive_command_select(prompt)
        return f"/{cmd}" if cmd else ""
    if first == "\x03":
        raise KeyboardInterrupt
    if first == "\x04":
        raise EOFError
    if first in ("\r", "\n"):
        sys.stdout.write("\n")
        return ""
    if not first.isprintable():
        sys.stdout.write("\r\033[K")
        sys.stdout.flush()
        return _get_input(prompt)

    sys.stdout.write("\r\033[K")
    sys.stdout.flush()
    readline.set_startup_hook(lambda: readline.insert_text(first))
    try:
        return input(prompt)
    finally:
        readline.set_startup_hook(None)


def _setup_tab_completion():
    def completer(text, state):
        if text.startswith("/"):
            options = [f"/{name}" for name in _COMMANDS if f"/{name}".startswith(text)]
        else:
            options = []
        return options[state] if state < len(options) else None

    readline.set_completer(completer)
    readline.set_completer_delims(" \t\n")
    readline.parse_and_bind("tab: complete")


def parse_filters(raw_query: str) -> tuple[str, dict]:
    """Extract source:/section: filters from query text."""
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
    return clean, filters


def _truncate(text: str, max_len: int) -> str:
    text = text.replace("\n", " ")
    return text[:max_len - 3] + "..." if len(text) > max_len else text


def send_query(server: str, query: str, filters: dict) -> dict:
    """Send a non-streaming query to the RAG API."""
    payload = {"query": query, **filters}
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{server}/query",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def send_query_stream(server: str, query: str, filters: dict):
    """Stream a query via SSE. Yields (event_type, data_dict) tuples."""
    payload = {"query": query, **filters}
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{server}/query/stream",
        data=data,
        headers={
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
        method="POST",
    )
    resp = urllib.request.urlopen(req, timeout=120)
    current_event = None
    try:
        for raw_line in resp:
            line = raw_line.decode("utf-8").rstrip("\n")
            if line.startswith("event: "):
                current_event = line[7:]
            elif line.startswith("data: ") and current_event:
                yield current_event, json.loads(line[6:])
                current_event = None
    finally:
        resp.close()


def check_server(server: str, retries: int = 5, backoff: float = 1.0) -> dict | None:
    """Check if the API server is reachable, retrying on failure.

    Returns the parsed health JSON on success, or None if completely unreachable.
    """
    for attempt in range(retries):
        try:
            req = urllib.request.Request(f"{server}/health", method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                logger.info(
                    "Health check OK (attempt %d/%d): %s", attempt + 1, retries, data
                )
                return data
        except Exception as exc:
            logger.debug(
                "Health check attempt %d/%d failed: %s", attempt + 1, retries, exc
            )
            if attempt < retries - 1:
                time.sleep(backoff)
    logger.warning("Server unreachable after %d attempts", retries)
    return None


def display_retrieval(response: dict) -> None:
    """Display retrieval metadata and chunks (no generated answer — that streams separately)."""
    print()
    print(f"  {DIM}{'─' * 72}{RESET}")
    print(f"  {B_WHITE}Query{RESET}         {response['query']}")
    print(f"  {DIM}Processed{RESET}     {response['processed_query']}")

    conf = response["query_confidence"]
    if conf >= 0.7:
        cc = B_GREEN
    elif conf >= 0.4:
        cc = B_YELLOW
    else:
        cc = B_RED
    print(f"  {DIM}Confidence{RESET}    {cc}{conf:.0%}{RESET}")

    action_colors = {"answer": B_GREEN, "ask_user": B_YELLOW, "search": B_CYAN}
    ac = action_colors.get(response["action"], DIM)
    print(f"  {DIM}Action{RESET}        {ac}{response['action']}{RESET}")

    if response.get("kg_expanded_terms"):
        terms = ", ".join(response["kg_expanded_terms"][:5])
        print(f"  {DIM}KG expansion{RESET}  {B_BLUE}{terms}{RESET}")

    latency = response.get("latency_ms")
    if latency is not None:
        print(f"  {DIM}Retrieval{RESET}     {latency:.0f}ms")

    wf_id = response.get("workflow_id")
    if wf_id:
        logger.debug("Query handled by workflow %s", wf_id)

    print(f"  {DIM}{'─' * 72}{RESET}")

    if response["action"] == "ask_user":
        print(f"\n  {B_YELLOW}?{RESET} {response.get('clarification_message', '')}")
        return

    results = response.get("results", [])
    if not results:
        print(f"\n  {B_YELLOW}⚠{RESET} No results found.\n")
        return

    print(f"\n  {B_WHITE}Top {len(results)} retrieved chunks{RESET}\n")
    for i, r in enumerate(results, 1):
        score = r["score"]
        sc = B_GREEN if score >= 0.5 else (B_YELLOW if score >= 0.2 else DIM)
        source = r.get("metadata", {}).get("source", "unknown")
        print(f"  {B_CYAN}#{i}{RESET}  {sc}score: {score:.4f}{RESET}  {DIM}│{RESET}  {B_MAGENTA}{source}{RESET}")
        section = r.get("metadata", {}).get("section_path", "")
        if section:
            print(f"      {DIM}section:{RESET} {section}")
        print(f"      {DIM}{_truncate(r['text'], 200)}{RESET}")
        print()


def _display_stage_timings(done_data: dict | None, retrieval_data: dict | None) -> None:
    """Verbose stage-level timing split for retrieval/generation."""
    if not _verbose_mode:
        return

    stage_timings = []
    if done_data and done_data.get("stage_timings"):
        stage_timings = done_data.get("stage_timings", [])
    elif retrieval_data and retrieval_data.get("stage_timings"):
        stage_timings = retrieval_data.get("stage_timings", [])

    if not stage_timings:
        return

    print()
    print(f"  {B_WHITE}Stage timings (verbose){RESET}")
    print(f"  {DIM}{'-' * 72}{RESET}")
    for stage in stage_timings:
        bucket = str(stage.get("bucket", "other"))
        name = str(stage.get("stage", "unknown"))
        ms = float(stage.get("ms", 0.0))
        bucket_color = B_CYAN if bucket == "retrieval" else (B_GREEN if bucket == "generation" else DIM)
        print(f"  {bucket_color}{bucket:10}{RESET} {DIM}{name:24}{RESET} {ms:7.1f}ms")

    totals = {}
    if done_data and done_data.get("timing_totals"):
        totals = done_data.get("timing_totals", {})
    if totals:
        retrieval_total = float(totals.get("retrieval_ms", 0.0))
        generation_total = float(totals.get("generation_ms", 0.0))
        total = float(totals.get("total_ms", retrieval_total + generation_total))
        print(f"  {DIM}{'-' * 72}{RESET}")
        print(
            f"  {DIM}stage totals:{RESET} "
            f"{B_CYAN}retrieval {retrieval_total:.1f}ms{RESET} {DIM}|{RESET} "
            f"{B_GREEN}generation {generation_total:.1f}ms{RESET} {DIM}|{RESET} "
            f"{B_WHITE}total {total:.1f}ms{RESET}"
        )


def clear_screen():
    os.system("clear" if os.name != "nt" else "cls")


def print_banner(server: str):
    clear_screen()
    print()
    chip_lines = [
        "                    ██      ██      ██      ██      ██      ██      ██",
        "                    ║║      ║║      ║║      ║║      ║║      ║║      ║║",
        "           ┏━━━━━━━━╩╩━━━━━━╩╩━━━━━━╩╩━━━━━━╩╩━━━━━━╩╩━━━━━━╩╩━━━━━━╩╩━━━━━━━━━┓",
        "           ┃░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░┃│",
        "   ██━━━━━━┨░░ · · · · · · · · · · · · · · · · · · · · · · · · · · · · · · · ░░┠━━━━━━██",
        "           ┃░░    ┏╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍┓   ░░┃│",
        "   ██━━━━━━┨░░    ╏            ██████╗   █████╗   ██████╗                ╏   ░░┠━━━━━━██",
        "           ┃░░    ╏            ██╔══██╗ ██╔══██╗ ██╔════╝                ╏   ░░┃│",
        "   ██━━━━━━┨░░    ╏            ██████╔╝ ███████║ ██║  ███╗               ╏   ░░┠━━━━━━██",
        "           ┃░░    ╏            ██╔══██╗ ██╔══██║ ██║   ██║               ╏   ░░┃│",
        "   ██━━━━━━┨░░    ╏            ██║  ██║ ██║  ██║ ╚██████╔╝               ╏   ░░┠━━━━━━██",
        "           ┃░░    ╏            ╚═╝  ╚═╝ ╚═╝  ╚═╝  ╚═════╝                ╏   ░░┃│",
        "   ██━━━━━━┨░░    ┗╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍┛   ░░┠━━━━━━██",
        "           ┃░░ · · · · · · · · · · · · · · · · · · · · · · · · · · · · · · · ░░┃│",
        "           ┃░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░┃│",
        "           ┗━━━━━━━━╦╦━━━━━━╦╦━━━━━━╦╦━━━━━━╦╦━━━━━━╦╦━━━━━━╦╦━━━━━━╦╦━━━━━━━━━┛│",
        "            └───────║║──────║║──────║║──────║║──────║║──────║║──────║║──────────┘",
        "                    ║║      ║║      ║║      ║║      ║║      ║║      ║║",
        "                    ██      ██      ██      ██      ██      ██      ██",
    ]
    min_col = min((j for line in chip_lines for j, ch in enumerate(line) if ch != " "), default=0)
    max_col = max((j for line in chip_lines for j, ch in enumerate(line) if ch != " "), default=1)
    col_span = max(max_col - min_col, 1)
    for line in chip_lines:
        colored = []
        for j, ch in enumerate(line):
            t = max(0, j - min_col) / col_span
            r = int(255 * t)
            g = int(255 * (1 - t))
            colored.append(f"\033[1;38;2;{r};{g};255m{ch}")
        print("".join(colored) + RESET)
    print(f"{RESET}")
    print(f"{DIM}    ─────────────────────────────────────────────────────────────────────────────{RESET}")
    print(f"{B_WHITE}    RAG Query Engine{RESET}  {DIM}powered by{RESET} {B_MAGENTA}Claude{RESET} {DIM}+{RESET} {B_CYAN}Server Mode{RESET}")
    print(f"{DIM}    ─────────────────────────────────────────────────────────────────────────────{RESET}")
    print()
    print(f"  {DIM}Server:{RESET}  {B_WHITE}{server}{RESET}")
    print(f"  {DIM}Models loaded remotely — queries execute in ~100-500ms{RESET}")
    print()
    print(f"  {B_MAGENTA}[ Retrieval ]{RESET}  {B_BLUE}[ Reranker ]{RESET}  {B_GREEN}[ KG Expansion ]{RESET}  {B_YELLOW}[ Generation ]{RESET}")
    print()
    print(f"  {DIM}Filters: {RESET}{B_WHITE}source:<file>{RESET}{DIM} · {RESET}{B_WHITE}section:<heading>{RESET}")
    print(f"  {DIM}Type {RESET}{B_WHITE}/{RESET} {DIM}to see all commands{RESET}")
    print(f"{DIM}    ─────────────────────────────────────────────────────────────────────────────{RESET}")
    print()


def print_help():
    print(f"""
{B_WHITE}  Commands:{RESET}  {DIM}(type {RESET}{B_WHITE}/{RESET}{DIM} to open menu){RESET}
""")
    for name, (_, desc) in _COMMANDS.items():
        padded = f"/{name}".ljust(14)
        print(f"    {B_CYAN}{padded}{RESET} {DIM}{desc}{RESET}")
    print(f"""
{B_WHITE}  Filter Syntax:{RESET}
    {B_YELLOW}source:<file>{RESET}      Filter by source document
    {B_YELLOW}section:<heading>{RESET}  Filter by section heading

{B_WHITE}  Logs:{RESET}
    {DIM}Client logs are saved to{RESET} {B_WHITE}{_LOG_DIR / "cli_client.log"}{RESET}

{B_WHITE}  Example Queries:{RESET}
    {DIM}•{RESET} What is retrieval-augmented generation?
    {DIM}•{RESET} source:sample_doc_3.txt what is RAG?
    {DIM}•{RESET} section:Introduction explain the main concepts
    {DIM}•{RESET} How does the embedding pipeline work?
""")


@_register_command("help", "Show help message")
def _cmd_help():
    print_help()


@_register_command("clear", "Clear screen and show banner")
def _cmd_clear():
    print_banner(_CURRENT_SERVER)


@_register_command("verbose", "Toggle verbose client logging")
def _cmd_verbose():
    global _verbose_mode
    _verbose_mode = not _verbose_mode
    state = f"{B_GREEN}ON{RESET}" if _verbose_mode else f"{DIM}OFF{RESET}"
    print(f"  {B_CYAN}⟡{RESET} Verbose logging: {state}")
    print()


@_register_command("quit", "Exit the query engine")
def _cmd_quit():
    print(f"\n  {DIM}Goodbye! 👋{RESET}\n")
    os._exit(0)


def main() -> None:
    import argparse
    global _CURRENT_SERVER
    parser = argparse.ArgumentParser(description="RAG CLI client (server mode)")
    parser.add_argument("--server", default=DEFAULT_SERVER, help="API server URL")
    args = parser.parse_args()

    server = args.server.rstrip("/")
    _CURRENT_SERVER = server
    _setup_tab_completion()
    print_banner(server)

    print(f"  {B_CYAN}⟡{RESET} {DIM}Connecting to {server}...{RESET}", end="", flush=True)
    health = check_server(server, retries=6, backoff=1.5)
    if health is not None:
        temporal_ok = health.get("temporal_connected", False)
        worker_ok = health.get("worker_available", False)
        logger.info(
            "Connected — temporal=%s, worker=%s, status=%s",
            temporal_ok, worker_ok, health.get("status"),
        )
        if temporal_ok and worker_ok:
            print(f"\r  {B_GREEN}✓{RESET} Connected — ready to query                 ")
        elif temporal_ok:
            print(f"\r  {B_GREEN}✓{RESET} Connected — worker still loading models     ")
        else:
            print(f"\r  {B_GREEN}✓{RESET} Connected — backend services starting       ")
            print(f"    {DIM}Queries will work once all services are ready.{RESET}")
    else:
        print(f"\r  {B_YELLOW}⚠{RESET} Could not reach {server}              ")
        print(f"    {DIM}Make sure the server stack is running:{RESET}")
        print(f"    {B_WHITE}1.{RESET} {DIM}docker compose up -d{RESET}")
        print(f"    {B_WHITE}2.{RESET} {DIM}.venv/bin/python -m server.worker{RESET}")
        print(f"    {B_WHITE}3.{RESET} {DIM}.venv/bin/uvicorn server.api:app --port 8000{RESET}")
        print()
        print(f"    {DIM}You can still type queries — they'll work once the server is up.{RESET}")
    print()

    PROMPT = f"  {B_CYAN}❯{RESET} "

    while True:
        try:
            raw_input_str = _get_input(PROMPT).strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n\n  {DIM}Goodbye! 👋{RESET}\n")
            os._exit(0)

        if not raw_input_str:
            continue

        if raw_input_str.startswith("/"):
            cmd_name = raw_input_str[1:].lower()
            if cmd_name in _COMMANDS:
                handler, _ = _COMMANDS[cmd_name]
                handler()
            else:
                print(f"  {B_YELLOW}⚠{RESET} Unknown command: {B_WHITE}{raw_input_str}{RESET}")
                print(f"    {DIM}Type{RESET} {B_WHITE}/{RESET} {DIM}to see available commands{RESET}")
                print()
            continue

        query_text, filters = parse_filters(raw_input_str)
        if not query_text:
            print(f"  {B_YELLOW}⚠{RESET} Please provide a query (not just filters).")
            continue

        if filters:
            for k, v in filters.items():
                print(f"    {B_YELLOW}⬡{RESET} {DIM}{k}:{RESET} {v}")

        print()
        print(f"  {B_CYAN}⟡{RESET} {DIM}Querying server...{RESET}", end="", flush=True)
        start = time.time()

        try:
            retrieval_data = None
            generated_tokens = []
            done_data = None

            for event_type, data in send_query_stream(server, query_text, filters):
                if event_type == "retrieval":
                    retrieval_data = data
                    elapsed = time.time() - start
                    print(f"\r  {B_GREEN}✓{RESET} Retrieved {DIM}({elapsed:.1f}s){RESET}        ")
                    display_retrieval(retrieval_data)

                    if data.get("action") == "search" and data.get("results"):
                        print(f"\n  {B_GREEN}✦ Answer{RESET}\n")
                        sys.stdout.write("  ")
                        sys.stdout.flush()

                elif event_type == "token":
                    token = data.get("token", "")
                    generated_tokens.append(token)
                    if token == "\n":
                        sys.stdout.write(f"\n  ")
                    else:
                        sys.stdout.write(token)
                    sys.stdout.flush()

                elif event_type == "done":
                    done_data = data

                elif event_type == "error":
                    print(f"\n  {B_RED}✗{RESET} {data.get('message', 'Unknown error')}")

            if generated_tokens:
                print()
                total = done_data.get("latency_ms", 0) if done_data else (time.time() - start) * 1000
                ret_ms = done_data.get("retrieval_ms", 0) if done_data else 0
                gen_ms = done_data.get("generation_ms", 0) if done_data else 0
                tok_count = done_data.get("token_count", len(generated_tokens)) if done_data else len(generated_tokens)
                print()
                print(f"  {DIM}retrieval: {ret_ms:.0f}ms │ generation: {gen_ms:.0f}ms ({tok_count} tokens) │ total: {total:.0f}ms{RESET}")
                _display_stage_timings(done_data, retrieval_data)
            elif retrieval_data:
                # ask_user / no-generation path
                _display_stage_timings(done_data, retrieval_data)

            if retrieval_data and retrieval_data.get("action") == "ask_user":
                print(f"  {DIM}(Please rephrase your query or provide more detail.){RESET}\n")

        except urllib.error.HTTPError as exc:
            elapsed = time.time() - start
            print(f"\r  {B_RED}✗{RESET} HTTP {exc.code} {DIM}({elapsed:.1f}s){RESET}        ")
            try:
                body = json.loads(exc.read().decode("utf-8"))
                print(f"    {DIM}{body.get('detail', str(exc))}{RESET}")
            except Exception:
                print(f"    {DIM}{exc}{RESET}")
            print()
            continue
        except urllib.error.URLError as exc:
            print(f"\r  {B_RED}✗{RESET} Connection failed                   ")
            print(f"    {DIM}{exc.reason}{RESET}")
            print(f"    {DIM}Is the server running?{RESET}")
            print()
            continue
        except Exception as exc:
            print(f"\r  {B_RED}✗{RESET} Error: {exc}                   ")
            logger.exception("Query failed")
            print()
            continue

        print(f"\n  {DIM}{'─' * 72}{RESET}\n")


if __name__ == "__main__":
    main()
