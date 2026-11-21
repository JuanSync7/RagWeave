# @summary
# LLM-as-judge for the pilot eval harness. Runs Claude headless (`claude -p`)
# to grade a RagWeave answer against the expected answer / rubric, diagnose
# WHY it passed or failed, and propose concrete fixes. Returns a structured
# verdict dict; never raises.
# Exports: judge_case, JUDGE_SCHEMA_KEYS
# Deps: (stdlib only: subprocess, json) + the `claude` CLI on PATH
# @end-summary
"""Claude-headless judge that scores answers and suggests improvements.

The judge is the engine of the self-improving loop: besides a pass/fail it
emits a failure-mode taxonomy and targeted fix suggestions that improve.py
aggregates across the whole run.
"""

from __future__ import annotations

import json
import re
import subprocess

JUDGE_SCHEMA_KEYS = (
    "verdict", "overall", "scores", "why",
    "key_points_hit", "key_points_missed",
    "failure_modes", "suggested_fixes", "abstain_expected", "abstained",
)

_SYSTEM = """You are a rigorous RAG evaluation judge for an ASIC/semiconductor \
engineering knowledge base. You grade the answer a RAG \
system ("RagWeave") produced for an evaluation question, against an expected \
answer / rubric written by domain experts. Be strict, specific and fair. \
You output ONLY a single JSON object, no prose, no markdown fences."""

_RUBRIC = """\
Grade on these axes, each 0-5 (5 = excellent):
- faithfulness: every claim in the answer is supported by the retrieved chunks (no hallucination).
- correctness: the answer agrees with the expected answer / rubric on the substantive facts.
- completeness: the answer covers the key points the expected answer requires.
- retrieval: the retrieved chunks/documents are the right sources to answer this question.
- citations: the answer cites/attributes sources where the rubric expects citations.

IMPORTANT - relevance handling:
- If this test case is marked Non-relevant, the CORRECT behaviour is for the system to
  abstain / say the information is not in the knowledge base, and NOT to fabricate an answer.
  Set "abstain_expected": true. Set "abstained": true if the answer correctly declined.
  For Non-relevant cases, a confident fabricated answer is a FAIL even if it sounds plausible.
- If the RagWeave call failed (infra error / no answer), verdict is "error" and you must add
  the failure mode "infra_error" and NOT penalise retrieval/generation quality scores
  (leave them at 0 and explain).

Choose verdict: "pass" (fully acceptable), "partial" (usable but missing/again wrong points),
"fail" (wrong, fabricated, or empty), or "error" (the system errored / returned nothing).

overall: integer 0-100 holistic score consistent with the axis scores and verdict.

failure_modes: zero or more of:
  "retrieval_miss"      - the right document/section was not retrieved
  "wrong_doc"           - retrieved irrelevant or wrong-version documents
  "hallucination"       - asserted facts not supported by chunks
  "incomplete"          - missed required key points
  "no_citation"         - failed to cite sources the rubric expects
  "should_have_abstained" - fabricated an answer for a Non-relevant question
  "over_abstained"      - declined although the answer was retrievable
  "infra_error"         - the query failed / returned nothing
  "formatting"          - content ok but structure/format poor

suggested_fixes: concrete, actionable items aimed at the RAG pipeline. Each item:
  {"area": one of ["indexing","chunking","retrieval","reranking","query_processing",
                    "generation","prompting","data_coverage","citations","other"],
   "fix": "specific change to try",
   "rationale": "why this would help, tied to what you observed"}

Output JSON shape EXACTLY:
{
  "verdict": "pass|partial|fail|error",
  "overall": 0-100,
  "scores": {"faithfulness":0-5,"correctness":0-5,"completeness":0-5,"retrieval":0-5,"citations":0-5},
  "abstain_expected": true|false,
  "abstained": true|false,
  "key_points_hit": ["..."],
  "key_points_missed": ["..."],
  "why": "2-5 sentence diagnosis of why the answer is right or wrong",
  "failure_modes": ["..."],
  "suggested_fixes": [{"area":"...","fix":"...","rationale":"..."}]
}
"""


def _clip(text, n):
    if not text:
        return ""
    text = str(text)
    return text if len(text) <= n else text[:n] + "\n...[truncated]..."


def build_prompt(case: dict, result: dict) -> str:
    """Assemble the full judge prompt from a test case and a RagWeave result."""
    chunks = result.get("chunks") or []
    chunk_blocks = []
    for i, c in enumerate(chunks):
        chunk_blocks.append(
            f"[chunk {i+1}] score={c.get('score')} source={c.get('source')!r} "
            f"section={c.get('section')!r}\n{_clip(c.get('text'), 1200)}"
        )
    chunks_text = "\n\n".join(chunk_blocks) if chunk_blocks else "(no chunks retrieved)"

    sources = result.get("sources") or []
    src_text = "\n".join(
        f"- {s.get('source')} (chunks={s.get('chunk_count')}, best_score={s.get('best_score')})"
        for s in sources
    ) or "(none)"

    if result.get("ok"):
        answer = result.get("answer")
        answer_text = answer if answer else "(system returned no generated answer)"
    else:
        answer_text = f"(RAGWEAVE CALL FAILED: {result.get('error')})"

    return f"""{_SYSTEM}

{_RUBRIC}

=== TEST CASE {case.get('id')} ===
Category: {case.get('category')}
Use case: {case.get('use_case')}
Complexity: {case.get('complexity')}
Relevance: {case.get('relevance')}   <-- if "Non-relevant", abstaining is the correct answer

QUESTION ASKED:
{case.get('query')}

EXPECTED ANSWER / RUBRIC (authored by domain experts):
{_clip(case.get('expected_answer'), 6000)}

EXPECTED SOURCE REFERENCES:
{_clip(case.get('expected_sources'), 1500) or '(not specified)'}

ADDITIONAL GRADING CONTEXT:
{_clip(case.get('context'), 2000) or '(none)'}

=== RAGWEAVE OUTPUT ===
ok: {result.get('ok')}   http_status: {result.get('http_status')}   latency_ms: {result.get('latency_ms')}
generation_source: {result.get('generation_source')}   llm_confidence: {result.get('llm_confidence')}

ANSWER:
{_clip(answer_text, 6000)}

RETRIEVED DOCUMENTS (deduped):
{src_text}

RETRIEVED CHUNKS:
{_clip(chunks_text, 9000)}

=== END ===
Now output ONLY the JSON verdict object."""


def _extract_json(text: str):
    """Pull the first balanced JSON object out of arbitrary model text."""
    if not text:
        return None
    # Strip code fences if present.
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        return None
    return None


def _run_claude(cfg, prompt: str) -> dict:
    """Invoke the Claude CLI headless; return {'text':..} or {'error':..}."""
    cmd = [cfg.claude_bin, "-p", "--output-format", "json"]
    if cfg.judge_model:
        cmd += ["--model", cfg.judge_model]
    try:
        proc = subprocess.run(
            cmd, input=prompt, capture_output=True, text=True,
            timeout=cfg.judge_timeout_s,
        )
    except subprocess.TimeoutExpired:
        return {"error": f"judge timed out after {cfg.judge_timeout_s}s"}
    except FileNotFoundError:
        return {"error": f"claude binary not found: {cfg.claude_bin}"}
    if proc.returncode != 0:
        return {"error": f"claude exited {proc.returncode}: {proc.stderr[:400]}"}
    # --output-format json wraps the model output: {"result": "...", ...}
    out = proc.stdout.strip()
    try:
        wrapper = json.loads(out)
        inner = wrapper.get("result", out) if isinstance(wrapper, dict) else out
    except json.JSONDecodeError:
        inner = out
    return {"text": inner}


def judge_case(cfg, case: dict, result: dict) -> dict:
    """Grade one (case, result) pair. Returns a verdict dict (never raises)."""
    prompt = build_prompt(case, result)
    run = _run_claude(cfg, prompt)
    if "error" in run:
        return _error_verdict(f"judge_failed: {run['error']}", result)
    verdict = _extract_json(run["text"])
    if not verdict or "verdict" not in verdict:
        return _error_verdict("judge_unparseable_output", result,
                              raw=run["text"][:1000])
    # Defensive defaults so downstream code can trust the shape.
    verdict.setdefault("scores", {})
    for k in ("faithfulness", "correctness", "completeness", "retrieval", "citations"):
        verdict["scores"].setdefault(k, 0)
    verdict.setdefault("overall", 0)
    verdict.setdefault("failure_modes", [])
    verdict.setdefault("suggested_fixes", [])
    verdict.setdefault("key_points_hit", [])
    verdict.setdefault("key_points_missed", [])
    verdict.setdefault("why", "")
    return verdict


def _error_verdict(msg: str, result: dict, raw: str = "") -> dict:
    fm = ["infra_error"] if not result.get("ok") else ["judge_error"]
    return {
        "verdict": "error",
        "overall": 0,
        "scores": {"faithfulness": 0, "correctness": 0, "completeness": 0,
                   "retrieval": 0, "citations": 0},
        "abstain_expected": False,
        "abstained": False,
        "key_points_hit": [],
        "key_points_missed": [],
        "why": msg + (f" | raw: {raw}" if raw else ""),
        "failure_modes": fm,
        "suggested_fixes": [],
        "_judge_error": msg,
    }
