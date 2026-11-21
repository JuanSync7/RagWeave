#!/usr/bin/env python3
# @summary
# Orchestrator for the pilot eval harness. Loads test cases, queries RagWeave
# for each, runs the Claude judge, writes a timestamped run.json + report.html,
# and (optionally) the self-improvement plan. This is the "go" entrypoint.
# Exports: run_eval, main
# Deps: config, client, judge, report, improve (all local, stdlib-only)
# @end-summary
"""Run the pilot RAG evaluation end-to-end.

Usage (see README):
    python run.py                      # full run: all cases, query mode, judge on
    python run.py --limit 3            # smoke test on first 3 cases
    python run.py --ids ARCH.1 DFT.2   # only these cases
    python run.py --mode retrieval     # retrieval-only (no LLM answer)
    python run.py --no-judge           # skip the judge (just collect answers)
    python run.py --improve            # also generate the improvement plan
    python run.py --loop 2             # eval -> improve, repeated N iterations
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import client
import config as config_mod
import judge as judge_mod
import report as report_mod


def _load_cases(cfg):
    cases = json.loads(Path(cfg.testcases_path).read_text())
    if cfg.only_ids:
        wanted = {x.upper() for x in cfg.only_ids}
        cases = [c for c in cases if c["id"].upper() in wanted]
    if cfg.limit:
        cases = cases[: cfg.limit]
    return cases


def _run_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def run_eval(cfg) -> dict:
    """Execute the eval and return the full run dict (also written to disk)."""
    cases = _load_cases(cfg)
    if not cases:
        sys.exit("No test cases selected.")

    run_id = _run_id()
    out_dir = Path(cfg.runs_dir) / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    h = client.health(cfg.rag_url)
    print(f"[pilot] run {run_id} | {len(cases)} cases | mode={cfg.mode} | "
          f"endpoint={cfg.rag_url}")
    print(f"[pilot] RagWeave health: {h}")
    if h.get("error"):
        print("[pilot] WARNING: RagWeave health check failed — queries will likely "
              "error. Continuing so the report still captures the failures.")

    rows = []
    t_start = time.time()
    for i, case in enumerate(cases, 1):
        print(f"[pilot] ({i}/{len(cases)}) {case['id']:8} querying… ", end="", flush=True)
        res = client.ask(cfg, case["query"])
        if res["ok"]:
            n_ans = len(res.get("answer") or "")
            print(f"ok ({res.get('wall_s')}s, {len(res['chunks'])} chunks, "
                  f"{n_ans}c answer)", end="")
        else:
            print(f"FAILED ({res.get('error')})", end="")

        if cfg.judge_enabled:
            print(" | judging… ", end="", flush=True)
            verdict = judge_mod.judge_case(cfg, case, res)
            print(f"{verdict.get('verdict','?')} {verdict.get('overall','?')}/100")
        else:
            verdict = {"verdict": "skipped", "overall": 0, "scores": {},
                       "failure_modes": [], "suggested_fixes": [],
                       "key_points_hit": [], "key_points_missed": [], "why": "judge disabled"}
            print(" | judge skipped")

        rows.append({"case": case, "result": res, "verdict": verdict})
        # Persist incrementally so a long run is crash-safe.
        _write_partial(out_dir, run_id, cfg, h, rows, t_start)

    run = _assemble(run_id, cfg, h, rows, t_start)

    # Final artifacts.
    (out_dir / "run.json").write_text(json.dumps(run, indent=2, ensure_ascii=False))
    html_path = out_dir / "report.html"
    html_path.write_text(report_mod.render_report(run))
    # Maintain a stable "latest" pointer.
    latest = Path(cfg.runs_dir) / "latest"
    try:
        if latest.is_symlink() or latest.exists():
            latest.unlink()
        latest.symlink_to(out_dir.name)
    except OSError:
        pass

    _print_summary(run)
    print(f"\n[pilot] report:  {html_path}")
    print(f"[pilot] run dir: {out_dir}")
    run["_out_dir"] = str(out_dir)
    return run


def _assemble(run_id, cfg, health, rows, t_start) -> dict:
    return {
        "meta": {
            "run_id": run_id,
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "elapsed_s": round(time.time() - t_start, 1),
            "mode": cfg.mode,
            "rag_url": cfg.rag_url,
            "judge_model": cfg.judge_model or "(cli default)",
            "config": cfg.as_dict(),
        },
        "health": health,
        "rows": rows,
    }


def _write_partial(out_dir, run_id, cfg, health, rows, t_start):
    run = _assemble(run_id, cfg, health, rows, t_start)
    (out_dir / "run.partial.json").write_text(json.dumps(run, ensure_ascii=False))


def _print_summary(run):
    rows = run["rows"]
    n = len(rows)
    cnt = {"pass": 0, "partial": 0, "fail": 0, "error": 0, "skipped": 0}
    tot = 0
    for r in rows:
        v = r["verdict"].get("verdict", "error")
        cnt[v] = cnt.get(v, 0) + 1
        tot += r["verdict"].get("overall", 0) or 0
    print("\n" + "=" * 56)
    print(f"[pilot] SUMMARY  ({n} cases, mean {round(tot/n,1) if n else 0}/100)")
    print(f"        pass={cnt['pass']}  partial={cnt['partial']}  "
          f"fail={cnt['fail']}  error={cnt['error']}")
    print("=" * 56)


def _build_cfg(args) -> "config_mod.Config":
    kw = {}
    if args.mode:
        kw["mode"] = args.mode
    if args.ids:
        kw["only_ids"] = args.ids
    if args.limit:
        kw["limit"] = args.limit
    if args.no_judge:
        kw["judge_enabled"] = False
    if args.rag_url:
        kw["rag_url"] = args.rag_url
    if args.judge_model:
        kw["judge_model"] = args.judge_model
    if args.timeout:
        kw["request_timeout_s"] = args.timeout
    if args.search_limit:
        kw["search_limit"] = args.search_limit
    if args.rerank_top_k:
        kw["rerank_top_k"] = args.rerank_top_k
    return config_mod.load_config(**kw)


def main(argv=None):
    ap = argparse.ArgumentParser(description="RagWeave pilot evaluation harness")
    ap.add_argument("--mode", choices=["query", "retrieval"], help="pipeline mode")
    ap.add_argument("--ids", nargs="+", help="only run these test-case ids")
    ap.add_argument("--limit", type=int, help="run only the first N cases")
    ap.add_argument("--no-judge", action="store_true", help="skip the LLM judge")
    ap.add_argument("--improve", action="store_true",
                    help="generate the self-improvement plan after the run")
    ap.add_argument("--loop", type=int, default=0, metavar="N",
                    help="run eval+improve N times (self-improving loop)")
    ap.add_argument("--rag-url", help="override RagWeave base URL")
    ap.add_argument("--judge-model", help="pin a Claude model for the judge")
    ap.add_argument("--timeout", type=int, help="per-query timeout seconds")
    ap.add_argument("--search-limit", type=int)
    ap.add_argument("--rerank-top-k", type=int)
    args = ap.parse_args(argv)

    cfg = _build_cfg(args)

    iterations = max(1, args.loop) if args.loop else 1
    do_improve = args.improve or bool(args.loop)
    history = []
    for it in range(iterations):
        if iterations > 1:
            print(f"\n########## ITERATION {it+1}/{iterations} ##########")
        run = run_eval(cfg)
        history.append(run)
        if do_improve:
            import improve as improve_mod
            plan = improve_mod.build_improvement_plan(cfg, run, history)
            improve_mod.write_plan(Path(run["_out_dir"]), plan)
            print(f"[pilot] improvement plan: {run['_out_dir']}/improvement.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
