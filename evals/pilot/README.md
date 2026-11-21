<!-- @summary
Pilot-phase evaluation harness: runs the QnA test cases against RagWeave,
judges each answer with Claude headless, renders an HTML report, and produces a
self-improvement plan. Entry point: ./go
@end-summary -->

# RagWeave Pilot Evaluation Harness

An automated, looping evaluation system for RagWeave built from the pilot-phase
test cases in `pilot_phase_evaluation_QnA.docx`.

**One command:**

```bash
./go                # all cases → query RagWeave → judge each → HTML report → improvement plan
```

It launches every evaluation question into RagWeave, collects each response
(answer + retrieved chunks + source documents), grades it with an LLM judge
(**Claude headless**) that explains *why* each answer is right or wrong and
proposes fixes, collates everything into a single self-contained **HTML report**,
and synthesizes a prioritized **improvement plan** — the engine of a
self-improving eval loop.

## What's here

| File | Role |
| --- | --- |
| `extract_testcases.py` | Parses the QnA `.docx` → `testcases.json` (reproducible) |
| `testcases.json` | 31 extracted cases (ARCH, FE, DFT, DV/Verification, FIN, BE) |
| `config.py` | All tunables (endpoint, timeouts, judge model, paths) via env/flags |
| `client.py` | Stdlib HTTP client for `POST /query`; normalizes answer/chunks/sources; never raises |
| `judge.py` | Claude-headless LLM-as-judge → structured verdict + failure modes + fixes |
| `report.py` | Renders the standalone `report.html` |
| `improve.py` | Aggregates verdicts → prioritized improvement plan (`improvement.md/.json`) |
| `run.py` | Orchestrator (`go` calls this) |
| `mock_ragweave.py` | Offline stand-in for `/query` + `/health` to smoke-test without the real stack |
| `runs/<ts>/` | Per-run artifacts; `runs/latest` → most recent |

## Usage

```bash
./go                              # full run + judge + improvement plan
./go --limit 3                    # smoke test on first 3 cases
./go --ids ARCH.1 DFT.2           # only these cases
./go --mode retrieval --no-judge  # retrieval-only, skip the LLM + judge
./go --loop 3                     # self-improving loop: eval → improve, ×3 (tracks score trend)
```

Common flags (full list: `python run.py -h`):
`--rag-url`, `--timeout` (per-query seconds), `--judge-model` (e.g. `sonnet`),
`--search-limit`, `--rerank-top-k`, `--improve`.

Config via env (overrides defaults): `PILOT_RAG_URL`, `PILOT_RAG_TOKEN`,
`PILOT_TIMEOUT_S`, `PILOT_JUDGE_MODEL`, `PILOT_CLAUDE_BIN`.

### Offline smoke test (no GPU host / vLLM needed)

```bash
python mock_ragweave.py --port 8077 &      # canned backend
./go --ids ARCH.1 --rag-url http://localhost:8077
```

## Outputs (per run, in `runs/<timestamp>/`)

- `report.html` — summary KPIs, per-category breakdown, failure-mode tally, and a
  collapsible card per case: question, RagWeave answer, judge scores + reasoning +
  fixes, **retrieved documents** and **retrieved chunks**, and the expected rubric.
- `run.json` — full structured results (machine-readable).
- `improvement.md` / `improvement.json` — root-cause clustering + prioritized
  recommendations (operational vs pipeline vs data vs eval), regression watch,
  and what to re-test next.
- `run.partial.json` — written after every case (crash-safe).

## How judging works

For each case the judge receives the question, the expert-authored expected
answer/rubric, the expected source references, and RagWeave's full output
(answer + chunks + sources). It returns a JSON verdict: per-axis scores
(faithfulness, correctness, completeness, retrieval, citations), an overall
0–100, a verdict (pass/partial/fail/error), a failure-mode taxonomy, and
concrete `suggested_fixes`. **Non-relevant** cases are graded inversely — the
correct behaviour is to abstain, and a confident fabricated answer is a fail.

## The self-improving loop

`improve.py` feeds every verdict to Claude acting as a RAG engineer: it clusters
failures into root causes, separates **operational** issues (e.g. a down
embedding endpoint) from **pipeline/data/eval** issues, and emits a prioritized
plan. With `--loop N`, the harness re-runs and tracks the score trajectory so you
can see whether a change actually helped. Applying the fixes is a human gate by
design (changes to chunking/embedding/indexing can require re-indexing).

## Regenerating test cases

```bash
python extract_testcases.py [path/to/QnA.docx]   # rewrites testcases.json
```

## Requirements

- Python ≥ 3.10 (stdlib only — no pip installs).
- The `claude` CLI on PATH for judging/improvement (`./go --no-judge` to skip).
- A reachable RagWeave `/query` endpoint for real results (default
  `http://localhost:8000`).
