# research/

This directory holds artifacts from auto-research loops — focused, time-bounded
investigations that optimize a specific subsystem against a measurable target
(latency, accuracy, lint cleanliness, etc.). Each loop produces a research
brief, an iteration log, a reusable benchmark fixture, and a narrative writeup.

## Layout convention

`research/` mirrors `src/` by **logical domain**. A loop targeting code under
`src/<domain>/` writes its artifacts to `research/<domain>/`.

```
research/
├── README.md                     # this file
└── retrieval/                    # loops targeting src/retrieval/
    ├── PROGRAM.md                # research brief: objective, scoring, mutable files, stop conditions
    ├── changelog.md              # narrative writeup after the loop closes
    ├── iterations.tsv            # one row per iteration (commit, score, status, summary)
    ├── benchmark_queries.json    # reusable benchmark fixture (immutable across runs)
    └── baseline_outputs.json     # reusable regression-guard snapshot (immutable across runs)
```

When a future loop targets a different subsystem (e.g., `src/ingestion/`,
`src/knowledge_graph/`), it MUST create its own `research/<domain>/` directory.
Loops MUST NOT write artifacts to repo root or to a flat `research/`.

## Why mirror `src/`?

- **Predictable**: anyone looking for "the loop that touched the retrieval
  pipeline" knows exactly where to look.
- **Collision-free**: parallel loops on different subsystems never overwrite
  each other's fixtures or reports.
- **Co-located narrative + data**: PROGRAM.md, changelog.md, and the JSON
  fixtures live next to each other so the story and the evidence stay together.

## Naming note

The current `research/retrieval/` mirrors `src/retrieval/`. The latter is a
slight historical misnomer — it's actually the umbrella for the whole RAG
pipeline (query-side retrieval *and* answer generation), not just document
retrieval. A future refactor may rename `src/retrieval/` → `src/rag/`, at
which point this directory should also rename to `research/rag/`. Until then,
`research/retrieval/` matches the current src layout.

## Reusable vs per-run artifacts

Within a domain folder, two kinds of files coexist:

- **Reusable across runs** — `benchmark_queries.json`, `baseline_outputs.json`.
  These are the harness's permanent inputs. Future investigations on the same
  domain reuse them as the regression-guard contract. Updating them is itself
  a deliberate act (re-baselining, expanding the query set).
- **Per-run** — `PROGRAM.md`, `changelog.md`, `iterations.tsv`. These describe
  one specific investigation. If the same domain is investigated again later,
  introduce a `runs/<date>_<topic>/` subdirectory rather than overwriting.

## Running the harness

The retrieval-pipeline benchmark is `scripts/benchmark_retrieval_query.py`.
It reads its fixtures from `research/retrieval/` and writes its report there
(default: `research/retrieval/latest_report.json`). Multi-sample runs go
through `scripts/bench_multirun.sh`, which writes per-sample reports to
`research/retrieval/<label>_run<i>.json`.

Per-sample bench reports are noisy intermediate output and should generally
not be committed long-term — `iterations.tsv` is the durable record.
