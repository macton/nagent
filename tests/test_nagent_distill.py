#!/usr/bin/python3

import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
import uuid
from pathlib import Path

BIN = Path(__file__).resolve().parent.parent / "bin"
HELPERS = BIN / "helpers"
NAGENT = BIN / "nagent"
NAGENT_DISTILL = BIN / "nagent-distill"

sys.path.insert(0, str(HELPERS))
import nagent_distill_lib as gc
from nagent_file_edit_lib import file_id_for_path


def load_nagent_module():
    from importlib.machinery import SourceFileLoader

    loader = SourceFileLoader("nagent_mod_gc_tests", str(NAGENT))
    spec = importlib.util.spec_from_loader("nagent_mod_gc_tests", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def make_root(tmp: str) -> Path:
    root = Path(tmp) / "nagent-root"
    (root / "conversations").mkdir(parents=True)
    return root


def harvest_payload(file_path: str | None = None) -> str:
    return json.dumps(
        {
            "facts": [{"statement": "Service X needs the VPN", "detail": "deploy fails silently without it"}],
            "decisions": [{"statement": "Chose sqlite over postgres", "detail": "single writer"}],
            "tasks_done": [{"statement": "Fixed the parser retry bug"}],
            "tasks_open": [{"statement": "Migrate the config format"}],
            "questions": [{"statement": "Why does CI flake on arm64?"}],
            "playbooks": [{"name": "redeploy", "steps": "make build && make push"}],
            "files": [{"path": file_path or "/nonexistent/gone.py", "note": "uses tabs, not spaces"}],
        }
    )


def classes_by_path(artifacts) -> dict[str, str]:
    return {str(a.path): a.klass for a in artifacts}


class ScanClassificationTests(unittest.TestCase):
    def test_classifies_conversations_and_splits(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp)
            conversations = root / "conversations"

            live = conversations / "latest-host-1"
            live.write_text("live", encoding="utf-8")
            archive = conversations / f"latest-host-1-{uuid.uuid4()}"
            archive.write_text("archived", encoding="utf-8")
            delegated = conversations / f"{uuid.uuid4()}-1234"
            delegated.write_text("delegated", encoding="utf-8")
            unclassified = conversations / "notes"
            unclassified.write_text("user file", encoding="utf-8")

            saved = conversations / "before-refactor"
            saved.write_text("saved", encoding="utf-8")
            (conversations / "index-saved-conversations-1.json").write_text(
                json.dumps({"conversations": [{"name": "before-refactor", "path": str(saved.resolve())}]}),
                encoding="utf-8",
            )

            target = Path(tmp) / "project.py"
            target.write_text("code", encoding="utf-8")
            per_file_live = conversations / f"project-{uuid.uuid4()}"
            per_file_live.write_text("per-file live", encoding="utf-8")
            per_file_dead = conversations / f"gone-{uuid.uuid4()}"
            per_file_dead.write_text("per-file dead", encoding="utf-8")
            (conversations / "file-index-1.json").write_text(
                json.dumps(
                    {
                        "by_file_id": {
                            "1:1": {"file_id": "1:1", "path": str(target), "conversation": per_file_live.name},
                            "1:2": {"file_id": "1:2", "path": str(Path(tmp) / "deleted.py"), "conversation": per_file_dead.name},
                        }
                    }
                ),
                encoding="utf-8",
            )

            splits = root / "splits"
            source = Path(tmp) / "big.txt"
            source.write_text("content", encoding="utf-8")
            current_split = splits / "big-current"
            current_split.mkdir(parents=True)
            (current_split / "index.json").write_text(
                json.dumps({"source_path": str(source), "source_sha256": gc.source_sha256(source)}),
                encoding="utf-8",
            )
            stale_split = splits / "big-stale"
            stale_split.mkdir()
            (stale_split / "index.json").write_text(
                json.dumps({"source_path": str(source), "source_sha256": "0" * 64}),
                encoding="utf-8",
            )
            orphan_split = splits / "big-orphan"
            orphan_split.mkdir()
            (orphan_split / "index.json").write_text(
                json.dumps({"source_path": str(Path(tmp) / "missing.txt"), "source_sha256": "0" * 64}),
                encoding="utf-8",
            )
            broken_split = splits / "big-broken"
            broken_split.mkdir()

            classes = classes_by_path(gc.scan_root(root))

            self.assertEqual(classes[str(live)], "live")
            self.assertEqual(classes[str(archive)], "harvest")
            self.assertEqual(classes[str(delegated)], "harvest")
            self.assertEqual(classes[str(unclassified)], "keep")
            self.assertEqual(classes[str(saved)], "user-kept")
            self.assertEqual(classes[str(per_file_live)], "live")
            self.assertEqual(classes[str(per_file_dead)], "harvest")
            self.assertEqual(classes[str(current_split)], "live")
            self.assertEqual(classes[str(stale_split)], "prune")
            self.assertEqual(classes[str(orphan_split)], "prune")
            self.assertEqual(classes[str(broken_split)], "keep")

    def test_dry_run_mutates_nothing_and_estimates_cost(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp)
            archive = root / "conversations" / f"latest-host-1-{uuid.uuid4()}"
            archive.write_text("x" * 400, encoding="utf-8")

            report = gc.run_gc(root, apply=False)

            self.assertTrue(archive.is_file())
            self.assertFalse(gc.knowledge_dir(root).exists())
            self.assertEqual(report["totals"].get("harvest"), 1)
            self.assertEqual(report["harvest_candidate_bytes"], 400)
            self.assertEqual(report["estimated_harvest_input_tokens"], 100)
            self.assertNotIn("reclaimed_bytes", report)


class ApplyTests(unittest.TestCase):
    def test_apply_harvests_merges_and_deletes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp)
            target = Path(tmp) / "noted.py"
            target.write_text("code", encoding="utf-8")
            archive = root / "conversations" / f"latest-host-1-{uuid.uuid4()}"
            archive.write_text("conversation text", encoding="utf-8")
            calls: list[str] = []

            def fake_generate(prompt, provider, model):
                calls.append(prompt)
                return harvest_payload(str(target))

            report = gc.run_gc(
                root, apply=True, provider="openai", model="gpt-5.5", generate=fake_generate
            )

            self.assertEqual(len(calls), 1)
            self.assertIn("conversation text", calls[0])
            self.assertFalse(archive.exists())
            self.assertEqual(report["reclaimed_bytes"], len("conversation text"))

            knowledge = gc.knowledge_dir(root)
            facts = (knowledge / "facts.md").read_text(encoding="utf-8")
            self.assertIn("Service X needs the VPN — deploy fails silently without it", facts)
            self.assertIn(f"[from: {archive.name},", facts)
            self.assertIn("Chose sqlite over postgres", (knowledge / "decisions.md").read_text(encoding="utf-8"))
            self.assertIn("Why does CI flake on arm64?", (knowledge / "questions.md").read_text(encoding="utf-8"))
            self.assertIn("**redeploy**: make build && make push", (knowledge / "playbooks.md").read_text(encoding="utf-8"))

            tasks = (knowledge / "tasks.md").read_text(encoding="utf-8")
            self.assertLess(tasks.index("Migrate the config format"), tasks.index("## Done"))
            self.assertLess(tasks.index("## Done"), tasks.index("Fixed the parser retry bug"))

            file_id = file_id_for_path(target)
            file_notes = gc.file_knowledge_path(root, file_id).read_text(encoding="utf-8")
            self.assertIn("uses tabs, not spaces", file_notes)

            ledger = gc.load_ledger(root)
            entry = next(iter(ledger["entries"].values()))
            self.assertEqual(entry["status"], "harvested")
            self.assertTrue(entry["deleted"])

            digest = gc.digest_path(root).read_text(encoding="utf-8")
            self.assertIn("Migrate the config format", digest)
            self.assertLess(digest.index("Open tasks"), digest.index("Facts"))

    def test_file_note_for_missing_target_lands_in_facts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp)
            archive = root / "conversations" / f"latest-host-1-{uuid.uuid4()}"
            archive.write_text("conversation", encoding="utf-8")

            report = gc.run_gc(
                root,
                apply=True,
                provider="openai",
                model="gpt-5.5",
                generate=lambda prompt, provider, model: harvest_payload("/nonexistent/gone.py"),
            )

            facts = (gc.knowledge_dir(root) / "facts.md").read_text(encoding="utf-8")
            self.assertIn("/nonexistent/gone.py: uses tabs, not spaces", facts)
            self.assertEqual(report["harvested_items"]["files"], 1)

    def test_invalid_harvest_json_keeps_artifact_and_records_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp)
            archive = root / "conversations" / f"latest-host-1-{uuid.uuid4()}"
            archive.write_text("conversation", encoding="utf-8")
            calls: list[str] = []

            def bad_generate(prompt, provider, model):
                calls.append(prompt)
                return "this is not json"

            report = gc.run_gc(
                root, apply=True, provider="openai", model="gpt-5.5", generate=bad_generate
            )

            self.assertEqual(len(calls), gc.HARVEST_MAX_ATTEMPTS)
            self.assertIn("not valid JSON", calls[-1])
            self.assertTrue(archive.is_file())
            self.assertEqual(len(report["failures"]), 1)
            entry = next(iter(gc.load_ledger(root)["entries"].values()))
            self.assertEqual(entry["status"], "harvest-failed")
            self.assertFalse(entry["deleted"])

    def test_no_harvest_deletes_without_llm(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp)
            archive = root / "conversations" / f"latest-host-1-{uuid.uuid4()}"
            archive.write_text("conversation", encoding="utf-8")

            report = gc.run_gc(root, apply=True, harvest=False)

            self.assertFalse(archive.exists())
            self.assertEqual(report["reclaimed_bytes"], len("conversation"))
            entry = next(iter(gc.load_ledger(root)["entries"].values()))
            self.assertEqual(entry["status"], "deleted-unharvested")

    def test_oversized_conversation_is_kept_as_too_large(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp)
            archive = root / "conversations" / f"latest-host-1-{uuid.uuid4()}"
            archive.write_text("x" * (gc.MAX_HARVEST_SOURCE_BYTES + 1), encoding="utf-8")

            def unexpected_generate(prompt, provider, model):
                raise AssertionError("LLM must not be called for too-large artifacts")

            gc.run_gc(root, apply=True, provider="openai", model="gpt-5.5", generate=unexpected_generate)

            self.assertTrue(archive.is_file())
            entry = next(iter(gc.load_ledger(root)["entries"].values()))
            self.assertEqual(entry["status"], "too-large")

    def test_large_conversation_harvests_from_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp)
            archive = root / "conversations" / f"latest-host-1-{uuid.uuid4()}"
            archive.write_text("y" * (gc.SUMMARIZE_THRESHOLD_BYTES + 1), encoding="utf-8")
            seen: dict[str, str] = {}

            def fake_summarize(path, provider, model, config_path):
                seen["summarized"] = str(path)
                return "summary of a large conversation"

            def fake_generate(prompt, provider, model):
                seen["prompt"] = prompt
                return harvest_payload()

            gc.run_gc(
                root,
                apply=True,
                provider="openai",
                model="gpt-5.5",
                generate=fake_generate,
                summarize=fake_summarize,
            )

            self.assertEqual(seen["summarized"], str(archive))
            self.assertIn("summary of a large conversation", seen["prompt"])
            self.assertFalse(archive.exists())

    def test_max_harvest_bytes_defers_excess(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp)
            first = root / "conversations" / f"latest-host-1-{uuid.uuid4()}"
            first.write_text("a" * 100, encoding="utf-8")
            second = root / "conversations" / f"latest-host-1-{uuid.uuid4()}"
            second.write_text("b" * 100, encoding="utf-8")

            report = gc.run_gc(
                root,
                apply=True,
                max_harvest_bytes=150,
                provider="openai",
                model="gpt-5.5",
                generate=lambda prompt, provider, model: harvest_payload(),
            )

            self.assertEqual(report["deferred"], 1)
            remaining = [first.exists(), second.exists()]
            self.assertEqual(sorted(remaining), [False, True])

    def test_rerun_with_same_content_skips_llm_via_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp)
            content = "identical conversation content"
            archive = root / "conversations" / f"latest-host-1-{uuid.uuid4()}"
            archive.write_text(content, encoding="utf-8")
            calls: list[str] = []

            def counting_generate(prompt, provider, model):
                calls.append(prompt)
                return harvest_payload()

            gc.run_gc(root, apply=True, provider="openai", model="gpt-5.5", generate=counting_generate)
            self.assertEqual(len(calls), 1)

            # Same content reappears (e.g. another archive of the same state).
            again = root / "conversations" / f"latest-host-1-{uuid.uuid4()}"
            again.write_text(content, encoding="utf-8")
            gc.run_gc(root, apply=True, provider="openai", model="gpt-5.5", generate=counting_generate)

            self.assertEqual(len(calls), 1)
            self.assertFalse(again.exists())

    def test_apply_reports_progress_and_uses_spinner(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp)
            good = root / "conversations" / f"latest-host-1-{uuid.uuid4()}"
            good.write_text("conversation a", encoding="utf-8")
            bad = root / "conversations" / f"latest-host-1-{uuid.uuid4()}"
            bad.write_text("conversation b", encoding="utf-8")

            responses = {str(good): harvest_payload(), str(bad): "not json"}

            def routing_generate(prompt, provider, model):
                for path_text, response in responses.items():
                    if Path(path_text).name in prompt:
                        return response
                return "not json"

            spinner_messages: list[str] = []
            progress_messages: list[str] = []

            class FakeSpinner:
                def __init__(self, message):
                    spinner_messages.append(message)

                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return None

            gc.run_gc(
                root,
                apply=True,
                provider="openai",
                model="gpt-5.5",
                generate=routing_generate,
                spinner=FakeSpinner,
                progress=progress_messages.append,
            )

            self.assertEqual(len(spinner_messages), 2)
            self.assertTrue(all(m.startswith("Harvesting ") for m in spinner_messages))
            self.assertTrue(any(m.startswith("harvested: ") for m in progress_messages))
            self.assertTrue(any(m.startswith("harvest failed: ") for m in progress_messages))
            # Labels carry position-in-run context.
            self.assertTrue(any("(1/2)" in m for m in spinner_messages))
            self.assertTrue(any("(2/2)" in m for m in spinner_messages))

    def test_prunes_stale_splits_and_dead_index_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp)
            conversations = root / "conversations"

            splits = root / "splits"
            stale_split = splits / "big-stale"
            stale_split.mkdir(parents=True)
            (stale_split / "index.json").write_text(
                json.dumps({"source_path": str(Path(tmp) / "missing.txt"), "source_sha256": "0" * 64}),
                encoding="utf-8",
            )
            (stale_split / "big-0001.txt").write_text("segment", encoding="utf-8")

            (conversations / "file-index-1.json").write_text(
                json.dumps(
                    {"by_file_id": {"1:2": {"file_id": "1:2", "path": str(Path(tmp) / "deleted.py"), "conversation": "dead-conv"}}}
                ),
                encoding="utf-8",
            )
            (conversations / "index-saved-conversations-1.json").write_text(
                json.dumps({"conversations": [{"name": "gone", "path": str(Path(tmp) / "gone-saved")}]}),
                encoding="utf-8",
            )

            report = gc.run_gc(root, apply=True, harvest=False)

            self.assertFalse(stale_split.exists())
            file_index = json.loads((conversations / "file-index-1.json").read_text(encoding="utf-8"))
            self.assertEqual(file_index["by_file_id"], {})
            saved_index = json.loads(
                (conversations / "index-saved-conversations-1.json").read_text(encoding="utf-8")
            )
            self.assertEqual(saved_index["conversations"], [])
            self.assertEqual(report["pruned_index_entries"], 2)


class DigestTests(unittest.TestCase):
    def test_digest_orders_sections_and_newest_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp)
            gc.merge_harvest(root, "conv-a", {"facts": ["older fact"], "tasks_open": ["older task"]}, "2026-01-01")
            gc.merge_harvest(root, "conv-b", {"facts": ["newer fact"], "tasks_open": ["newer task"]}, "2026-02-01")

            digest = gc.regenerate_digest(root).read_text(encoding="utf-8")

            self.assertLess(digest.index("Open tasks"), digest.index("Facts"))
            self.assertLess(digest.index("newer task"), digest.index("older task"))
            self.assertLess(digest.index("newer fact"), digest.index("older fact"))

    def test_digest_respects_byte_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp)
            harvested = {"facts": [f"fact number {i} with some padding text" for i in range(100)]}
            gc.merge_harvest(root, "conv", harvested, "2026-01-01")

            digest_file = gc.regenerate_digest(root, max_bytes=1024)
            content = digest_file.read_text(encoding="utf-8")

            self.assertLessEqual(len(content.encode("utf-8")), 1024 + 128)
            self.assertIn("(truncated; see the category files for the rest)", content)

    def test_user_edits_propagate_and_empty_store_removes_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp)
            gc.merge_harvest(root, "conv", {"facts": ["keep me", "drop me"]}, "2026-01-01")
            gc.regenerate_digest(root)

            facts_file = gc.knowledge_dir(root) / "facts.md"
            lines = [
                line for line in facts_file.read_text(encoding="utf-8").splitlines() if "drop me" not in line
            ]
            facts_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

            digest = gc.regenerate_digest(root).read_text(encoding="utf-8")
            self.assertIn("keep me", digest)
            self.assertNotIn("drop me", digest)

            facts_file.unlink()
            self.assertIsNone(gc.regenerate_digest(root))
            self.assertFalse(gc.digest_path(root).exists())

    def test_knowledge_item_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp)
            gc.merge_harvest(
                root,
                "conv",
                {"facts": ["a", "b"], "tasks_open": ["t"], "tasks_done": ["d"], "questions": ["q"]},
                "2026-01-01",
            )
            counts = gc.knowledge_item_counts(root)
            self.assertEqual(counts["facts"], 2)
            self.assertEqual(counts["tasks_open"], 1)
            self.assertEqual(counts["tasks_done"], 1)
            self.assertEqual(counts["questions"], 1)
            self.assertEqual(counts["playbooks"], 0)


class ContextInjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_nagent_module()

    def test_initial_context_includes_knowledge_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp)
            digest = gc.digest_path(root)
            digest.parent.mkdir(parents=True)
            digest.write_text("# Knowledge digest\n- remember the VPN\n", encoding="utf-8")

            text = self.mod.build_initial_context(root, NAGENT.resolve(), "user", "conv")

            self.assertIn("{knowledge}", text)
            self.assertIn("remember the VPN", text)
            self.assertIn("{/knowledge}", text)

    def test_initial_context_omits_block_without_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp)
            text = self.mod.build_initial_context(root, NAGENT.resolve(), "user", "conv")
            self.assertNotIn("{knowledge}", text)

    def test_file_edit_context_includes_per_file_knowledge(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp)
            target = Path(tmp) / "edited.py"
            target.write_text("code", encoding="utf-8")
            file_id = file_id_for_path(target)
            note_path = gc.file_knowledge_path(root, file_id)
            note_path.parent.mkdir(parents=True)
            note_path.write_text(f"# {target}\n- uses tabs [from: conv, 2026-01-01]\n", encoding="utf-8")

            text = self.mod.build_initial_context(
                root,
                NAGENT.resolve(),
                "user",
                "conv",
                file_edit_path=target,
                file_edit_id=file_id,
            )

            self.assertIn("{file-knowledge}", text)
            self.assertIn("uses tabs", text)

    def test_status_reports_knowledge_items_and_root_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp)
            gc.merge_harvest(root, "conv", {"facts": ["a fact"]}, "2026-01-01")
            conversation = root / "conversations" / "conv"
            conversation.write_text("hello", encoding="utf-8")

            stdout = io.StringIO()
            with unittest.mock.patch.object(sys, "stdout", stdout):
                self.mod.print_conversation_status(conversation, "openai", "gpt-5.5", root)

            lines = stdout.getvalue().strip().splitlines()
            self.assertTrue(lines[2].startswith("knowledge_items:1 root_size_bytes:"))

            stdout = io.StringIO()
            with unittest.mock.patch.object(sys, "stdout", stdout):
                self.mod.print_conversation_status(conversation, "openai", "gpt-5.5", root, json_mode=True)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["knowledge_items"]["facts"], 1)
            self.assertGreater(payload["root_size_bytes"], 0)


class GcCliTests(unittest.TestCase):
    def test_description_flag(self):
        result = subprocess.run([str(NAGENT_DISTILL), "--description"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn("Reclaim dead nagent artifacts", result.stdout)

    def test_dry_run_lists_candidates_and_mutates_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp)
            archive = root / "conversations" / f"latest-host-1-{uuid.uuid4()}"
            archive.write_text("archived conversation", encoding="utf-8")

            result = subprocess.run(
                [str(NAGENT_DISTILL), "--root", str(root)],
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(str(archive), result.stdout)
            self.assertIn("dry run; pass --apply", result.stdout)
            self.assertTrue(archive.is_file())

    def test_dry_run_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp)
            archive = root / "conversations" / f"latest-host-1-{uuid.uuid4()}"
            archive.write_text("archived conversation", encoding="utf-8")

            result = subprocess.run(
                [str(NAGENT_DISTILL), "--root", str(root), "--json"],
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["totals"]["harvest"], 1)
            self.assertFalse(payload["apply"])

    def test_apply_no_harvest_reclaims_without_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp)
            archive = root / "conversations" / f"latest-host-1-{uuid.uuid4()}"
            archive.write_text("archived conversation", encoding="utf-8")

            result = subprocess.run(
                [str(NAGENT_DISTILL), "--root", str(root), "--apply", "--no-harvest"],
                capture_output=True,
                text=True,
                env={"PATH": "/usr/bin:/bin"},
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(archive.exists())
            self.assertIn("reclaimed:", result.stdout)
            self.assertIn("reclaimed (no harvest):", result.stderr)
            self.assertTrue(gc.ledger_path(root).is_file())

    def test_missing_root_errors(self):
        result = subprocess.run(
            [str(NAGENT_DISTILL), "--root", "/nonexistent/nagent-root"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("root not found", result.stderr)


class SummaryBackfillTests(unittest.TestCase):
    def _seed_index(self, root, summary_source="extracted", summary="the original ask"):
        conversations = root / "conversations"
        conversations.mkdir(parents=True, exist_ok=True)
        saved = conversations / "saved-copy"
        saved.write_text("<user-prompt>\nthe ask\n</user-prompt>\nlots of work\n", encoding="utf-8")
        index = conversations / "index-saved-conversations-1.json"
        entry = {"name": "saved-copy", "path": str(saved.resolve()), "summary": summary}
        if summary_source is not None:
            entry["summary_source"] = summary_source
        index.write_text(json.dumps({"conversations": [entry]}), encoding="utf-8")
        return index

    def test_apply_backfills_extracted_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index = self._seed_index(root)
            captured = {}

            def fake_generate(prompt, *args):
                captured["prompt"] = prompt
                return "what was asked and what was produced"

            report = gc.run_gc(
                root, apply=True, provider="openai", model="m", generate=fake_generate
            )

            self.assertEqual(report["summaries_backfilled"], ["saved-copy"])
            self.assertIn("the ask", captured["prompt"])
            entry = json.loads(index.read_text(encoding="utf-8"))["conversations"][0]
            self.assertEqual(entry["summary"], "what was asked and what was produced")
            self.assertEqual(entry["summary_source"], "llm")

    def test_llm_summaries_are_not_redone(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index = self._seed_index(root, summary_source="llm", summary="already good")

            def must_not_run(prompt, *args):
                raise AssertionError("llm summaries must not be regenerated")

            report = gc.run_gc(
                root, apply=True, provider="openai", model="m", generate=must_not_run
            )

            self.assertEqual(report["summaries_backfilled"], [])
            entry = json.loads(index.read_text(encoding="utf-8"))["conversations"][0]
            self.assertEqual(entry["summary"], "already good")

    def test_dry_run_reports_candidates_and_no_harvest_skips(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index = self._seed_index(root)

            report = gc.run_gc(root, apply=False)
            self.assertEqual(report["summary_backfill_candidates"], 1)

            report = gc.run_gc(root, apply=True, harvest=False)
            self.assertEqual(report["summaries_backfilled"], [])
            entry = json.loads(index.read_text(encoding="utf-8"))["conversations"][0]
            self.assertEqual(entry["summary"], "the original ask")


class MergePassTests(unittest.TestCase):
    def _seed_duplicates(self, root):
        gc.merge_harvest(
            root,
            "conv-a",
            {"facts": ["the loader caches results", "the loader caches results"]},
            "2026-01-01",
        )
        gc.merge_harvest(root, "conv-b", {"facts": ["the loader caches results"]}, "2026-02-01")

    def test_merge_rewrites_file_with_backup_and_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed_duplicates(root)
            facts = gc.knowledge_dir(root) / "facts.md"
            original = facts.read_text(encoding="utf-8")
            captured = {}

            def fake_generate(prompt):
                captured["prompt"] = prompt
                return (
                    "# Facts\n\n- the loader caches results "
                    "[from: conv-a, 2026-01-01] [from: conv-b, 2026-02-01]"
                )

            report = gc.run_merge(root, apply=True, generate=fake_generate)

            self.assertIn("facts.md", report["merged"])
            self.assertIn(original.strip(), captured["prompt"])
            merged = facts.read_text(encoding="utf-8")
            self.assertEqual(merged.count("the loader caches results"), 1)
            self.assertIn("[from: conv-a, 2026-01-01]", merged)
            backup = facts.with_name("facts.md.pre-merge")
            self.assertEqual(backup.read_text(encoding="utf-8"), original)
            digest = gc.digest_path(root).read_text(encoding="utf-8")
            self.assertEqual(digest.count("the loader caches results"), 1)

    def test_merge_rejects_empty_result_and_keeps_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed_duplicates(root)
            facts = gc.knowledge_dir(root) / "facts.md"
            original = facts.read_text(encoding="utf-8")

            report = gc.run_merge(root, apply=True, generate=lambda prompt: "")

            self.assertTrue(report["failures"])
            self.assertEqual(facts.read_text(encoding="utf-8"), original)

    def test_merge_dry_run_reports_candidates_and_mutates_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed_duplicates(root)
            facts = gc.knowledge_dir(root) / "facts.md"
            original = facts.read_text(encoding="utf-8")

            report = gc.run_merge(root, apply=False, generate=None)

            self.assertFalse(report["apply"])
            names = [Path(c["path"]).name for c in report["candidates"]]
            self.assertIn("facts.md", names)
            self.assertGreater(report["candidates"][0]["estimated_input_tokens"], 0)
            self.assertEqual(facts.read_text(encoding="utf-8"), original)
            self.assertEqual(report["merged"], [])


class GraduatePassTests(unittest.TestCase):
    def _seed_playbooks(self, root):
        gc.merge_harvest(
            root,
            "conv",
            {"playbooks": [{"name": "redeploy", "steps": "make build && make push"}]},
            "2026-01-01",
        )

    def _seed_finished_campaign(self, root, with_tool=True):
        campaign = root / "campaigns" / "done-campaign"
        (campaign / "bin").mkdir(parents=True)
        (campaign / "items" / "0001-x").mkdir(parents=True)
        (campaign / "index.yaml").write_text(
            "name: Done Campaign\nstatus: done\nitems:\n- id: 0001-x\n  status: done\n",
            encoding="utf-8",
        )
        if with_tool:
            (campaign / "bin" / "proven-tool").write_text(
                "#!/bin/sh\necho proven\n", encoding="utf-8"
            )
        (campaign / "items" / "0001-x" / "conversation").write_text(
            "worker history", encoding="utf-8"
        )
        return campaign

    def test_graduate_drafts_tool_and_prompt_non_executable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed_playbooks(root)

            def fake_generate(prompt):
                self.assertIn("redeploy", prompt)
                return json.dumps(
                    {
                        "drafts": [
                            {
                                "kind": "tool",
                                "name": "redeploy",
                                "description": "rebuild and push",
                                "content": "#!/bin/sh\nmake build && make push\n",
                            },
                            {
                                "kind": "prompt",
                                "name": "deploy-guidance",
                                "description": "how deploys work",
                                "content": "# Deploys\nAlways build first.\n",
                            },
                        ]
                    }
                )

            report = gc.run_graduate(root, apply=True, generate=fake_generate)

            tool_draft = root / "bin" / "redeploy.draft"
            prompt_draft = root / "prompts" / "deploy-guidance.md.draft"
            self.assertTrue(tool_draft.is_file())
            self.assertTrue(prompt_draft.is_file())
            # Drafts are not executable: invisible to tool discovery.
            self.assertFalse(tool_draft.stat().st_mode & 0o111)
            self.assertEqual(len(report["drafts"]), 2)

            # Re-running skips existing drafts.
            report = gc.run_graduate(root, apply=True, generate=fake_generate)
            self.assertEqual(report["drafts"], [])
            self.assertEqual(len(report["skipped_existing"]), 2)

    def test_graduate_stages_finished_campaign_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed_finished_campaign(root)

            report = gc.run_graduate(root, apply=True, generate=None)

            staged = root / "bin" / "proven-tool.draft"
            self.assertTrue(staged.is_file())
            self.assertIn("echo proven", staged.read_text(encoding="utf-8"))
            self.assertEqual(report["campaign_candidates"][0]["campaign"], "done-campaign")

    def test_graduate_dry_run_lists_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed_playbooks(root)
            self._seed_finished_campaign(root)

            report = gc.run_graduate(root, apply=False, generate=None)

            self.assertFalse(report["apply"])
            self.assertEqual(report["playbook_bullets"], 1)
            self.assertEqual(len(report["campaign_candidates"]), 1)
            self.assertEqual(report["drafts"], [])
            self.assertFalse((root / "bin").exists())

    def test_scan_root_harvests_finished_campaign_conversations(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "conversations").mkdir(parents=True)
            campaign = self._seed_finished_campaign(root, with_tool=False)
            active = root / "campaigns" / "active-campaign"
            (active / "items" / "0001-y").mkdir(parents=True)
            (active / "index.yaml").write_text(
                "name: Active\nstatus: active\nitems:\n- id: 0001-y\n  status: todo\n",
                encoding="utf-8",
            )
            (active / "items" / "0001-y" / "conversation").write_text("live", encoding="utf-8")

            artifacts = gc.scan_root(root)
            classes = {str(a.path): (a.klass, a.reason) for a in artifacts}

            done_conv = str(campaign / "items" / "0001-x" / "conversation")
            self.assertIn(done_conv, classes)
            self.assertEqual(classes[done_conv][0], "harvest")
            self.assertIn("finished campaign", classes[done_conv][1])
            active_conv = str(active / "items" / "0001-y" / "conversation")
            self.assertNotIn(active_conv, classes)

    def test_cli_merge_and_graduate_dry_runs_need_no_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed_playbooks(root)

            result = subprocess.run(
                [str(NAGENT_DISTILL), "--root", str(root), "--merge", "--graduate"],
                capture_output=True,
                text=True,
                env={"PATH": "/usr/bin:/bin"},
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("merge candidate:", result.stdout)
            self.assertIn("graduate candidates:", result.stdout)
            self.assertIn("dry run; pass --apply", result.stdout)


if __name__ == "__main__":
    unittest.main()
