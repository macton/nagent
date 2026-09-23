#!/usr/bin/python3

import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
import unittest.mock
from datetime import datetime, timezone
from importlib.machinery import SourceFileLoader
from pathlib import Path

BIN = Path(__file__).resolve().parent.parent / "bin"
HELPERS = BIN / "helpers"
NAGENT = BIN / "nagent"
NAGENT_MESSAGE = BIN / "nagent-message"


def load_message_lib():
    loader = SourceFileLoader("nagent_message_lib", str(HELPERS / "nagent_message_lib.py"))
    spec = importlib.util.spec_from_loader("nagent_message_lib", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def load_nagent_module():
    loader = SourceFileLoader("nagent_main", str(NAGENT))
    spec = importlib.util.spec_from_loader("nagent_main", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class MessageSpoolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_message_lib()

    def test_enqueue_then_drain_round_trips_in_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            inbox = Path(tmp) / "conv.inbox"
            self.mod.enqueue_messages(inbox, ["first"])
            self.mod.enqueue_messages(inbox, ["second", "third"])
            self.assertEqual(len(self.mod.pending_message_paths(inbox)), 3)
            self.assertEqual(self.mod.drain_messages(inbox), ["first", "second", "third"])
            self.assertEqual(self.mod.drain_messages(inbox), [])

    def test_message_names_sort_by_arrival_time(self):
        early = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        late = datetime(2026, 1, 1, 0, 0, 1, tzinfo=timezone.utc)
        self.assertLess(self.mod.message_filename(early), self.mod.message_filename(late))

    def test_drain_missing_inbox_is_empty_not_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            inbox = Path(tmp) / "absent.inbox"
            self.assertEqual(self.mod.pending_message_paths(inbox), [])
            self.assertEqual(self.mod.drain_messages(inbox), [])
            self.assertFalse(inbox.exists())

    def test_temp_files_are_never_drained(self):
        with tempfile.TemporaryDirectory() as tmp:
            inbox = Path(tmp) / "conv.inbox"
            inbox.mkdir()
            (inbox / ".20260101T000000000000Z-abcdef01.txt").write_text("partial", encoding="utf-8")
            self.mod.enqueue_messages(inbox, ["real"])
            self.assertEqual(self.mod.drain_messages(inbox), ["real"])

    def test_enqueue_preserves_text_exactly(self):
        with tempfile.TemporaryDirectory() as tmp:
            inbox = Path(tmp) / "conv.inbox"
            text = "line one\n\nline two with <tags> & \"quotes\"\n"
            self.mod.enqueue_messages(inbox, [text])
            self.assertEqual(self.mod.drain_messages(inbox), [text])


class RunfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_message_lib()

    def test_runfile_round_trips_and_reports_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "conv.run"
            self.mod.write_runfile(path, hostname="testhost")
            payload = self.mod.read_runfile(path)
            self.assertEqual(payload["host"], "testhost")
            self.assertEqual(payload["pid"], os.getpid())
            self.assertEqual(self.mod.runfile_state(payload, hostname="testhost"), "running")
            self.mod.remove_runfile(path)
            self.assertIsNone(self.mod.read_runfile(path))

    def test_dead_pid_is_stale(self):
        payload = {"host": "testhost", "pid": 2, "started": "now", "cwd": "/"}
        with unittest.mock.patch.object(self.mod, "process_alive", return_value=False):
            self.assertEqual(self.mod.runfile_state(payload, hostname="testhost"), "stale")

    def test_other_host_is_unknown_not_guessed(self):
        payload = {"host": "elsewhere", "pid": os.getpid(), "started": "now", "cwd": "/"}
        self.assertEqual(self.mod.runfile_state(payload, hostname="testhost"), "unknown")

    def test_corrupt_runfile_reads_as_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "conv.run"
            path.write_text("{not json", encoding="utf-8")
            self.assertIsNone(self.mod.read_runfile(path))

    def test_instances_report_state_and_queue_depth(self):
        with tempfile.TemporaryDirectory() as tmp:
            conversations = Path(tmp)
            live = conversations / "latest-live"
            live.write_text("x", encoding="utf-8")
            self.mod.write_runfile(self.mod.runfile_path(live), hostname="testhost")
            self.mod.enqueue_messages(self.mod.inbox_dir(live), ["hi"])

            idle = conversations / "latest-idle"
            idle.write_text("x", encoding="utf-8")
            self.mod.enqueue_messages(self.mod.inbox_dir(idle), ["later"])

            rows = self.mod.conversation_instances(conversations, hostname="testhost")

        by_name = {row["conversation"]: row for row in rows}
        self.assertEqual(sorted(by_name), ["latest-idle", "latest-live"])
        self.assertEqual(by_name["latest-live"]["state"], "running")
        self.assertEqual(by_name["latest-live"]["pending"], 1)
        self.assertEqual(by_name["latest-idle"]["state"], "not-running")
        self.assertEqual(by_name["latest-idle"]["pending"], 1)

    def test_instances_of_missing_directory_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self.mod.conversation_instances(Path(tmp) / "absent"), [])


class LoopDeliveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_nagent_module()
        cls.lib = load_message_lib()

    def test_queued_message_is_delivered_as_user_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conversation = root / "conversation"
            conversation.write_text("initial", encoding="utf-8")
            self.lib.enqueue_messages(self.lib.inbox_dir(conversation), ["queued instruction"])

            with unittest.mock.patch.object(
                self.mod,
                "call_llm",
                return_value=("<nagent-response>done</nagent-response>", None),
            ):
                code, responses = self.mod.run_agent_loop(
                    conversation,
                    root,
                    self.mod.LlmSettings(provider="openai", model="gpt-5.5"),
                    None,
                    "4242",
                    json_mode=True,
                )
            contents = conversation.read_text(encoding="utf-8")

        self.assertEqual(code, 0)
        self.assertEqual(responses, ["done"])
        self.assertIn("<user-prompt>\nqueued instruction\n</user-prompt>", contents)
        self.assertEqual(self.lib.drain_messages(self.lib.inbox_dir(conversation)), [])

    def test_message_arriving_during_a_turn_extends_the_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conversation = root / "conversation"
            conversation.write_text("initial", encoding="utf-8")
            inbox = self.lib.inbox_dir(conversation)
            calls = []

            def fake_call_llm(*args, **kwargs):
                calls.append(1)
                if len(calls) == 1:
                    # Arrives while the first turn is in flight.
                    self.lib.enqueue_messages(inbox, ["late message"])
                return "<nagent-response>ok</nagent-response>", None

            with unittest.mock.patch.object(self.mod, "call_llm", fake_call_llm):
                code, responses = self.mod.run_agent_loop(
                    conversation,
                    root,
                    self.mod.LlmSettings(provider="openai", model="gpt-5.5"),
                    "hello",
                    "4242",
                    json_mode=True,
                )
            contents = conversation.read_text(encoding="utf-8")

        self.assertEqual(code, 0)
        self.assertEqual(len(calls), 2)
        self.assertEqual(responses, ["ok", "ok"])
        self.assertIn("<user-prompt>\nlate message\n</user-prompt>", contents)

    def test_queued_prompts_survive_a_conversation_rebuild(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conversation = root / "conversation"
            conversation.write_text(
                "<initial_context>\ncontext\n</initial_context>\n"
                "<user-prompt>\nqueued instruction\n</user-prompt>\n"
                "<agent-response>\nwork\n</agent-response>\n",
                encoding="utf-8",
            )
            with unittest.mock.patch.object(self.mod, "write_checkpoint", return_value=None):
                self.mod.rebuild_conversation(
                    conversation,
                    root,
                    self.mod.LlmSettings(provider="openai", model="gpt-5.5"),
                )
            contents = conversation.read_text(encoding="utf-8")

        self.assertIn("<user-prompt>\nqueued instruction\n</user-prompt>", contents)


class MessageCliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib = load_message_lib()

    def run_cli(self, args, root, stdin=""):
        return subprocess.run(
            [str(NAGENT_MESSAGE), "--root", str(root), *args],
            capture_output=True,
            text=True,
            input=stdin,
        )

    def test_description_is_self_reported(self):
        result = subprocess.run(
            [str(NAGENT_MESSAGE), "--description"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("nagent-message", result.stdout)

    def test_queue_to_named_conversation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conversations = root / "conversations"
            conversations.mkdir(parents=True)
            (conversations / "worker").write_text("x", encoding="utf-8")

            result = self.run_cli(["--conversation", "worker", "hello", "there"], root)
            self.assertEqual(result.returncode, 0, result.stderr)
            queued = self.lib.drain_messages(self.lib.inbox_dir(conversations / "worker"))

        self.assertEqual(queued, ["hello there"])

    def test_missing_conversation_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "conversations").mkdir(parents=True)
            result = self.run_cli(["--conversation", "absent", "hello"], root)

        self.assertEqual(result.returncode, 1)
        self.assertIn("conversation not found", result.stderr)

    def test_no_running_instance_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "conversations").mkdir(parents=True)
            result = self.run_cli(["hello"], root)

        self.assertEqual(result.returncode, 1)
        self.assertIn("no running nagent instance", result.stderr)

    def test_empty_message_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conversations = root / "conversations"
            conversations.mkdir(parents=True)
            (conversations / "worker").write_text("x", encoding="utf-8")
            result = self.run_cli(["--conversation", "worker", "   "], root)

        self.assertEqual(result.returncode, 1)
        self.assertIn("message text is empty", result.stderr)

    def test_stdin_message_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conversations = root / "conversations"
            conversations.mkdir(parents=True)
            (conversations / "worker").write_text("x", encoding="utf-8")

            result = self.run_cli(["--conversation", "worker", "-"], root, stdin="from stdin\n")
            self.assertEqual(result.returncode, 0, result.stderr)
            queued = self.lib.drain_messages(self.lib.inbox_dir(conversations / "worker"))

        self.assertEqual(queued, ["from stdin\n"])

    def test_single_running_instance_needs_no_argument(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conversations = root / "conversations"
            conversations.mkdir(parents=True)
            live = conversations / "latest-live"
            live.write_text("x", encoding="utf-8")
            self.lib.write_runfile(self.lib.runfile_path(live))

            result = self.run_cli(["hello"], root)
            self.assertEqual(result.returncode, 0, result.stderr)
            queued = self.lib.drain_messages(self.lib.inbox_dir(live))

        self.assertEqual(queued, ["hello"])

    def test_ambiguous_targets_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conversations = root / "conversations"
            conversations.mkdir(parents=True)
            for name in ("latest-one", "latest-two"):
                path = conversations / name
                path.write_text("x", encoding="utf-8")
                self.lib.write_runfile(self.lib.runfile_path(path))

            result = self.run_cli(["hello"], root)

        self.assertEqual(result.returncode, 1)
        self.assertIn("running nagent instances", result.stderr)

    def test_list_reports_pending_and_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conversations = root / "conversations"
            conversations.mkdir(parents=True)
            live = conversations / "latest-live"
            live.write_text("x", encoding="utf-8")
            self.lib.write_runfile(self.lib.runfile_path(live))
            self.lib.enqueue_messages(self.lib.inbox_dir(live), ["one"])

            result = self.run_cli(["--list", "--json"], root)
            payload = json.loads(result.stdout)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(payload["instances"]), 1)
        self.assertEqual(payload["instances"][0]["state"], "running")
        self.assertEqual(payload["instances"][0]["pending"], 1)


if __name__ == "__main__":
    unittest.main()
