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
NAGENT_LLM_UPLOAD = BIN / "nagent-llm-upload"
NAGENT_FILE_SPLIT = BIN / "nagent-file-split"
NAGENT_FILE_PATCH = BIN / "nagent-file-patch"
BIN_TOOLS = (
    NAGENT,
    NAGENT_LLM_TEXT,
    NAGENT_LLM_UPLOAD,
    NAGENT_FILE_SPLIT,
    NAGENT_FILE_PATCH,
)


def load_nagent_module():
    from importlib.machinery import SourceFileLoader

    loader = SourceFileLoader("nagent_mod", str(NAGENT))
    spec = importlib.util.spec_from_loader("nagent_mod", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def load_nagent_llm_module():
    from importlib.machinery import SourceFileLoader

    loader = SourceFileLoader("nagent_llm_mod", str(BIN / "helpers" / "nagent_llm.py"))
    spec = importlib.util.spec_from_loader("nagent_llm_mod", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def load_nagent_llm_upload_module():
    from importlib.machinery import SourceFileLoader

    loader = SourceFileLoader("nagent_llm_upload_mod", str(NAGENT_LLM_UPLOAD))
    spec = importlib.util.spec_from_loader("nagent_llm_upload_mod", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class NagentLlmUploadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_nagent_llm_upload_module()

    def test_classify_image_and_document(self):
        self.assertEqual(self.mod.classify_file(Path("photo.png")), "image")
        self.assertEqual(self.mod.classify_file(Path("report.pdf")), "document")
        self.assertEqual(self.mod.classify_file(Path("data.csv")), "document")

    def test_classify_zip_exits(self):
        with self.assertRaises(SystemExit) as ctx:
            self.mod.classify_file(Path("archive.zip"))
        self.assertEqual(ctx.exception.code, 1)

    def test_help_lists_supported_file_types(self):
        result = subprocess.run(
            [str(NAGENT_LLM_UPLOAD), "--help"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("Supported file types:", result.stdout)
        self.assertIn("Images:", result.stdout)
        self.assertIn("pdf", result.stdout)
        self.assertIn("png", result.stdout)

    def test_missing_file_cli(self):
        result = subprocess.run(
            [
                str(NAGENT_LLM_UPLOAD),
                "--file",
                "/nonexistent/upload.txt",
                "--prompt",
                "summarize",
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("file not found", result.stderr)


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
                    self.mod.LlmSettings(provider="openai", model="gpt-5.5"),
                    NAGENT,
                    "parent-conv",
                    "4242",
                )

            pid_index = captured["cmd"].index("--pid")
            self.assertEqual(captured["cmd"][pid_index + 1], "4242")
            self.assertEqual(captured["cmd"][captured["cmd"].index("--provider") + 1], "openai")
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

    def test_git_repo_context_outside_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self.mod.git_repo_context(Path(tmp)), "")

    def test_git_repo_context_in_repo(self):
        with unittest.mock.patch.object(self.mod.subprocess, "run") as mock_run:
            mock_run.side_effect = [
                unittest.mock.Mock(returncode=0, stdout="/home/macton/nagent\n", stderr=""),
                unittest.mock.Mock(
                    returncode=0,
                    stdout="origin\tgit@github.com:macton/nagent.git (fetch)\n"
                    "origin\tgit@github.com:macton/nagent.git (push)\n",
                    stderr="",
                ),
            ]
            context = self.mod.git_repo_context(Path("/home/macton/nagent"))
        self.assertIn("git toplevel: /home/macton/nagent", context)
        self.assertIn("git remote -v:", context)
        self.assertIn("origin\tgit@github.com:macton/nagent.git (fetch)", context)

    def test_create_initial_text_includes_git_context_in_repo(self):
        repo_root = Path(__file__).resolve().parent.parent
        with unittest.mock.patch.object(self.mod, "git_repo_context", return_value="- git toplevel: /repo"):
            text = self.mod.create_initial_text(
                Path("/tmp/nagent-root"),
                NAGENT.resolve(),
                "user",
                "conv",
            )
        self.assertIn("- git toplevel: /repo", text)

    def test_create_initial_text_in_nagent_repo(self):
        repo_root = Path(__file__).resolve().parent.parent
        text = self.mod.create_initial_text(
            repo_root / ".nagent",
            NAGENT.resolve(),
            "user",
            "conv",
        )
        self.assertIn("git toplevel:", text)
        self.assertIn("git remote -v:", text)
        self.assertIn(str(repo_root), text)

    def test_create_initial_text_includes_bin_tool_descriptions(self):
        text = self.mod.create_initial_text(
            Path("/tmp/nagent-root"),
            NAGENT.resolve(),
            "user",
            "conv",
        )
        self.assertIn("Available tools:", text)
        self.assertIn("path:", text)
        self.assertIn("nagent-file-split", text)
        self.assertIn("nagent-file-patch", text)


class ToolDescriptionTests(unittest.TestCase):
    def test_all_bin_tools_support_description(self):
        for tool in BIN_TOOLS:
            with self.subTest(tool=tool.name):
                result = subprocess.run(
                    [str(tool), "--description"],
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("path:", result.stdout)
                self.assertGreater(len(result.stdout.strip()), 20)

    def test_nagent_description_does_not_require_prompt(self):
        result = subprocess.run(
            [str(NAGENT), "--description"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("orchestrator", result.stdout.lower())


class RefreshInitialContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_nagent_module()

    def test_refresh_initial_context_replaces_existing_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conversation_file = root / "conv"
            conversation_file.write_text(
                "header\n<initial_context>\n- cwd: /old/path\n</initial_context>\n<user-prompt>\nhello\n</user-prompt>\n",
                encoding="utf-8",
            )
            with unittest.mock.patch.object(
                self.mod,
                "build_initial_context",
                return_value="<initial_context>\n- cwd: /new/path\n</initial_context>",
            ):
                self.mod.refresh_initial_context(
                    conversation_file,
                    root,
                    NAGENT.resolve(),
                    "user",
                    "conv",
                )
            contents = conversation_file.read_text(encoding="utf-8")
            self.assertIn("- cwd: /new/path", contents)
            self.assertNotIn("/old/path", contents)
            self.assertIn("<user-prompt>", contents)
            self.assertIn("hello", contents)

    def test_refresh_initial_context_prepends_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conversation_file = root / "conv"
            conversation_file.write_text("<user-prompt>\nhello\n</user-prompt>\n", encoding="utf-8")
            with unittest.mock.patch.object(
                self.mod,
                "build_initial_context",
                return_value="<initial_context>\n- cwd: /new/path\n</initial_context>",
            ):
                self.mod.refresh_initial_context(
                    conversation_file,
                    root,
                    NAGENT.resolve(),
                    "user",
                    "conv",
                )
            contents = conversation_file.read_text(encoding="utf-8")
            self.assertTrue(contents.startswith("<initial_context>"))
            self.assertIn("<user-prompt>", contents)


class CliTests(unittest.TestCase):
    def clean_env(self):
        env = os.environ.copy()
        env.pop("NAGENT_CONFIG", None)
        return env

    def test_llm_text_missing_file(self):
        result = subprocess.run(
            [str(NAGENT_LLM_TEXT), "--file", "/nonexistent/nagent-test.txt"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("file not found", result.stderr)

    def test_status_prints_path_size_provider_and_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conv = "status-test"
            conversation_file = root / conv
            conversation_file.write_text("hello", encoding="utf-8")

            result = subprocess.run(
                [
                    str(NAGENT),
                    "--root",
                    str(root),
                    "--conversation",
                    conv,
                    "--config",
                    str(root / "missing-config.json"),
                    "--status",
                ],
                capture_output=True,
                text=True,
                env=self.clean_env(),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            lines = result.stdout.strip().splitlines()
            self.assertEqual(lines[0], f"conversation:{conversation_file} size:{conversation_file.stat().st_size}")
            self.assertEqual(lines[1], "provider:openai model:gpt-5.5")

    def test_status_honors_provider_and_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conv = "status-test"
            conversation_file = root / conv

            result = subprocess.run(
                [
                    str(NAGENT),
                    "--root",
                    str(root),
                    "--conversation",
                    conv,
                    "--provider",
                    "anthropic",
                    "--model",
                    "claude-test",
                    "--status",
                ],
                capture_output=True,
                text=True,
                env=self.clean_env(),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            lines = result.stdout.strip().splitlines()
            self.assertEqual(lines[0], f"conversation:{conversation_file} size:0")
            self.assertEqual(lines[1], "provider:anthropic model:claude-test")

    def test_status_missing_conversation_reports_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conv = "missing-conv"
            conversation_file = root / conv

            result = subprocess.run(
                [
                    str(NAGENT),
                    "--root",
                    str(root),
                    "--conversation",
                    conv,
                    "--config",
                    str(root / "missing-config.json"),
                    "--status",
                ],
                capture_output=True,
                text=True,
                env=self.clean_env(),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            lines = result.stdout.strip().splitlines()
            self.assertEqual(lines[0], f"conversation:{conversation_file} size:0")
            self.assertEqual(lines[1], "provider:openai model:gpt-5.5")

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

            code = mod.run_agent_loop(
                conversation_file,
                root,
                mod.LlmSettings(provider="openai", model="gpt-5.5"),
                "hello",
                "4242",
            )
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
                [str(NAGENT_LLM_TEXT), "--file", prompt_file, "--provider", "openai", "--model", "gpt-5.5"],
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
                    "--provider",
                    "openai",
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


class NagentLlmConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_nagent_llm_module()

    def test_resolve_settings_from_config_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            config_path.write_text(
                '{"provider": "anthropic", "model": "claude-sonnet-4-6"}',
                encoding="utf-8",
            )
            provider, model = self.mod.resolve_settings(config_path=config_path)
            self.assertEqual(provider, "anthropic")
            self.assertEqual(model, "claude-sonnet-4-6")

    def test_cli_overrides_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            config_path.write_text('{"provider": "openai", "model": "gpt-5.5"}', encoding="utf-8")
            provider, model = self.mod.resolve_settings(
                provider="google",
                model="gemini-2.5-pro",
                config_path=config_path,
            )
            self.assertEqual(provider, "google")
            self.assertEqual(model, "gemini-2.5-pro")

    def test_missing_credentials_exits(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            message_path = Path(tmp) / "message.txt"
            config_path.write_text('{"provider": "anthropic"}', encoding="utf-8")
            message_path.write_text("hello", encoding="utf-8")
            env = os.environ.copy()
            env.pop("ANTHROPIC_API_KEY", None)
            result = subprocess.run(
                [
                    str(NAGENT_LLM_TEXT),
                    "--file",
                    str(message_path),
                    "--config",
                    str(config_path),
                ],
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("missing credentials", result.stderr)

    def test_resolve_settings_without_model_uses_provider_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            config_path.write_text('{"provider": "anthropic"}', encoding="utf-8")
            provider, model = self.mod.resolve_settings(config_path=config_path)
            self.assertEqual(provider, "anthropic")
            self.assertEqual(model, self.mod.default_model("anthropic"))

    def test_list_models_openai(self):
        fake_models = [unittest.mock.Mock(id="gpt-5.5"), unittest.mock.Mock(id="gpt-4o")]

        class FakeModels:
            def list(self):
                return fake_models

        class FakeClient:
            models = FakeModels()

        mock_openai = unittest.mock.Mock(return_value=FakeClient())
        with unittest.mock.patch.object(self.mod, "require_package", return_value=mock_openai):
            models = self.mod.list_models("openai")
        self.assertEqual(models, ["gpt-4o", "gpt-5.5"])

    def test_cursor_finished_status_is_success(self):
        result = unittest.mock.Mock(status="finished", result="done")
        self.assertEqual(self.mod._cursor_result_text(result), "done")

    def test_cursor_error_status_raises(self):
        result = unittest.mock.Mock(status="error", result="")
        with self.assertRaises(RuntimeError):
            self.mod._cursor_result_text(result)

    def test_utilities_autodetect_config_without_flags(self):
        import argparse

        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            config_path.write_text(
                '{"provider": "openai", "model": "gpt-5.5"}',
                encoding="utf-8",
            )
            args = argparse.Namespace(provider=None, model=None, config=None)
            with unittest.mock.patch.dict(
                os.environ,
                {"OPENAI_API_KEY": "test-key", "NAGENT_CONFIG": str(config_path)},
                clear=False,
            ):
                provider, model = self.mod.resolve_from_args(args)
            self.assertEqual(provider, "openai")
            self.assertEqual(model, "gpt-5.5")


if __name__ == "__main__":
    unittest.main(verbosity=2)
