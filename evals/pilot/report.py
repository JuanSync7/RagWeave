# @summary
# Renders a self-contained HTML report for a pilot eval run: run summary,
# aggregate scores, per-category breakdown, and a collapsible card per test
# case showing the question, RagWeave answer, judge verdict, retrieved
# documents and chunks. No external assets — one portable .html file.
# Exports: render_report
# Deps: (stdlib only: html, json, datetime)
# @end-summary
"""HTML report generation for pilot eval runs."""

from __future__ import annotations

import html
import json
from datetime import datetime

_VERDICT_COLORS = {
    "pass": "#1a7f37", "partial": "#9a6700", "fail": "#cf222e", "error": "#6e7781",
}


def _esc(x) -> str:
    return html.escape("" if x is None else str(x))


def _score_bar(value, maxv=5):
    try:
        pct = max(0.0, min(1.0, float(value) / maxv)) * 100
    except (TypeError, ValueError):
        pct = 0
    hue = int(pct * 1.2)  # 0=red -> 120=green
    return (f'<span class="bar"><span class="fill" style="width:{pct:.0f}%;'
            f'background:hsl({hue},70%,45%)"></span></span>')


def _aggregate(rows: list) -> dict:
    n = len(rows)
    verdicts = {"pass": 0, "partial": 0, "fail": 0, "error": 0}
    cat = {}
    overalls = []
    fm_counter = {}
    fix_areas = {}
    for r in rows:
        v = r["verdict"]
        verdicts[v.get("verdict", "error")] = verdicts.get(v.get("verdict", "error"), 0) + 1
        overalls.append(v.get("overall", 0) or 0)
        c = r["case"].get("category", "?")
        cat.setdefault(c, {"pass": 0, "partial": 0, "fail": 0, "error": 0, "overall": []})
        cat[c][v.get("verdict", "error")] = cat[c].get(v.get("verdict", "error"), 0) + 1
        cat[c]["overall"].append(v.get("overall", 0) or 0)
        for fm in v.get("failure_modes", []):
            fm_counter[fm] = fm_counter.get(fm, 0) + 1
        for fx in v.get("suggested_fixes", []):
            a = fx.get("area", "other")
            fix_areas[a] = fix_areas.get(a, 0) + 1
    return {
        "n": n,
        "verdicts": verdicts,
        "mean_overall": round(sum(overalls) / n, 1) if n else 0,
        "pass_rate": round(100 * verdicts["pass"] / n, 1) if n else 0,
        "by_category": cat,
        "failure_modes": dict(sorted(fm_counter.items(), key=lambda kv: -kv[1])),
        "fix_areas": dict(sorted(fix_areas.items(), key=lambda kv: -kv[1])),
    }


def _chunk_html(chunks: list) -> str:
    if not chunks:
        return '<p class="muted">No chunks retrieved.</p>'
    out = []
    for i, c in enumerate(chunks):
        out.append(f"""
        <div class="chunk">
          <div class="chunk-h">#{i+1}
            <span class="pill">score {(_esc(round(c['score'],3)) if isinstance(c.get('score'),(int,float)) else _esc(c.get('score')))}</span>
            <span class="pill">{_esc(c.get('source'))}</span>
            {('<span class="pill">' + _esc(c.get('section')) + '</span>') if c.get('section') else ''}
          </div>
          <pre class="chunk-t">{_esc(c.get('text'))}</pre>
        </div>""")
    return "\n".join(out)


def _sources_html(sources: list) -> str:
    if not sources:
        return '<p class="muted">No documents retrieved.</p>'
    rows = []
    for s in sources:
        bs = s.get("best_score")
        bs = round(bs, 3) if isinstance(bs, (int, float)) else bs
        rows.append(
            f"<tr><td>{_esc(s.get('source'))}</td>"
            f"<td>{_esc(s.get('chunk_count'))}</td>"
            f"<td>{_esc(bs)}</td>"
            f"<td class='muted'>{_esc('; '.join(s.get('sections', [])))}</td></tr>"
        )
    return ("<table class='src'><thead><tr><th>Document</th><th>#chunks</th>"
            "<th>best score</th><th>sections</th></tr></thead><tbody>"
            + "".join(rows) + "</tbody></table>")


def _fixes_html(fixes: list) -> str:
    if not fixes:
        return ""
    items = []
    for f in fixes:
        items.append(
            f"<li><span class='pill area'>{_esc(f.get('area'))}</span> "
            f"<b>{_esc(f.get('fix'))}</b>"
            + (f"<div class='muted'>{_esc(f.get('rationale'))}</div>" if f.get('rationale') else "")
            + "</li>"
        )
    return "<ul class='fixes'>" + "".join(items) + "</ul>"


def _case_card(idx: int, row: dict) -> str:
    case = row["case"]
    res = row["result"]
    v = row["verdict"]
    verdict = v.get("verdict", "error")
    color = _VERDICT_COLORS.get(verdict, "#6e7781")
    sc = v.get("scores", {})

    if res.get("ok"):
        answer = res.get("answer") or "<em>(no generated answer returned)</em>"
        answer_html = _esc(answer) if res.get("answer") else answer
        err_banner = ""
    else:
        answer_html = "<em>(no answer)</em>"
        err_banner = (f"<div class='err'>RagWeave call failed: "
                      f"{_esc(res.get('error'))} (HTTP {_esc(res.get('http_status'))})</div>")

    score_rows = "".join(
        f"<tr><td>{k}</td><td>{_score_bar(sc.get(k,0))}</td><td>{_esc(sc.get(k,0))}/5</td></tr>"
        for k in ("faithfulness", "correctness", "completeness", "retrieval", "citations")
    )
    fm = v.get("failure_modes", [])
    fm_html = " ".join(f"<span class='pill fm'>{_esc(x)}</span>" for x in fm) or "<span class='muted'>none</span>"
    missed = v.get("key_points_missed", [])
    missed_html = ("<ul class='missed'>" + "".join(f"<li>{_esc(m)}</li>" for m in missed) + "</ul>") if missed else ""

    latency = res.get("latency_ms")
    latency_txt = f"{latency:.0f} ms" if isinstance(latency, (int, float)) else (f"{res.get('wall_s')} s wall" if res.get('wall_s') else "—")

    return f"""
    <details class="case" id="case-{_esc(case.get('id'))}">
      <summary>
        <span class="badge" style="background:{color}">{_esc(verdict.upper())}</span>
        <span class="cid">{_esc(case.get('id'))}</span>
        <span class="ctitle">{_esc(case.get('title') or case.get('query'))[:90]}</span>
        <span class="score-chip">{_esc(v.get('overall',0))}/100</span>
        <span class="meta-chip">{_esc(case.get('category'))} · {_esc(case.get('complexity') or '?')}/{_esc(case.get('relevance') or '?')}</span>
      </summary>
      <div class="case-body">
        {err_banner}
        <div class="grid">
          <div class="col">
            <h4>Question</h4>
            <pre class="q">{_esc(case.get('query'))}</pre>
            <h4>RagWeave answer <span class="muted">({_esc(res.get('llm_confidence'))} conf · {latency_txt})</span></h4>
            <div class="answer">{answer_html}</div>
          </div>
          <div class="col">
            <h4>Judge verdict</h4>
            <table class="scores"><tbody>{score_rows}</tbody></table>
            <p class="why"><b>Why:</b> {_esc(v.get('why'))}</p>
            <p><b>Failure modes:</b> {fm_html}</p>
            {('<p><b>Key points missed:</b></p>' + missed_html) if missed_html else ''}
            <h4>Suggested fixes</h4>
            {_fixes_html(v.get('suggested_fixes')) or '<p class="muted">none</p>'}
          </div>
        </div>
        <details class="sub"><summary>Retrieved documents ({len(res.get('sources') or [])})</summary>{_sources_html(res.get('sources'))}</details>
        <details class="sub"><summary>Retrieved chunks ({len(res.get('chunks') or [])})</summary>{_chunk_html(res.get('chunks'))}</details>
        <details class="sub"><summary>Expected answer / rubric</summary><pre class="rubric">{_esc(case.get('expected_answer') or case.get('context'))}</pre></details>
      </div>
    </details>"""


def _cat_table(agg: dict) -> str:
    rows = []
    for c, d in sorted(agg["by_category"].items()):
        mean = round(sum(d["overall"]) / len(d["overall"]), 1) if d["overall"] else 0
        rows.append(
            f"<tr><td>{_esc(c)}</td><td>{d['pass']}</td><td>{d['partial']}</td>"
            f"<td>{d['fail']}</td><td>{d['error']}</td><td>{mean}</td></tr>"
        )
    return ("<table class='agg'><thead><tr><th>Category</th><th>pass</th><th>partial</th>"
            "<th>fail</th><th>error</th><th>mean/100</th></tr></thead><tbody>"
            + "".join(rows) + "</tbody></table>")


def _kv_pills(d: dict) -> str:
    return " ".join(f"<span class='pill'>{_esc(k)} ×{v}</span>" for k, v in d.items()) or "<span class='muted'>none</span>"


def render_report(run: dict) -> str:
    """Render a full run dict (see run.py) into a standalone HTML document."""
    rows = run["rows"]
    agg = _aggregate(rows)
    meta = run["meta"]
    health = run.get("health", {})
    v = agg["verdicts"]

    cards = "\n".join(_case_card(i, r) for i, r in enumerate(rows))
    ts = meta.get("started_at", datetime.now().isoformat(timespec="seconds"))

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RagWeave Pilot Eval — {_esc(ts)}</title>
<style>
:root{{--bg:#f6f8fa;--card:#fff;--bd:#d0d7de;--ink:#1f2328;--mut:#656d76}}
*{{box-sizing:border-box}}
body{{font:14px/1.5 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;margin:0;background:var(--bg);color:var(--ink)}}
header{{background:#0d1117;color:#fff;padding:20px 28px}}
header h1{{margin:0 0 4px;font-size:20px}} header .sub{{color:#9da7b3;font-size:13px}}
.wrap{{max-width:1180px;margin:0 auto;padding:22px 28px 80px}}
.summary{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:18px 0}}
.kpi{{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:14px 16px}}
.kpi .big{{font-size:26px;font-weight:700}} .kpi .lbl{{color:var(--mut);font-size:12px;text-transform:uppercase;letter-spacing:.04em}}
table{{border-collapse:collapse;width:100%;font-size:13px}}
th,td{{border:1px solid var(--bd);padding:6px 9px;text-align:left;vertical-align:top}}
th{{background:#eaeef2}}
.agg td:nth-child(n+2),.agg th:nth-child(n+2){{text-align:center}}
details.case{{background:var(--card);border:1px solid var(--bd);border-radius:10px;margin:10px 0;overflow:hidden}}
details.case>summary{{cursor:pointer;padding:12px 16px;display:flex;align-items:center;gap:10px;list-style:none}}
details.case>summary::-webkit-details-marker{{display:none}}
.badge{{color:#fff;font-weight:700;font-size:11px;padding:3px 8px;border-radius:6px}}
.cid{{font-weight:700;font-family:ui-monospace,Menlo,monospace}}
.ctitle{{flex:1;color:var(--ink)}} .score-chip{{font-weight:700}}
.meta-chip{{color:var(--mut);font-size:12px}}
.case-body{{padding:4px 16px 16px;border-top:1px solid var(--bd)}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:20px}}
@media(max-width:860px){{.grid{{grid-template-columns:1fr}}}}
h4{{margin:14px 0 6px;font-size:13px;text-transform:uppercase;letter-spacing:.03em;color:var(--mut)}}
pre{{white-space:pre-wrap;word-wrap:break-word;background:#f6f8fa;border:1px solid var(--bd);border-radius:8px;padding:10px;margin:0;font:12.5px/1.5 ui-monospace,Menlo,monospace}}
.answer{{background:#fff;border:1px solid var(--bd);border-radius:8px;padding:10px;white-space:pre-wrap}}
.scores td{{border:none;padding:2px 6px}} .scores td:first-child{{color:var(--mut);width:110px}}
.bar{{display:inline-block;width:120px;height:9px;background:#e6e6e6;border-radius:5px;overflow:hidden;vertical-align:middle}}
.bar .fill{{display:block;height:100%}}
.pill{{display:inline-block;background:#eaeef2;border:1px solid var(--bd);border-radius:20px;padding:1px 9px;font-size:11.5px;margin:1px}}
.pill.fm{{background:#fff1e5;border-color:#ffb07a}} .pill.area{{background:#ddf4ff;border-color:#80ccff}}
.fixes{{margin:4px 0;padding-left:18px}} .fixes li{{margin:6px 0}}
.missed{{margin:4px 0;padding-left:18px;color:#8a3a00}}
.muted{{color:var(--mut)}} .why{{margin:8px 0}}
.err{{background:#ffebe9;border:1px solid #ff8182;border-radius:8px;padding:8px 12px;margin:8px 0;color:#a40e26}}
details.sub{{margin:10px 0;border:1px solid var(--bd);border-radius:8px}}
details.sub>summary{{cursor:pointer;padding:8px 12px;font-weight:600;background:#f6f8fa}}
details.sub>div,details.sub>table,details.sub>pre,details.sub>p{{margin:10px}}
.chunk{{border:1px solid var(--bd);border-radius:8px;margin:8px 0}}
.chunk-h{{padding:6px 10px;background:#f6f8fa;font-size:12px;border-bottom:1px solid var(--bd)}}
.chunk-t{{border:none;border-radius:0 0 8px 8px;max-height:280px;overflow:auto}}
.health{{font-size:12.5px}}
code{{background:#eaeef2;padding:1px 5px;border-radius:4px}}
</style></head>
<body>
<header>
  <h1>RagWeave — Pilot Phase Evaluation Report</h1>
  <div class="sub">Run <code>{_esc(meta.get('run_id'))}</code> · started {_esc(ts)} ·
   {_esc(agg['n'])} test cases · mode <code>{_esc(meta.get('mode'))}</code> ·
   endpoint <code>{_esc(meta.get('rag_url'))}</code></div>
</header>
<div class="wrap">

  <div class="summary">
    <div class="kpi"><div class="big">{agg['mean_overall']}</div><div class="lbl">Mean score /100</div></div>
    <div class="kpi"><div class="big" style="color:{_VERDICT_COLORS['pass']}">{v['pass']}</div><div class="lbl">Pass</div></div>
    <div class="kpi"><div class="big" style="color:{_VERDICT_COLORS['partial']}">{v['partial']}</div><div class="lbl">Partial</div></div>
    <div class="kpi"><div class="big" style="color:{_VERDICT_COLORS['fail']}">{v['fail']}</div><div class="lbl">Fail</div></div>
    <div class="kpi"><div class="big" style="color:{_VERDICT_COLORS['error']}">{v['error']}</div><div class="lbl">Error</div></div>
    <div class="kpi"><div class="big">{agg['pass_rate']}%</div><div class="lbl">Pass rate</div></div>
  </div>

  <div class="health">
    <b>RagWeave health at run start:</b> <code>{_esc(json.dumps(health))}</code>
  </div>

  <h3>By category</h3>
  {_cat_table(agg)}

  <h3>Failure modes across run</h3>
  <p>{_kv_pills(agg['failure_modes'])}</p>
  <h3>Suggested-fix areas (judge)</h3>
  <p>{_kv_pills(agg['fix_areas'])}</p>

  <h3>Test cases</h3>
  {cards}

</div></body></html>"""
