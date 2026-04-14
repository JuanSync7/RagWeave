"""
evals/retrieval/conftest.py — Retrieval eval suite fixtures.

Provides fixtures for loading retrieval golden query sets. Currently a stub;
extend this file when retrieval eval fixtures are populated.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import pytest

from evals.conftest import load_json_fixture

_FIXTURES_ROOT = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def golden_queries_retrieval_asic() -> Dict[str, Any]:
    """Load the ASIC golden query set for retrieval-only evals.

    These queries live in evals/retrieval/fixtures/ and are separate from the
    KG evaluation queries in evals/knowledge_graph/fixtures/.
    """
    path = _FIXTURES_ROOT / "asic" / "golden_queries.json"
    if not path.exists():
        pytest.skip(f"Retrieval golden queries not yet populated: {path}")
    return load_json_fixture(path)
