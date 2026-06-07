#!/usr/bin/python3

import difflib
import json
from dataclasses import dataclass
from pathlib import Path

from nagent_file_split_lib import build_index, read_lines, source_sha256, write_index_file


@dataclass
class PatchResult:
    source_path: Path
    index_path: Path
    patch_path: Path | None
    changed: bool
    source_sha256: str


def load_index(index_path: Path) -> dict:
    if not index_path.is_file():
        raise FileNotFoundError(f"index not found: {index_path}")
    return json.loads(index_path.read_text(encoding="utf-8"))


def validate_index(index: dict, *, require_hash_match: bool = True) -> tuple[Path, list[dict]]:
    source_raw = index.get("source_path")
    segments = index.get("segments")
    if not source_raw:
        raise ValueError("index.json missing source_path")
    if not segments:
        raise ValueError("index.json has no segments")

    source = Path(source_raw)
    if not source.is_file():
        raise FileNotFoundError(f"source file not found: {source}")

    if require_hash_match and index.get("source_sha256"):
        current_hash = source_sha256(source)
        if current_hash != index["source_sha256"]:
            raise ValueError(
                "source file hash does not match index.json "
                f"(expected {index['source_sha256']}, got {current_hash})"
            )

    sorted_segments = sorted(segments, key=lambda segment: segment["start_line_num"])
    expected_line = sorted_segments[0]["start_line_num"]
    for segment in sorted_segments:
        segment_path = Path(segment["path"])
        if not segment_path.is_file():
            raise FileNotFoundError(f"segment not found: {segment_path}")
        if segment["start_line_num"] != expected_line:
            raise ValueError(
                "segments are not contiguous in index.json "
                f"(expected start_line_num {expected_line}, got {segment['start_line_num']})"
            )
        expected_line = segment["end_line_num"] + 1

    return source, sorted_segments


def merge_segments(segments: list[dict]) -> str:
    return "".join(Path(segment["path"]).read_text(encoding="utf-8") for segment in segments)


def make_unified_patch(source: Path, original: str, updated: str) -> str:
    if original == updated:
        return ""
    return "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            updated.splitlines(keepends=True),
            fromfile=str(source),
            tofile=str(source),
        )
    )


def refresh_line_numbers(segments: list[dict]) -> list[dict]:
    current_line = 1
    refreshed: list[dict] = []

    for segment_index, segment in enumerate(segments, start=1):
        line_count = len(read_lines(Path(segment["path"])))
        if line_count == 0:
            refreshed.append(
                {
                    **segment,
                    "segment_index": segment_index,
                    "start_line_num": current_line,
                    "end_line_num": current_line - 1,
                }
            )
            continue

        start_line = current_line
        end_line = current_line + line_count - 1
        refreshed.append(
            {
                **segment,
                "segment_index": segment_index,
                "start_line_num": start_line,
                "end_line_num": end_line,
            }
        )
        current_line = end_line + 1

    return refreshed


def default_patch_path(index_path: Path, source: Path) -> Path:
    return index_path.parent / f"{source.stem}.patch"


def apply_segment_patches(
    index_path: Path,
    patch_path: Path | None = None,
    *,
    dry_run: bool = False,
    apply: bool = True,
    force: bool = False,
) -> PatchResult:
    index = load_index(index_path)
    source, segments = validate_index(index, require_hash_match=not force)

    original = source.read_text(encoding="utf-8")
    updated = merge_segments(segments)
    changed = original != updated

    resolved_patch_path = patch_path or default_patch_path(index_path, source)
    patch_text = make_unified_patch(source, original, updated)

    if patch_text:
        resolved_patch_path.write_text(patch_text, encoding="utf-8")
    else:
        resolved_patch_path = None

    refreshed_segments = refresh_line_numbers(segments)

    if not dry_run:
        if apply and changed:
            source.write_text(updated, encoding="utf-8")

        updated_index = build_index(
            source,
            refreshed_segments,
            index.get("split_type", "txt"),
            int(index.get("target_bytes", 32 * 1024)),
            natural=bool(index.get("natural", False)),
            created_at=index.get("created_at"),
        )
        write_index_file(index_path, updated_index)
        current_hash = updated_index["source_sha256"]
    else:
        current_hash = source_sha256(source)

    return PatchResult(
        source_path=source,
        index_path=index_path,
        patch_path=resolved_patch_path,
        changed=changed,
        source_sha256=current_hash,
    )
