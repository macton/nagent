#!/usr/bin/python3
"""Campaign system: plans as operable artifacts (issues/0002-campaign-system.md).

The plan is a hand-editable artifact (index.yaml spine, per-item item.yaml,
per-item conversations) and the driver is a deterministic one-pass transform
over it. Invariants (load-bearing):

1. One pass, then exit — no resident process.
2. One writer for the tree — workers return data (result.json in their own
   item dir); only the driver mutates index.yaml and item files.
3. Plan changes pass a review gate, not a cap — decomposition lands as
   proposals; large changes (and a new campaign's initial decomposition,
   always) wait for confirmation with their scope reported.
4. The schema is the whole schema — spine in index.yaml, detail in
   items/{id}/item.yaml, nothing else.
"""

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from nagent_cli import resolve_prompt_path
from nagent_file_split_lib import slugify

ITEM_STATUSES = ("todo", "proposed", "in-progress", "blocked", "question", "review", "done", "failed")
CAMPAIGN_STATUSES = ("active", "paused", "done")

DEFAULT_REVIEW = {"auto_confirm_max_items": 5, "auto_confirm_max_depth": 2}
DEFAULT_DISPATCH = {"max_per_update": 4}

ITEM_ID_PATTERN = re.compile(r"^(\d{4})-")
JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)

DECOMPOSE_PROMPT_NAME = "campaign-decompose.md"
ITEM_PROMPT_NAME = "campaign-item.md"
JUDGE_PROMPT_NAME = "campaign-judge.md"


def campaigns_dir(root: Path) -> Path:
    return root / "campaigns"


def campaign_dir(root: Path, slug: str) -> Path:
    return campaigns_dir(root) / slug


def index_path(campaign: Path) -> Path:
    return campaign / "index.yaml"


def items_dir(campaign: Path) -> Path:
    return campaign / "items"


def item_dir(campaign: Path, item_id: str) -> Path:
    return items_dir(campaign) / item_id


def questions_path(campaign: Path) -> Path:
    return campaign / "questions.md"


def _dump_yaml(payload: dict) -> str:
    # Hand-editability: block style, insertion order preserved.
    return yaml.safe_dump(payload, default_flow_style=False, sort_keys=False, allow_unicode=True)


def load_index(campaign: Path) -> dict:
    payload = yaml.safe_load(index_path(campaign).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"index.yaml is not a mapping: {index_path(campaign)}")
    payload.setdefault("items", [])
    payload.setdefault("review", dict(DEFAULT_REVIEW))
    payload.setdefault("dispatch", dict(DEFAULT_DISPATCH))
    return payload


def save_index(campaign: Path, index: dict) -> None:
    index_path(campaign).write_text(_dump_yaml(index), encoding="utf-8")


def load_item(campaign: Path, item_id: str) -> dict:
    path = item_dir(campaign, item_id) / "item.yaml"
    if not path.is_file():
        return {"id": item_id}
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {"id": item_id}


def save_item(campaign: Path, item: dict) -> None:
    directory = item_dir(campaign, item["id"])
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "item.yaml").write_text(_dump_yaml(item), encoding="utf-8")


def walk_items(nodes: list, depth: int = 1):
    """Yield (node, depth, parent_list) for every node in the tree."""
    for node in nodes:
        yield node, depth, nodes
        children = node.get("items") or []
        yield from walk_items(children, depth + 1)


def find_node(index: dict, item_id: str) -> dict | None:
    for node, _depth, _siblings in walk_items(index.get("items", [])):
        if node.get("id") == item_id:
            return node
    return None


def tree_depth(nodes: list) -> int:
    depth = 0
    for _node, node_depth, _siblings in walk_items(nodes):
        depth = max(depth, node_depth)
    return depth


def status_counts(index: dict) -> dict[str, int]:
    counts: dict[str, int] = {}
    for node, _depth, _siblings in walk_items(index.get("items", [])):
        status = node.get("status", "todo")
        counts[status] = counts.get(status, 0) + 1
    return counts


def next_item_id(index: dict, description: str) -> str:
    highest = 0
    for node, _depth, _siblings in walk_items(index.get("items", [])):
        match = ITEM_ID_PATTERN.match(str(node.get("id", "")))
        if match:
            highest = max(highest, int(match.group(1)))
    words = slugify(" ".join(description.split()[:4]))[:24].strip("-") or "item"
    return f"{highest + 1:04d}-{words}"


def new_campaign(root: Path, name: str, description: str = "") -> Path:
    slug = slugify(name)
    campaign = campaign_dir(root, slug)
    if campaign.exists():
        raise FileExistsError(f"campaign already exists: {campaign}")
    items_dir(campaign).mkdir(parents=True)
    (campaign / "conversations").mkdir()
    (campaign / "tests").mkdir()
    index = {
        "name": name,
        "description": description,
        "status": "active",
        "completion": [],
        "references": [],
        "review": dict(DEFAULT_REVIEW),
        "dispatch": dict(DEFAULT_DISPATCH),
        "items": [],
    }
    save_index(campaign, index)
    return campaign


def list_campaigns(root: Path) -> list[Path]:
    base = campaigns_dir(root)
    if not base.is_dir():
        return []
    return sorted(p for p in base.iterdir() if (p / "index.yaml").is_file())


def add_item(
    campaign: Path,
    description: str,
    parent: str | None = None,
    blocked_by: list[str] | None = None,
) -> str:
    index = load_index(campaign)
    item_id = next_item_id(index, description)
    node = {"id": item_id, "status": "todo"}
    if blocked_by:
        node["blocked_by"] = list(blocked_by)
    if parent is not None:
        parent_node = find_node(index, parent)
        if parent_node is None:
            raise KeyError(f"parent item not found: {parent}")
        parent_node.setdefault("items", []).append(node)
    else:
        index.setdefault("items", []).append(node)
    save_index(campaign, index)
    save_item(campaign, {"id": item_id, "description": description})
    return item_id


# --- questions -------------------------------------------------------------

def append_question(campaign: Path, item_id: str, question: str) -> None:
    path = questions_path(campaign)
    entry = f"## [{item_id}] {' '.join(question.split())}\n\n"
    if path.is_file():
        existing = path.read_text(encoding="utf-8")
        if entry.splitlines()[0] in existing:
            return
        path.write_text(existing.rstrip("\n") + "\n\n" + entry, encoding="utf-8")
    else:
        path.write_text("# Open questions\n\n" + entry, encoding="utf-8")


def answered_questions(campaign: Path) -> dict[str, str]:
    """item_id -> answer text, for sections where the user wrote an answer
    below the question heading."""
    path = questions_path(campaign)
    if not path.is_file():
        return {}
    answers: dict[str, str] = {}
    current_id: str | None = None
    current_lines: list[str] = []

    def flush():
        if current_id is not None:
            body = "\n".join(current_lines).strip()
            if body:
                answers[current_id] = body

    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^## \[([^\]]+)\]", line)
        if match:
            flush()
            current_id = match.group(1)
            current_lines = []
        elif current_id is not None and not line.startswith("# "):
            current_lines.append(line)
    flush()
    return answers


# --- proposals -------------------------------------------------------------

def proposal_path(campaign: Path, item_id: str | None) -> Path:
    if item_id is None:
        return campaign / "proposal.yaml"
    return item_dir(campaign, item_id) / "proposal.yaml"


def load_proposal(path: Path) -> dict | None:
    if not path.is_file():
        return None
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else None


def pending_proposals(campaign: Path, index: dict) -> list[dict]:
    """Each entry: {parent: id|None, path: Path, items: [...], scope: {...}}."""
    pending: list[dict] = []
    candidates: list[tuple[str | None, Path]] = [(None, proposal_path(campaign, None))]
    for node, _depth, _siblings in walk_items(index.get("items", [])):
        candidates.append((node.get("id"), proposal_path(campaign, node["id"])))
    for parent, path in candidates:
        proposal = load_proposal(path)
        if not proposal:
            continue
        proposed_items = proposal.get("items") or []
        parent_depth = 0
        if parent is not None:
            for node, depth, _siblings in walk_items(index.get("items", [])):
                if node.get("id") == parent:
                    parent_depth = depth
                    break
        scope = {
            "items_added": sum(1 for _ in _walk_proposed(proposed_items)),
            "resulting_depth": parent_depth + _proposed_depth(proposed_items),
            "estimated_tokens": sum(
                (len(str(item.get("description", ""))) + 3) // 4 + 500
                for item, _d in _walk_proposed_with_depth(proposed_items)
            ),
        }
        pending.append({"parent": parent, "path": path, "items": proposed_items, "scope": scope})
    return pending


def _walk_proposed(items: list):
    for item in items:
        yield item
        yield from _walk_proposed(item.get("items") or [])


def _walk_proposed_with_depth(items: list, depth: int = 1):
    for item in items:
        yield item, depth
        yield from _walk_proposed_with_depth(item.get("items") or [], depth + 1)


def _proposed_depth(items: list) -> int:
    depth = 0
    for _item, item_depth in _walk_proposed_with_depth(items):
        depth = max(depth, item_depth)
    return depth


def within_review_thresholds(index: dict, proposal: dict) -> bool:
    review = index.get("review") or {}
    max_items = int(review.get("auto_confirm_max_items", DEFAULT_REVIEW["auto_confirm_max_items"]))
    max_depth = int(review.get("auto_confirm_max_depth", DEFAULT_REVIEW["auto_confirm_max_depth"]))
    scope = proposal["scope"]
    if proposal["parent"] is None:
        return False  # a new campaign's initial decomposition is always reviewed
    return scope["items_added"] <= max_items and scope["resulting_depth"] <= max_depth


def confirm_proposal(campaign: Path, index: dict, proposal: dict) -> list[str]:
    """Materialize a proposal into the tree. Driver-only. Returns new ids."""
    new_ids: list[str] = []

    def materialize(proposed: list, target_list: list):
        for entry in proposed:
            description = str(entry.get("description", "")).strip() or "item"
            item_id = next_item_id(index, description)
            node = {"id": item_id, "status": "todo"}
            if entry.get("blocked_by"):
                node["blocked_by"] = list(entry["blocked_by"])
            target_list.append(node)
            detail = {"id": item_id, "description": description}
            for key in ("completion", "references", "notes"):
                if entry.get(key):
                    detail[key] = entry[key]
            save_item(campaign, detail)
            new_ids.append(item_id)
            children = entry.get("items") or []
            if children:
                node["items"] = []
                materialize(children, node["items"])

    if proposal["parent"] is None:
        materialize(proposal["items"], index.setdefault("items", []))
    else:
        parent_node = find_node(index, proposal["parent"])
        if parent_node is None:
            raise KeyError(f"proposal parent not found: {proposal['parent']}")
        parent_node.setdefault("items", [])
        materialize(proposal["items"], parent_node["items"])
        parent_node["status"] = "in-progress"
    proposal["path"].unlink()
    save_index(campaign, index)
    return new_ids


# --- worker results --------------------------------------------------------

def parse_worker_result(text: str) -> dict:
    stripped = text.strip()
    fence = JSON_FENCE.search(stripped)
    if fence:
        stripped = fence.group(1).strip()
    payload = json.loads(stripped)
    if not isinstance(payload, dict):
        raise ValueError("worker result is not a JSON object")
    status = str(payload.get("status", "")).strip()
    if status not in ("done", "question", "failed"):
        raise ValueError(f"worker result has unsupported status: {status!r}")
    return {
        "status": status,
        "summary": str(payload.get("summary", "")).strip(),
        "questions": [str(q) for q in payload.get("questions") or [] if str(q).strip()],
        "proposal": payload.get("proposal"),
    }


def write_worker_result(campaign: Path, item_id: str, result: dict) -> Path:
    directory = item_dir(campaign, item_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "result.json"
    path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return path


# --- the driver: one update pass -------------------------------------------

@dataclass
class UpdateReport:
    campaign: str
    dry_run: bool = False
    merged: list[str] = field(default_factory=list)
    answered: list[str] = field(default_factory=list)
    checked: list[str] = field(default_factory=list)
    completed: list[str] = field(default_factory=list)
    auto_confirmed: list[str] = field(default_factory=list)
    pending_review: list[dict] = field(default_factory=list)
    dispatched: list[str] = field(default_factory=list)
    questions_open: int = 0
    failures: list[str] = field(default_factory=list)
    status_counts: dict = field(default_factory=dict)
    campaign_status: str = "active"

    def as_dict(self) -> dict:
        payload = dict(self.__dict__)
        payload["pending_review"] = [
            {"parent": p["parent"], "scope": p["scope"]} for p in self.pending_review
        ]
        return payload


def _append_note(campaign: Path, item_id: str, note: str) -> None:
    detail = load_item(campaign, item_id)
    existing = str(detail.get("notes") or "").rstrip()
    detail["notes"] = (existing + "\n" + note).strip()
    save_item(campaign, detail)


def _run_condition(campaign: Path, item_id: str | None, condition: dict, judge) -> tuple[bool, str]:
    if "test" in condition:
        script = Path(condition["test"])
        if not script.is_absolute():
            base = item_dir(campaign, item_id) if item_id else campaign
            script = (base / script).resolve()
        result = subprocess.run(
            [str(script)], capture_output=True, text=True, cwd=campaign
        )
        detail = (result.stdout + result.stderr).strip()[-500:]
        return result.returncode == 0, f"test {condition['test']}: exit {result.returncode} {detail}".strip()
    if "judge" in condition:
        if judge is None:
            return False, f"judge condition has no judge available: {condition['judge']}"
        verdict = judge(str(condition["judge"]), campaign, item_id)
        return bool(verdict.get("pass")), f"judge {condition['judge']}: {verdict.get('reason', '')}".strip()
    return False, f"unknown condition shape: {condition}"


def build_item_briefing(root: Path, campaign: Path, index: dict, item_id: str) -> str:
    template = ""
    template_path = resolve_prompt_path(root, ITEM_PROMPT_NAME)
    if template_path.is_file():
        template = template_path.read_text(encoding="utf-8").strip()
    detail = load_item(campaign, item_id)
    parts = [template] if template else []
    parts.append(f"Campaign: {index.get('name', campaign.name)}")
    if index.get("description"):
        parts.append(f"Campaign goal:\n{index['description']}")
    parts.append(f"Item: {item_id}")
    if detail.get("description"):
        parts.append(f"Item description:\n{detail['description']}")
    if detail.get("references"):
        parts.append("References:\n" + "\n".join(f"- {r}" for r in detail["references"]))
    if detail.get("completion"):
        parts.append("Completion conditions:\n" + _dump_yaml({"completion": detail["completion"]}).strip())
    if detail.get("notes"):
        parts.append(f"Notes (including answered questions):\n{detail['notes']}")
    return "\n\n".join(parts)


def _default_dispatch(root: Path, campaign: Path, item_id: str, briefing: str, llm_args: list[str]) -> dict:
    """Run an item worker as a delegated nagent conversation; returns the
    parsed worker result. Raises on parse failure."""
    nagent_path = Path(__file__).resolve().parent.parent / "nagent"
    conversation = item_dir(campaign, item_id) / "conversation"
    command = [
        str(nagent_path),
        "--root",
        str(root),
        "--conversation",
        str(conversation),
        "--campaign-item",
        str(item_dir(campaign, item_id)),
        "--invocation",
        "delegated",
        "--json",
        *llm_args,
        briefing,
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "worker failed")
    payload = json.loads(result.stdout)
    responses = payload.get("responses") or []
    return parse_worker_result(responses[-1] if responses else "")


def _decompose(root: Path, campaign: Path, index: dict, generate) -> dict | None:
    template_path = resolve_prompt_path(root, DECOMPOSE_PROMPT_NAME)
    template = template_path.read_text(encoding="utf-8").strip() if template_path.is_file() else (
        "Decompose this campaign goal into a small tree of concrete todo items. "
        'Return only JSON: {"items": [{"description": "...", "items": [...]}]}.'
    )
    prompt = f"{template}\n\nCampaign: {index.get('name')}\n\nGoal:\n{index.get('description', '')}\n"
    response = generate(prompt)
    stripped = response.strip()
    fence = JSON_FENCE.search(stripped)
    if fence:
        stripped = fence.group(1).strip()
    payload = json.loads(stripped)
    items = payload.get("items") if isinstance(payload, dict) else None
    if not items:
        return None
    return {"items": items}


def eligible_items(index: dict) -> list[str]:
    """Leaf items that are todo and unblocked, in tree order."""
    done_ids = {
        node["id"]
        for node, _d, _s in walk_items(index.get("items", []))
        if node.get("status") == "done"
    }
    eligible: list[str] = []
    for node, _depth, _siblings in walk_items(index.get("items", [])):
        if node.get("items"):
            continue
        if node.get("status") != "todo":
            continue
        blocked_by = node.get("blocked_by") or []
        if any(dep not in done_ids for dep in blocked_by):
            continue
        eligible.append(node["id"])
    return eligible


def run_update(
    root: Path,
    slug: str,
    *,
    dry_run: bool = False,
    max_dispatch: int | None = None,
    generate=None,
    judge=None,
    dispatch=None,
    llm_args: list[str] | None = None,
) -> UpdateReport:
    campaign = campaign_dir(root, slug)
    index = load_index(campaign)
    report = UpdateReport(campaign=slug, dry_run=dry_run)

    # Phase 1 — merge worker results (and route answered questions).
    for node, _depth, _siblings in walk_items(index.get("items", [])):
        result_file = item_dir(campaign, node["id"]) / "result.json"
        if not result_file.is_file():
            continue
        report.merged.append(node["id"])
        if dry_run:
            continue
        try:
            result = json.loads(result_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            node["status"] = "failed"
            append_question(campaign, node["id"], "worker result.json was unreadable; re-dispatch?")
            result_file.unlink()
            continue
        if result.get("summary"):
            detail = load_item(campaign, node["id"])
            detail["result"] = result["summary"]
            save_item(campaign, detail)
        for question in result.get("questions") or []:
            append_question(campaign, node["id"], question)
        if result.get("proposal") and (result["proposal"].get("items") if isinstance(result["proposal"], dict) else None):
            proposal_file = proposal_path(campaign, node["id"])
            proposal_file.parent.mkdir(parents=True, exist_ok=True)
            proposal_file.write_text(_dump_yaml({"items": result["proposal"]["items"]}), encoding="utf-8")
            node["status"] = "proposed"
        elif result.get("status") == "done":
            detail = load_item(campaign, node["id"])
            node["status"] = "review" if detail.get("completion") else "done"
        elif result.get("status") == "question":
            node["status"] = "question"
        else:
            node["status"] = "failed"
            append_question(campaign, node["id"], f"worker failed: {result.get('summary', 'no detail')}")
        result_file.unlink()

    answers = answered_questions(campaign)
    for node, _depth, _siblings in walk_items(index.get("items", [])):
        if node.get("status") in ("question", "failed") and node["id"] in answers:
            report.answered.append(node["id"])
            if not dry_run:
                _append_note(campaign, node["id"], f"Answer: {answers[node['id']]}")
                node["status"] = "todo"

    # Parent propagation: a container is done when all its children are.
    if not dry_run:
        changed = True
        while changed:
            changed = False
            for node, _depth, _siblings in walk_items(index.get("items", [])):
                children = node.get("items") or []
                if children and node.get("status") != "done":
                    if all(child.get("status") == "done" for child, _d, _s in walk_items(children)):
                        node["status"] = "done"
                        changed = True

    # Phase 2 — check completion conditions for items claiming done.
    for node, _depth, _siblings in walk_items(index.get("items", [])):
        if node.get("status") != "review":
            continue
        report.checked.append(node["id"])
        if dry_run:
            continue
        detail = load_item(campaign, node["id"])
        verdicts = [
            _run_condition(campaign, node["id"], condition, judge)
            for condition in detail.get("completion") or []
        ]
        if all(passed for passed, _note in verdicts):
            node["status"] = "done"
            report.completed.append(node["id"])
        else:
            node["status"] = "todo"
            for passed, note in verdicts:
                if not passed:
                    _append_note(campaign, node["id"], f"Condition failed: {note}")

    # Phase 3 — propose: initial decomposition for an empty campaign.
    if (
        not index.get("items")
        and index.get("description")
        and load_proposal(proposal_path(campaign, None)) is None
        and generate is not None
    ):
        if not dry_run:
            try:
                proposal = _decompose(root, campaign, index, generate)
            except (json.JSONDecodeError, ValueError, RuntimeError) as exc:
                report.failures.append(f"decomposition failed: {exc}")
                proposal = None
            if proposal:
                proposal_path(campaign, None).write_text(_dump_yaml(proposal), encoding="utf-8")

    # Phase 4 — review gate.
    for proposal in pending_proposals(campaign, index):
        if not dry_run and within_review_thresholds(index, proposal):
            confirm_proposal(campaign, index, proposal)
            report.auto_confirmed.append(proposal["parent"] or "(campaign)")
        else:
            report.pending_review.append(proposal)

    # Phase 5 — dispatch unblocked todo leaves.
    limit = max_dispatch
    if limit is None:
        limit = int((index.get("dispatch") or {}).get("max_per_update", DEFAULT_DISPATCH["max_per_update"]))
    for item_id in eligible_items(index)[: max(0, limit)]:
        report.dispatched.append(item_id)
        if dry_run:
            continue
        node = find_node(index, item_id)
        node["status"] = "in-progress"
        save_index(campaign, index)  # persist before the worker runs
        briefing = build_item_briefing(root, campaign, index, item_id)
        try:
            if dispatch is not None:
                result = dispatch(item_id, briefing)
            else:
                result = _default_dispatch(root, campaign, item_id, briefing, llm_args or [])
        except Exception as exc:  # worker failures are data, not crashes
            write_worker_result(
                campaign,
                item_id,
                {"status": "failed", "summary": str(exc), "questions": [], "proposal": None},
            )
            report.failures.append(f"{item_id}: {exc}")
            continue
        write_worker_result(campaign, item_id, result)

    # Campaign-level completion: all top items done and conditions pass.
    if not dry_run and index.get("items"):
        all_done = all(
            node.get("status") == "done" for node, _d, _s in walk_items(index["items"])
        )
        if all_done and index.get("status") == "active":
            verdicts = [
                _run_condition(campaign, None, condition, judge)
                for condition in index.get("completion") or []
            ]
            if all(passed for passed, _note in verdicts):
                index["status"] = "done"

    if not dry_run:
        save_index(campaign, index)

    final_index = load_index(campaign) if not dry_run else index
    report.status_counts = status_counts(final_index)
    report.campaign_status = final_index.get("status", "active")
    report.questions_open = sum(
        1
        for node, _d, _s in walk_items(final_index.get("items", []))
        if node.get("status") == "question"
    )
    return report


# --- ambient status for initial context ------------------------------------

def campaign_status_lines(root: Path) -> list[str]:
    lines: list[str] = []
    for campaign in list_campaigns(root):
        try:
            index = load_index(campaign)
        except (OSError, ValueError, yaml.YAMLError):
            continue
        if index.get("status") == "done":
            continue
        counts = status_counts(index)
        pending = len(pending_proposals(campaign, index))
        summary = ", ".join(
            f"{counts[s]} {s}" for s in ("todo", "in-progress", "review", "question", "done") if counts.get(s)
        ) or "no items yet"
        extras = []
        if counts.get("question"):
            extras.append(f"{counts['question']} open question(s)")
        if pending:
            extras.append(f"{pending} pending proposal(s)")
        suffix = f"; {'; '.join(extras)}" if extras else ""
        lines.append(f"- {campaign.name}: {summary}{suffix}")
    return lines
