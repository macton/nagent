#!/usr/bin/python3

import hashlib
import json
import re
import shutil
import subprocess
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from nagent_file_edit_lib import file_id_for_path
from nagent_file_split_lib import source_sha256

# Reuse the thresholds the rest of the system already commits to.
SUMMARIZE_THRESHOLD_BYTES = 64 * 1024
MAX_HARVEST_SOURCE_BYTES = 1024 * 1024
DIGEST_MAX_BYTES = 4 * 1024
HARVEST_MAX_ATTEMPTS = 2

UUID_PATTERN = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
ENDS_WITH_UUID = re.compile(rf"-{UUID_PATTERN}\Z")
DELEGATED_NAME = re.compile(rf"\A{UUID_PATTERN}-")
JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)

HARVEST_PROMPT_NAME = "harvest-conversation.md"
REPO_HARVEST_PROMPT_PATH = Path(__file__).resolve().parent.parent.parent / "prompts" / HARVEST_PROMPT_NAME

ITEM_CATEGORIES = ("facts", "decisions", "tasks_done", "tasks_open", "questions", "playbooks", "files")

CATEGORY_FILES = {
    "facts": ("facts.md", "# Facts"),
    "decisions": ("decisions.md", "# Decisions"),
    "questions": ("questions.md", "# Questions"),
    "playbooks": ("playbooks.md", "# Playbooks"),
}

DIGEST_SECTIONS = (
    ("Open tasks", "tasks_open"),
    ("Open questions", "questions"),
    ("Decisions", "decisions"),
    ("Facts", "facts"),
    ("Playbooks", "playbooks"),
)


@dataclass
class Artifact:
    path: Path
    kind: str  # "conversation" | "split-dir" | "index" | "index-entry"
    klass: str  # "live" | "user-kept" | "prune" | "harvest" | "keep"
    reason: str
    size_bytes: int = 0
    name: str = ""

    def as_dict(self) -> dict:
        return {
            "path": str(self.path),
            "kind": self.kind,
            "class": self.klass,
            "reason": self.reason,
            "size_bytes": self.size_bytes,
        }


def knowledge_dir(root: Path) -> Path:
    return root / "knowledge"


def ledger_path(root: Path) -> Path:
    return knowledge_dir(root) / "ledger.json"


def digest_path(root: Path) -> Path:
    return knowledge_dir(root) / "digest.md"


def file_knowledge_path(root: Path, file_id: str) -> Path:
    return knowledge_dir(root) / "files" / f"{file_id}.md"


def harvest_prompt_path(root: Path) -> Path:
    # The harvest prompt is user-editable data; a copy under the nagent root
    # wins over the repo copy shipped next to the executable.
    user_prompt = root / "prompts" / HARVEST_PROMPT_NAME
    if user_prompt.is_file():
        return user_prompt
    return REPO_HARVEST_PROMPT_PATH


def load_ledger(root: Path) -> dict:
    path = ledger_path(root)
    payload = {"entries": {}}
    if not path.is_file():
        return payload
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return payload
    if isinstance(loaded, dict) and isinstance(loaded.get("entries"), dict):
        payload["entries"] = loaded["entries"]
    return payload


def save_ledger(root: Path, ledger: dict) -> Path:
    path = ledger_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def directory_size_bytes(path: Path) -> int:
    total = 0
    for child in path.rglob("*"):
        try:
            if child.is_file():
                total += child.stat().st_size
        except OSError:
            continue
    return total


def root_size_bytes(root: Path) -> int:
    if not root.is_dir():
        return 0
    return directory_size_bytes(root)


def _load_index_json(path: Path) -> dict | None:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _saved_paths(conversations: Path) -> set[str]:
    saved: set[str] = set()
    for index_file in conversations.glob("index-saved-conversations-*.json"):
        loaded = _load_index_json(index_file)
        if loaded is None:
            continue
        for entry in loaded.get("conversations", []):
            if isinstance(entry, dict) and isinstance(entry.get("path"), str):
                saved.add(entry["path"])
    return saved


def _file_index_entries(conversations: Path) -> dict[str, dict]:
    """Map conversation name -> file-index entry, across all pids."""
    by_conversation: dict[str, dict] = {}
    for index_file in conversations.glob("file-index-*.json"):
        loaded = _load_index_json(index_file)
        if loaded is None:
            continue
        for entry in loaded.get("by_file_id", {}).values():
            if isinstance(entry, dict) and isinstance(entry.get("conversation"), str):
                by_conversation[entry["conversation"]] = entry
    return by_conversation


def scan_root(root: Path) -> list[Artifact]:
    artifacts: list[Artifact] = []
    conversations = root / "conversations"

    if conversations.is_dir():
        saved_paths = _saved_paths(conversations)
        file_index = _file_index_entries(conversations)

        for path in sorted(conversations.iterdir()):
            if not path.is_file():
                continue
            name = path.name
            size = path.stat().st_size

            if name.startswith("file-index-") or name.startswith("index-saved-conversations-"):
                artifacts.append(Artifact(path, "index", "live", "index file", size, name))
                continue
            if str(path.resolve()) in saved_paths:
                artifacts.append(Artifact(path, "conversation", "user-kept", "saved conversation", size, name))
                continue
            if name in file_index:
                target = file_index[name].get("path", "")
                if target and Path(target).is_file():
                    artifacts.append(
                        Artifact(path, "conversation", "live", f"per-file conversation for {target}", size, name)
                    )
                else:
                    artifacts.append(
                        Artifact(
                            path, "conversation", "harvest",
                            f"per-file conversation; target gone: {target or 'unknown'}", size, name,
                        )
                    )
                continue
            if ENDS_WITH_UUID.search(name):
                artifacts.append(Artifact(path, "conversation", "harvest", "archived conversation", size, name))
                continue
            if DELEGATED_NAME.match(name):
                artifacts.append(Artifact(path, "conversation", "harvest", "delegated sub-conversation", size, name))
                continue
            if name.startswith("latest-"):
                artifacts.append(Artifact(path, "conversation", "live", "active conversation", size, name))
                continue
            artifacts.append(Artifact(path, "conversation", "keep", "unclassified; kept", size, name))

    splits = root / "splits"
    if splits.is_dir():
        for split_dir in sorted(splits.iterdir()):
            if not split_dir.is_dir():
                continue
            size = directory_size_bytes(split_dir)
            index_file = split_dir / "index.json"
            index = _load_index_json(index_file) if index_file.is_file() else None
            if index is None:
                artifacts.append(Artifact(split_dir, "split-dir", "keep", "no readable index.json; kept", size))
                continue
            source = Path(index.get("source_path", ""))
            if not source.is_file():
                artifacts.append(Artifact(split_dir, "split-dir", "prune", "split source gone", size))
                continue
            recorded_hash = index.get("source_sha256")
            if recorded_hash and source_sha256(source) != recorded_hash:
                artifacts.append(Artifact(split_dir, "split-dir", "prune", "split stale (source changed)", size))
                continue
            artifacts.append(Artifact(split_dir, "split-dir", "live", "split current", size))

    return artifacts


def parse_harvest_json(text: str) -> dict:
    stripped = text.strip()
    fence = JSON_FENCE.match(stripped)
    if fence:
        stripped = fence.group(1).strip()
    payload = json.loads(stripped)
    if not isinstance(payload, dict):
        raise ValueError("harvest output is not a JSON object")
    harvested: dict[str, list] = {}
    for category in ITEM_CATEGORIES:
        rows = payload.get(category, [])
        harvested[category] = rows if isinstance(rows, list) else []
    return harvested


def _item_text(row, *, key_a: str = "statement", key_b: str = "detail") -> str | None:
    if isinstance(row, str):
        text = row.strip()
        return text or None
    if isinstance(row, dict):
        statement = str(row.get(key_a) or "").strip()
        detail = str(row.get(key_b) or "").strip()
        if not statement:
            return None
        return f"{statement} — {detail}" if detail else statement
    return None


def _append_bullets(path: Path, header: str, bullets: list[str]) -> None:
    if not bullets:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file():
        path.write_text(f"{header}\n\n", encoding="utf-8")
    with path.open("a", encoding="utf-8") as handle:
        for bullet in bullets:
            handle.write(f"- {bullet}\n")


def _append_task_bullets(path: Path, open_bullets: list[str], done_bullets: list[str]) -> None:
    if not open_bullets and not done_bullets:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file():
        path.write_text("# Tasks\n\n## Open\n\n## Done\n", encoding="utf-8")
    lines = path.read_text(encoding="utf-8").splitlines()
    if "## Done" not in lines:
        lines.extend(["", "## Done"])
    done_at = lines.index("## Done")
    inserted = [f"- {bullet}" for bullet in open_bullets]
    lines[done_at:done_at] = inserted
    lines.extend(f"- {bullet}" for bullet in done_bullets)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def merge_harvest(root: Path, conversation_name: str, harvested: dict, date: str) -> dict[str, int]:
    """Append harvested items to the category files; returns per-category counts."""
    knowledge = knowledge_dir(root)
    provenance = f"[from: {conversation_name}, {date}]"
    counts: dict[str, int] = {category: 0 for category in ITEM_CATEGORIES}

    for category, (file_name, header) in CATEGORY_FILES.items():
        bullets = []
        for row in harvested.get(category, []):
            if category == "playbooks":
                if isinstance(row, dict):
                    name = str(row.get("name") or "").strip()
                    steps = str(row.get("steps") or "").strip()
                    text = f"**{name}**: {steps}" if name and steps else (name or steps)
                else:
                    text = _item_text(row)
                if not text:
                    continue
            else:
                text = _item_text(row)
                if not text:
                    continue
            bullets.append(f"{text} {provenance}")
        _append_bullets(knowledge / file_name, header, bullets)
        counts[category] = len(bullets)

    open_bullets = []
    for row in harvested.get("tasks_open", []):
        text = _item_text(row)
        if text:
            open_bullets.append(f"{text} {provenance}")
    done_bullets = []
    for row in harvested.get("tasks_done", []):
        text = _item_text(row)
        if text:
            done_bullets.append(f"{text} {provenance}")
    _append_task_bullets(knowledge / "tasks.md", open_bullets, done_bullets)
    counts["tasks_open"] = len(open_bullets)
    counts["tasks_done"] = len(done_bullets)

    file_notes = 0
    for row in harvested.get("files", []):
        if not isinstance(row, dict):
            continue
        path_text = str(row.get("path") or "").strip()
        note = str(row.get("note") or "").strip()
        if not note:
            continue
        target = Path(path_text) if path_text else None
        if target is not None and target.is_file():
            try:
                file_id = file_id_for_path(target)
            except OSError:
                file_id = None
            if file_id is not None:
                _append_bullets(
                    file_knowledge_path(root, file_id),
                    f"# {target.resolve()}",
                    [f"{note} {provenance}"],
                )
                file_notes += 1
                continue
        # Target no longer resolvable: the note survives as a fact.
        prefix = f"{path_text}: " if path_text else ""
        _append_bullets(knowledge / "facts.md", "# Facts", [f"{prefix}{note} {provenance}"])
        file_notes += 1
    counts["files"] = file_notes

    return counts


def _read_bullets(path: Path) -> list[str]:
    if not path.is_file():
        return []
    bullets: list[str] = []
    current: list[str] | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("- "):
            if current:
                bullets.append("\n".join(current))
            current = [line]
        elif current and line.startswith(("  ", "\t")):
            current.append(line)
        else:
            if current:
                bullets.append("\n".join(current))
            current = None
    if current:
        bullets.append("\n".join(current))
    return bullets


def _read_task_bullets(path: Path) -> tuple[list[str], list[str]]:
    if not path.is_file():
        return [], []
    open_bullets: list[str] = []
    done_bullets: list[str] = []
    section = "open"
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() == "## Done":
            section = "done"
            continue
        if line.strip() == "## Open":
            section = "open"
            continue
        if line.startswith("- "):
            (open_bullets if section == "open" else done_bullets).append(line)
    return open_bullets, done_bullets


def regenerate_digest(root: Path, max_bytes: int = DIGEST_MAX_BYTES) -> Path | None:
    """Rebuild digest.md from the category files. Returns None when empty."""
    knowledge = knowledge_dir(root)
    open_tasks, _done = _read_task_bullets(knowledge / "tasks.md")
    sections: list[tuple[str, list[str]]] = []
    for title, category in DIGEST_SECTIONS:
        if category == "tasks_open":
            bullets = open_tasks
        else:
            file_name, _header = CATEGORY_FILES[category]
            bullets = _read_bullets(knowledge / file_name)
        if bullets:
            # Newest knowledge first: category files are append-only.
            sections.append((title, list(reversed(bullets))))

    target = digest_path(root)
    if not sections:
        if target.is_file():
            target.unlink()
        return None

    header = (
        "# Knowledge digest\n"
        "(regenerated by nagent-gc; edit the category files, not this file)\n"
    )
    parts: list[str] = [header]
    used = len(header.encode("utf-8"))
    truncated = False
    for title, bullets in sections:
        section_header = f"\n## {title}\n"
        used += len(section_header.encode("utf-8"))
        if used > max_bytes:
            truncated = True
            break
        parts.append(section_header)
        for bullet in bullets:
            line = f"{bullet}\n"
            used += len(line.encode("utf-8"))
            if used > max_bytes:
                truncated = True
                break
            parts.append(line)
        if truncated:
            break
    if truncated:
        parts.append("\n(truncated; see the category files for the rest)\n")

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("".join(parts), encoding="utf-8")
    return target


def knowledge_item_counts(root: Path) -> dict[str, int]:
    knowledge = knowledge_dir(root)
    counts: dict[str, int] = {}
    for category, (file_name, _header) in CATEGORY_FILES.items():
        counts[category] = len(_read_bullets(knowledge / file_name))
    open_tasks, done_tasks = _read_task_bullets(knowledge / "tasks.md")
    counts["tasks_open"] = len(open_tasks)
    counts["tasks_done"] = len(done_tasks)
    files_dir = knowledge / "files"
    counts["files"] = (
        sum(len(_read_bullets(path)) for path in files_dir.glob("*.md")) if files_dir.is_dir() else 0
    )
    return counts


def _default_summarize(path: Path, provider: str, model: str, config_path: Path | None) -> str:
    summarize_script = Path(__file__).resolve().parent.parent / "nagent-file-summarize"
    command = [
        str(summarize_script),
        "--file",
        str(path),
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
        raise RuntimeError(error)
    payload = json.loads(result.stdout)
    summary = payload.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise RuntimeError("nagent-file-summarize returned no summary")
    return summary


def build_harvest_prompt(template: str, conversation_name: str, content: str, *, retry: bool = False) -> str:
    suffix = (
        "\nYour previous reply was not valid JSON. Return only the JSON object.\n"
        if retry
        else ""
    )
    return (
        f"{template}\n\n"
        f"Conversation name: {conversation_name}\n\n"
        f"<conversation>\n{content}\n</conversation>\n{suffix}"
    )


def harvest_conversation(
    root: Path,
    path: Path,
    provider: str,
    model: str,
    config_path: Path | None,
    *,
    generate,
    summarize=None,
) -> dict:
    """Harvest one conversation. Returns the parsed category dict.

    Raises RuntimeError/ValueError on any failure; the caller decides
    disposition (keep + ledger entry)."""
    size = path.stat().st_size
    if size > SUMMARIZE_THRESHOLD_BYTES:
        summarize_fn = summarize or _default_summarize
        content = summarize_fn(path, provider, model, config_path)
    else:
        content = path.read_text(encoding="utf-8")

    template = harvest_prompt_path(root).read_text(encoding="utf-8").strip()
    last_error: Exception | None = None
    for attempt in range(HARVEST_MAX_ATTEMPTS):
        prompt = build_harvest_prompt(template, path.name, content, retry=attempt > 0)
        response = generate(prompt, provider, model)
        try:
            return parse_harvest_json(response)
        except (json.JSONDecodeError, ValueError) as exc:
            last_error = exc
    raise RuntimeError(f"harvest output invalid after {HARVEST_MAX_ATTEMPTS} attempts: {last_error}")


def _prune_file_index_entries(conversations: Path) -> int:
    """Drop file-index entries whose target file no longer exists."""
    pruned = 0
    for index_file in conversations.glob("file-index-*.json"):
        loaded = _load_index_json(index_file)
        if loaded is None or not isinstance(loaded.get("by_file_id"), dict):
            continue
        kept = {
            file_id: entry
            for file_id, entry in loaded["by_file_id"].items()
            if isinstance(entry, dict)
            and isinstance(entry.get("path"), str)
            and Path(entry["path"]).is_file()
        }
        dropped = len(loaded["by_file_id"]) - len(kept)
        if dropped:
            loaded["by_file_id"] = kept
            index_file.write_text(json.dumps(loaded, indent=2) + "\n", encoding="utf-8")
            pruned += dropped
    return pruned


def _prune_saved_index_entries(conversations: Path) -> int:
    """Drop saved-conversation index entries whose saved copy no longer exists."""
    pruned = 0
    for index_file in conversations.glob("index-saved-conversations-*.json"):
        loaded = _load_index_json(index_file)
        if loaded is None or not isinstance(loaded.get("conversations"), list):
            continue
        kept = [
            entry
            for entry in loaded["conversations"]
            if isinstance(entry, dict)
            and isinstance(entry.get("path"), str)
            and Path(entry["path"]).is_file()
        ]
        dropped = len(loaded["conversations"]) - len(kept)
        if dropped:
            loaded["conversations"] = kept
            index_file.write_text(json.dumps(loaded, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            pruned += dropped
    return pruned


def run_gc(
    root: Path,
    *,
    apply: bool = False,
    harvest: bool = True,
    max_harvest_bytes: int | None = None,
    provider: str | None = None,
    model: str | None = None,
    config_path: Path | None = None,
    generate=None,
    summarize=None,
    now: datetime | None = None,
    spinner=None,
    progress=None,
) -> dict:
    # spinner: callable(message) -> context manager shown while an LLM call
    # runs. progress: callable(message) -> None for per-artifact status lines.
    # Both default to silent so library callers and tests stay quiet.
    spin = spinner or (lambda message: nullcontext())

    def emit(message: str) -> None:
        if progress is not None:
            progress(message)

    artifacts = scan_root(root)
    harvest_candidates = [a for a in artifacts if a.klass == "harvest"]
    prune_candidates = [a for a in artifacts if a.klass == "prune"]

    totals: dict[str, int] = {}
    for artifact in artifacts:
        totals[artifact.klass] = totals.get(artifact.klass, 0) + 1

    harvest_bytes = sum(a.size_bytes for a in harvest_candidates)
    report = {
        "root": str(root),
        "apply": apply,
        "harvest": harvest,
        "artifacts": [a.as_dict() for a in artifacts],
        "totals": totals,
        "harvest_candidate_bytes": harvest_bytes,
        "estimated_harvest_input_tokens": harvest_bytes // 4,
        "prune_candidate_bytes": sum(a.size_bytes for a in prune_candidates),
    }
    if not apply:
        return report

    timestamp = (now or datetime.now(timezone.utc)).isoformat()
    date = timestamp[:10]
    ledger = load_ledger(root)
    entries = ledger["entries"]
    reclaimed = 0
    harvested_counts: dict[str, int] = {category: 0 for category in ITEM_CATEGORIES}
    failures: list[dict] = []
    deferred = 0
    harvested_input_bytes = 0

    total_candidates = len(harvest_candidates)
    for index, artifact in enumerate(harvest_candidates, start=1):
        path = artifact.path
        label = f"{path.name} ({index}/{total_candidates})"
        try:
            sha = sha256_of(path)
        except OSError as exc:
            failures.append({"path": str(path), "error": str(exc)})
            emit(f"failed: {label}: {exc}")
            continue

        existing = entries.get(sha)
        if existing is not None and existing.get("status") == "harvested":
            # Distillation already proven for this exact content: just reclaim.
            reclaimed += artifact.size_bytes
            path.unlink()
            existing["deleted"] = True
            emit(f"reclaimed (already harvested): {label}")
            continue

        if not harvest:
            reclaimed += artifact.size_bytes
            path.unlink()
            entries[sha] = {
                "path": str(path),
                "status": "deleted-unharvested",
                "at": timestamp,
                "deleted": True,
            }
            emit(f"reclaimed (no harvest): {label}")
            continue

        if artifact.size_bytes > MAX_HARVEST_SOURCE_BYTES:
            entries[sha] = {
                "path": str(path),
                "status": "too-large",
                "at": timestamp,
                "deleted": False,
            }
            emit(f"kept (too large): {label}")
            continue

        if max_harvest_bytes is not None and harvested_input_bytes + artifact.size_bytes > max_harvest_bytes:
            deferred += 1
            emit(f"deferred (over --max-harvest-bytes): {label}")
            continue

        try:
            with spin(f"Harvesting {label}"):
                harvested = harvest_conversation(
                    root,
                    path,
                    provider,
                    model,
                    config_path,
                    generate=generate,
                    summarize=summarize,
                )
        except (OSError, RuntimeError, ValueError, UnicodeDecodeError) as exc:
            failures.append({"path": str(path), "error": str(exc)})
            entries[sha] = {
                "path": str(path),
                "status": "harvest-failed",
                "at": timestamp,
                "deleted": False,
                "error": str(exc),
            }
            emit(f"harvest failed: {label}: {exc}")
            continue

        harvested_input_bytes += artifact.size_bytes
        counts = merge_harvest(root, path.name, harvested, date)
        for category, count in counts.items():
            harvested_counts[category] += count
        reclaimed += artifact.size_bytes
        path.unlink()
        entries[sha] = {
            "path": str(path),
            "status": "harvested",
            "at": timestamp,
            "items": counts,
            "deleted": True,
        }
        item_summary = ", ".join(
            f"{category}:{count}" for category, count in sorted(counts.items()) if count
        )
        emit(f"harvested: {label} ({item_summary or 'nothing durable'})")

    if prune_candidates:
        emit(f"pruning {len(prune_candidates)} stale artifact{'s' if len(prune_candidates) != 1 else ''}")
    for artifact in prune_candidates:
        try:
            if artifact.path.is_dir():
                shutil.rmtree(artifact.path)
            else:
                artifact.path.unlink()
            reclaimed += artifact.size_bytes
            entries[f"path:{artifact.path}"] = {
                "path": str(artifact.path),
                "status": "pruned",
                "at": timestamp,
                "deleted": True,
            }
        except OSError as exc:
            failures.append({"path": str(artifact.path), "error": str(exc)})

    conversations = root / "conversations"
    pruned_entries = 0
    if conversations.is_dir():
        pruned_entries += _prune_file_index_entries(conversations)
        pruned_entries += _prune_saved_index_entries(conversations)

    save_ledger(root, ledger)
    digest = regenerate_digest(root)

    report["reclaimed_bytes"] = reclaimed
    report["harvested_items"] = harvested_counts
    report["failures"] = failures
    report["deferred"] = deferred
    report["pruned_index_entries"] = pruned_entries
    report["ledger_path"] = str(ledger_path(root))
    report["digest_path"] = str(digest) if digest else None
    return report
