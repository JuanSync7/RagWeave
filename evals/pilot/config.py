# @summary
# Central configuration for the pilot-phase eval harness. All tunables read from
# the environment with sensible defaults so the harness runs with zero setup.
# Exports: Config, load_config
# Deps: (stdlib only)
# @end-summary
"""Configuration contract for the pilot evaluation harness.

Everything the harness needs to know — where RagWeave lives, how patient to be,
which judge model to use, and where to write output — is resolved here so the
rest of the code stays free of magic constants.
"""

from __future__ import annotations

import os
from pathlib import Path

HERE = Path(__file__).resolve().parent


class Config:
    """Resolved runtime configuration (immutable in spirit; set once at start)."""

    def __init__(self, **kw):
        # --- RagWeave endpoint ---------------------------------------------
        self.rag_url: str = kw.get("rag_url") or os.environ.get(
            "PILOT_RAG_URL", os.environ.get("RAG_API_URL", "http://localhost:8000")
        )
        self.rag_auth_token: str = kw.get("rag_auth_token") or os.environ.get(
            "PILOT_RAG_TOKEN", ""
        )
        # Query pipeline knobs forwarded to POST /query.
        self.mode: str = kw.get("mode", "query")            # "query" | "retrieval"
        self.search_limit: int = int(kw.get("search_limit", 10))
        self.rerank_top_k: int = int(kw.get("rerank_top_k", 6))
        self.alpha: float = float(kw.get("alpha", 0.5))
        self.fast_path = kw.get("fast_path", None)          # None=server default

        # RagWeave generation can take minutes (LLM + retrieval over a tunnel).
        # The server's own RAG_RETRIEVAL_TIMEOUT_MS defaults to 30 min, so be
        # generous but bounded. Per-query wall-clock ceiling in seconds.
        self.request_timeout_s: int = int(kw.get("request_timeout_s",
                                                  os.environ.get("PILOT_TIMEOUT_S", "1200")))
        self.retries: int = int(kw.get("retries", 1))       # extra attempts on hard failure

        # The server appears to serialize query workflows, so default to one at a
        # time. Override only if you know the deployment can take concurrency.
        self.concurrency: int = int(kw.get("concurrency", 1))

        # --- Judge (Claude headless) ---------------------------------------
        self.judge_enabled: bool = bool(kw.get("judge_enabled", True))
        self.claude_bin: str = kw.get("claude_bin") or os.environ.get(
            "PILOT_CLAUDE_BIN", "claude"
        )
        # Empty string => use the CLI's default model. Set e.g. "sonnet" to pin.
        self.judge_model: str = kw.get("judge_model", os.environ.get("PILOT_JUDGE_MODEL", ""))
        self.judge_timeout_s: int = int(kw.get("judge_timeout_s", 300))

        # --- IO ------------------------------------------------------------
        self.testcases_path: Path = Path(kw.get("testcases_path") or HERE / "testcases.json")
        self.runs_dir: Path = Path(kw.get("runs_dir") or HERE / "runs")

        # --- Selection -----------------------------------------------------
        self.only_ids = kw.get("only_ids")                  # list[str] | None
        self.limit = kw.get("limit")                        # int | None

    def as_dict(self) -> dict:
        d = dict(self.__dict__)
        d["testcases_path"] = str(self.testcases_path)
        d["runs_dir"] = str(self.runs_dir)
        return d


def load_config(**overrides) -> Config:
    """Build a Config, applying explicit overrides on top of env defaults."""
    return Config(**overrides)
