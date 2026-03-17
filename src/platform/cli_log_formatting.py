# @summary
# Shared console log styling helpers for query and ingestion logger messages.
# Exports: build_logger_style, build_level_badges, style_log_message
# Deps: re
# @end-summary
"""Shared CLI console log formatting helpers."""

from __future__ import annotations

import re


def build_logger_style(palette: dict[str, str]) -> dict[str, tuple[str, str]]:
    """Build default logger label styling map."""
    return {
        "rag.query_processor": (
            f"{palette['B_MAGENTA']}⟡ Query{palette['RESET']}",
            palette["MAGENTA"],
        ),
        "rag.rag_chain": (
            f"{palette['B_CYAN']}⟡ Chain{palette['RESET']}",
            palette["CYAN"],
        ),
        "rag.vector_store": (
            f"{palette['B_BLUE']}⟡ Store{palette['RESET']}",
            palette["BLUE"],
        ),
        "rag.generator": (
            f"{palette['B_GREEN']}⟡ Gen{palette['RESET']}",
            palette["GREEN"],
        ),
        "rag.knowledge_graph": (
            f"{palette['B_YELLOW']}⟡ KG{palette['RESET']}",
            palette["YELLOW"],
        ),
        "rag.ingest.pipeline": (
            f"{palette['B_GREEN']}⟡ Ingest{palette['RESET']}",
            palette["GREEN"],
        ),
        "rag.ingest.pipeline.stage": (
            f"{palette['B_GREEN']}⟡ Stage{palette['RESET']}",
            palette["GREEN"],
        ),
        "rag.query_cli": (
            f"{palette['B_WHITE']}⟡ CLI{palette['RESET']}",
            palette["WHITE"],
        ),
    }


def build_level_badges(palette: dict[str, str]) -> dict[str, str]:
    """Build default level badge styling map."""
    return {
        "DEBUG": f"{palette['DIM']}DBG{palette['RESET']}",
        "INFO": f"{palette['B_CYAN']}ℹ{palette['RESET']}",
        "WARNING": f"{palette['B_YELLOW']}⚠{palette['RESET']}",
        "ERROR": f"{palette['B_RED']}✗{palette['RESET']}",
        "CRITICAL": f"{palette['B_RED']}✗✗{palette['RESET']}",
    }


def style_log_message(logger_name: str, msg: str, palette: dict[str, str]) -> str:
    """Apply logger-specific message styling."""
    if logger_name == "rag.query_processor":
        return _style_query_processor_msg(msg, palette)
    if logger_name == "rag.ingest.pipeline.stage":
        return _style_ingest_stage_msg(msg, palette)
    if logger_name == "rag.ingest.pipeline":
        return _style_ingest_pipeline_msg(msg, palette)
    return msg


def _style_query_processor_msg(msg: str, palette: dict[str, str]) -> str:
    m = re.match(r"Iteration (\d+): reformulated '(.+)' -> '(.+)'", msg)
    if m:
        return f"Reformulation #{m.group(1)}: {palette['RESET']}{m.group(3)}"

    m = re.match(r"Iteration (\d+): confidence=([\d.]+) reasoning='(.+)'", msg)
    if m:
        conf = float(m.group(2))
        if conf >= 0.7:
            conf_color = palette["B_GREEN"]
        elif conf >= 0.4:
            conf_color = palette["B_YELLOW"]
        else:
            conf_color = palette["B_RED"]
        return (
            f"Confidence: {conf_color}{conf:.0%}{palette['RESET']}  "
            f"{palette['DIM']}{m.group(3)}{palette['RESET']}"
        )

    m = re.match(
        r"Query processing complete: action=(\w+) confidence=([\d.]+) iterations=(\d+) query='(.+)'",
        msg,
    )
    if m:
        return (
            f"Final: {palette['RESET']}{palette['B_WHITE']}{m.group(4)}"
            f"{palette['RESET']} {palette['DIM']}({m.group(1)}, {m.group(3)} iters)"
            f"{palette['RESET']}"
        )

    m = re.match(r"Processing query: '(.+)'", msg)
    if m:
        return f"Processing: {palette['RESET']}{m.group(1)}"
    return msg


def _style_ingest_stage_msg(msg: str, palette: dict[str, str]) -> str:
    m = re.match(r"source=([^\s]+)\s+stage=([a-z_]+):([a-z_]+)", msg)
    if not m:
        return msg

    source = m.group(1)
    stage = m.group(2).replace("_", " ")
    status = m.group(3).lower()
    if status == "ok":
        status_part = f"{palette['B_GREEN']}ok{palette['RESET']}"
    elif status == "skipped":
        status_part = f"{palette['B_YELLOW']}skipped{palette['RESET']}"
    elif status == "failed":
        status_part = f"{palette['B_RED']}failed{palette['RESET']}"
    else:
        status_part = f"{palette['B_CYAN']}{status}{palette['RESET']}"

    return (
        f"{palette['B_WHITE']}{source}{palette['RESET']} "
        f"{palette['DIM']}|{palette['RESET']} "
        f"{palette['B_CYAN']}{stage}{palette['RESET']} "
        f"{palette['DIM']}|{palette['RESET']} {status_part}"
    )


def _style_ingest_pipeline_msg(msg: str, palette: dict[str, str]) -> str:
    m = re.match(r"ingestion_start source=(.+)", msg)
    if m:
        source = m.group(1).split("/")[-1]
        return (
            f"{palette['B_WHITE']}{source}{palette['RESET']} "
            f"{palette['DIM']}|{palette['RESET']} "
            f"{palette['B_CYAN']}start{palette['RESET']}"
        )

    m = re.match(r"ingestion_failed source=([^\s]+)\s+errors=(.+)", msg)
    if m:
        source = m.group(1)
        errors = m.group(2)
        return (
            f"{palette['B_WHITE']}{source}{palette['RESET']} "
            f"{palette['DIM']}|{palette['RESET']} "
            f"{palette['B_RED']}failed{palette['RESET']}"
            f"\n      {palette['DIM']}error:{palette['RESET']} "
            f"{palette['B_RED']}{errors}{palette['RESET']}"
        )

    m = re.match(
        r"ingestion_skipped source=([^\s]+)\s+reason=([^\s]+)\s+stages=(.+)",
        msg,
    )
    if m:
        source = m.group(1)
        reason = m.group(2).replace("_", " ")
        stages = _format_stage_path(m.group(3), palette)
        return (
            f"{palette['B_WHITE']}{source}{palette['RESET']} "
            f"{palette['DIM']}|{palette['RESET']} "
            f"{palette['B_YELLOW']}skipped{palette['RESET']} "
            f"{palette['DIM']}({reason}){palette['RESET']}"
            f"\n      {palette['DIM']}stages:{palette['RESET']} {stages}"
        )

    m = re.match(
        r"ingestion_done source=([^\s]+)\s+chunks=(\d+)\s+stored=(\d+)\s+stages=(.+)",
        msg,
    )
    if m:
        source = m.group(1)
        chunks = m.group(2)
        stored = m.group(3)
        stages = _format_stage_path(m.group(4), palette)
        return (
            f"{palette['B_WHITE']}{source}{palette['RESET']} "
            f"{palette['DIM']}|{palette['RESET']} {palette['B_GREEN']}done"
            f"{palette['RESET']} {palette['DIM']}|{palette['RESET']} chunks "
            f"{palette['B_CYAN']}{chunks}{palette['RESET']} "
            f"{palette['DIM']}|{palette['RESET']} stored "
            f"{palette['B_CYAN']}{stored}{palette['RESET']}"
            f"\n      {palette['DIM']}stages:{palette['RESET']} {stages}"
        )
    return msg


def _format_stage_path(raw_stages: str, palette: dict[str, str]) -> str:
    stage_items = []
    for item in [part.strip() for part in raw_stages.split(">") if part.strip()]:
        m = re.match(r"([a-z_]+):([a-z_]+)", item)
        if not m:
            stage_items.append(item)
            continue
        stage_name = m.group(1).replace("_", " ")
        status = m.group(2).lower()
        if status == "ok":
            status_display = f"{palette['B_GREEN']}ok{palette['RESET']}"
        elif status == "skipped":
            status_display = f"{palette['B_YELLOW']}skipped{palette['RESET']}"
        elif status == "failed":
            status_display = f"{palette['B_RED']}failed{palette['RESET']}"
        else:
            status_display = status
        stage_items.append(
            f"{palette['B_CYAN']}{stage_name}{palette['RESET']}:{status_display}"
        )
    return f" {palette['DIM']}|{palette['RESET']} ".join(stage_items)
