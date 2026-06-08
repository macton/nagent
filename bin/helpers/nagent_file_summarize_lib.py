#!/usr/bin/python3

import json
import subprocess
from pathlib import Path

from nagent_llm import generate_text

SUMMARIZE_THRESHOLD_BYTES = 64 * 1024
SUMMARY_MAX_ATTEMPTS = 2


def count_words(text: str) -> int:
    return len(text.split())


def build_summary_prompt(
    source_label: str,
    content: str,
    limit_word_count: int | None = None,
    previous_word_count: int | None = None,
) -> str:
    instructions = [
        "Summarize this file concisely. Note its purpose, main components, "
        "and anything unusual or important.",
    ]
    if limit_word_count is not None:
        instructions.append(f"Fit the summary into {limit_word_count} words or less.")
    if previous_word_count is not None:
        instructions.append(
            f"The previous summary was {previous_word_count} words, which exceeded the limit. "
            "Retry with a shorter summary that meets the limit."
        )
    return f"{' '.join(instructions)}\nFile: {source_label}\n\n{content}"


def summarize_content(
    content: str,
    source_label: str,
    provider: str,
    model: str,
    limit_word_count: int | None = None,
) -> str:
    previous_word_count = None
    for _ in range(SUMMARY_MAX_ATTEMPTS):
        prompt = build_summary_prompt(
            source_label,
            content,
            limit_word_count,
            previous_word_count,
        )
        summary = generate_text(prompt, provider, model)
        word_count = count_words(summary)
        if limit_word_count is None or word_count <= limit_word_count:
            return summary
        previous_word_count = word_count
    raise RuntimeError(
        f"summary exceeded --limit-word-count {limit_word_count} "
        f"after {SUMMARY_MAX_ATTEMPTS} attempts (last word count: {previous_word_count})"
    )


def summarize_file_path(
    path: Path,
    provider: str,
    model: str,
    limit_word_count: int | None = None,
) -> str:
    content = path.read_text(encoding="utf-8")
    return summarize_content(content, str(path.resolve()), provider, model, limit_word_count)


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
