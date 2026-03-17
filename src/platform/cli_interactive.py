"""Shared interactive command menu/input helpers for terminal CLIs."""

from __future__ import annotations

import os
import readline
import sys
import termios
import tty
from typing import Iterable


def get_menu_items(
    registry: dict[str, tuple],
    filter_text: str = "",
) -> list[tuple[str, str]]:
    """Return filtered (command_name, description) pairs."""
    ft = filter_text.lower()
    return [
        (name, desc)
        for name, (_, desc) in registry.items()
        if name.lower().startswith(ft)
    ]


def redraw_menu(
    prompt: str,
    buf: str,
    items: Iterable[tuple[str, str]],
    sel: int,
    *,
    box_width: int,
    dim: str,
    reset: str,
    bold_cyan: str,
    bg_sel: str,
) -> None:
    """Redraw prompt + typed buffer + command dropdown below it."""
    items = list(items)
    w = box_width
    sys.stdout.write(f"\r\033[J{prompt}{buf}")
    sys.stdout.write("\033[s")
    if items:
        sys.stdout.write(f"\n  {dim}┌{'─' * w}┐{reset}")
        for i, (name, desc) in enumerate(items):
            tag = f"/{name}"
            desc_w = w - 17
            cell_name = tag.ljust(14)
            cell_desc = desc[:desc_w].ljust(desc_w)
            if i == sel:
                sys.stdout.write(
                    f"\n  {dim}│{bg_sel} {bold_cyan}{cell_name}"
                    f"{reset}{bg_sel} {cell_desc} {reset}{dim}│{reset}"
                )
            else:
                sys.stdout.write(
                    f"\n  {dim}│{reset} {bold_cyan}{cell_name}"
                    f"{reset} {dim}{cell_desc}{reset} {dim}│{reset}"
                )
        sys.stdout.write(f"\n  {dim}└{'─' * w}┘{reset}")
    else:
        sys.stdout.write(f"\n    {dim}No matching commands{reset}")
    sys.stdout.write("\033[u")
    sys.stdout.flush()


def read_key(fd: int) -> str:
    """Read one keypress, including arrow key escape sequences."""
    ch = sys.stdin.read(1)
    if ch == "\x1b":
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


def interactive_command_select(
    prompt: str,
    registry: dict[str, tuple],
    *,
    box_width: int,
    dim: str,
    reset: str,
    bold_cyan: str,
    bg_sel: str,
) -> str | None:
    """Live-filtering command selector. Returns selected command or None."""
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    buf = "/"
    sel = 0
    items = get_menu_items(registry)
    try:
        tty.setcbreak(fd)
        redraw_menu(
            prompt, buf, items, sel,
            box_width=box_width, dim=dim, reset=reset, bold_cyan=bold_cyan, bg_sel=bg_sel
        )
        while True:
            key = read_key(fd)
            if key in ("\r", "\n"):
                sys.stdout.write("\r\033[J")
                if items:
                    chosen = items[sel][0]
                    sys.stdout.write(f"{prompt}/{chosen}\n")
                    sys.stdout.flush()
                    return chosen
                sys.stdout.flush()
                return None
            if key == "ESC":
                sys.stdout.write("\r\033[J")
                sys.stdout.flush()
                return None
            if key == "UP":
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

            items = get_menu_items(registry, buf[1:])
            if sel >= len(items):
                sel = max(0, len(items) - 1)
            redraw_menu(
                prompt, buf, items, sel,
                box_width=box_width, dim=dim, reset=reset, bold_cyan=bold_cyan, bg_sel=bg_sel
            )
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def get_input_with_menu(
    prompt: str,
    registry: dict[str, tuple],
    *,
    box_width: int,
    dim: str,
    reset: str,
    bold_cyan: str,
    bg_sel: str,
) -> str:
    """Read one line; opens interactive / menu when first key is slash."""
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
        cmd = interactive_command_select(
            prompt,
            registry,
            box_width=box_width,
            dim=dim,
            reset=reset,
            bold_cyan=bold_cyan,
            bg_sel=bg_sel,
        )
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
        return get_input_with_menu(
            prompt,
            registry,
            box_width=box_width,
            dim=dim,
            reset=reset,
            bold_cyan=bold_cyan,
            bg_sel=bg_sel,
        )

    sys.stdout.write("\r\033[K")
    sys.stdout.flush()
    readline.set_startup_hook(lambda: readline.insert_text(first))
    try:
        return input(prompt)
    finally:
        readline.set_startup_hook(None)


def setup_tab_completion(registry: dict[str, tuple]) -> None:
    """Configure readline tab-completion for / commands."""
    def completer(text, state):
        if text.startswith("/"):
            options = [f"/{name}" for name in registry if f"/{name}".startswith(text)]
        else:
            options = []
        return options[state] if state < len(options) else None

    readline.set_completer(completer)
    readline.set_completer_delims(" \t\n")
    readline.parse_and_bind("tab: complete")
