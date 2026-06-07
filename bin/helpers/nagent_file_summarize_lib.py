#!/usr/bin/python3

import json
import subprocess
from pathlib import Path

from nagent_llm import generate_text

SUMMARIZE_THRESHOLD_BYTES = 64 * 1024


def build_summary_prompt(source_label: str, content: str) -> str:
    return (
        "Summarize this file concisely. Note its purpose, main components, "
        f"and anything unusual or important.\nFile: {source_label}\n\n{content}"
    )


def summarize_content(content: str, source_label: str, provider: str, model: str) -> str:
    prompt = build_summary_prompt(source_label, content)
    return generate_text(prompt, provider, model)


def summarize_file_path(path: Path, provider: str, model: str) -> str:
    content = path.read_text(encoding="utf-8")
    return summarize_content(content, str(path.resolve()), provider, model)


def combined_summary_from_index(index: dict) -> str:
    parts: list[str] = []
    for segment in index.get("segments", []):
        summary = segment.get("summary")
        if not summary:
            continue
        start = segment.get("start_line_num", "?")
        end = segment.get("end_line_num", "?")
        parts.append(f"Lines {start}-{end}: {summary.strip()}")
    return "\n\n".join(parts)


def add_summaries_to_index(
    index: dict,
    provider: str,
    model: str,
    config_path: Path | None,
    summarize_script: Path,
) -> dict:
    for segment in index.get("segments", []):
        segment_path = Path(segment["path"])
        segment["summary"] = run_segment_summarize(
            segment_path,
            summarize_script,
            provider,
            model,
            config_path,
        )
    index["summary"] = combined_summary_from_index(index)
    return index


def run_segment_summarize(
    segment_path: Path,
    summarize_script: Path,
    provider: str,
    model: str,
    config_path: Path | None,
) -> str:
    command = [
        str(summarize_script),
        "--file",
        str(segment_path),
        "--provider",
        provider,
        "--model",
        model,
        "--json",
    ]
    if config_path is not None:
        command.extend(["--config", str(config_path)])

    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        error = result.stderr.strip() or result.stdout.strip() or "nagent-file-summarize failed"
        raise RuntimeError(f"{segment_path}: {error}")

    payload = json.loads(result.stdout)
    summary = payload.get("summary")
    if not isinstance(summary, str):
        raise RuntimeError(f"{segment_path}: summarize JSON missing summary field")
    return summary
