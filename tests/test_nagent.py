#!/usr/bin/python3

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

BIN = Path(__file__).resolve().parent.parent / "bin"
NAGENT = BIN / "nagent"
NAGENT_LLM_TEXT = BIN / "nagent-llm-text"


def load_nagent_module():
    from importlib.machinery import SourceFileLoader

    loader = SourceFileLoader("nagent_mod", str(NAGENT))
    spec = importlib.util.spec_from_loader("nagent_mod", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class ParseResponseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_nagent_module()

    def test_valid_multi_tag_response(self):
        text = (
            '<nagent-response>Hello</nagent-response>\n'
            '<nagent-read path="/tmp/foo" />\n'
            "<nagent-next>continue</nagent-next>"
        )
        tags, err = self.mod.parse_response(text)
        self.assertIsNone(err)
        self.assertEqual([t.kind for t in tags], ["response", "read", "next"])
        self.assertEqual(tags[0].content, "Hello")
        self.assertEqual(tags[1].path, "/tmp/foo")
        self.assertEqual(tags[2].content, "continue")

    def test_invalid_leading_text(self):
        tags, err = self.mod.parse_response("oops <nagent-response>Hi</nagent-response>")
        self.assertIsNone(tags)
        self.assertIn("Unexpected content", err)

    def test_empty_response(self):
        tags, err = self.mod.parse_response("   ")
        self.assertIsNone(tags)
        self.assertIn("no nagent tags", err)


class ActionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_nagent_module()

    def test_execute_read_and_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.txt"
            path.write_text("sample content", encoding="utf-8")

            read_result = self.mod.execute_read(str(path))
            self.assertIn("sample content", read_result)

            missing = self.mod.execute_read(str(Path(tmp) / "missing.txt"))
            self.assertIn("file not found", missing)

            target = Path(tmp) / "out" / "written.txt"
            write_result = self.mod.execute_write(str(target), "written")
            self.assertIn('status="ok"', write_result)
            self.assertEqual(target.read_text(encoding="utf-8"), "written")

    def test_execute_shell(self):
        result = self.mod.execute_shell("echo hello-nagent")
        self.assertIn("hello-nagent", result)
        self.assertIn("exit_code: 0", result)

    def test_default_pid_prefers_bashpid(self):
        with unittest.mock.patch.dict(os.environ, {"BASHPID": "9999"}, clear=False):
            self.assertEqual(self.mod.default_pid(), "9999")

    def test_default_pid_falls_back_to_parent_shell(self):
        env = os.environ.copy()
        env.pop("BASHPID", None)
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            with unittest.mock.patch.object(self.mod.os, "getppid", return_value=4242):
                self.assertEqual(self.mod.default_pid(), "4242")

    def test_default_conversation_name_uses_pid(self):
        name = self.mod.default_conversation_name("4242")
        self.assertTrue(name.endswith("-4242"))
        self.assertIn("latest-", name)

    def test_execute_agent_passes_pid(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            captured: dict[str, list[str]] = {}

            def fake_run(cmd, **kwargs):
                captured["cmd"] = cmd
                class Result:
                    returncode = 0
                    stdout = "<nagent-response>done</nagent-response>"
                    stderr = ""
                return Result()

            with unittest.mock.patch.object(self.mod.subprocess, "run", fake_run):
                self.mod.execute_agent(
                    "do task",
                    root,
                    "gpt-5.5",
                    NAGENT,
                    "parent-conv",
                    "4242",
                )

            pid_index = captured["cmd"].index("--pid")
            self.assertEqual(captured["cmd"][pid_index + 1], "4242")
            self.assertIn("4242", captured["cmd"][captured["cmd"].index("--conversation") + 1])


class InitialTextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_nagent_module()

    def test_delegated_initial_text(self):
        text = self.mod.create_initial_text(
            Path("/tmp/nagent-root"),
            NAGENT.resolve(),
            "delegated",
            "sub-agent-1",
            "parent-conv",
        )
        self.assertIn("invocation: delegated", text)
        self.assertIn("conversation: sub-agent-1", text)
        self.assertIn("parent conversation: parent-conv", text)
        self.assertIn("Delegated invocation:", text)
        self.assertIn("Still decompose and delegate", text)
        self.assertNotIn("User invocation:", text)


class CliTests(unittest.TestCase):
    def test_llm_text_missing_file(self):
        result = subprocess.run(
            [str(NAGENT_LLM_TEXT), "--file", "/nonexistent/nagent-test.txt"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("file not found", result.stderr)

    def test_status_prints_path_and_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conv = "status-test"
            conversation_file = root / conv
            conversation_file.write_text("hello", encoding="utf-8")

            result = subprocess.run(
                [str(NAGENT), "--root", str(root), "--conversation", conv, "--status"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            lines = result.stdout.strip().splitlines()
            self.assertEqual(lines[0], str(conversation_file))
            self.assertEqual(int(lines[1]), conversation_file.stat().st_size)

    def test_status_missing_conversation_reports_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conv = "missing-conv"
            conversation_file = root / conv

            result = subprocess.run(
                [str(NAGENT), "--root", str(root), "--conversation", conv, "--status"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            lines = result.stdout.strip().splitlines()
            self.assertEqual(lines[0], str(conversation_file))
            self.assertEqual(lines[1], "0")

    def test_nagent_seeds_conversation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conv = "test-seed"
            fake_llm = root / "fake-llm"
            fake_llm.write_text(
                "#!/usr/bin/python3\nprint('<nagent-response>seed ok</nagent-response>')\n",
                encoding="utf-8",
            )
            fake_llm.chmod(0o755)

            mod = load_nagent_module()
            mod.NAGENT_LLM_TEXT = fake_llm
            conversation_file = root / conv
            conversation_file.write_text(
                mod.create_initial_text(root, NAGENT.resolve(), "user", conv),
                encoding="utf-8",
            )

            code = mod.run_agent_loop(conversation_file, root, "gpt-5.5", "hello", "4242")
            self.assertEqual(code, 0)

            self.assertTrue(conversation_file.exists())
            contents = conversation_file.read_text(encoding="utf-8")
            self.assertIn("<initial_context>", contents)
            self.assertIn("invocation: user", contents)
            self.assertIn(f"conversation: {conv}", contents)
            self.assertIn("parent conversation: none", contents)
            self.assertIn("nagent root:", contents)
            self.assertIn("nagent process:", contents)
            self.assertIn("cwd:", contents)
            self.assertIn("host (uname -a):", contents)
            self.assertIn("Context management (every nagent instance", contents)
            self.assertIn("User invocation:", contents)
            self.assertIn("<user-prompt>", contents)
            self.assertIn("hello", contents)
            self.assertIn("<nagent-response>seed ok</nagent-response>", contents)


class LiveIntegrationTests(unittest.TestCase):
    def test_live_llm_text(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as handle:
            handle.write("Reply with exactly: LIVE-OK")
            prompt_file = handle.name

        try:
            result = subprocess.run(
                [str(NAGENT_LLM_TEXT), "--file", prompt_file, "--model", "gpt-5.5"],
                capture_output=True,
                text=True,
                timeout=120,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("LIVE", result.stdout.upper())
        finally:
            Path(prompt_file).unlink(missing_ok=True)

    def test_live_nagent_simple_response(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [
                    str(NAGENT),
                    "--root",
                    tmp,
                    "--conversation",
                    "live-test",
                    "--model",
                    "gpt-5.5",
                    "Respond only with <nagent-response>integration-ok</nagent-response>",
                ],
                capture_output=True,
                text=True,
                timeout=180,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("integration-ok", result.stdout)

            conversation = Path(tmp) / "live-test"
            self.assertTrue(conversation.exists())
            self.assertIn("<user-prompt>", conversation.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
