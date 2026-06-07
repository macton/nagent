#!/usr/bin/python3

import json
import re
import uuid
from pathlib import Path


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", name).strip("-").lower()
    return slug or "file"


def file_index_path(root: Path, pid: str) -> Path:
    return root / "conversations" / f"file-index-{pid}.json"


def file_id_for_path(path: Path) -> str:
    stat = path.stat()
    return f"{stat.st_dev}:{stat.st_ino}"


def same_file(path_a: Path, path_b: Path) -> bool:
    try:
        return path_a.expanduser().resolve().samefile(path_b.expanduser().resolve())
    except OSError:
        return False


def empty_index() -> dict:
    return {"by_file_id": {}}


def normalize_index(raw: dict) -> dict:
    if "by_file_id" in raw:
        return raw
    by_file_id: dict[str, dict] = {}
    for key, conversation in raw.items():
        if not isinstance(conversation, str):
            continue
        entry = {"path": key, "conversation": conversation}
        path = Path(key)
        if path.is_file():
            try:
                file_id = file_id_for_path(path)
                entry["file_id"] = file_id
                by_file_id[file_id] = entry
                continue
            except OSError:
                pass
        by_file_id[f"path:{key}"] = entry
    return {"by_file_id": by_file_id}


def load_file_index(index_path: Path) -> dict:
    if not index_path.is_file():
        return empty_index()
    return normalize_index(json.loads(index_path.read_text(encoding="utf-8")))


def save_file_index(index_path: Path, index: dict) -> None:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")


def lookup_conversation(index: dict, resolved: Path) -> tuple[str | None, str | None]:
    by_file_id = index.get("by_file_id", {})
    file_id = file_id_for_path(resolved)
    resolved_str = str(resolved)

    entry = by_file_id.get(file_id)
    if entry is not None:
        entry["path"] = resolved_str
        entry["file_id"] = file_id
        return entry["conversation"], file_id

    for candidate_id, candidate in by_file_id.items():
        if candidate.get("path") == resolved_str:
            candidate["file_id"] = file_id
            by_file_id[file_id] = candidate
            if candidate_id != file_id:
                del by_file_id[candidate_id]
            return candidate["conversation"], file_id

    return None, file_id


def resolve_file_edit_conversation(root: Path, pid: str, file_path: Path) -> tuple[str, Path, str]:
    resolved = file_path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"file not found: {file_path}")

    index_path = file_index_path(root, pid)
    index = load_file_index(index_path)
    conversation_name, file_id = lookup_conversation(index, resolved)

    if conversation_name is None:
        conversation_name = f"{slugify(resolved.stem)}-{uuid.uuid4()}"
        index.setdefault("by_file_id", {})[file_id] = {
            "file_id": file_id,
            "path": str(resolved),
            "conversation": conversation_name,
        }
        save_file_index(index_path, index)
    else:
        save_file_index(index_path, index)

    return conversation_name, resolved, file_id


def list_file_edits(root: Path, pid: str) -> dict:
    index_path = file_index_path(root, pid)
    index = load_file_index(index_path)
    files: list[dict] = []
    for file_id, entry in sorted(index.get("by_file_id", {}).items()):
        files.append(
            {
                "file_id": entry.get("file_id", file_id),
                "path": entry.get("path"),
                "conversation": entry.get("conversation"),
            }
        )
    return {
        "file_index_path": str(index_path.resolve()) if index_path.is_file() else str(index_path),
        "pid": pid,
        "files": files,
    }


def is_split_segment_for_source(
    segment_path: Path,
    source_path: Path,
    root: Path,
    source_file_id: str | None = None,
) -> bool:
    try:
        resolved_segment = segment_path.expanduser().resolve()
    except OSError:
        return False

    splits_dir = root / "splits"
    if not splits_dir.is_dir():
        return False

    for index_path in splits_dir.glob("*/index.json"):
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        index_source = Path(index.get("source_path", ""))
        if not index_source.is_file():
            continue
        if source_file_id is not None:
            try:
                if file_id_for_path(index_source) != source_file_id:
                    continue
            except OSError:
                continue
        elif not same_file(index_source, source_path):
            continue

        for segment in index.get("segments", []):
            segment_file = segment.get("path")
            if segment_file is None:
                continue
            try:
                if Path(segment_file).expanduser().resolve() == resolved_segment:
                    return True
            except OSError:
                continue

    return False
