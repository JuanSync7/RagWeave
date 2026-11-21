# @summary
# Self-improvement step of the eval loop. Aggregates every judge verdict from a
# run, then asks Claude headless to act as a RAG engineer: cluster the failures,
# diagnose root causes, and emit a prioritized, concrete improvement plan
# (specific config/pipeline changes) plus expected impact. Writes markdown +
# JSON. Carries history across iterations to track whether scores improved.
# Exports: build_improvement_plan, write_plan
# Deps: judge (claude runner), config; stdlib json
# @end-summary
"""Turn per-case judge feedback into an actionable, prioritized improvement plan."""

from __future__ import annotations

import json
from pathlib import Path

import judge as judge_mod


def _digest(run: dict) -> dict:
    """Compact, judge-focused digest of a run for the planner prompt."""
    rows = run["rows"]
    items = []
    fm = {}
    fixes = {}
    verdicts = {"pass": 0, "partial": 0, "fail": 0, "error": 0, "skipped": 0}
    total = 0
    for r in rows:
        c, res, v = r["case"], r["result"], r["verdict"]
        verdicts[v.get("verdict", "error")] = verdicts.get(v.get("verdict", "error"), 0) + 1
        total += v.get("overall", 0) or 0
        for m in v.get("failure_modes", []):
            fm[m] = fm.get(m, 0) + 1
        for f in v.get("suggested_fixes", []):
            a = f.get("area", "other")
            fixes.setdefault(a, []).append(f.get("fix", ""))
        items.append({
            "id": c["id"],
            "category": c.get("category"),
            "complexity": c.get("complexity"),
            "relevance": c.get("relevance"),
            "verdict": v.get("verdict"),
            "overall": v.get("overall"),
            "scores": v.get("scores"),
            "failure_modes": v.get("failure_modes"),
            "why": v.get("why"),
            "missed": v.get("key_points_missed"),
            "ok": res.get("ok"),
            "error": res.get("error"),
            "n_chunks": len(res.get("chunks") or []),
            "top_sources": [s.get("source") for s in (res.get("sources") or [])[:3]],
            "expected_sources": c.get("expected_sources"),
            "suggested_fixes": v.get("suggested_fixes"),
        })
    n = len(rows)
    return {
        "n": n,
        "mean_overall": round(total / n, 1) if n else 0,
        "verdicts": verdicts,
        "failure_modes": dict(sorted(fm.items(), key=lambda kv: -kv[1])),
        "fix_areas": {k: len(v) for k, v in sorted(fixes.items(), key=lambda kv: -len(kv[1]))},
        "cases": items,
    }


_PLANNER_SYSTEM = """You are a senior RAG / retrieval systems engineer improving \
"RagWeave", a self-hosted RAG over an ASIC/semiconductor engineering document \
corpus (Weaviate hybrid search + reranker + vLLM generation). You are given the \
aggregated judge results of an evaluation run. Your job: find the systemic root \
causes behind the failures and produce a PRIORITIZED, CONCRETE improvement plan. \
Output ONLY a single JSON object, no markdown fences."""

_PLANNER_INSTR = """\
Analyse the run digest. Cluster individual case failures into a small number of
ROOT CAUSES (e.g. "embedding/retrieval not finding the right doc version",
"chunking splits tables", "generator ignores retrieved context", "no abstention
on out-of-corpus questions", "missing citations", "infra/endpoint failures").

For each root cause estimate how many cases it blocks and how confident you are.

Then produce prioritized RECOMMENDATIONS. Each must be specific enough to act on:
which pipeline stage, which config key or component, what change, and the
expected effect on the metrics. Prefer changes that unblock the most cases.

Distinguish:
- infra/operational issues (endpoints down, model mismatch) -> "operational"
- pipeline/quality issues (chunking, retrieval, reranking, generation, prompting) -> "pipeline"
- data/coverage issues (the answer truly isn't in the corpus) -> "data"
- eval/harness issues (question phrasing, rubric) -> "eval"

If most failures are a single operational cause (e.g. the embedding endpoint is
returning errors), SAY SO loudly and make that the #1 recommendation, because the
quality metrics are not trustworthy until it is fixed.

Output JSON shape EXACTLY:
{
  "headline": "one sentence verdict on this run",
  "run_trustworthy": true|false,
  "root_causes": [
    {"name":"...","cases_affected":["ID",...],"confidence":"high|medium|low","explanation":"..."}
  ],
  "recommendations": [
    {"priority":1,"type":"operational|pipeline|data|eval","stage":"...",
     "change":"specific change incl. config key / component if known",
     "expected_impact":"which cases/metrics improve and roughly how much",
     "effort":"low|medium|high"}
  ],
  "regression_watch": ["things that could get worse if we apply the above"],
  "next_eval_focus": ["which cases or categories to re-test first next iteration"]
}
"""


def _history_note(history) -> str:
    if not history or len(history) < 2:
        return "(first iteration — no prior run to compare against)"
    lines = []
    for i, run in enumerate(history):
        d = _digest(run)
        lines.append(f"iteration {i+1}: mean={d['mean_overall']}/100 verdicts={d['verdicts']}")
    return "Score trajectory across iterations:\n" + "\n".join(lines)


def build_improvement_plan(cfg, run: dict, history=None) -> dict:
    """Ask Claude to synthesize a prioritized improvement plan. Never raises."""
    digest = _digest(run)
    prompt = f"""{_PLANNER_SYSTEM}

{_PLANNER_INSTR}

=== RUN DIGEST (JSON) ===
{json.dumps(digest, ensure_ascii=False)[:60000]}

=== HISTORY ===
{_history_note(history or [run])}

Now output ONLY the JSON improvement plan object."""

    run_out = judge_mod._run_claude(cfg, prompt)  # reuse the headless runner
    if "error" in run_out:
        return {"_error": run_out["error"], "digest": digest}
    plan = judge_mod._extract_json(run_out["text"])
    if not plan:
        return {"_error": "planner_unparseable", "raw": run_out["text"][:2000],
                "digest": digest}
    plan["digest"] = digest
    return plan


def _plan_to_markdown(plan: dict, run: dict) -> str:
    meta = run["meta"]
    d = plan.get("digest", {})
    if plan.get("_error"):
        return (f"# RagWeave Pilot — Improvement Plan (run {meta.get('run_id')})\n\n"
                f"> Planner could not produce a plan: `{plan['_error']}`\n\n"
                f"## Run digest\n```json\n{json.dumps(d, indent=2)[:8000]}\n```\n")

    lines = [
        f"# RagWeave Pilot — Improvement Plan",
        f"_Run `{meta.get('run_id')}` · mean **{d.get('mean_overall')}/100** · "
        f"verdicts {d.get('verdicts')}_",
        "",
        f"**Headline:** {plan.get('headline','')}",
        "",
        f"**Run trustworthy for quality conclusions:** "
        f"{'✅ yes' if plan.get('run_trustworthy') else '⚠️ NO — fix operational issues first'}",
        "",
        "## Root causes",
    ]
    for rc in plan.get("root_causes", []):
        lines.append(f"- **{rc.get('name')}** "
                     f"(_{rc.get('confidence')} confidence_, affects "
                     f"{len(rc.get('cases_affected', []))} cases: "
                     f"{', '.join(rc.get('cases_affected', []))})")
        lines.append(f"  - {rc.get('explanation')}")
    lines += ["", "## Recommendations (prioritized)"]
    for r in sorted(plan.get("recommendations", []), key=lambda x: x.get("priority", 99)):
        lines.append(f"### {r.get('priority')}. [{r.get('type')}/{r.get('stage')}] "
                     f"{r.get('change')}")
        lines.append(f"- **Expected impact:** {r.get('expected_impact')}")
        lines.append(f"- **Effort:** {r.get('effort')}")
        lines.append("")
    if plan.get("regression_watch"):
        lines += ["## Regression watch"] + [f"- {x}" for x in plan["regression_watch"]] + [""]
    if plan.get("next_eval_focus"):
        lines += ["## Re-test focus next iteration"] + \
                 [f"- {x}" for x in plan["next_eval_focus"]] + [""]
    lines += ["## Failure-mode tally", f"```\n{json.dumps(d.get('failure_modes', {}), indent=2)}\n```"]
    return "\n".join(lines)


def write_plan(out_dir: Path, plan: dict) -> None:
    out_dir = Path(out_dir)
    (out_dir / "improvement.json").write_text(json.dumps(plan, indent=2, ensure_ascii=False))
    # Re-load the run for the markdown header context.
    run = json.loads((out_dir / "run.json").read_text())
    (out_dir / "improvement.md").write_text(_plan_to_markdown(plan, run))
