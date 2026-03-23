#!/usr/bin/env python3
"""
Reformat FR requirement blocks in markdown specs.

This script is intentionally narrow: it targets requirement blocks that use the
blockquote style:

> **FR-101** | Priority: MUST
> **Description:** ...
> **Rationale:** ...
> **Acceptance Criteria:** ...

It normalizes spacing so each sub-section is separated by a blank `>` line and
ensures Acceptance Criteria is a numbered list when it is written as a run-on
sentence ("Given..., Given..., ...").
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path


FR_HEADER_RE = re.compile(r"^> \*\*FR-(\d+)\*\* \| Priority: (MUST|SHOULD|MAY)\s*$")
SUBSECTION_RE = re.compile(r"^> \*\*(Description|Rationale|Acceptance Criteria):\*\*\s*(.*)$")
AC_LIST_ITEM_RE = re.compile(r"^> \d+\. ")


@dataclass(frozen=True)
class FormatResult:
    changed: bool
    output: str
    fr_blocks_seen: int
    fr_blocks_changed: int


def _split_run_on_acceptance_criteria(text: str) -> list[str]:
    """
    Convert a run-on Acceptance Criteria line into numbered items.

    Heuristic: split on occurrences of "Given " that start a new clause.
    We preserve the original punctuation as much as possible.
    """
    s = " ".join(text.strip().split())
    if not s:
        return []

    # If already looks like a list, leave it.
    if re.match(r"^\d+\.\s", s):
        return [s]

    # Split on "Given " occurrences that are likely to begin a new criterion.
    parts = re.split(r"(?<!\w)(?=Given )", s)
    parts = [p.strip() for p in parts if p.strip()]

    # If we didn't actually split, keep as a single item.
    if len(parts) <= 1:
        return [s]

    # Ensure each part ends with punctuation for readability.
    normalized: list[str] = []
    for p in parts:
        if p[-1] not in ".!?":
            p = p + "."
        normalized.append(p)
    return normalized


def _format_fr_block(lines: list[str]) -> tuple[list[str], bool]:
    """
    Given raw lines for a single FR block (starting at FR header), return
    formatted lines and whether a change occurred.
    """
    # Preserve any trailing blank lines that were captured as part of the block
    # so the formatter can be idempotent (both `>` blank quote lines and empty lines).
    trailing_lines: list[str] = []
    while len(lines) > 1 and (lines[-1].strip() == ">" or (lines[-1].strip() == "" and not lines[-1].startswith(">"))):
        trailing_lines.append(lines.pop())
    trailing_lines.reverse()

    out: list[str] = []

    # Always keep header line.
    out.append(lines[0])

    i = 1
    # Preserve (but do not force) blank quote lines after header.
    while i < len(lines) and lines[i].strip() == ">":
        out.append(">")
        i += 1

    # We will re-emit subsections with normalized spacing.
    pending_subsections: list[tuple[str, str]] = []
    acceptance_criteria_lines: list[str] = []
    acceptance_criteria_raw: list[str] = []

    def flush_pending() -> None:
        for name, payload in pending_subsections:
            out.append(f"> **{name}:**{(' ' + payload) if payload else ''}".rstrip())
            out.append(">")
        pending_subsections.clear()

    while i < len(lines):
        line = lines[i]

        m = SUBSECTION_RE.match(line)
        if m:
            name, payload = m.group(1), m.group(2)
            if name == "Acceptance Criteria":
                # Flush Description/Rationale already collected.
                flush_pending()

                # Emit AC header line.
                out.append("> **Acceptance Criteria:**")

                # Collect AC content lines until next subsection or end.
                i += 1
                while i < len(lines):
                    nxt = lines[i]
                    if SUBSECTION_RE.match(nxt) or FR_HEADER_RE.match(nxt):
                        break
                    if nxt.strip().startswith(">"):
                        # Remove leading "> " prefix for parsing.
                        stripped = nxt[1:].lstrip()
                        if stripped:
                            acceptance_criteria_lines.append(stripped)
                            acceptance_criteria_raw.append(nxt.rstrip())
                    i += 1

                def _looks_like_complex_multiline_ac(items: list[str]) -> bool:
                    # If AC contains nested bullets/indentation, preserve verbatim.
                    for it in items:
                        s = it.lstrip()
                        if s.startswith(("-", "*")):
                            return True
                        if it.startswith(("  ", "\t")):
                            return True
                    return False

                # If AC content already numbered list, keep as-is.
                if _looks_like_complex_multiline_ac(acceptance_criteria_lines):
                    # Preserve complex, multi-line AC blocks verbatim.
                    out.extend(acceptance_criteria_raw)
                elif any(AC_LIST_ITEM_RE.match(l) for l in lines):
                    # Re-emit original numbered lines (already prefixed in original).
                    # But we still enforce a blank quote line above (done) and keep the items.
                    # Prefer canonical numbering starting at 1 in case numbering is off.
                    items: list[str] = []
                    for raw in acceptance_criteria_lines:
                        raw = raw.strip()
                        if not raw:
                            continue
                        raw = re.sub(r"^\d+\.\s*", "", raw)
                        items.append(raw)
                    for n, item in enumerate(items, start=1):
                        out.append(f"> {n}. {item}")
                else:
                    # Collapse all AC lines into one and split heuristically.
                    joined = " ".join(acceptance_criteria_lines).strip()
                    items = _split_run_on_acceptance_criteria(joined)
                    if len(items) == 1:
                        out.append(f"> 1. {items[0]}")
                    else:
                        for n, item in enumerate(items, start=1):
                            out.append(f"> {n}. {item}")

                acceptance_criteria_lines.clear()
                acceptance_criteria_raw.clear()

                continue

            # For Description/Rationale: store; we'll re-emit with spacing.
            pending_subsections.append((name, payload.strip()))
            i += 1
            continue

        # Preserve other quote lines that aren't subsections, but normalize spacing:
        if line.strip() == ">":
            # If we have a pending subsection (e.g., Description) that hasn't been
            # emitted yet, we don't want to move blank lines ahead of it. We'll
            # let the normalized subsection flush insert the spacer.
            if pending_subsections:
                i += 1
                continue
            # Preserve a single blank quote line (collapse runs).
            if not out or out[-1].strip() != ">":
                out.append(">")
            i += 1
            continue

        # If we hit non-subsection content within the blockquote (e.g., a table),
        # flush pending subsections then pass through as-is, keeping it quoted.
        if line.startswith(">"):
            if pending_subsections:
                flush_pending()
            out.append(line.rstrip())
            i += 1
            continue

        # Non-quote line ends the FR block. Flush pending and stop.
        break

    if pending_subsections:
        # If block ended without AC section, still flush Description/Rationale with spacing.
        flush_pending()

    # Add any remaining original trailing lines within the FR block that were beyond parsing.
    # (In practice, the loop breaks on the first non-quote line; we don't include it.)
    # If our normalization matched the existing style exactly, we might falsely mark changed.
    # We'll do a final equality check against original.
    original = "\n".join(l.rstrip() for l in (lines + trailing_lines)).rstrip() + "\n"
    formatted = "\n".join(l.rstrip() for l in (out + trailing_lines)).rstrip() + "\n"
    out.extend(trailing_lines)
    return out, (original != formatted)


def format_markdown(text: str) -> FormatResult:
    lines = text.splitlines()
    out: list[str] = []
    i = 0
    seen = 0
    changed_blocks = 0
    changed_any = False

    while i < len(lines):
        line = lines[i]
        if FR_HEADER_RE.match(line):
            seen += 1
            block: list[str] = [line.rstrip()]
            i += 1
            while i < len(lines):
                nxt = lines[i]
                if FR_HEADER_RE.match(nxt):
                    break
                # Stop block when we leave the blockquote context and hit a new section header.
                if nxt.startswith("## ") or nxt.startswith("### ") or nxt.startswith("#### "):
                    break
                # Keep collecting: FR blocks in this spec are in blockquotes; we include
                # intervening blank lines as part of the block so the formatter can normalize.
                if nxt.startswith(">") or nxt.strip() == "":
                    block.append(nxt.rstrip())
                    i += 1
                    continue
                # Non-quote content ends the block.
                break

            formatted_block, block_changed = _format_fr_block(block)
            out.extend(formatted_block)
            if block_changed:
                changed_blocks += 1
                changed_any = True
            continue

        out.append(line.rstrip())
        i += 1

    output_text = "\n".join(out).rstrip() + "\n"
    return FormatResult(
        changed=changed_any,
        output=output_text,
        fr_blocks_seen=seen,
        fr_blocks_changed=changed_blocks,
    )


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Reformat FR blocks in a markdown spec.")
    p.add_argument("path", type=Path, help="Path to markdown spec file to reformat")
    p.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if changes would be made (no write).",
    )
    p.add_argument(
        "--write",
        action="store_true",
        help="Write changes back to the file.",
    )
    return p


def main() -> int:
    args = _build_parser().parse_args()
    path: Path = args.path
    if not path.exists():
        print(f"File not found: {path}", file=sys.stderr)
        return 2

    original = path.read_text(encoding="utf-8")
    res = format_markdown(original)

    if args.check:
        if res.changed:
            print(
                f"Would reformat {path} (FR blocks seen={res.fr_blocks_seen}, changed={res.fr_blocks_changed}).",
                file=sys.stderr,
            )
            return 1
        print(f"OK: {path} (FR blocks seen={res.fr_blocks_seen}).")
        return 0

    if args.write:
        if res.changed:
            path.write_text(res.output, encoding="utf-8")
            print(
                f"Reformatted {path} (FR blocks seen={res.fr_blocks_seen}, changed={res.fr_blocks_changed})."
            )
        else:
            print(f"No changes needed: {path} (FR blocks seen={res.fr_blocks_seen}).")
        return 0

    # Default is dry-run summary.
    if res.changed:
        print(
            f"Would reformat {path} (FR blocks seen={res.fr_blocks_seen}, changed={res.fr_blocks_changed})."
        )
    else:
        print(f"No changes needed: {path} (FR blocks seen={res.fr_blocks_seen}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

