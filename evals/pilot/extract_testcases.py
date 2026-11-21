#!/usr/bin/env python3
"""Extract pilot-phase evaluation test cases from the QnA .docx into testcases.json.

The source document (pilot_phase_evaluation_QnA.docx) defines a set of
structured question/answer evaluation cases across engineering disciplines
(Architecture, Front-End, DFT, Verification, Finance/HR, Back-End).

This script is stdlib-only (zipfile + xml) so it runs anywhere without python-docx.
It is reproducible: re-run it whenever the source doc changes.

Output schema (list of objects):
    id                 e.g. "ARCH.1"
    category           e.g. "Architecture"
    title              human description of the case (may be empty)
    use_case           e.g. "UC1" (the referenced use-case id, may be empty)
    complexity         "Simple" | "Medium" | "Complex" | ""
    relevance          "Relevant" | "Partially relevant" | "Non-relevant" | ""
    query              the user prompt to send to RagWeave (<= 2000 chars)
    expected_answer    the rubric / model answer used by the LLM judge
    context            "Context & Expected Outcome" narrative (grading context)
    expected_sources   expected paragraph/document references (may be empty)
"""

from __future__ import annotations

import json
import os
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

DEFAULT_DOCX = os.environ.get("PILOT_QNA_DOCX", "pilot_phase_evaluation_QnA.docx")
OUT = Path(__file__).resolve().parent / "testcases.json"

# Maps the test-case id prefix to a human-readable discipline/category.
CATEGORY = {
    "ARCH": "Architecture",
    "FE": "Front-End",
    "DFT": "DFT",
    "DV": "Verification",
    "FIN": "Finance/HR",
    "BE": "Back-End",
}

# Markers that separate the user prompt from grading material in the doc body.
QUERY_END_MARKERS = [
    "context & expected",
    "context and expected",
    "source document",
    "expected response",
    "expected answer",
    "expected outcome",
    "why asked",
]

# API limit for the query field (see server/schemas.py QueryRequest.query max_length).
QUERY_MAX = 2000


def _text_of(el) -> str:
    parts = []
    for t in el.iter():
        tag = t.tag.split("}")[-1]
        if tag == "t":
            parts.append(t.text or "")
        elif tag == "tab":
            parts.append("\t")
        elif tag in ("br", "cr"):
            parts.append("\n")
    return "".join(parts)


def docx_to_lines(path: str) -> list:
    """Flatten document.xml paragraphs/tables into a list of text lines."""
    with zipfile.ZipFile(path) as zf:
        xml = zf.read("word/document.xml")
    root = ET.fromstring(xml)
    body = root.find(W + "body")
    out = []

    def walk(el):
        for child in el:
            tag = child.tag.split("}")[-1]
            if tag == "p":
                out.append(_text_of(child))
            elif tag == "tbl":
                out.append("[TABLE]")
                for row in child.findall(W + "tr"):
                    cells = [
                        " ".join(_text_of(p) for p in cell.findall(W + "p")).strip()
                        for cell in row.findall(W + "tc")
                    ]
                    out.append(" | ".join(cells))
                out.append("[/TABLE]")
            else:
                walk(child)

    walk(body)
    return out


def parse_classification(header_tail: str):
    """Split the header text after the id into use_case/complexity/relevance/title."""
    use_case = complexity = relevance = ""
    title_bits = []
    for tok in re.split(r"[/:]", header_tail):
        t = tok.strip()
        if not t:
            continue
        low = t.lower()
        if re.fullmatch(r"uc\s*\d+", low):
            use_case = "UC" + re.sub(r"\D", "", t)
        elif low in ("simple", "medium", "complex"):
            complexity = t.capitalize()
        elif low in ("relevant", "non-relevant", "nonrelevant", "non relevant"):
            relevance = "Non-relevant" if low.startswith("non") else "Relevant"
        elif "partially relevant" in low:
            relevance = "Partially relevant"
        else:
            title_bits.append(t)
    return use_case, complexity, relevance, ": ".join(title_bits).strip()


def split_query(question_block: str):
    """Return (query_to_send, context_remainder) from a raw question block."""
    q = question_block.strip()
    # Strip a leading "Question:" / "Question" label.
    q = re.sub(r"^question\s*:?\s*", "", q, flags=re.IGNORECASE)
    low = q.lower()
    positions = [low.find(m) for m in QUERY_END_MARKERS]
    positions = [p for p in positions if p >= 0]
    # A pasted table inside the prompt is grading scaffolding, not user text,
    # UNLESS the prompt is essentially only a table reference (rare). Cut there too.
    tbl = q.find("[TABLE]")
    if tbl >= 0:
        positions.append(tbl)
    cut = min(positions) if positions else len(q)
    query = q[:cut].strip()
    context = q[cut:].strip()
    # Collapse internal whitespace runs but keep sentence structure.
    query = re.sub(r"[ \t]+", " ", query).strip()
    if len(query) > QUERY_MAX:
        query = query[:QUERY_MAX].rsplit(" ", 1)[0].strip()
    return query, context


def main():
    docx = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DOCX
    if not Path(docx).exists():
        sys.exit(f"Source docx not found: {docx}")

    lines = docx_to_lines(docx)

    # Locate the real "Architecture test cases" heading (skip the table-of-contents
    # entry near the top by requiring it to appear well past the contents block).
    start = None
    for i, l in enumerate(lines):
        if i > 200 and l.strip() == "Architecture test cases":
            start = i
            break
    if start is None:
        sys.exit("Could not locate the test-cases section in the document.")
    body = lines[start:]

    hdr_re = re.compile(r"^Test [Cc]ase\s+([A-Z]{2,4}\.\d+)\s*:?\s*(.*)$")
    heads = []
    for i, l in enumerate(body):
        m = hdr_re.match(l.strip())
        if m:
            heads.append((i, m.group(1), m.group(2).strip()))
    heads.append((len(body), None, None))

    exp_re = re.compile(r"^Expected\b", re.IGNORECASE)
    para_re = re.compile(r"^Expected Paragraph", re.IGNORECASE)

    cases = []
    for k in range(len(heads) - 1):
        si, cid, header_tail = heads[k]
        ei = heads[k + 1][0]
        block = body[si + 1: ei]

        q_start = e_start = ref_start = None
        for j, l in enumerate(block):
            s = l.strip()
            if s.lower() == "question" and q_start is None:
                q_start = j
            if exp_re.match(s) and not para_re.match(s) and e_start is None:
                e_start = j
            if para_re.match(s) and ref_start is None:
                ref_start = j

        if q_start is not None:
            qend = e_start if e_start is not None else (ref_start or len(block))
            qblock = "\n".join(block[q_start + 1: qend])
        else:
            qend = e_start if e_start is not None else (ref_start or len(block))
            qblock = "\n".join(block[:qend])

        if e_start is not None:
            eend = ref_start if (ref_start is not None and ref_start > e_start) else len(block)
            expected = "\n".join(block[e_start: eend]).strip()
        else:
            expected = ""

        refs = "\n".join(block[ref_start:]).strip() if ref_start is not None else ""
        # Strip the "Expected Paragraph References" label from the refs body.
        refs = re.sub(r"^Expected Paragraph References\s*:?\s*", "", refs, flags=re.IGNORECASE).strip()

        prefix = cid.split(".")[0]
        use_case, complexity, relevance, title = parse_classification(header_tail)

        query, ctx_from_q = split_query(qblock)
        # Context lives either inline in the question block or is implied; keep what we found.
        context = ctx_from_q.strip()

        cases.append({
            "id": cid,
            "category": CATEGORY.get(prefix, prefix),
            "title": title,
            "use_case": use_case,
            "complexity": complexity,
            "relevance": relevance,
            "query": query,
            "expected_answer": expected,
            "context": context,
            "expected_sources": refs,
        })

    # Drop any case whose query came out empty (malformed block).
    cases = [c for c in cases if c["query"]]

    OUT.write_text(json.dumps(cases, indent=2, ensure_ascii=False))
    print(f"Wrote {len(cases)} test cases -> {OUT}")
    for c in cases:
        print(f"  {c['id']:8} [{c['complexity'] or '?'}/{c['relevance'] or '?'}] "
              f"q={len(c['query'])}c exp={len(c['expected_answer'])}c :: {c['query'][:70]}")


if __name__ == "__main__":
    main()
