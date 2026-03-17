#!/usr/bin/env python3
"""Download and verify Docling Heron + TableFormer model artifacts."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ingest.support.docling import warmup_docling_models


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Warm up Docling model artifacts for ingestion preflight",
    )
    parser.add_argument(
        "--artifacts-path",
        type=Path,
        default=None,
        help="Optional target directory for Docling model cache",
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    path_value = str(args.artifacts_path.resolve()) if args.artifacts_path else ""
    model_root = warmup_docling_models(artifacts_path=path_value)
    print(f"Docling warmup complete: {model_root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

