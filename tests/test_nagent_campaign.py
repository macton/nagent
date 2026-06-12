#!/usr/bin/python3

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

BIN = Path(__file__).resolve().parent.parent / "bin"
HELPERS = BIN / "helpers"
NAGENT = BIN / "nagent"
NAGENT_CAMPAIGN = BIN / "nagent-campaign"

sys.path.insert(0, str(HELPERS))
import nagent_campaign_lib as camp


def load_nagent_module():
    from importlib.machinery import SourceFileLoader

    loader = SourceFileLoader("nagent_mod_campaign_tests", str(NAGENT))
    spec = importlib.util.spec_from_loader("nagent_mod_campaign_tests", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def make_root(tmp: str) -> Path:
    root = Path(tmp) / "nagent-root"
    root.mkdir(parents=True)
    return root


def worker(status="done", summary="did the thing", questions=None, proposal=None):
    return {
        "status": status,
        "summary": summary,
        "questions": questions or [],
        "proposal": proposal,
    }


class CampaignSchemaTests(unittest.TestCase):
    def test_new_add_status_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp)
            campaign = camp.new_campaign(root, "Migrate Config", "Replace the loader.")
            self.assertEqual(campaign.name, "migrate-config")
            index = camp.load_index(campaign)
            self.assertEqual(index["name"], "Migrate Config")
            self.assertEqual(index["status"], "active")

            first = camp.add_item(campaign, "Inventory all call sites")
            second = camp.add_item(campaign, "Write the new loader", blocked_by=[first])
            child = camp.add_item(campaign, "Loader unit tests", parent=second)

            index = camp.load_index(campaign)
            self.assertEqual([n["id"] for n in index["items"]], [first, second])
            self.assertEqual(index["items"][1]["items"][0]["id"], child)
            self.assertEqual(index["items"][1]["blocked_by"], [first])

            detail = camp.load_item(campaign, first)
            self.assertEqual(detail["description"], "Inventory all call sites")

            # The spine is hand-editable YAML: a raw text edit round-trips.
            raw = camp.index_path(campaign).read_text(encoding="utf-8")
            camp.index_path(campaign).write_text(
                raw.replace("status: todo", "status: done", 1), encoding="utf-8"
            )
            index = camp.load_index(campaign)
            self.assertEqual(index["items"][0]["status"], "done")

    def test_item_ids_are_sequential_and_sluggy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp)
            campaign = camp.new_campaign(root, "c")
            first = camp.add_item(campaign, "Alpha beta gamma delta epsilon")
            second = camp.add_item(campaign, "Second thing")
            self.assertTrue(first.startswith("0001-"))
            self.assertTrue(second.startswith("0002-"))


class DriverTests(unittest.TestCase):
    def test_two_item_campaign_runs_to_done(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp)
            campaign = camp.new_campaign(root, "demo", "do two things")
            a = camp.add_item(campaign, "thing one")
            b = camp.add_item(campaign, "thing two", blocked_by=[a])
            dispatched: list[str] = []

            def dispatch(item_id, briefing):
                dispatched.append(item_id)
                self.assertIn("demo", briefing)
                return worker(summary=f"{item_id} ok")

            # Pass 1: only the unblocked item dispatches.
            report = camp.run_update(root, "demo", dispatch=dispatch)
            self.assertEqual(report.dispatched, [a])
            index = camp.load_index(campaign)
            self.assertEqual(camp.find_node(index, a)["status"], "in-progress")

            # Pass 2: a's claim merges to done; b unblocks and dispatches.
            report = camp.run_update(root, "demo", dispatch=dispatch)
            self.assertEqual(report.merged, [a])
            self.assertEqual(report.dispatched, [b])

            # Pass 3: b merges; everything done; campaign done.
            report = camp.run_update(root, "demo", dispatch=dispatch)
            self.assertEqual(report.merged, [b])
            self.assertEqual(report.campaign_status, "done")
            self.assertEqual(report.status_counts.get("done"), 2)
            detail = camp.load_item(campaign, a)
            self.assertEqual(detail["result"], f"{a} ok")

    def test_executable_condition_gates_false_done_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp)
            campaign = camp.new_campaign(root, "demo")
            item = camp.add_item(campaign, "guarded work")
            check = campaign / "tests" / "check.sh"
            check.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
            check.chmod(0o755)
            detail = camp.load_item(campaign, item)
            detail["completion"] = [{"test": "../../tests/check.sh"}]
            camp.save_item(campaign, detail)

            camp.run_update(root, "demo", dispatch=lambda i, b: worker())
            # The claim merges to review and its condition is checked in the
            # same pass; it fails, so the item bounces back to todo.
            report = camp.run_update(root, "demo", dispatch=lambda i, b: worker(), max_dispatch=0)
            self.assertEqual(report.checked, [item])
            self.assertEqual(report.completed, [])
            index = camp.load_index(campaign)
            self.assertEqual(camp.find_node(index, item)["status"], "todo")
            self.assertIn("Condition failed", camp.load_item(campaign, item).get("notes", ""))

            # Fix the check; claim again; condition passes.
            check.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            camp.write_worker_result(campaign, item, worker())
            report = camp.run_update(root, "demo", max_dispatch=0)
            self.assertEqual(report.completed, [item])

    def test_question_blocks_until_answered_in_questions_md(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp)
            campaign = camp.new_campaign(root, "demo")
            item = camp.add_item(campaign, "needs a decision")

            camp.run_update(
                root,
                "demo",
                dispatch=lambda i, b: worker(status="question", questions=["Tabs or spaces?"]),
            )
            report = camp.run_update(root, "demo", max_dispatch=0)
            index = camp.load_index(campaign)
            self.assertEqual(camp.find_node(index, item)["status"], "question")
            self.assertEqual(report.questions_open, 1)
            questions = camp.questions_path(campaign).read_text(encoding="utf-8")
            self.assertIn(f"## [{item}] Tabs or spaces?", questions)

            # The user answers by editing the file.
            camp.questions_path(campaign).write_text(
                questions + "Spaces. Two of them.\n", encoding="utf-8"
            )
            report = camp.run_update(root, "demo", max_dispatch=0)
            self.assertEqual(report.answered, [item])
            index = camp.load_index(campaign)
            self.assertEqual(camp.find_node(index, item)["status"], "todo")
            self.assertIn("Spaces. Two of them.", camp.load_item(campaign, item)["notes"])

    def test_worker_proposal_small_auto_confirms_large_parks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp)
            campaign = camp.new_campaign(root, "demo")
            small = camp.add_item(campaign, "small split")
            large = camp.add_item(campaign, "large split")

            proposals = {
                small: {"items": [{"description": "part one"}, {"description": "part two"}]},
                large: {"items": [{"description": f"part {i}"} for i in range(10)]},
            }

            camp.run_update(
                root,
                "demo",
                dispatch=lambda item_id, b: worker(status="question", proposal=proposals[item_id]),
            )
            report = camp.run_update(root, "demo", max_dispatch=0)

            self.assertIn(small, report.auto_confirmed)
            pending_parents = [p["parent"] for p in report.pending_review]
            self.assertIn(large, pending_parents)

            index = camp.load_index(campaign)
            small_node = camp.find_node(index, small)
            self.assertEqual(small_node["status"], "in-progress")
            self.assertEqual(len(small_node["items"]), 2)
            self.assertEqual(camp.find_node(index, large)["status"], "proposed")
            # Pending subtrees are not dispatched into.
            self.assertNotIn(large, report.dispatched)

            # Hand-edit the parked proposal, then confirm.
            proposal_file = camp.proposal_path(campaign, large)
            edited = camp.load_proposal(proposal_file)
            edited["items"] = edited["items"][:3]
            proposal_file.write_text(camp._dump_yaml(edited), encoding="utf-8")
            index = camp.load_index(campaign)
            pending = camp.pending_proposals(campaign, index)
            new_ids = camp.confirm_proposal(campaign, index, pending[0])
            self.assertEqual(len(new_ids), 3)
            index = camp.load_index(campaign)
            self.assertEqual(len(camp.find_node(index, large)["items"]), 3)

    def test_initial_decomposition_always_parks_for_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp)
            camp.new_campaign(root, "demo", "a goal worth decomposing")

            def generate(prompt):
                return json.dumps({"items": [{"description": "only one tiny item"}]})

            report = camp.run_update(root, "demo", generate=generate)
            # Even a one-item proposal (well inside thresholds) parks.
            self.assertEqual(report.auto_confirmed, [])
            self.assertEqual(len(report.pending_review), 1)
            self.assertIsNone(report.pending_review[0]["parent"])
            self.assertEqual(report.dispatched, [])

            campaign = camp.campaign_dir(root, "demo")
            index = camp.load_index(campaign)
            pending = camp.pending_proposals(campaign, index)
            camp.confirm_proposal(campaign, index, pending[0])
            index = camp.load_index(campaign)
            self.assertEqual(len(index["items"]), 1)

    def test_dry_run_mutates_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp)
            campaign = camp.new_campaign(root, "demo")
            item = camp.add_item(campaign, "work")
            camp.write_worker_result(campaign, item, worker())
            before_index = camp.index_path(campaign).read_text(encoding="utf-8")

            report = camp.run_update(root, "demo", dry_run=True)

            self.assertTrue(report.dry_run)
            self.assertEqual(report.merged, [item])
            self.assertEqual(
                camp.index_path(campaign).read_text(encoding="utf-8"), before_index
            )
            self.assertTrue((camp.item_dir(campaign, item) / "result.json").is_file())

    def test_interrupted_update_converges_on_rerun(self):
        # A result.json left by a killed pass merges on the next one.
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp)
            campaign = camp.new_campaign(root, "demo")
            item = camp.add_item(campaign, "work")
            index = camp.load_index(campaign)
            camp.find_node(index, item)["status"] = "in-progress"
            camp.save_index(campaign, index)
            camp.write_worker_result(campaign, item, worker())

            report = camp.run_update(root, "demo", max_dispatch=0)
            self.assertEqual(report.merged, [item])
            index = camp.load_index(campaign)
            self.assertEqual(camp.find_node(index, item)["status"], "done")

    def test_hand_edits_to_index_are_honored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp)
            campaign = camp.new_campaign(root, "demo")
            keep = camp.add_item(campaign, "keep me")
            drop = camp.add_item(campaign, "drop me")

            index = camp.load_index(campaign)
            index["items"] = [n for n in index["items"] if n["id"] == keep]
            camp.save_index(campaign, index)

            report = camp.run_update(root, "demo", dispatch=lambda i, b: worker())
            self.assertEqual(report.dispatched, [keep])
            self.assertNotIn(drop, report.dispatched)

    def test_failed_worker_is_data_not_a_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp)
            campaign = camp.new_campaign(root, "demo")
            item = camp.add_item(campaign, "explodes")

            def dispatch(item_id, briefing):
                raise RuntimeError("worker died")

            report = camp.run_update(root, "demo", dispatch=dispatch)
            self.assertTrue(report.failures)
            report = camp.run_update(root, "demo", max_dispatch=0)
            index = camp.load_index(campaign)
            self.assertEqual(camp.find_node(index, item)["status"], "failed")
            self.assertIn(
                f"## [{item}]",
                camp.questions_path(campaign).read_text(encoding="utf-8"),
            )


class ContextWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_nagent_module()

    def test_campaign_direction_always_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp)
            text = self.mod.build_initial_context(root, NAGENT.resolve(), "user", "conv")
        self.assertIn("Campaigns (long-horizon plans as data", text)
        self.assertIn("nagent-campaign new", text)
        self.assertNotIn("Active campaigns", text)

    def test_ambient_status_block_appears_iff_campaign_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp)
            campaign = camp.new_campaign(root, "demo", "goal")
            camp.add_item(campaign, "one thing")
            text = self.mod.build_initial_context(root, NAGENT.resolve(), "user", "conv")
            self.assertIn("Active campaigns", text)
            self.assertIn("demo: 1 todo", text)

            index = camp.load_index(campaign)
            index["status"] = "done"
            camp.save_index(campaign, index)
            text = self.mod.build_initial_context(root, NAGENT.resolve(), "user", "conv")
            self.assertNotIn("Active campaigns", text)

    def test_campaign_item_mode_adds_contract_and_campaign_bin(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp)
            campaign = camp.new_campaign(root, "demo", "goal")
            item = camp.add_item(campaign, "one thing")
            tool = campaign / "bin" / "campaign-tool"
            tool.parent.mkdir()
            tool.write_text(
                "#!/usr/bin/env python3\nprint('CAMPAIGN-TOOL-MARKER description')\n",
                encoding="utf-8",
            )
            tool.chmod(0o755)

            text = self.mod.build_initial_context(
                root,
                NAGENT.resolve(),
                "delegated",
                "conv",
                campaign_item_dir=camp.item_dir(campaign, item),
            )

            self.assertIn("Campaign item worker (this session):", text)
            self.assertIn("the driver merges; you produce data", text)
            self.assertIn("CAMPAIGN-TOOL-MARKER", text)
            self.assertIn(f"campaign item: {camp.item_dir(campaign, item)}", text)

            plain = self.mod.build_initial_context(root, NAGENT.resolve(), "user", "conv")
            self.assertNotIn("Campaign item worker", plain)


class CampaignCliTests(unittest.TestCase):
    def test_description_flag(self):
        result = subprocess.run(
            [str(NAGENT_CAMPAIGN), "--description"], capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("plans", result.stdout)

    def test_new_add_status_update_dry_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp)

            result = subprocess.run(
                [str(NAGENT_CAMPAIGN), "--root", str(root), "new", "Demo Campaign",
                 "--goal", "do the demo"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            result = subprocess.run(
                [str(NAGENT_CAMPAIGN), "--root", str(root), "add", "demo-campaign", "first item"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("item:0001-", result.stdout)

            result = subprocess.run(
                [str(NAGENT_CAMPAIGN), "--root", str(root), "status", "demo-campaign"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("[todo]", result.stdout)

            result = subprocess.run(
                [str(NAGENT_CAMPAIGN), "--root", str(root), "update", "demo-campaign", "--dry-run"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("would dispatch: 0001-", result.stdout)

            # Dry run requires no credentials and mutates nothing.
            index = camp.load_index(camp.campaign_dir(root, "demo-campaign"))
            self.assertEqual(index["items"][0]["status"], "todo")


if __name__ == "__main__":
    unittest.main()
