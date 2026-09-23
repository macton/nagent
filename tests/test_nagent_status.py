#!/usr/bin/python3

import importlib.util
import json
import subprocess
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path

BIN = Path(__file__).resolve().parent.parent / "bin"
NAGENT_STATUS = BIN / "nagent-status"


def load_status_module():
    loader = SourceFileLoader("nagent_status_main", str(NAGENT_STATUS))
    spec = importlib.util.spec_from_loader("nagent_status_main", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


TURN_LINE = (
    '<nagent-turn-status utc="2026-08-23T20:57:25Z" turn="39" '
    'tokens_in_total="3330173" tokens_out_total="143786" />'
)


class TurnStatusParseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_status_module()

    def test_last_turn_status_takes_the_final_line(self):
        text = (
            '<nagent-turn-status utc="a" turn="1" tokens_in_total="10" tokens_out_total="1" />\n'
            "chatter\n" + TURN_LINE + "\ntrailing text\n"
        )
        status = self.mod.last_turn_status(text)
        self.assertEqual(status["turn"], "39")
        self.assertEqual(status["tokens_in_total"], "3330173")
        self.assertEqual(status["utc"], "2026-08-23T20:57:25Z")

    def test_no_turn_status_line_is_none(self):
        self.assertIsNone(self.mod.last_turn_status("no status here\n"))
        self.assertIsNone(self.mod.last_turn_status(""))

    def test_unterminated_tag_still_parses_attributes(self):
        text = '<nagent-turn-status utc="x" turn="7" tokens_in_total="5'
        status = self.mod.last_turn_status(text)
        self.assertEqual(status["turn"], "7")


class TailWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_status_module()

    def test_small_file_reads_whole_and_not_truncated(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "conv"
            path.write_text("line1\nline2\n", encoding="utf-8")
            text, size, truncated = self.mod.read_tail_window(path)
            self.assertEqual(text, "line1\nline2\n")
            self.assertEqual(size, 12)
            self.assertFalse(truncated)

    def test_large_file_reads_only_the_tail_aligned_to_a_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "conv"
            filler = ("x" * 99 + "\n") * ((self.mod.TAIL_WINDOW_BYTES // 100) + 10)
            path.write_text(filler + TURN_LINE + "\n", encoding="utf-8")
            text, size, truncated = self.mod.read_tail_window(path)
            self.assertTrue(truncated)
            self.assertLess(len(text.encode()), self.mod.TAIL_WINDOW_BYTES)
            # Window starts at a line boundary and still holds the final status.
            self.assertFalse(text.startswith("x" * 100))
            self.assertEqual(self.mod.last_turn_status(text)["turn"], "39")

    def test_missing_file_reports_absence_not_error(self):
        text, size, truncated = self.mod.read_tail_window(Path("/nonexistent/conv"))
        self.assertIsNone(text)
        self.assertEqual(size, 0)
        self.assertFalse(truncated)


class HelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_status_module()

    def test_format_age_bands(self):
        self.assertEqual(self.mod.format_age(45), "45s")
        self.assertEqual(self.mod.format_age(300), "5m")
        self.assertEqual(self.mod.format_age(7200), "2.0h")
        self.assertEqual(self.mod.format_age(-5), "0s")

    def test_bare_name_resolves_into_conversations_dir(self):
        conversations = Path("/root/conversations")
        self.assertEqual(
            self.mod.resolve_conversation_file(conversations, "worker"),
            conversations / "worker",
        )

    def test_path_like_name_is_used_as_a_path(self):
        conversations = Path("/root/conversations")
        self.assertEqual(
            self.mod.resolve_conversation_file(conversations, "/abs/conv"),
            Path("/abs/conv"),
        )

    def test_child_process_lines_rejects_bad_pids(self):
        self.assertEqual(self.mod.child_process_lines(None), [])
        self.assertEqual(self.mod.child_process_lines(0), [])
        self.assertEqual(self.mod.child_process_lines(True), [])


class CliTests(unittest.TestCase):
    def run_status(self, *args):
        return subprocess.run(
            [str(NAGENT_STATUS), *args],
            capture_output=True,
            text=True,
        )

    def make_root(self, tmp):
        root = Path(tmp) / "nagent-root"
        (root / "conversations").mkdir(parents=True)
        return root

    def test_full_report_on_a_dead_conversation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_root(tmp)
            conv = root / "conversations" / "worker"
            conv.write_text("hello\n" + TURN_LINE + "\n", encoding="utf-8")
            result = self.run_status("worker", "--root", str(root))
            self.assertEqual(result.returncode, 0)
            self.assertIn("state: not-running", result.stdout)
            self.assertIn("turn=39", result.stdout)
            self.assertIn("tokens_in_total=3330173", result.stdout)
            self.assertIn(TURN_LINE, result.stdout)

    def test_json_report_carries_turn_status_and_tail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_root(tmp)
            conv = root / "conversations" / "worker"
            conv.write_text("hello\n" + TURN_LINE + "\n", encoding="utf-8")
            result = self.run_status("worker", "--root", str(root), "--json", "--tail", "1")
            self.assertEqual(result.returncode, 0)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["state"], "not-running")
            self.assertEqual(payload["turn_status"]["turn"], "39")
            self.assertEqual(payload["tail"], [TURN_LINE])

    def test_missing_conversation_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_root(tmp)
            result = self.run_status("absent", "--root", str(root))
            self.assertEqual(result.returncode, 1)
            self.assertIn("conversation not found", result.stderr)

    def test_summary_lists_instances_with_runfiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_root(tmp)
            conv = root / "conversations" / "worker"
            conv.write_text(TURN_LINE + "\n", encoding="utf-8")
            # A runfile with a dead pid: state must be stale, never running.
            runfile = root / "conversations" / "worker.run"
            runfile.write_text(
                json.dumps(
                    {
                        "host": subprocess.run(
                            ["hostname"], capture_output=True, text=True
                        ).stdout.strip(),
                        "pid": 2**22 - 1,
                        "started": "2026-08-23T00:00:00+00:00",
                        "cwd": "/tmp",
                    }
                ),
                encoding="utf-8",
            )
            result = self.run_status("--root", str(root))
            self.assertEqual(result.returncode, 0)
            self.assertIn("worker", result.stdout)
            self.assertIn("turn=39", result.stdout)
            self.assertNotIn("running\tworker", result.stdout.replace("not-running", "X"))

    def test_negative_tail_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_root(tmp)
            result = self.run_status("worker", "--root", str(root), "--tail", "-1")
            self.assertEqual(result.returncode, 1)

    def test_description_flag(self):
        result = self.run_status("--description")
        self.assertEqual(result.returncode, 0)
        self.assertIn("nagent-status", result.stdout)


if __name__ == "__main__":
    unittest.main()
