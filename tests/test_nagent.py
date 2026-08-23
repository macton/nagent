#!/usr/bin/python3

import importlib.util
import io
import json
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
NAGENT_FILE_EDIT = BIN / "nagent-file-edit"
NAGENT_FILE_SUMMARIZE = BIN / "nagent-file-summarize"
BIN_TOOLS = (
    NAGENT,
    NAGENT_LLM_TEXT,
    NAGENT_LLM_UPLOAD,
    NAGENT_FILE_SPLIT,
    NAGENT_FILE_PATCH,
    NAGENT_FILE_EDIT,
    NAGENT_FILE_SUMMARIZE,
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


def load_nagent_llm_text_module():
    from importlib.machinery import SourceFileLoader

    loader = SourceFileLoader("nagent_llm_text_mod", str(NAGENT_LLM_TEXT))
    spec = importlib.util.spec_from_loader("nagent_llm_text_mod", loader)
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


def load_nagent_file_summarize_module():
    from importlib.machinery import SourceFileLoader

    loader = SourceFileLoader("nagent_file_summarize_mod", str(NAGENT_FILE_SUMMARIZE))
    spec = importlib.util.spec_from_loader("nagent_file_summarize_mod", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def load_nagent_file_summarize_lib_module():
    from importlib.machinery import SourceFileLoader

    helpers = BIN / "helpers"
    if str(helpers) not in sys.path:
        sys.path.insert(0, str(helpers))
    loader = SourceFileLoader(
        "nagent_file_summarize_lib_mod",
        str(helpers / "nagent_file_summarize_lib.py"),
    )
    spec = importlib.util.spec_from_loader("nagent_file_summarize_lib_mod", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class NagentFileSummarizeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_nagent_file_summarize_module()
        cls.lib = load_nagent_file_summarize_lib_module()

    def test_limit_word_count_prompt_retries_when_too_long(self):
        prompts = []
        summaries = iter(["one two three four", "one two"])

        def fake_generate_text(prompt, provider, model):
            prompts.append(prompt)
            return next(summaries)

        with unittest.mock.patch.object(self.lib, "generate_text", fake_generate_text):
            summary = self.lib.summarize_content(
                "source content",
                "source.txt",
                "openai",
                "gpt-5.5",
                limit_word_count=3,
            )

        self.assertEqual(summary, "one two")
        self.assertEqual(len(prompts), 2)
        self.assertIn("Fit the summary into 3 words or less.", prompts[0])
        self.assertIn("previous summary was 4 words", prompts[1])

    def test_limit_word_count_raises_after_retry_exceeds_limit(self):
        def fake_generate_text(prompt, provider, model):
            return "one two three four"

        with unittest.mock.patch.object(self.lib, "generate_text", fake_generate_text):
            with self.assertRaisesRegex(RuntimeError, "exceeded --limit-word-count 3"):
                self.lib.summarize_content(
                    "source content",
                    "source.txt",
                    "openai",
                    "gpt-5.5",
                    limit_word_count=3,
                )

    def test_main_passes_limit_word_count_to_inline_summarize(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.txt"
            source.write_text("source content", encoding="utf-8")
            captured = {}

            def fake_summarize(path, provider, model, limit_word_count=None):
                captured["limit_word_count"] = limit_word_count
                return "short summary"

            argv = [
                "nagent-file-summarize",
                "--file",
                str(source),
                "--limit-word-count",
                "8",
            ]
            with unittest.mock.patch.object(self.mod.sys, "argv", argv), \
                unittest.mock.patch.object(self.mod, "resolve_from_args", return_value=("openai", "gpt-5.5")), \
                unittest.mock.patch.object(self.mod, "summarize_file_path", fake_summarize), \
                unittest.mock.patch.object(self.mod.sys, "stdout", io.StringIO()) as stdout:
                self.mod.main()

        self.assertEqual(captured["limit_word_count"], 8)
        self.assertEqual(stdout.getvalue(), "short summary\n")

    def test_main_accepts_max_word_count_alias(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.txt"
            source.write_text("source content", encoding="utf-8")
            captured = {}

            def fake_summarize(path, provider, model, limit_word_count=None):
                captured["limit_word_count"] = limit_word_count
                return "short summary"

            argv = [
                "nagent-file-summarize",
                "--file",
                str(source),
                "--max-word-count",
                "8",
            ]
            with unittest.mock.patch.object(self.mod.sys, "argv", argv), \
                unittest.mock.patch.object(self.mod, "resolve_from_args", return_value=("openai", "gpt-5.5")), \
                unittest.mock.patch.object(self.mod, "summarize_file_path", fake_summarize), \
                unittest.mock.patch.object(self.mod.sys, "stdout", io.StringIO()) as stdout:
                self.mod.main()

        self.assertEqual(captured["limit_word_count"], 8)
        self.assertEqual(stdout.getvalue(), "short summary\n")


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


class RootAndLayerResolutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import importlib.util
        from importlib.machinery import SourceFileLoader

        loader = SourceFileLoader("nagent_cli_mod", str(BIN / "helpers" / "nagent_cli.py"))
        spec = importlib.util.spec_from_loader("nagent_cli_mod", loader)
        cls.cli = importlib.util.module_from_spec(spec)
        loader.exec_module(cls.cli)

    def test_resolve_default_root_explicit_wins(self):
        self.assertEqual(
            self.cli.resolve_default_root("/some/where"), Path("/some/where")
        )

    def test_resolve_default_root_uses_project_dotdir_in_git_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "proj"
            (project / "sub").mkdir(parents=True)
            subprocess.run(["git", "init"], cwd=project, check=True, capture_output=True)
            previous_cwd = os.getcwd()
            os.chdir(project / "sub")
            try:
                root = self.cli.resolve_default_root(None)
            finally:
                os.chdir(previous_cwd)
        self.assertEqual(root.resolve(), (project / ".nagent").resolve())

    def test_resolve_default_root_falls_back_to_user_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            outside = Path(tmp) / "outside"
            home.mkdir()
            outside.mkdir()
            previous_cwd = os.getcwd()
            os.chdir(outside)
            try:
                with unittest.mock.patch.dict(os.environ, {"HOME": str(home)}):
                    root = self.cli.resolve_default_root(None)
            finally:
                os.chdir(previous_cwd)
        self.assertEqual(root, home / ".nagent")

    def test_ensure_root_scaffold_writes_gitignore_only_on_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            fresh = Path(tmp) / "fresh-root"
            self.cli.ensure_root_scaffold(fresh)
            self.assertEqual(
                (fresh / ".gitignore").read_text(encoding="utf-8"), "splits/\n"
            )

            existing = Path(tmp) / "existing-root"
            existing.mkdir()
            self.cli.ensure_root_scaffold(existing)
            self.assertFalse((existing / ".gitignore").exists())

            # A user-deleted .gitignore stays deleted.
            (fresh / ".gitignore").unlink()
            self.cli.ensure_root_scaffold(fresh)
            self.assertFalse((fresh / ".gitignore").exists())

    def test_resolve_prompt_path_layers_root_then_user_then_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            root = Path(tmp) / "root"
            (home / ".nagent" / "prompts").mkdir(parents=True)
            (root / "prompts").mkdir(parents=True)
            name = "compact-conversation.md"

            with unittest.mock.patch.dict(os.environ, {"HOME": str(home)}):
                install_copy = self.cli.resolve_prompt_path(root, name)
                self.assertEqual(install_copy, self.cli.INSTALL_DIR / "prompts" / name)

                user_copy = home / ".nagent" / "prompts" / name
                user_copy.write_text("user", encoding="utf-8")
                self.assertEqual(self.cli.resolve_prompt_path(root, name), user_copy)

                root_copy = root / "prompts" / name
                root_copy.write_text("root", encoding="utf-8")
                self.assertEqual(self.cli.resolve_prompt_path(root, name), root_copy)

    def test_tool_discovery_layers_shadow_by_basename(self):
        with tempfile.TemporaryDirectory() as tmp:
            install_bin = Path(tmp) / "install" / "bin"
            user_bin = Path(tmp) / "home" / ".nagent" / "bin"
            root_bin = Path(tmp) / "root" / "bin"
            for directory in (install_bin, user_bin, root_bin):
                directory.mkdir(parents=True)

            def write_tool(directory, name, description):
                tool = directory / name
                tool.write_text(
                    "#!/usr/bin/env python3\n"
                    f"print({description!r})\n",
                    encoding="utf-8",
                )
                tool.chmod(0o755)

            write_tool(install_bin, "shared-tool", "install version")
            write_tool(user_bin, "shared-tool", "user version")
            write_tool(root_bin, "shared-tool", "project version")
            write_tool(install_bin, "install-only", "install only tool")
            write_tool(root_bin, "project-only", "project only tool")

            with unittest.mock.patch.dict(os.environ, {"HOME": str(Path(tmp) / "home")}):
                dirs = self.cli.tool_search_dirs(install_bin, Path(tmp) / "root")
                text = self.cli.collect_bin_tool_descriptions(dirs)

        self.assertIn("project version", text)
        self.assertNotIn("install version", text)
        self.assertNotIn("user version", text)
        self.assertIn("install only tool", text)
        self.assertIn("project only tool", text)

    def test_default_config_path_layers(self):
        nagent_llm = load_nagent_llm_module()
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            home.mkdir()
            project = Path(tmp) / "proj"
            project.mkdir()
            subprocess.run(["git", "init"], cwd=project, check=True, capture_output=True)

            previous_cwd = os.getcwd()
            os.chdir(project)
            try:
                env = {"HOME": str(home), "NAGENT_CONFIG": str(Path(tmp) / "env.json")}
                with unittest.mock.patch.dict(os.environ, env):
                    # NAGENT_CONFIG wins.
                    self.assertEqual(
                        nagent_llm.default_config_path(), Path(tmp) / "env.json"
                    )
                with unittest.mock.patch.dict(os.environ, {"HOME": str(home)}, clear=False):
                    os.environ.pop("NAGENT_CONFIG", None)
                    # No project config yet: user config.
                    self.assertEqual(
                        nagent_llm.default_config_path(),
                        home / ".nagent" / "config.json",
                    )
                    # Project config exists: it wins over the user config.
                    project_config = project / ".nagent" / "config.json"
                    project_config.parent.mkdir(parents=True)
                    project_config.write_text("{}", encoding="utf-8")
                    self.assertEqual(nagent_llm.default_config_path(), project_config)
            finally:
                os.chdir(previous_cwd)


class ParseResponseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_nagent_module()

    def test_valid_multi_tag_response(self):
        text = (
            '<nagent-response>Hello</nagent-response>\n'
            '<nagent-read path="/tmp/foo" />\n'
            '<nagent-file-read path="/tmp/big.py" />\n'
            '<nagent-file-patch index="/tmp/split/index.json" />\n'
            "<nagent-next>continue</nagent-next>\n"
            "<nagent-conversation>delegate</nagent-conversation>\n"
            '<nagent-conversation conversation-file="existing-conv">continue file</nagent-conversation>\n'
            '<nagent-conversation conversation-name="saved-conv">continue saved</nagent-conversation>'
        )
        tags, ignored, err = self.mod.parse_response(text)
        self.assertIsNone(err)
        self.assertEqual(ignored, [])
        self.assertEqual(
            [t.kind for t in tags],
            [
                "response",
                "read",
                "file_read",
                "file_patch",
                "next",
                "conversation",
                "conversation",
                "conversation",
            ],
        )
        self.assertEqual(tags[0].content, "Hello")
        self.assertEqual(tags[1].path, "/tmp/foo")
        self.assertEqual(tags[2].path, "/tmp/big.py")
        self.assertEqual(tags[3].path, "/tmp/split/index.json")
        self.assertEqual(tags[4].content, "continue")
        self.assertEqual(tags[5].content, "delegate")
        self.assertEqual(tags[6].content, "continue file")
        self.assertEqual(tags[6].conversation_file, "existing-conv")
        self.assertEqual(tags[7].content, "continue saved")
        self.assertEqual(tags[7].conversation_name, "saved-conv")

    def test_conversation_tag_rejects_unsupported_options(self):
        tags, ignored, err = self.mod.parse_response(
            '<nagent-conversation unknown="conv">delegate</nagent-conversation>'
        )
        self.assertEqual(tags, [])
        self.assertIn("Unsupported <nagent-conversation> attribute", err)

        tags, ignored, err = self.mod.parse_response(
            '<nagent-conversation conversation-file="conv" conversation-name="saved">'
            "delegate</nagent-conversation>"
        )
        self.assertEqual(tags, [])
        self.assertIn("supports only one", err)

    def test_write_tag_carries_raw_content(self):
        body = 'line1\nif a < b && c: print("&")\nline3\n'
        tags, ignored, err = self.mod.parse_response(
            f'<nagent-write path="/tmp/out.py">{body}</nagent-write>'
        )
        self.assertIsNone(err)
        self.assertEqual(tags[0].kind, "write")
        self.assertEqual(tags[0].path, "/tmp/out.py")
        self.assertEqual(tags[0].content, body)

    def test_read_tag_requires_exactly_path_attribute(self):
        # A *known* tag with a bad shape is a hard error (clear intent, fixable),
        # not silently ignored.
        tags, ignored, err = self.mod.parse_response("<nagent-read />")
        self.assertEqual(tags, [])
        self.assertIn('requires exactly one path="..."', err)

        tags, ignored, err = self.mod.parse_response('<nagent-read path="/tmp/f" extra="x" />')
        self.assertEqual(tags, [])
        self.assertIn('requires exactly one path="..."', err)

    def test_shell_tag_rejects_attributes(self):
        tags, ignored, err = self.mod.parse_response('<nagent-shell mode="x">ls</nagent-shell>')
        self.assertEqual(tags, [])
        self.assertIn("does not take attributes", err)

    def test_unclosed_known_tag_is_an_error(self):
        # write/shell stay strict: an unclosed body could carry content that
        # must never run, so it is a hard error, not an EOF capture.
        for text in ("<nagent-shell>ls", '<nagent-write path="/tmp/f">data'):
            tags, ignored, err = self.mod.parse_response(text)
            self.assertEqual(tags, [], text)
            self.assertIn("missing </nagent-", err, text)

    def test_unclosed_trailing_response_is_captured_to_eof(self):
        # Observed Gemini failure: a leaked <thought> plus a final
        # <nagent-response> the model never closed. The thought is ignored and
        # the response body is recovered instead of discarding a finished turn.
        text = (
            "<thought\nEverything is done. Reporting now."
            "<nagent-response>All 181 tests pass; 95x speedup."
        )
        tags, ignored, err = self.mod.parse_response(text)
        self.assertIsNone(err)
        self.assertEqual([t.kind for t in tags], ["response"])
        self.assertEqual(tags[0].content, "All 181 tests pass; 95x speedup.")

    def test_closed_response_still_parses_normally(self):
        tags, ignored, err = self.mod.parse_response(
            "<nagent-response>done</nagent-response>"
        )
        self.assertIsNone(err)
        self.assertEqual(tags[0].content, "done")

    def test_leading_prose_is_ignored_not_rejected(self):
        tags, ignored, err = self.mod.parse_response(
            "oops <nagent-response>Hi</nagent-response>"
        )
        self.assertIsNone(err)
        self.assertEqual([t.kind for t in tags], ["response"])
        self.assertEqual(tags[0].content, "Hi")
        self.assertTrue(any("oops" in note for note in ignored))

    def test_reasoning_leak_is_ignored_with_valid_tag(self):
        # Gemini's failure mode: a <thought> preamble (well-formed or malformed)
        # alongside a real action tag. The action runs; the thought is ignored.
        for thought in (
            "<thought>Okay, let's think.</thought>",
            "<thought Okay, let's think.",  # malformed: looks like a bad attribute
        ):
            tags, ignored, err = self.mod.parse_response(
                f"{thought}\n<nagent-shell>ls</nagent-shell>"
            )
            self.assertIsNone(err, thought)
            self.assertEqual([t.kind for t in tags], ["shell"], thought)
            self.assertTrue(ignored, thought)

    def test_trailing_prose_after_valid_tag_is_ignored(self):
        tags, ignored, err = self.mod.parse_response(
            "<nagent-shell>find .</nagent-shell> Standard input linter is used."
        )
        self.assertIsNone(err)
        self.assertEqual([t.kind for t in tags], ["shell"])
        self.assertTrue(any("Standard input linter" in note for note in ignored))

    def test_echoed_agent_response_wrapper_is_unwrapped(self):
        tags, ignored, err = self.mod.parse_response(
            "<agent-response>\n<nagent-conversation>do it</nagent-conversation>\n</agent-response>"
        )
        self.assertIsNone(err)
        self.assertEqual([t.kind for t in tags], ["conversation"])
        self.assertEqual(tags[0].content, "do it")
        self.assertEqual(ignored, [])

    def test_pure_reasoning_yields_no_tags(self):
        tags, ignored, err = self.mod.parse_response("<thought>just thinking</thought>")
        self.assertIsNone(err)
        self.assertEqual(tags, [])
        self.assertTrue(ignored)

    def test_empty_response_has_no_tags_and_no_error(self):
        tags, ignored, err = self.mod.parse_response("   ")
        self.assertIsNone(err)
        self.assertEqual(tags, [])
        self.assertEqual(ignored, [])

    def test_cleaned_response_strips_junk_and_closes_eof_capture(self):
        # leaked <thought> + a real shell tag -> only the shell survives.
        cleaned, dupes = self.mod.cleaned_response_text(
            "<thought\nthinking.<nagent-shell>ls</nagent-shell>"
        )
        self.assertEqual(cleaned, "<nagent-shell>ls</nagent-shell>")
        self.assertEqual(dupes, 0)
        # leaked <thought> + an unclosed final response -> response, closed.
        cleaned, dupes = self.mod.cleaned_response_text("<thought\ndone.<nagent-response>answer")
        self.assertEqual(cleaned, "<nagent-response>answer</nagent-response>")
        self.assertEqual(dupes, 0)

    def test_duplicate_tags_are_collapsed(self):
        # A stutter that emits the same read+shell+next four times runs once.
        turn = (
            '<nagent-read path="/tmp/f" />'
            "<nagent-shell>ls</nagent-shell>"
            "<nagent-next>go</nagent-next>"
        ) * 4
        tags, ignored, err = self.mod.parse_response(turn)
        self.assertIsNone(err)
        self.assertEqual([t.kind for t in tags], ["read", "shell", "next"])  # deduped
        cleaned, dupes = self.mod.cleaned_response_text(turn)
        self.assertEqual(dupes, 9)  # 12 tags in, 3 unique kept
        self.assertEqual(
            cleaned,
            '<nagent-read path="/tmp/f" />\n<nagent-shell>ls</nagent-shell>\n<nagent-next>go</nagent-next>',
        )

    def test_distinct_tags_are_not_deduped(self):
        # Same kind, different content/attrs -> both kept.
        tags, ignored, err = self.mod.parse_response(
            "<nagent-next>a</nagent-next><nagent-next>b</nagent-next>"
            '<nagent-read path="/tmp/x" /><nagent-read path="/tmp/y" />'
        )
        self.assertIsNone(err)
        self.assertEqual(len(tags), 4)
        _, dupes = self.mod.cleaned_response_text(
            "<nagent-next>a</nagent-next><nagent-next>b</nagent-next>"
        )
        self.assertEqual(dupes, 0)

    def test_ignored_correction_does_not_echo_the_offending_tag(self):
        note = self.mod.ignored_correction(['malformed <thought>: "<thought ..."'])
        self.assertNotIn("thought", note)
        self.assertIn("non-protocol", note)


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
            write_result = self.mod.execute_write(str(target), "written", scratch_dir=Path(tmp))
            self.assertIn('status="ok"', write_result)
            self.assertEqual(target.read_text(encoding="utf-8"), "written")

    def test_execute_read_binary_file_returns_error_result(self):
        # Undecodable bytes must become an error result in the conversation,
        # not an uncaught UnicodeDecodeError that kills the loop.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "blob.bin"
            path.write_bytes(b"\x00\xff\xfe\x80binary")

            read_result = self.mod.execute_read(str(path))
            self.assertIn('<nagent-read-result path="', read_result)
            self.assertIn("error=", read_result)

            file_read_result = self.mod.execute_file_read(str(path), Path(tmp))
            self.assertIn('<nagent-file-read-result path="', file_read_result)
            self.assertIn("error=", file_read_result)

    def test_conversation_cache_boundaries(self):
        text = (
            "<initial_context>\nstable rules\nInstance:\n- conversation: c\n"
            "</initial_context>\n<user-prompt>\nhi\n</user-prompt>"
        )
        boundaries = self.mod.conversation_cache_boundaries(text)
        volatile_at = text.find("\nInstance:")
        context_end = text.index("</initial_context>") + len("</initial_context>")
        self.assertEqual(boundaries, [volatile_at, context_end])

        # No initial context, or context not at the start: no boundaries.
        self.assertEqual(self.mod.conversation_cache_boundaries("plain text"), [])
        self.assertEqual(self.mod.conversation_cache_boundaries(f"x{text}"), [])

        # File that is exactly the context: only the volatile boundary.
        context_only = text[:context_end]
        self.assertEqual(self.mod.conversation_cache_boundaries(context_only), [volatile_at])

    def test_call_llm_passes_cache_boundaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            conversation = Path(tmp) / "conv"
            text = (
                "<initial_context>\nstable rules\nInstance:\n- conversation: c\n"
                "</initial_context>\n<user-prompt>\nhi\n</user-prompt>"
            )
            conversation.write_text(text, encoding="utf-8")
            captured: dict = {}

            def fake_run(cmd, **kwargs):
                captured["cmd"] = cmd
                payload = {"response": "ok", "input_tokens": 1, "output_tokens": 1}
                return unittest.mock.Mock(returncode=0, stdout=json.dumps(payload), stderr="")

            with unittest.mock.patch.object(self.mod.subprocess, "run", fake_run):
                self.mod.call_llm(
                    conversation,
                    self.mod.LlmSettings(provider="anthropic", model="m"),
                    self.mod.TokenStats(),
                )

            cmd = captured["cmd"]
            values = [int(cmd[i + 1]) for i, arg in enumerate(cmd) if arg == "--cache-prefix-chars"]
            self.assertEqual(values, self.mod.conversation_cache_boundaries(text))

    def test_execute_shell(self):
        result = self.mod.execute_shell("echo hello-nagent")
        self.assertIn("hello-nagent", result)
        self.assertIn("exit_code: 0", result)

    def test_shell_output_precedes_next_input_in_either_order(self):
        # A turn with both <nagent-shell> and <nagent-next> must record the
        # shell output in the conversation BEFORE the next-prompt, so the next
        # turn sees the output. process_tags appends shell output in place but
        # only collects next-prompts; run_agent_loop appends <nagent-next-input>
        # afterwards. That ordering must hold regardless of tag order, because
        # <nagent-next> never appends in the loop.
        def conversation_after(turn):
            with tempfile.TemporaryDirectory() as tmp:
                conv = Path(tmp) / "conv"
                conv.write_text("", encoding="utf-8")
                tags, _ignored, err = self.mod.parse_response(turn)
                self.assertIsNone(err)
                _resp, next_prompts, _cont = self.mod.process_tags(
                    tags, conv, Path(tmp), None, NAGENT, "pid", self.mod.TokenStats()
                )
                # mirror run_agent_loop's post-process_tags next-input append
                for prompt in next_prompts:
                    self.mod.append_to_conversation(
                        conv, f"<nagent-next-input>\n{prompt}\n</nagent-next-input>"
                    )
                return conv.read_text(encoding="utf-8")

        for turn in (
            "<nagent-shell>echo SHELL_MARKER</nagent-shell><nagent-next>go</nagent-next>",
            "<nagent-next>go</nagent-next><nagent-shell>echo SHELL_MARKER</nagent-shell>",
        ):
            text = conversation_after(turn)
            i_shell = text.find("SHELL_MARKER")
            i_next = text.find("<nagent-next-input>")
            self.assertNotEqual(i_shell, -1, "shell output missing")
            self.assertNotEqual(i_next, -1, "next-input missing")
            self.assertLess(i_shell, i_next, f"shell must precede next-input for: {turn}")

    def test_parse_llm_json_output_includes_tokens(self):
        parsed = self.mod.parse_llm_json_output(
            json.dumps(
                {
                    "response": "<nagent-response>ok</nagent-response>",
                    "input_tokens": 12,
                    "output_tokens": 3,
                }
            )
        )
        self.assertEqual(parsed, ("<nagent-response>ok</nagent-response>", 12, 3))

    def test_call_llm_updates_token_stats_from_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conversation = root / "conversation"
            conversation.write_text("prompt text", encoding="utf-8")
            fake_llm = root / "fake-llm"
            fake_llm.write_text(
                "#!/usr/bin/python3\n"
                "import json\n"
                "print(json.dumps({"
                "'response': '<nagent-response>token ok</nagent-response>', "
                "'input_tokens': 17, "
                "'output_tokens': 5"
                "}))\n",
                encoding="utf-8",
            )
            fake_llm.chmod(0o755)

            self.mod.NAGENT_LLM_TEXT = fake_llm
            stats = self.mod.TokenStats()
            output, error = self.mod.call_llm(
                conversation,
                self.mod.LlmSettings(provider="openai", model="gpt-5.5"),
                stats,
            )

        self.assertIsNone(error)
        self.assertEqual(output, "<nagent-response>token ok</nagent-response>")
        self.assertEqual(stats.turn_count, 1)
        self.assertEqual(stats.conversation_input_tokens, 17)
        self.assertEqual(stats.recursive_input_tokens, 17)
        self.assertEqual(stats.recursive_output_tokens, 5)

    def test_call_llm_returns_subprocess_exceptions_as_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            conversation = Path(tmp) / "conversation"
            conversation.write_text("prompt text", encoding="utf-8")

            def fake_run(*args, **kwargs):
                raise RuntimeError("bridge failed")

            stats = self.mod.TokenStats()
            with unittest.mock.patch.object(self.mod.subprocess, "run", fake_run):
                output, error = self.mod.call_llm(
                    conversation,
                    self.mod.LlmSettings(provider="openai", model="gpt-5.5"),
                    stats,
                )

        self.assertIsNone(output)
        self.assertEqual(error, "bridge failed")

    def test_run_agent_loop_retries_llm_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conversation = root / "conversation"
            conversation.write_text("initial", encoding="utf-8")
            attempts = []

            def fake_call_llm(*args, **kwargs):
                attempts.append(1)
                if len(attempts) == 1:
                    return None, "transient bridge failure"
                return "<nagent-response>retry ok</nagent-response>", None

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
        self.assertEqual(responses, ["retry ok"])
        self.assertEqual(len(attempts), 2)
        self.assertIn("LLM provider error on attempt 1", contents)

    def test_run_agent_loop_reports_after_llm_retry_exhaustion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conversation = root / "conversation"
            conversation.write_text("initial", encoding="utf-8")

            with unittest.mock.patch.object(
                self.mod,
                "call_llm",
                return_value=(None, "persistent bridge failure"),
            ):
                code, responses = self.mod.run_agent_loop(
                    conversation,
                    root,
                    self.mod.LlmSettings(provider="openai", model="gpt-5.5"),
                    "hello",
                    "4242",
                    json_mode=True,
                )
            contents = conversation.read_text(encoding="utf-8")

        self.assertEqual(code, 1)
        self.assertEqual(
            responses,
            ["Error: LLM provider failed after 3 attempts; nagent cannot continue."],
        )
        self.assertIn("LLM provider error on attempt 3", contents)
        self.assertIn("persistent bridge failure", contents)

    def test_run_agent_loop_appends_initial_reads_before_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conversation = root / "conversation"
            conversation.write_text("initial", encoding="utf-8")
            first = root / "first.txt"
            second = root / "second.txt"
            first.write_text("first content", encoding="utf-8")
            second.write_text("second content", encoding="utf-8")

            with unittest.mock.patch.object(
                self.mod,
                "call_llm",
                return_value=("<nagent-response>ok</nagent-response>", None),
            ):
                code, responses = self.mod.run_agent_loop(
                    conversation,
                    root,
                    self.mod.LlmSettings(provider="openai", model="gpt-5.5"),
                    "prompt content",
                    "4242",
                    json_mode=True,
                    initial_read_paths=[str(first), str(second)],
                )
            contents = conversation.read_text(encoding="utf-8")

        self.assertEqual(code, 0)
        self.assertEqual(responses, ["ok"])
        self.assertLess(contents.index("first content"), contents.index("second content"))
        self.assertLess(contents.index("second content"), contents.index("<user-prompt>"))
        self.assertIn("prompt content", contents)

    def test_run_hook_block_reports_output_and_exit_code(self):
        ok = self.mod.run_hook("echo HOOK_OK", "hook-per-run")
        self.assertIn('<hook-per-run exit_code="0">', ok)
        self.assertIn("HOOK_OK", ok)
        self.assertIn("</hook-per-run>", ok)

        # A failing hook surfaces its non-zero exit and stderr, not silence.
        bad = self.mod.run_hook("echo OOPS >&2; exit 3", "hook-per-file-edit", path="x.c")
        self.assertIn('<hook-per-file-edit exit_code="3" path="x.c">', bad)
        self.assertIn("OOPS", bad)

        # A silent hook still records that it ran.
        quiet = self.mod.run_hook("true", "hook-per-run")
        self.assertIn("(no output)", quiet)

    def test_hook_per_run_runs_before_every_turn(self):
        # Two turns (an action turn that continues, then a final response):
        # the per-run hook must inject fresh status at the top of each.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conversation = root / "conversation"
            conversation.write_text("", encoding="utf-8")
            call_llm = unittest.mock.Mock(
                side_effect=[
                    ("<nagent-shell>echo work</nagent-shell>", None),
                    ("<nagent-response>done</nagent-response>", None),
                ]
            )
            with unittest.mock.patch.object(self.mod, "call_llm", call_llm):
                code, responses = self.mod.run_agent_loop(
                    conversation,
                    root,
                    self.mod.LlmSettings(provider="openai", model="gpt-5.5"),
                    "prompt",
                    "4242",
                    json_mode=True,
                    hook_per_run="echo STATUS_MARKER",
                )
            contents = conversation.read_text(encoding="utf-8")

        self.assertEqual(code, 0)
        self.assertEqual(call_llm.call_count, 2)
        self.assertEqual(contents.count('<hook-per-run exit_code="0">'), 2)
        self.assertEqual(contents.count("STATUS_MARKER"), 2)
        # The first hook output precedes the first agent-response (status first).
        self.assertLess(contents.index("STATUS_MARKER"), contents.index("<agent-response>"))

    def test_hook_per_file_edit_runs_after_file_patch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conversation = root / "conversation"
            conversation.write_text("", encoding="utf-8")
            tags, _ignored, err = self.mod.parse_response(
                '<nagent-file-patch index="/tmp/nonexistent-index.json" />'
            )
            self.assertIsNone(err)
            self.mod.process_tags(
                tags,
                conversation,
                root,
                None,
                NAGENT,
                "4242",
                self.mod.TokenStats(),
                None,
                None,
                "echo COMPILED",
            )
            contents = conversation.read_text(encoding="utf-8")

        # The patch result is recorded, and the verify hook fires right after it.
        self.assertIn('<hook-per-file-edit exit_code="0"', contents)
        self.assertIn("COMPILED", contents)

    def test_resolve_hooks_cli_overrides_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.json"
            config.write_text(
                json.dumps({"hook_per_run": "cfg-run", "hook_per_file_edit": ""}),
                encoding="utf-8",
            )
            # Config supplies per-run; empty per-file-edit string means disabled.
            self.assertEqual(self.mod.resolve_hooks(None, None, config), ("cfg-run", None))
            # CLI wins over config.
            self.assertEqual(
                self.mod.resolve_hooks("cli-run", "cli-edit", config), ("cli-run", "cli-edit")
            )
            # No CLI, no config file at all -> both disabled.
            self.assertEqual(
                self.mod.resolve_hooks(None, None, Path(tmp) / "missing.json"), (None, None)
            )

    def test_default_pid_prefers_screen_window(self):
        env = os.environ.copy()
        env.update({"STY": "screen-name", "WINDOW": "7", "BASHPID": "9999"})
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(self.mod.default_pid(), "screen-name-7")

    def test_default_pid_prefers_bashpid_without_screen(self):
        env = os.environ.copy()
        env.pop("STY", None)
        env.pop("WINDOW", None)
        env["BASHPID"] = "9999"
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(self.mod.default_pid(), "9999")

    def test_default_pid_falls_back_to_parent_shell(self):
        env = os.environ.copy()
        env.pop("STY", None)
        env.pop("WINDOW", None)
        env.pop("BASHPID", None)
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            with unittest.mock.patch.object(self.mod.os, "getppid", return_value=4242):
                self.assertEqual(self.mod.default_pid(), "4242")

    def test_default_conversation_name_uses_pid(self):
        name = self.mod.default_conversation_name("4242")
        self.assertTrue(name.endswith("-4242"))
        self.assertIn("latest-", name)

    def test_load_root_context_reads_context_md(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "context.md").write_text("Project-specific guidance.\n", encoding="utf-8")

            self.assertEqual(self.mod.load_root_context(root), "Project-specific guidance.")

    def test_load_root_context_expands_context_yaml_recursively(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            nested = root / "nested"
            nested.mkdir()
            (root / "one.md").write_text("First context.\n", encoding="utf-8")
            (nested / "two.md").write_text("Second context.\n", encoding="utf-8")
            (nested / "context.yaml").write_text("- nested/two.md\n- missing.md\n", encoding="utf-8")
            (root / "context.yaml").write_text("- one.md\n- nested/context.yaml\n", encoding="utf-8")

            self.assertEqual(
                self.mod.load_root_context(root),
                "First context.\n\nSecond context.",
            )

    def test_build_initial_context_orders_stable_before_volatile(self):
        # Role and protocol lead; context blocks follow; instance facts and
        # environment are the volatile tail so request prefixes stay shareable.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "context.md").write_text("Custom root context.", encoding="utf-8")
            context = self.mod.build_initial_context(
                root,
                NAGENT.resolve(),
                "user",
                "conv",
            )

        self.assertIn("Custom root context.", context)
        self.assertLess(
            context.index("User invocation:"),
            context.index("Respond only with"),
        )
        self.assertLess(
            context.index("Respond only with"),
            context.index("Custom root context."),
        )
        self.assertLess(
            context.index("Custom root context."),
            context.index("Instance:"),
        )
        self.assertLess(
            context.index("Instance:"),
            context.index("Environment:"),
        )

    def test_build_initial_context_states_loop_contract_and_conversation_reuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            context = self.mod.build_initial_context(
                Path(tmp),
                NAGENT.resolve(),
                "user",
                "conv",
            )

        # Loop contract and raw-body protocol rules.
        self.assertIn("Never fabricate results", context)
        self.assertIn("Tag bodies are raw text", context)
        self.assertIn("first matching close tag ends the body", context)
        self.assertIn("error status is data", context)
        # Conversations-as-data direction.
        self.assertIn("Conversations are data", context)
        self.assertIn("Reuse a worker", context)
        self.assertIn("Author a worker's context", context)
        self.assertIn("Hand off when noisy", context)
        self.assertIn("Never rewrite your own conversation file while running", context)
        self.assertIn("the user may edit it between runs", context)

    def test_resolve_initial_prompt_prefers_cli_prompt(self):
        with unittest.mock.patch.object(self.mod.sys, "stdin", io.StringIO("from stdin")):
            self.assertEqual(self.mod.resolve_initial_prompt("from cli"), "from cli")

    def test_resolve_initial_prompt_joins_prompt_parts(self):
        self.assertEqual(self.mod.resolve_initial_prompt(["from", "cli"]), "from cli")

    def test_resolve_initial_prompt_reads_explicit_stdin_prompt(self):
        with unittest.mock.patch.object(self.mod.sys, "stdin", io.StringIO("from stdin")):
            self.assertEqual(self.mod.resolve_initial_prompt(["-"]), "from stdin")

    def test_resolve_initial_prompt_appends_explicit_stdin_to_prompt(self):
        with unittest.mock.patch.object(self.mod.sys, "stdin", io.StringIO("from stdin")):
            self.assertEqual(
                self.mod.resolve_initial_prompt(["summarize", "-"]),
                "summarize\nfrom stdin",
            )

    def test_resolve_initial_prompt_reads_piped_stdin(self):
        with unittest.mock.patch.object(self.mod.sys, "stdin", io.StringIO("from stdin")):
            self.assertEqual(self.mod.resolve_initial_prompt(None), "from stdin")

    def test_resolve_initial_prompt_treats_empty_stdin_as_absent(self):
        with unittest.mock.patch.object(self.mod.sys, "stdin", io.StringIO("")):
            self.assertIsNone(self.mod.resolve_initial_prompt(None))

    def test_resolve_initial_prompt_skips_unready_pipe(self):
        read_fd, write_fd = os.pipe()
        stdin = os.fdopen(read_fd, "r", encoding="utf-8")
        try:
            with unittest.mock.patch.object(self.mod.sys, "stdin", stdin):
                self.assertIsNone(self.mod.resolve_initial_prompt(None))
        finally:
            stdin.close()
            os.close(write_fd)

    def test_resolve_initial_prompt_ignores_tty_stdin(self):
        stdin = unittest.mock.Mock()
        stdin.isatty.return_value = True
        with unittest.mock.patch.object(self.mod.sys, "stdin", stdin):
            self.assertIsNone(self.mod.resolve_initial_prompt(None))
            stdin.read.assert_not_called()

    def test_execute_read_accepts_relative_paths_from_cwd(self):
        with tempfile.TemporaryDirectory() as tmp:
            previous = Path.cwd()
            try:
                os.chdir(tmp)
                Path("relative.txt").write_text("relative content", encoding="utf-8")
                result = self.mod.execute_read("relative.txt")
            finally:
                os.chdir(previous)

        self.assertIn("relative content", result)

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
            self.assertIn("--json", captured["cmd"])
            self.assertIn("4242", captured["cmd"][captured["cmd"].index("--conversation") + 1])

    def test_execute_agent_accepts_conversation_file_option(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            captured: dict[str, list[str]] = {}

            def fake_run(cmd, **kwargs):
                captured["cmd"] = cmd
                return unittest.mock.Mock(returncode=0, stdout="", stderr="")

            with unittest.mock.patch.object(self.mod.subprocess, "run", fake_run):
                self.mod.execute_agent(
                    "do task",
                    root,
                    self.mod.LlmSettings(provider="openai", model="gpt-5.5"),
                    NAGENT,
                    "parent-conv",
                    "4242",
                    conversation_file="existing-conv",
                )

        self.assertEqual(captured["cmd"][captured["cmd"].index("--conversation") + 1], "existing-conv")

    def test_execute_agent_loads_saved_conversation_name_option(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            saved = root / "saved-outside-conversations"
            saved.write_text("saved history", encoding="utf-8")
            self.mod.update_saved_conversations_index(
                root,
                "4242",
                "saved",
                saved,
                "summary",
            )
            captured: dict[str, list[str]] = {}

            def fake_run(cmd, **kwargs):
                captured["cmd"] = cmd
                return unittest.mock.Mock(returncode=0, stdout="", stderr="")

            with unittest.mock.patch.object(self.mod.subprocess, "run", fake_run):
                self.mod.execute_agent(
                    "do task",
                    root,
                    self.mod.LlmSettings(provider="openai", model="gpt-5.5"),
                    NAGENT,
                    "parent-conv",
                    "4242",
                    conversation_name="saved",
                )

            child_name = captured["cmd"][captured["cmd"].index("--conversation") + 1]
            child_conversation = root / "conversations" / child_name
            self.assertEqual(child_conversation.read_text(encoding="utf-8"), "saved history")
            self.assertNotEqual(child_name, "saved")

    def test_execute_agent_adds_recursive_token_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def fake_run(cmd, **kwargs):
                return unittest.mock.Mock(
                    returncode=0,
                    stdout=json.dumps(
                        {
                            "responses": ["done"],
                            "recursive_input_tokens": 21,
                            "recursive_output_tokens": 8,
                        }
                    ),
                    stderr="",
                )

            stats = self.mod.TokenStats()
            with unittest.mock.patch.object(self.mod.subprocess, "run", fake_run):
                result = self.mod.execute_agent(
                    "do task",
                    root,
                    self.mod.LlmSettings(provider="openai", model="gpt-5.5"),
                    NAGENT,
                    "parent-conv",
                    "4242",
                    stats,
                )

        self.assertIn('tokens_in="21"', result)
        self.assertIn("done", result)
        self.assertEqual(stats.recursive_input_tokens, 21)
        self.assertEqual(stats.recursive_output_tokens, 8)

    def test_token_status_line_format(self):
        stats = self.mod.TokenStats(
            turn_count=2,
            conversation_input_tokens=100,
            recursive_input_tokens=150,
            recursive_output_tokens=40,
        )
        self.assertEqual(
            stats.status_line(),
            "[Turns:2 Conversation-Tokens:100 Tokens-In:150 Tokens-Out:40]",
        )

    def test_call_llm_wait_spinner_names_provider_and_model(self):
        # The spinner says what it's waiting on; model is omitted when empty
        # (e.g. claude-code using Claude Code's configured model).
        cases = [
            (self.mod.LlmSettings(provider="openai", model="gpt-5.5"), "Waiting for openai/gpt-5.5"),
            (self.mod.LlmSettings(provider="claude-code", model=""), "Waiting for claude-code"),
        ]
        for settings, expected in cases:
            with tempfile.TemporaryDirectory() as tmp:
                conversation = Path(tmp) / "conversation"
                conversation.write_text("prompt text", encoding="utf-8")
                result = unittest.mock.Mock(
                    returncode=0,
                    stdout=json.dumps(
                        {
                            "response": "<nagent-response>ok</nagent-response>",
                            "input_tokens": 4,
                            "output_tokens": 2,
                        }
                    ),
                    stderr="",
                )

                with unittest.mock.patch.object(self.mod, "WaitSpinner") as spinner, \
                    unittest.mock.patch.object(self.mod.subprocess, "run", return_value=result):
                    self.mod.call_llm(
                        conversation,
                        settings,
                        self.mod.TokenStats(),
                    )

            spinner.assert_called_once_with(expected, enabled=True)

    def test_main_prints_final_status_for_user_direct_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def fake_run_agent_loop(*args, **kwargs):
                token_stats = kwargs["token_stats"]
                token_stats.turn_count = 2
                token_stats.conversation_input_tokens = 100
                token_stats.recursive_input_tokens = 150
                token_stats.recursive_output_tokens = 40
                print("done")
                return 0, ["done"]

            argv = [
                "nagent",
                "--root",
                str(root),
                "--conversation",
                "conv",
                "hello",
            ]
            with unittest.mock.patch.object(self.mod.sys, "argv", argv), \
                unittest.mock.patch.object(self.mod.sys, "stdout", io.StringIO()) as stdout, \
                unittest.mock.patch.object(self.mod, "require_credentials"), \
                unittest.mock.patch.object(self.mod, "run_agent_loop", fake_run_agent_loop):
                code = self.mod.main()

            self.assertEqual(code, 0)
            self.assertEqual(
                stdout.getvalue().strip().splitlines(),
                [
                    "done",
                    "[Turns:2 Conversation-Tokens:100 Tokens-In:150 Tokens-Out:40]",
                ],
            )

    def test_main_omits_final_status_when_pid_is_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def fake_run_agent_loop(*args, **kwargs):
                token_stats = kwargs["token_stats"]
                token_stats.turn_count = 2
                print("done")
                return 0, ["done"]

            argv = [
                "nagent",
                "--root",
                str(root),
                "--conversation",
                "conv",
                "--pid",
                "4242",
                "hello",
            ]
            with unittest.mock.patch.object(self.mod.sys, "argv", argv), \
                unittest.mock.patch.object(self.mod.sys, "stdout", io.StringIO()) as stdout, \
                unittest.mock.patch.object(self.mod, "require_credentials"), \
                unittest.mock.patch.object(self.mod, "run_agent_loop", fake_run_agent_loop):
                code = self.mod.main()

            self.assertEqual(code, 0)
            self.assertEqual(stdout.getvalue().strip().splitlines(), ["done"])

    def test_main_allows_read_without_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.txt"
            source.write_text("source content", encoding="utf-8")
            captured: dict[str, object] = {}

            def fake_run_agent_loop(*args, **kwargs):
                captured["initial_prompt"] = args[3]
                captured["initial_read_paths"] = kwargs["initial_read_paths"]
                return 0, []

            argv = [
                "nagent",
                "--root",
                str(root),
                "--conversation",
                "conv",
                "--pid",
                "4242",
                "--read",
                str(source),
            ]
            with unittest.mock.patch.object(self.mod.sys, "argv", argv), \
                unittest.mock.patch.object(self.mod, "require_credentials"), \
                unittest.mock.patch.object(self.mod, "run_agent_loop", fake_run_agent_loop):
                code = self.mod.main()

        self.assertEqual(code, 0)
        self.assertIsNone(captured["initial_prompt"])
        self.assertEqual(captured["initial_read_paths"], [str(source)])

    def test_main_records_keyboard_interrupt(self):
        mod = load_nagent_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            argv = [
                "nagent",
                "--root",
                str(root),
                "--conversation",
                "conv",
                "hello",
            ]

            def fake_run_agent_loop(*args, **kwargs):
                raise KeyboardInterrupt()

            with unittest.mock.patch.object(mod.sys, "argv", argv), \
                unittest.mock.patch.object(mod.sys, "stdout", io.StringIO()) as stdout, \
                unittest.mock.patch.object(mod, "require_credentials"), \
                unittest.mock.patch.object(mod, "run_agent_loop", fake_run_agent_loop):
                code = mod.main()

            conversation = root / "conversations" / "conv"
            self.assertEqual(code, 130)
            self.assertEqual(stdout.getvalue(), "Interrupted...\n")
            self.assertTrue(conversation.exists())
            self.assertIn("Interrupted...", conversation.read_text(encoding="utf-8"))

    def test_save_and_load_conversation_helpers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current = root / "conversations" / "current"
            saved = root / "conversations" / "saved"
            current.parent.mkdir(parents=True)
            current.write_text("current history", encoding="utf-8")

            self.mod.save_conversation(current, saved)
            self.assertEqual(saved.read_text(encoding="utf-8"), "current history")
            self.assertEqual(current.read_text(encoding="utf-8"), "current history")

            source = root / "conversations" / "source"
            source.write_text("loaded history", encoding="utf-8")
            archived = self.mod.load_conversation(current, source)

            self.assertIsNotNone(archived)
            self.assertEqual(current.read_text(encoding="utf-8"), "loaded history")
            self.assertEqual(archived.read_text(encoding="utf-8"), "current history")

    def test_summarize_saved_conversation_uses_file_summarize_max_word_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            conversation = Path(tmp) / "conversation"
            conversation.write_text("conversation history", encoding="utf-8")
            captured: dict[str, list[str]] = {}

            def fake_run(cmd, **kwargs):
                captured["cmd"] = cmd
                return unittest.mock.Mock(
                    returncode=0,
                    stdout=json.dumps({"summary": "short summary"}),
                    stderr="",
                )

            with unittest.mock.patch.object(self.mod.subprocess, "run", fake_run):
                summary = self.mod.summarize_saved_conversation(
                    conversation,
                    "openai",
                    "gpt-5.5",
                    None,
                )

        self.assertEqual(summary, "short summary")
        self.assertIn("--max-word-count", captured["cmd"])
        self.assertEqual(
            captured["cmd"][captured["cmd"].index("--max-word-count") + 1],
            "50",
        )
        self.assertIn("--json", captured["cmd"])

    def test_saved_conversations_index_records_and_replaces_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            saved = root / "conversations" / "saved"
            saved.parent.mkdir(parents=True)
            saved.write_text("conversation history", encoding="utf-8")

            index = self.mod.update_saved_conversations_index(
                root,
                "4242",
                "saved",
                saved,
                "first summary",
            )
            self.mod.update_saved_conversations_index(
                root,
                "4242",
                "saved",
                saved,
                "updated summary",
            )
            payload = json.loads(index.read_text(encoding="utf-8"))

        self.assertEqual(payload["pid"], "4242")
        self.assertEqual(len(payload["conversations"]), 1)
        self.assertEqual(payload["conversations"][0]["name"], "saved")
        self.assertEqual(payload["conversations"][0]["path"], str(saved.resolve()))
        self.assertEqual(payload["conversations"][0]["summary"], "updated summary")

    def test_main_save_conversation_is_instant_with_extracted_summary(self):
        # Saving is a file copy: no LLM call, no credentials. The index
        # summary is extracted deterministically from the first user prompt.
        mod = load_nagent_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current = root / "conversations" / "current"
            current.parent.mkdir(parents=True)
            current.write_text(
                "<initial_context>\nrules\n</initial_context>\n"
                "<user-prompt>\nMigrate the config loader to the new format\n</user-prompt>\n"
                "<agent-response>\nworking\n</agent-response>\n",
                encoding="utf-8",
            )

            def llm_must_not_run(*args, **kwargs):
                raise AssertionError("save must not call the LLM")

            argv = [
                "nagent",
                "--root",
                str(root),
                "--conversation",
                "current",
                "--pid",
                "4242",
                "--save-conversation",
                "saved",
            ]
            with unittest.mock.patch.object(mod.sys, "argv", argv), \
                unittest.mock.patch.object(mod.sys, "stdout", io.StringIO()) as stdout, \
                unittest.mock.patch.object(mod, "summarize_saved_conversation", llm_must_not_run):
                code = mod.main()

            saved = root / "conversations" / "saved"
            index = root / "conversations" / "index-saved-conversations-4242.json"
            payload = json.loads(index.read_text(encoding="utf-8"))

            self.assertEqual(code, 0)
            entry = payload["conversations"][0]
            self.assertEqual(entry["path"], str(saved.resolve()))
            self.assertEqual(entry["summary"], "Migrate the config loader to the new format")
            self.assertEqual(entry["summary_source"], "extracted")
            self.assertIn(f"saved:{saved}", stdout.getvalue())

    def test_extract_conversation_summary_prefers_checkpoint_intent(self):
        mod = load_nagent_module()
        with tempfile.TemporaryDirectory() as tmp:
            conversation = Path(tmp) / "conv"
            conversation.write_text(
                "<user-prompt>\nthe original ask\n</user-prompt>\n", encoding="utf-8"
            )
            checkpoint = mod.checkpoint_path(conversation)
            checkpoint.write_text(
                "# Checkpoint: conv\nupdated: 2026-06-12T00:00:00+00:00\n"
                "conversation_chars: 10\n\n## Intent\n- replace the loader end to end\n"
                "## Next action\n- run tests\n",
                encoding="utf-8",
            )
            summary = mod.extract_conversation_summary(conversation)
            self.assertEqual(summary, "replace the loader end to end")

    def test_extract_conversation_summary_falls_back_and_truncates(self):
        mod = load_nagent_module()
        with tempfile.TemporaryDirectory() as tmp:
            conversation = Path(tmp) / "conv"
            long_prompt = "word " * 60
            conversation.write_text(
                f"<user-prompt>\n{long_prompt}\n</user-prompt>\n", encoding="utf-8"
            )
            summary = mod.extract_conversation_summary(conversation)
            self.assertTrue(summary.endswith("..."))
            self.assertLessEqual(len(summary), mod.SUMMARY_EXTRACT_MAX_CHARS + 3)

            bare = Path(tmp) / "bare"
            bare.write_text("no prompt block here", encoding="utf-8")
            self.assertEqual(mod.extract_conversation_summary(bare), "")

    def test_main_summarize_conversation_upgrades_index_entry(self):
        mod = load_nagent_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            saved = root / "conversations" / "saved"
            saved.parent.mkdir(parents=True)
            saved.write_text("saved history", encoding="utf-8")
            mod.update_saved_conversations_index(
                root, "4242", "saved", saved, "the original ask", summary_source="extracted"
            )

            def fake_summarize(path, provider, model, config_path):
                self.assertEqual(path, saved)
                return "a proper llm summary"

            argv = [
                "nagent",
                "--root",
                str(root),
                "--pid",
                "4242",
                "--summarize-conversation",
                "saved",
            ]
            with unittest.mock.patch.object(mod.sys, "argv", argv), \
                unittest.mock.patch.object(mod.sys, "stdout", io.StringIO()) as stdout, \
                unittest.mock.patch.object(mod, "summarize_saved_conversation", fake_summarize):
                code = mod.main()

            self.assertEqual(code, 0)
            self.assertIn("a proper llm summary", stdout.getvalue())
            index = root / "conversations" / "index-saved-conversations-4242.json"
            entry = json.loads(index.read_text(encoding="utf-8"))["conversations"][0]
            self.assertEqual(entry["summary"], "a proper llm summary")
            self.assertEqual(entry["summary_source"], "llm")

    def test_main_fresh_conversation_builds_initial_context_once(self):
        # A fresh conversation (the path every delegated sub-conversation
        # takes) must pay tool discovery and git probes exactly once, not
        # create-then-refresh.
        mod = load_nagent_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_calls: list[tuple] = []
            real_build = mod.build_initial_context

            def counting_build(*args, **kwargs):
                build_calls.append(args)
                return real_build(*args, **kwargs)

            def fake_run_agent_loop(conversation_file, *args, **kwargs):
                return 0, ["done"]

            argv = [
                "nagent",
                "--root",
                str(root),
                "--conversation",
                "conv",
                "--pid",
                "4242",
                "hello",
            ]
            with unittest.mock.patch.object(mod.sys, "argv", argv), \
                unittest.mock.patch.object(mod.sys, "stdout", io.StringIO()), \
                unittest.mock.patch.object(mod, "require_credentials"), \
                unittest.mock.patch.object(mod, "build_initial_context", counting_build), \
                unittest.mock.patch.object(mod, "run_agent_loop", fake_run_agent_loop):
                code = mod.main()

            self.assertEqual(code, 0)
            self.assertEqual(len(build_calls), 1)
            contents = (root / "conversations" / "conv").read_text(encoding="utf-8")
            self.assertTrue(contents.startswith("<initial_context>"))

    def test_load_conversation_from_current_path_archives_and_restores(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current = root / "conversations" / "current"
            current.parent.mkdir(parents=True)
            current.write_text("current history", encoding="utf-8")

            archived = self.mod.load_conversation(current, current)

            self.assertIsNotNone(archived)
            self.assertEqual(current.read_text(encoding="utf-8"), "current history")
            self.assertEqual(archived.read_text(encoding="utf-8"), "current history")
            self.assertNotEqual(archived, current)

    def test_summarize_conversation_sends_conversation_prompt_to_llm(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conversation = root / "conversations" / "conv"
            conversation.parent.mkdir(parents=True)
            conversation.write_text("conversation history", encoding="utf-8")
            captured: dict[str, str] = {}

            def fake_run(cmd, **kwargs):
                prompt_path = Path(cmd[cmd.index("--file") + 1])
                captured["prompt"] = prompt_path.read_text(encoding="utf-8")
                payload = {
                    "response": "summary ok",
                    "input_tokens": 30,
                    "output_tokens": 4,
                }
                return unittest.mock.Mock(returncode=0, stdout=json.dumps(payload), stderr="")

            stdout = io.StringIO()
            with unittest.mock.patch.object(self.mod, "require_credentials"), \
                unittest.mock.patch.object(self.mod.subprocess, "run", fake_run), \
                unittest.mock.patch.object(sys, "stdout", stdout):
                code = self.mod.summarize_conversation(
                    conversation,
                    "openai",
                    "gpt-5.5",
                    None,
                )

            self.assertEqual(code, 0)
            self.assertEqual(stdout.getvalue(), "summary ok\n")
            self.assertIn("Summarize the following nagent conversation", captured["prompt"])
            self.assertIn("conversation history", captured["prompt"])
            self.assertIn("Do not summarize nagent as a tool", captured["prompt"])

    def test_summarize_conversation_prints_status_for_user_direct_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conversation = root / "conversations" / "conv"
            conversation.parent.mkdir(parents=True)
            conversation.write_text("conversation history", encoding="utf-8")

            def fake_run(cmd, **kwargs):
                payload = {
                    "response": "summary ok",
                    "input_tokens": 30,
                    "output_tokens": 4,
                }
                return unittest.mock.Mock(returncode=0, stdout=json.dumps(payload), stderr="")

            stdout = io.StringIO()
            with unittest.mock.patch.object(self.mod, "require_credentials"), \
                unittest.mock.patch.object(self.mod.subprocess, "run", fake_run), \
                unittest.mock.patch.object(sys, "stdout", stdout):
                code = self.mod.summarize_conversation(
                    conversation,
                    "openai",
                    "gpt-5.5",
                    None,
                    print_status=True,
                )

            self.assertEqual(code, 0)
            self.assertEqual(
                stdout.getvalue().strip().splitlines(),
                [
                    "summary ok",
                    "[Turns:1 Conversation-Tokens:5 Tokens-In:30 Tokens-Out:4]",
                ],
            )

    def test_edit_conversation_edits_backup_then_loads_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conversation = root / "conversations" / "conv"
            conversation.parent.mkdir(parents=True)
            conversation.write_text("old history", encoding="utf-8")
            captured: dict[str, list[str]] = {}

            def fake_run(cmd, **kwargs):
                if "--file-edit" not in cmd:
                    return unittest.mock.Mock(returncode=1, stdout="", stderr="")
                captured["cmd"] = cmd
                backup = Path(cmd[cmd.index("--file-edit") + 1])
                backup.write_text("edited history", encoding="utf-8")
                return unittest.mock.Mock(returncode=0, stdout="", stderr="")

            stdout = io.StringIO()
            with unittest.mock.patch.object(self.mod.subprocess, "run", fake_run):
                with unittest.mock.patch.object(sys, "stdout", stdout):
                    code = self.mod.edit_conversation(
                        conversation,
                        root,
                        NAGENT.resolve(),
                        "user",
                        "conv",
                        "4242",
                        None,
                        "remove noise",
                        "openai",
                        "gpt-5.5",
                        None,
                    )

            self.assertEqual(code, 0)
            # The edited backup is loaded, then initial context is restored on load.
            contents = conversation.read_text(encoding="utf-8")
            self.assertTrue(contents.startswith("<initial_context>"))
            self.assertTrue(contents.endswith("edited history"))
            self.assertIn("--clear", captured["cmd"])
            self.assertEqual(captured["cmd"][-1], "remove noise")

    def test_edit_conversation_rolls_up_child_token_stats(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conversation = root / "conversations" / "conv"
            conversation.parent.mkdir(parents=True)
            conversation.write_text("old history", encoding="utf-8")

            child_payload = {
                "exit_code": 0,
                "responses": ["ok"],
                "turn_count": 3,
                "conversation_input_tokens": 120,
                "recursive_input_tokens": 300,
                "recursive_output_tokens": 40,
                "tokens_in": 300,
                "tokens_out": 40,
            }

            def fake_run(cmd, **kwargs):
                if "--file-edit" not in cmd:
                    return unittest.mock.Mock(returncode=1, stdout="", stderr="")
                backup = Path(cmd[cmd.index("--file-edit") + 1])
                backup.write_text("edited history", encoding="utf-8")
                return unittest.mock.Mock(
                    returncode=0, stdout=json.dumps(child_payload), stderr=""
                )

            stdout = io.StringIO()
            with unittest.mock.patch.object(self.mod.subprocess, "run", fake_run):
                with unittest.mock.patch.object(sys, "stdout", stdout):
                    code = self.mod.edit_conversation(
                        conversation,
                        root,
                        NAGENT.resolve(),
                        "user",
                        "conv",
                        "4242",
                        None,
                        "remove noise",
                        "openai",
                        "gpt-5.5",
                        None,
                        json_mode=True,
                    )

            self.assertEqual(code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["turn_count"], 3)
            self.assertEqual(payload["tokens_in"], 300)
            self.assertEqual(payload["tokens_out"], 40)
            self.assertEqual(payload["conversation_input_tokens"], 120)

    def test_compact_prompt_path_prefers_root_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(self.mod.compact_prompt_path(root), self.mod.COMPACT_PROMPT_PATH)

            user_prompt = root / "prompts" / "compact-conversation.md"
            user_prompt.parent.mkdir(parents=True)
            user_prompt.write_text("custom guidance", encoding="utf-8")
            self.assertEqual(self.mod.compact_prompt_path(root), user_prompt)


class InitialTextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_nagent_module()

    def test_delegated_initial_text(self):
        text = self.mod.create_initial_text(
            Path("/tmp/nagent-root"),
            NAGENT.resolve(),
            "delegated",
            "sub-conversation-1",
            "parent-conv",
        )
        self.assertIn("invocation: delegated", text)
        self.assertIn("conversation: sub-conversation-1", text)
        self.assertIn("parent conversation: parent-conv", text)
        self.assertIn("Delegated invocation:", text)
        self.assertIn("parent nagent conversation spawned you", text)
        self.assertIn("spawn a sub-conversation only when it buys something", text)
        self.assertIn("<nagent-conversation>{prompt}</nagent-conversation>", text)
        self.assertNotIn("<nagent-agent>", text)
        self.assertNotIn("User invocation:", text)

    def test_install_context_injected_before_root_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            install = Path(tmp) / "install"
            (install / "bin").mkdir(parents=True)
            (install / "context").mkdir()
            (install / "context" / "rules.md").write_text(
                "install context rules", encoding="utf-8"
            )
            (install / "context.yaml").write_text("- context/rules.md\n", encoding="utf-8")
            root = Path(tmp) / "root"
            root.mkdir()
            (root / "context.md").write_text("root context body", encoding="utf-8")

            text = self.mod.build_initial_context(
                root,
                install / "bin" / "nagent",
                "user",
                "conv",
            )

            self.assertIn("install context rules", text)
            self.assertIn("root context body", text)
            self.assertLess(
                text.index("install context rules"), text.index("root context body")
            )

    def test_project_context_included_from_git_toplevel(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "proj"
            (project / "sub").mkdir(parents=True)
            subprocess.run(["git", "init"], cwd=project, check=True, capture_output=True)
            (project / "context.md").write_text("PROJECT-CONTEXT-MARKER", encoding="utf-8")
            root = Path(tmp) / "root"
            root.mkdir()

            previous_cwd = os.getcwd()
            os.chdir(project / "sub")
            try:
                text = self.mod.build_initial_context(root, NAGENT.resolve(), "user", "conv")
            finally:
                os.chdir(previous_cwd)

        self.assertIn("PROJECT-CONTEXT-MARKER", text)

    def test_context_layers_ordered_install_user_project_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            install = Path(tmp) / "install"
            (install / "bin").mkdir(parents=True)
            (install / "context.md").write_text("INSTALL-MARKER", encoding="utf-8")
            home = Path(tmp) / "home"
            (home / ".nagent").mkdir(parents=True)
            (home / ".nagent" / "context.md").write_text("USER-MARKER", encoding="utf-8")
            project = Path(tmp) / "proj"
            project.mkdir()
            subprocess.run(["git", "init"], cwd=project, check=True, capture_output=True)
            (project / "context.md").write_text("PROJECT-MARKER", encoding="utf-8")
            root = project / ".nagent"
            root.mkdir()
            (root / "context.md").write_text("ROOT-MARKER", encoding="utf-8")

            previous_cwd = os.getcwd()
            os.chdir(project)
            try:
                with unittest.mock.patch.dict(os.environ, {"HOME": str(home)}):
                    text = self.mod.build_initial_context(
                        root, install / "bin" / "nagent", "user", "conv"
                    )
            finally:
                os.chdir(previous_cwd)

        positions = [
            text.index("INSTALL-MARKER"),
            text.index("USER-MARKER"),
            text.index("PROJECT-MARKER"),
            text.index("ROOT-MARKER"),
        ]
        self.assertEqual(positions, sorted(positions))
        # Each layer appears exactly once.
        for marker in ("INSTALL-MARKER", "USER-MARKER", "PROJECT-MARKER", "ROOT-MARKER"):
            self.assertEqual(text.count(marker), 1, marker)

    def test_context_layers_dedup_when_root_is_user_root(self):
        # Outside a repo the root is ~/.nagent: the user layer and the root
        # layer are the same directory and its context appears once.
        with tempfile.TemporaryDirectory() as tmp:
            install = Path(tmp) / "install"
            (install / "bin").mkdir(parents=True)
            home = Path(tmp) / "home"
            (home / ".nagent").mkdir(parents=True)
            (home / ".nagent" / "context.md").write_text("USER-MARKER", encoding="utf-8")
            outside = Path(tmp) / "outside"
            outside.mkdir()

            previous_cwd = os.getcwd()
            os.chdir(outside)
            try:
                with unittest.mock.patch.dict(os.environ, {"HOME": str(home)}):
                    text = self.mod.build_initial_context(
                        home / ".nagent", install / "bin" / "nagent", "user", "conv"
                    )
            finally:
                os.chdir(previous_cwd)

        self.assertEqual(text.count("USER-MARKER"), 1)

    def test_project_context_not_duplicated_inside_install_checkout(self):
        # Running nagent from within its own checkout: the project toplevel is
        # the install dir, whose context is already included once.
        with tempfile.TemporaryDirectory() as tmp:
            install = Path(tmp) / "install"
            (install / "bin").mkdir(parents=True)
            subprocess.run(["git", "init"], cwd=install, check=True, capture_output=True)
            (install / "context.md").write_text("INSTALL-AND-PROJECT-MARKER", encoding="utf-8")
            root = Path(tmp) / "root"
            root.mkdir()

            previous_cwd = os.getcwd()
            os.chdir(install)
            try:
                text = self.mod.build_initial_context(
                    root, install / "bin" / "nagent", "user", "conv"
                )
            finally:
                os.chdir(previous_cwd)

        self.assertEqual(text.count("INSTALL-AND-PROJECT-MARKER"), 1)

    def test_project_context_ordered_between_install_and_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            install = Path(tmp) / "install"
            (install / "bin").mkdir(parents=True)
            (install / "context.md").write_text("INSTALL-MARKER", encoding="utf-8")
            project = Path(tmp) / "proj"
            project.mkdir()
            subprocess.run(["git", "init"], cwd=project, check=True, capture_output=True)
            (project / "context.md").write_text("PROJECT-MARKER", encoding="utf-8")
            root = Path(tmp) / "root"
            root.mkdir()
            (root / "context.md").write_text("ROOT-MARKER", encoding="utf-8")

            previous_cwd = os.getcwd()
            os.chdir(project)
            try:
                text = self.mod.build_initial_context(
                    root, install / "bin" / "nagent", "user", "conv"
                )
            finally:
                os.chdir(previous_cwd)

        self.assertLess(text.index("INSTALL-MARKER"), text.index("PROJECT-MARKER"))
        self.assertLess(text.index("PROJECT-MARKER"), text.index("ROOT-MARKER"))

    def test_repo_context_yaml_delivers_design_rules(self):
        # The shipped context.yaml routes context/data-oriented-design.md into
        # every initial context built from this checkout.
        text = self.mod.build_initial_context(
            Path("/tmp/nagent-root"),
            NAGENT.resolve(),
            "user",
            "conv",
        )
        self.assertIn("Data-Oriented Design", text)

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
        self.assertIn("- git toplevel/project-root: /home/macton/nagent", context)
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
        self.assertIn("project-root:", text)
        self.assertIn("git toplevel/project-root:", text)
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


class WaitSpinnerTests(unittest.TestCase):
    def test_wait_spinner_disabled_does_not_raise(self):
        mod = load_nagent_module()
        mod.set_spinner_enabled(False)
        with mod.wait_spinner("Testing"):
            pass

    def test_wait_spinner_uses_activity_message(self):
        mod = load_nagent_module()
        with unittest.mock.patch.object(mod, "WaitSpinner") as spinner:
            mod.wait_spinner("Testing")

        spinner.assert_called_once_with("Testing", enabled=True)


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

    def test_refresh_initial_context_preserves_backslashes_in_new_context(self):
        # Rebuilt context can contain backslash sequences (file summaries,
        # root context, uname output). They must be inserted literally, not
        # interpreted as re replacement escapes like \s or \g<0>.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conversation_file = root / "conv"
            conversation_file.write_text(
                "<initial_context>\nold\n</initial_context>\n<user-prompt>\nhello\n</user-prompt>\n",
                encoding="utf-8",
            )
            new_context = "<initial_context>\nuses \\s and \\g<0> in parsing\n</initial_context>"
            with unittest.mock.patch.object(
                self.mod,
                "build_initial_context",
                return_value=new_context,
            ):
                self.mod.refresh_initial_context(
                    conversation_file,
                    root,
                    NAGENT.resolve(),
                    "user",
                    "conv",
                )
            contents = conversation_file.read_text(encoding="utf-8")
            self.assertIn("uses \\s and \\g<0> in parsing", contents)
            self.assertNotIn("old", contents.split("<user-prompt>")[0])

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

    def test_list_providers_cli(self):
        # Static catalog: no credentials, no network, no root creation.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "nagent-root"
            result = subprocess.run(
                [str(NAGENT), "--root", str(root), "--list-providers"],
                capture_output=True,
                text=True,
                env=self.clean_env(),
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("openai", result.stdout)
        self.assertIn("together", result.stdout)
        self.assertIn("TOGETHER_API_KEY", result.stdout)
        self.assertIn("(alias: gemini)", result.stdout)
        self.assertFalse(root.exists())

    def test_list_providers_cli_json(self):
        result = subprocess.run(
            [str(NAGENT), "--list-providers", "--json"],
            capture_output=True,
            text=True,
            env=self.clean_env(),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        names = [entry["provider"] for entry in payload["providers"]]
        self.assertIn("together", names)
        self.assertNotIn("gemini", names)

    def test_status_shows_reasoning_level_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "r"
            config = Path(tmp) / "config.json"
            config.write_text(
                '{"provider": "anthropic", "model": "claude-fable-5", "reasoning": 4}',
                encoding="utf-8",
            )
            result = subprocess.run(
                [str(NAGENT), "--root", str(root), "--conversation", "c", "--config", str(config), "--status"],
                capture_output=True,
                text=True,
                env=self.clean_env(),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            # --status shows the resolved provider-native name for the level.
            self.assertIn("reasoning:xhigh (4/5)", result.stdout)

            override = subprocess.run(
                [str(NAGENT), "--root", str(root), "--conversation", "c", "--config", str(config),
                 "--reasoning", "1", "--status"],
                capture_output=True,
                text=True,
                env=self.clean_env(),
            )
            self.assertEqual(override.returncode, 0, override.stderr)
            self.assertIn("reasoning:low (1/5)", override.stdout)

    def test_list_file_edits_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "tracked.py"
            source.write_text("x\n", encoding="utf-8")
            subprocess.run(
                [
                    str(NAGENT),
                    "--file-edit",
                    str(source),
                    "--root",
                    str(root),
                    "--pid",
                    "1234",
                    "--clear",
                ],
                capture_output=True,
                text=True,
                env={**self.clean_env(), "BASHPID": "1234"},
            )
            result = subprocess.run(
                [
                    str(NAGENT),
                    "--root",
                    str(root),
                    "--pid",
                    "1234",
                    "--list-file-edits",
                    "--json",
                ],
                capture_output=True,
                text=True,
                env={**self.clean_env(), "BASHPID": "1234"},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["pid"], "1234")
            self.assertEqual(len(payload["files"]), 1)
            self.assertEqual(payload["files"][0]["path"], str(source.resolve()))

    def test_list_conversations_cli_reads_saved_conversation_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            saved = root / "conversations" / "saved"
            saved.parent.mkdir(parents=True)
            saved.write_text("conversation history", encoding="utf-8")
            index = root / "conversations" / "index-saved-conversations-1234.json"
            index.write_text(
                json.dumps(
                    {
                        "pid": "1234",
                        "index_path": str(index.resolve()),
                        "conversations": [
                            {
                                "name": "saved",
                                "path": str(saved.resolve()),
                                "summary": "short summary",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    str(NAGENT),
                    "--root",
                    str(root),
                    "--pid",
                    "1234",
                    "--list-conversations",
                    "--json",
                ],
                capture_output=True,
                text=True,
                env={**self.clean_env(), "BASHPID": "1234"},
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["pid"], "1234")
        self.assertEqual(payload["conversations"][0]["name"], "saved")
        self.assertEqual(payload["conversations"][0]["path"], str(saved.resolve()))
        self.assertEqual(payload["conversations"][0]["summary"], "short summary")

    def test_status_prints_path_size_provider_and_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conv = "status-test"
            conversation_file = root / "conversations" / conv
            conversation_file.parent.mkdir(parents=True)
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
            self.assertEqual(lines[1], "provider:openai model:gpt-5.5 reasoning:default")

    def test_status_honors_provider_and_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conv = "status-test"
            conversation_file = root / "conversations" / conv

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
            self.assertEqual(lines[1], "provider:anthropic model:claude-test reasoning:default")

    def test_status_missing_conversation_reports_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conv = "missing-conv"
            conversation_file = root / "conversations" / conv

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
            self.assertEqual(lines[1], "provider:openai model:gpt-5.5 reasoning:default")

    def test_clear_archives_existing_conversation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conv = "clear-test"
            conversation_file = root / "conversations" / conv
            conversation_file.parent.mkdir(parents=True)
            conversation_file.write_text("<user-prompt>\nold history\n</user-prompt>\n", encoding="utf-8")

            result = subprocess.run(
                [str(NAGENT), "--root", str(root), "--conversation", conv, "--clear"],
                capture_output=True,
                text=True,
                env=self.clean_env(),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            lines = result.stdout.strip().splitlines()
            self.assertTrue(lines[0].startswith("archived:"))
            self.assertEqual(lines[1], f"conversation:{conversation_file}")

            archived_path = Path(lines[0].split(":", 1)[1])
            self.assertTrue(archived_path.is_file())
            self.assertIn("old history", archived_path.read_text(encoding="utf-8"))
            self.assertNotEqual(archived_path, conversation_file)

            fresh = conversation_file.read_text(encoding="utf-8")
            self.assertIn("<initial_context>", fresh)
            self.assertNotIn("old history", fresh)

    def test_default_root_is_project_dotdir_inside_git_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "proj"
            project.mkdir()
            subprocess.run(["git", "init"], cwd=project, check=True, capture_output=True)

            result = subprocess.run(
                [str(NAGENT), "--conversation", "conv", "--status"],
                capture_output=True,
                text=True,
                cwd=project,
                env=self.clean_env(),
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            expected = project / ".nagent" / "conversations" / "conv"
            self.assertIn(f"conversation:{expected}", result.stdout)
            # --status is read-only: it must not create the root.
            self.assertFalse((project / ".nagent").exists())

    def test_explicit_root_still_wins_inside_git_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "proj"
            project.mkdir()
            subprocess.run(["git", "init"], cwd=project, check=True, capture_output=True)
            explicit = Path(tmp) / "elsewhere"

            result = subprocess.run(
                [str(NAGENT), "--root", str(explicit), "--conversation", "conv", "--status"],
                capture_output=True,
                text=True,
                cwd=project,
                env=self.clean_env(),
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(f"conversation:{explicit / 'conversations' / 'conv'}", result.stdout)

    def test_fresh_root_gets_gitignore_scaffold(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "fresh-root"

            result = subprocess.run(
                [str(NAGENT), "--root", str(root), "--conversation", "conv", "--clear"],
                capture_output=True,
                text=True,
                env=self.clean_env(),
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((root / ".gitignore").read_text(encoding="utf-8"), "splits/\n")

    def test_existing_root_does_not_gain_gitignore(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "old-root"
            root.mkdir()

            result = subprocess.run(
                [str(NAGENT), "--root", str(root), "--conversation", "conv", "--clear"],
                capture_output=True,
                text=True,
                env=self.clean_env(),
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((root / ".gitignore").exists())

    def test_clear_without_existing_conversation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conv = "clear-new"
            conversation_file = root / "conversations" / conv

            result = subprocess.run(
                [str(NAGENT), "--root", str(root), "--conversation", conv, "--clear"],
                capture_output=True,
                text=True,
                env=self.clean_env(),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                result.stdout.strip(),
                f"conversation:{conversation_file}",
            )
            self.assertTrue(conversation_file.is_file())
            self.assertIn("<initial_context>", conversation_file.read_text(encoding="utf-8"))

    def test_branch_conversation_copies_named_conversation_and_exits_without_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current = "current"
            source = "source"
            current_file = root / "conversations" / current
            source_file = root / "conversations" / source
            current_file.parent.mkdir(parents=True)
            current_file.write_text("current history", encoding="utf-8")
            source_file.write_text("source history", encoding="utf-8")

            result = subprocess.run(
                [
                    str(NAGENT),
                    "--root",
                    str(root),
                    "--conversation",
                    current,
                    "--branch-conversation",
                    source,
                ],
                capture_output=True,
                text=True,
                env=self.clean_env(),
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            # The branched copy is loaded, then initial context is restored on load.
            contents = current_file.read_text(encoding="utf-8")
            self.assertTrue(contents.startswith("<initial_context>"))
            self.assertTrue(contents.endswith("source history"))
            lines = result.stdout.strip().splitlines()
            self.assertTrue(lines[0].startswith("archived:"))
            self.assertEqual(lines[1], f"loaded:{source_file}")
            self.assertEqual(lines[2], f"conversation:{current_file}")
            archived_path = Path(lines[0].split(":", 1)[1])
            self.assertEqual(archived_path.read_text(encoding="utf-8"), "current history")

    def test_branch_conversation_missing_name_errors_without_archiving_current(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current = "current"
            current_file = root / "conversations" / current
            current_file.parent.mkdir(parents=True)
            current_file.write_text("current history", encoding="utf-8")

            result = subprocess.run(
                [
                    str(NAGENT),
                    "--root",
                    str(root),
                    "--conversation",
                    current,
                    "--branch-conversation",
                    "missing",
                ],
                capture_output=True,
                text=True,
                env=self.clean_env(),
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("conversation not found", result.stderr)
            self.assertEqual(current_file.read_text(encoding="utf-8"), "current history")
            self.assertEqual(list(current_file.parent.glob("current-*")), [])

    def test_branch_conversation_with_prompt_continues_from_copied_conversation(self):
        mod = load_nagent_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current = "current"
            source = "source"
            current_file = root / "conversations" / current
            source_file = root / "conversations" / source
            current_file.parent.mkdir(parents=True)
            current_file.write_text("current history", encoding="utf-8")
            source_file.write_text("source history", encoding="utf-8")

            captured: dict[str, object] = {}

            def fake_run_agent_loop(conversation_file, *args, **kwargs):
                captured["conversation_text"] = conversation_file.read_text(encoding="utf-8")
                captured["initial_prompt"] = args[2]
                return 0, []

            argv = [
                "nagent",
                "--root",
                str(root),
                "--conversation",
                current,
                "--pid",
                "4242",
                "--branch-conversation",
                source,
                "hello",
            ]
            with unittest.mock.patch.object(mod.sys, "argv", argv), \
                unittest.mock.patch.object(mod.sys, "stdout", io.StringIO()), \
                unittest.mock.patch.object(mod, "require_credentials"), \
                unittest.mock.patch.object(mod, "run_agent_loop", fake_run_agent_loop):
                code = mod.main()

            self.assertEqual(code, 0)
            self.assertIn("source history", captured["conversation_text"])
            self.assertNotIn("current history", captured["conversation_text"])
            self.assertEqual(captured["initial_prompt"], "hello")

    def test_legacy_root_conversation_moves_to_conversations_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conv = "legacy-conv"
            legacy_file = root / conv
            conversation_file = root / "conversations" / conv
            legacy_file.write_text("legacy history", encoding="utf-8")

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
            self.assertFalse(legacy_file.exists())
            self.assertEqual(conversation_file.read_text(encoding="utf-8"), "legacy history")
            self.assertEqual(
                result.stdout.strip().splitlines()[0],
                f"conversation:{conversation_file} size:{conversation_file.stat().st_size}",
            )

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

            code, responses = mod.run_agent_loop(
                conversation_file,
                root,
                mod.LlmSettings(provider="openai", model="gpt-5.5"),
                "hello",
                "4242",
            )
            self.assertEqual(code, 0)
            self.assertEqual(responses, ["seed ok"])

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
            self.assertIn("Context management (every nagent conversation", contents)
            self.assertIn("<nagent-conversation>{prompt}</nagent-conversation>", contents)
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

            conversation = Path(tmp) / "conversations" / "live-test"
            self.assertTrue(conversation.exists())
            self.assertIn("<user-prompt>", conversation.read_text(encoding="utf-8"))


class RebuildDueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_nagent_module()

    def test_byte_threshold_fires_when_window_unknown(self):
        settings = {"rebuild_at_kb": 384, "context_window_tokens": 0}
        self.assertFalse(self.mod.rebuild_due(100 * 1024, settings))
        self.assertTrue(self.mod.rebuild_due(400 * 1024, settings))

    def test_token_cap_fires_before_byte_threshold_for_small_window(self):
        # 16384-token window x 0.85 ~= 13926 tokens ~= 55703 chars, far below
        # the 384 KB byte ceiling — so the token cap is the binding trigger.
        settings = {"rebuild_at_kb": 384, "context_window_tokens": 16384}
        self.assertFalse(self.mod.rebuild_due(40_000, settings))   # ~10k tokens
        self.assertTrue(self.mod.rebuild_due(80_000, settings))    # ~20k tokens

    def test_large_window_leaves_byte_threshold_as_the_binding_trigger(self):
        # DeepSeek-V4-Pro: 512000 tokens. 384 KB (~98k tokens) trips long
        # before 512000 x 0.85, so the byte ceiling is what fires.
        settings = {"rebuild_at_kb": 384, "context_window_tokens": 512000}
        self.assertFalse(self.mod.rebuild_due(300 * 1024, settings))
        self.assertTrue(self.mod.rebuild_due(400 * 1024, settings))

    def test_unknown_window_does_not_fabricate_a_cap(self):
        # Large conversation, unknown window, byte ceiling not yet tripped:
        # must NOT rebuild on a guessed token cap.
        settings = {"rebuild_at_kb": 384, "context_window_tokens": 0}
        self.assertFalse(self.mod.rebuild_due(300_000, settings))


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

    def test_provider_override_uses_matching_default_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            config_path.write_text('{"provider": "openai", "model": "gpt-5.5"}', encoding="utf-8")
            provider, model = self.mod.resolve_settings(provider="gemini", config_path=config_path)

        self.assertEqual(provider, "google")
        self.assertEqual(model, self.mod.default_model("google"))

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

    def test_openai_usage_counts_are_preserved(self):
        class FakeResponses:
            def create(self, **kwargs):
                usage = unittest.mock.Mock(input_tokens=31, output_tokens=7)
                return unittest.mock.Mock(output_text="ok", usage=usage)

        class FakeClient:
            responses = FakeResponses()

        with unittest.mock.patch.object(self.mod, "require_package", return_value=lambda: FakeClient()):
            result = self.mod.generate_text_with_usage("hello", "openai", "gpt-5.5")

        self.assertEqual(result.text, "ok")
        self.assertEqual(result.input_tokens, 31)
        self.assertEqual(result.output_tokens, 7)

    def test_together_streams_chat_completions_and_preserves_usage(self):
        captured = {}

        def make_chunk(content=None, usage=None):
            choices = []
            if content is not None:
                choices = [unittest.mock.Mock(delta=unittest.mock.Mock(content=content))]
            return unittest.mock.Mock(choices=choices, usage=usage)

        class FakeCompletions:
            def create(self, **kwargs):
                captured.update(kwargs)
                usage = type("FakeUsage", (), {"prompt_tokens": 17, "completion_tokens": 4})()
                # Stream: text deltas, then a usage-only final chunk (no choices).
                return iter([
                    make_chunk(content="together "),
                    make_chunk(content="ok"),
                    make_chunk(content=None, usage=usage),
                ])

        class FakeChat:
            completions = FakeCompletions()

        class FakeClient:
            chat = FakeChat()

        def fake_openai(**kwargs):
            captured["client_kwargs"] = kwargs
            return FakeClient()

        with unittest.mock.patch.object(self.mod, "require_package", return_value=fake_openai), \
            unittest.mock.patch.dict(os.environ, {"TOGETHER_API_KEY": "test-key"}, clear=False):
            result = self.mod.generate_text_with_usage("hello together", "together", "some-model")

        self.assertEqual(result.text, "together ok")
        self.assertEqual(result.input_tokens, 17)
        self.assertEqual(result.output_tokens, 4)
        self.assertEqual(captured["model"], "some-model")
        self.assertEqual(captured["messages"], [{"role": "user", "content": "hello together"}])
        # Must stream: some Together models (e.g. Qwen3.7-Plus) reject non-streamed requests.
        self.assertTrue(captured["stream"])
        self.assertEqual(captured["stream_options"], {"include_usage": True})
        self.assertEqual(captured["client_kwargs"]["base_url"], self.mod.TOGETHER_BASE_URL)
        self.assertEqual(captured["client_kwargs"]["api_key"], "test-key")

    def test_list_models_together_parses_bare_array(self):
        # Together returns a top-level JSON array, not OpenAI's {"data": [...]}.
        import contextlib
        import io

        payload = json.dumps(
            [{"id": "meta-llama/Llama-3.3-70B-Instruct-Turbo"}, {"id": "deepseek-ai/DeepSeek-V3"}]
        ).encode("utf-8")

        @contextlib.contextmanager
        def fake_urlopen(request):
            captured["url"] = request.full_url
            captured["auth"] = request.headers.get("Authorization")
            yield io.BytesIO(payload)

        captured = {}
        with unittest.mock.patch("urllib.request.urlopen", fake_urlopen), \
            unittest.mock.patch.dict(os.environ, {"TOGETHER_API_KEY": "test-key"}, clear=False):
            models = self.mod.list_models("together")

        self.assertEqual(
            models, ["deepseek-ai/DeepSeek-V3", "meta-llama/Llama-3.3-70B-Instruct-Turbo"]
        )
        self.assertEqual(captured["url"], f"{self.mod.TOGETHER_BASE_URL}/models")
        self.assertEqual(captured["auth"], "Bearer test-key")

    def test_openrouter_streams_chat_completions_and_preserves_usage(self):
        captured = {}

        def make_chunk(content=None, usage=None):
            choices = []
            if content is not None:
                choices = [unittest.mock.Mock(delta=unittest.mock.Mock(content=content))]
            return unittest.mock.Mock(choices=choices, usage=usage)

        class FakeCompletions:
            def create(self, **kwargs):
                captured.update(kwargs)
                usage = type("FakeUsage", (), {"prompt_tokens": 11, "completion_tokens": 3})()
                return iter([
                    make_chunk(content="openrouter "),
                    make_chunk(content="ok"),
                    make_chunk(content=None, usage=usage),
                ])

        class FakeChat:
            completions = FakeCompletions()

        class FakeClient:
            chat = FakeChat()

        def fake_openai(**kwargs):
            captured["client_kwargs"] = kwargs
            return FakeClient()

        with unittest.mock.patch.object(self.mod, "require_package", return_value=fake_openai), \
            unittest.mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}, clear=False):
            result = self.mod.generate_text_with_usage("hello openrouter", "openrouter", "stealth/ox-alpha")

        self.assertEqual(result.text, "openrouter ok")
        self.assertEqual(result.input_tokens, 11)
        self.assertEqual(result.output_tokens, 3)
        self.assertEqual(captured["model"], "stealth/ox-alpha")
        self.assertEqual(captured["messages"], [{"role": "user", "content": "hello openrouter"}])
        self.assertTrue(captured["stream"])
        self.assertEqual(captured["stream_options"], {"include_usage": True})
        self.assertEqual(captured["client_kwargs"]["base_url"], self.mod.OPENROUTER_BASE_URL)
        self.assertEqual(captured["client_kwargs"]["api_key"], "test-key")

    def test_list_models_openrouter_parses_data_envelope(self):
        import contextlib
        import io

        payload = json.dumps(
            {"data": [{"id": "stealth/ox-alpha"}, {"id": "openai/gpt-5.1"}]}
        ).encode("utf-8")

        @contextlib.contextmanager
        def fake_urlopen(request):
            captured["url"] = request.full_url
            captured["auth"] = request.headers.get("Authorization")
            yield io.BytesIO(payload)

        captured = {}
        with unittest.mock.patch("urllib.request.urlopen", fake_urlopen), \
            unittest.mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}, clear=False):
            models = self.mod.list_models("openrouter")

        self.assertEqual(models, ["openai/gpt-5.1", "stealth/ox-alpha"])
        self.assertEqual(captured["url"], f"{self.mod.OPENROUTER_BASE_URL}/models")
        self.assertEqual(captured["auth"], "Bearer test-key")

    def test_model_context_window_known_and_unknown(self):
        # Verified against the Together API; the V4-Pro value was confirmed by
        # a context_length_exceeded error from the provider.
        self.assertEqual(self.mod.model_context_window("deepseek-ai/DeepSeek-V4-Pro"), 512000)
        self.assertEqual(self.mod.model_context_window("deepseek-ai/DeepSeek-V3.1"), 131072)
        # Qwen3.7-Plus advertises 1,000,000 total but enforces input <= 983616.
        self.assertEqual(self.mod.model_context_window("Qwen/Qwen3.7-Plus"), 983616)
        # Unknown -> None means "fall back to the byte threshold", not a guess.
        self.assertIsNone(self.mod.model_context_window("some/unknown-model"))

    def test_resolve_reasoning_integer_scale_maps_per_provider(self):
        self.assertEqual(self.mod.resolve_reasoning("anthropic", 4).native, "xhigh")
        self.assertEqual(self.mod.resolve_reasoning("openai", 1).native, "minimal")
        self.assertEqual(self.mod.resolve_reasoning("google", 5).native, -1)
        # digit strings are treated as the integer scale, not pass-through
        self.assertEqual(self.mod.resolve_reasoning("anthropic", "2").native, "medium")
        # out-of-range clamps to 1..5
        self.assertEqual(self.mod.resolve_reasoning("anthropic", 9).native, "max")
        self.assertEqual(self.mod.resolve_reasoning("anthropic", 0).native, "low")

    def test_resolve_reasoning_default_and_unsupported(self):
        default = self.mod.resolve_reasoning("openai", None)
        self.assertIsNone(default.native)
        self.assertEqual(default.label, "default")
        # Together has no portable per-level knob -> nothing sent, flagged unsupported.
        together = self.mod.resolve_reasoning("together", 3)
        self.assertIsNone(together.native)
        self.assertFalse(together.supported)
        self.assertIn("unsupported", together.label)

    def test_resolve_reasoning_string_passthrough(self):
        passthrough = self.mod.resolve_reasoning("anthropic", "xhigh")
        self.assertEqual(passthrough.native, "xhigh")
        self.assertIn("provider-specific", passthrough.label)
        # a provider-specific name is honored even where the integer scale isn't
        self.assertEqual(self.mod.resolve_reasoning("together", "low").native, "low")

    def test_reasoning_label_shows_provider_native_name(self):
        self.assertEqual(self.mod.resolve_reasoning("anthropic", 4).label, "xhigh (4/5)")
        self.assertEqual(self.mod.resolve_reasoning("google", 5).label, "dynamic (5/5)")
        self.assertEqual(self.mod.resolve_reasoning("google", 1).label, "off (1/5)")

    def test_openai_applies_reasoning_effort(self):
        captured = {}

        class FakeResponses:
            def create(self, **kwargs):
                captured.update(kwargs)
                usage = unittest.mock.Mock(input_tokens=1, output_tokens=1)
                return unittest.mock.Mock(output_text="ok", usage=usage)

        class FakeClient:
            responses = FakeResponses()

        with unittest.mock.patch.object(self.mod, "require_package", return_value=lambda: FakeClient()):
            self.mod.generate_text_with_usage("hi", "openai", "gpt-5.5", reasoning=4)
        self.assertEqual(captured["reasoning"], {"effort": "high"})

    def test_openai_omits_reasoning_when_unset(self):
        captured = {}

        class FakeResponses:
            def create(self, **kwargs):
                captured.update(kwargs)
                return unittest.mock.Mock(output_text="ok", usage=unittest.mock.Mock(input_tokens=1, output_tokens=1))

        class FakeClient:
            responses = FakeResponses()

        with unittest.mock.patch.object(self.mod, "require_package", return_value=lambda: FakeClient()):
            self.mod.generate_text_with_usage("hi", "openai", "gpt-5.5")
        self.assertNotIn("reasoning", captured)

    def test_anthropic_applies_effort(self):
        captured = {}

        class FakeMessages:
            def create(self, **kwargs):
                captured.update(kwargs)
                return unittest.mock.Mock(content=[], usage=None)

        class FakeClient:
            def __init__(self):
                self.messages = FakeMessages()

        fake_anthropic = unittest.mock.Mock(Anthropic=FakeClient)
        with unittest.mock.patch.object(self.mod, "require_package", return_value=fake_anthropic):
            self.mod.generate_text_with_usage("hi", "anthropic", "claude-fable-5", reasoning=5)
        self.assertEqual(captured["output_config"], {"effort": "max"})

    def test_google_applies_thinking_budget(self):
        captured = {}

        class FakeModels:
            def generate_content(self, **kwargs):
                captured.update(kwargs)
                return unittest.mock.Mock(text="ok", usage_metadata=None)

        class FakeClient:
            models = FakeModels()

        fake_genai = unittest.mock.Mock(Client=lambda api_key: FakeClient())
        with unittest.mock.patch.object(self.mod, "require_package", return_value=fake_genai), \
            unittest.mock.patch.dict(os.environ, {"GEMINI_API_KEY": "k"}, clear=False):
            self.mod.generate_text_with_usage("hi", "google", "gemini-2.5-flash", reasoning=3)
        self.assertEqual(captured["config"].thinking_config.thinking_budget, 8192)

    def test_together_passes_reasoning_effort_passthrough(self):
        captured = {}

        def make_chunk(content=None, usage=None):
            choices = [unittest.mock.Mock(delta=unittest.mock.Mock(content=content))] if content is not None else []
            return unittest.mock.Mock(choices=choices, usage=usage)

        class FakeCompletions:
            def create(self, **kwargs):
                captured.update(kwargs)
                usage = type("U", (), {"prompt_tokens": 1, "completion_tokens": 1})()
                return iter([make_chunk(content="ok"), make_chunk(usage=usage)])

        class FakeChat:
            completions = FakeCompletions()

        class FakeClient:
            chat = FakeChat()

        with unittest.mock.patch.object(self.mod, "require_package", return_value=lambda **k: FakeClient()), \
            unittest.mock.patch.dict(os.environ, {"TOGETHER_API_KEY": "k"}, clear=False):
            self.mod.generate_text_with_usage("hi", "together", "Qwen/Qwen3.7-Plus", reasoning="low")
        self.assertEqual(captured["extra_body"], {"reasoning_effort": "low"})

    def test_list_providers_catalog(self):
        catalog = self.mod.list_providers()
        names = [entry["provider"] for entry in catalog]
        # Canonical providers only — aliases are reported under their target.
        self.assertEqual(names, list(self.mod.DEFAULT_MODELS))
        self.assertNotIn("gemini", names)
        by_name = {entry["provider"]: entry for entry in catalog}
        self.assertEqual(by_name["google"]["aliases"], ["gemini"])
        self.assertEqual(by_name["together"]["default_model"], self.mod.DEFAULT_MODELS["together"])
        self.assertEqual(by_name["together"]["credentials"], ["TOGETHER_API_KEY"])
        self.assertEqual(by_name["openrouter"]["default_model"], "stealth/ox-alpha")
        self.assertEqual(by_name["openrouter"]["credentials"], ["OPENROUTER_API_KEY"])
        # claude-code manages its own login: empty credential list.
        self.assertEqual(by_name["claude-code"]["credentials"], [])

    def test_together_resolves_with_default_model(self):
        provider, model = self.mod.resolve_settings(provider="together")
        self.assertEqual(provider, "together")
        self.assertEqual(model, self.mod.DEFAULT_MODELS["together"])

    def test_openrouter_resolves_with_default_model(self):
        provider, model = self.mod.resolve_settings(provider="openrouter")
        self.assertEqual(provider, "openrouter")
        self.assertEqual(model, "stealth/ox-alpha")

    def test_together_upload_rejects_non_image(self):
        with tempfile.NamedTemporaryFile(suffix=".pdf") as handle:
            with self.assertRaises(ValueError):
                self.mod._together_upload(Path(handle.name), "summarize", "some-model")

    def test_openrouter_upload_rejects_non_image(self):
        with tempfile.NamedTemporaryFile(suffix=".pdf") as handle:
            with self.assertRaises(ValueError):
                self.mod._openrouter_upload(Path(handle.name), "summarize", "stealth/ox-alpha")

    def test_gemini_usage_counts_are_preserved(self):
        class FakeModels:
            def generate_content(self, **kwargs):
                usage = type(
                    "FakeUsage",
                    (),
                    {"prompt_token_count": 29, "candidates_token_count": 6},
                )()
                return unittest.mock.Mock(text="ok", usage_metadata=usage)

        class FakeClient:
            models = FakeModels()

        fake_genai = unittest.mock.Mock(Client=lambda api_key: FakeClient())
        with unittest.mock.patch.object(self.mod, "require_package", return_value=fake_genai), \
            unittest.mock.patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}, clear=False):
            result = self.mod.generate_text_with_usage("hello", "google", "gemini-2.5-flash")

        self.assertEqual(result.text, "ok")
        self.assertEqual(result.input_tokens, 29)
        self.assertEqual(result.output_tokens, 6)

    def test_cursor_usage_counts_fall_back_to_estimates(self):
        class FakeAgent:
            @staticmethod
            def prompt(message, options):
                return unittest.mock.Mock(status="finished", result="cursor ok")

        class FakeAgentOptions:
            def __init__(self, **kwargs):
                pass

        class FakeLocalAgentOptions:
            def __init__(self, **kwargs):
                pass

        with unittest.mock.patch.object(
            self.mod,
            "require_package",
            return_value=(FakeAgent, FakeAgentOptions, FakeLocalAgentOptions),
        ), unittest.mock.patch.dict(os.environ, {"CURSOR_API_KEY": "test-key"}, clear=False):
            result = self.mod.generate_text_with_usage("hello cursor", "cursor", "composer-2.5")

        self.assertEqual(result.text, "cursor ok")
        self.assertEqual(result.input_tokens, self.mod.estimate_token_count("hello cursor"))
        self.assertEqual(result.output_tokens, self.mod.estimate_token_count("cursor ok"))

    def _fake_claude_code_package(self, messages, captured_options):
        import asyncio

        class FakeTextBlock:
            def __init__(self, text):
                self.text = text

        class FakeAssistantMessage:
            def __init__(self, blocks, error=None):
                self.content = blocks
                self.error = error

        class FakeResultMessage:
            def __init__(self, result, usage=None, is_error=False, errors=None):
                self.result = result
                self.usage = usage
                self.is_error = is_error
                self.errors = errors

        class FakeOptions:
            def __init__(self, **kwargs):
                captured_options.update(kwargs)

        class FakeAnyio:
            @staticmethod
            def run(fn):
                return asyncio.run(fn())

        def fake_query(*, prompt, options):
            async def iterate():
                for message in messages(FakeAssistantMessage, FakeTextBlock, FakeResultMessage):
                    yield message

            return iterate()

        return (
            FakeAnyio,
            fake_query,
            FakeOptions,
            FakeAssistantMessage,
            FakeResultMessage,
            FakeTextBlock,
        ), FakeResultMessage

    def test_claude_code_text_generation_uses_result_and_usage(self):
        captured_options: dict = {}

        def messages(FakeAssistantMessage, FakeTextBlock, FakeResultMessage):
            return [
                FakeAssistantMessage([FakeTextBlock("partial")]),
                FakeResultMessage("claude-code ok", usage={"input_tokens": 21, "output_tokens": 5}),
            ]

        package, _ = self._fake_claude_code_package(messages, captured_options)
        with unittest.mock.patch.object(self.mod, "require_package", return_value=package):
            result = self.mod.generate_text_with_usage("hello", "claude-code", "default")

        self.assertEqual(result.text, "claude-code ok")
        self.assertEqual(result.input_tokens, 21)
        self.assertEqual(result.output_tokens, 5)
        # "default" model means: let Claude Code use its configured model.
        self.assertIsNone(captured_options["model"])
        self.assertEqual(captured_options["max_turns"], 1)
        self.assertEqual(captured_options["tools"], [])

    def test_claude_code_missing_model_means_default(self):
        # Not specifying a model behaves exactly like specifying "default".
        for model in (None, ""):
            captured_options: dict = {}

            def messages(FakeAssistantMessage, FakeTextBlock, FakeResultMessage):
                return [FakeResultMessage("ok")]

            package, _ = self._fake_claude_code_package(messages, captured_options)
            with unittest.mock.patch.object(self.mod, "require_package", return_value=package):
                result = self.mod.generate_text_with_usage("hello", "claude-code", model)

            self.assertEqual(result.text, "ok")
            self.assertIsNone(captured_options["model"], f"model={model!r}")

    def test_claude_code_explicit_model_and_text_fallback(self):
        captured_options: dict = {}

        def messages(FakeAssistantMessage, FakeTextBlock, FakeResultMessage):
            return [
                FakeAssistantMessage([FakeTextBlock("from blocks")]),
                FakeResultMessage(None),
            ]

        package, _ = self._fake_claude_code_package(messages, captured_options)
        with unittest.mock.patch.object(self.mod, "require_package", return_value=package):
            result = self.mod.generate_text_with_usage("hello", "claude-code", "claude-opus-4-8")

        self.assertEqual(result.text, "from blocks")
        self.assertEqual(captured_options["model"], "claude-opus-4-8")

    def test_claude_code_error_result_raises(self):
        captured_options: dict = {}

        def messages(FakeAssistantMessage, FakeTextBlock, FakeResultMessage):
            return [FakeResultMessage(None, is_error=True, errors=["login required"])]

        package, _ = self._fake_claude_code_package(messages, captured_options)
        with unittest.mock.patch.object(self.mod, "require_package", return_value=package):
            with self.assertRaisesRegex(RuntimeError, "login required"):
                self.mod.generate_text_with_usage("hello", "claude-code", "default")

    def test_claude_code_error_result_survives_stream_exception(self):
        # After an error result the CLI exits non-zero; the SDK yields the
        # ResultMessage (real error text) and THEN raises a generic exception
        # ("Claude Code returned an error result: success"). The provider must
        # report the result's text, not the masked exception.
        captured_options: dict = {}

        def messages(FakeAssistantMessage, FakeTextBlock, FakeResultMessage):
            yield FakeAssistantMessage(
                [FakeTextBlock("Credit balance is too low")], error="billing_error"
            )
            yield FakeResultMessage("Credit balance is too low", is_error=True)
            raise Exception("Claude Code returned an error result: success")

        package, _ = self._fake_claude_code_package(messages, captured_options)
        with unittest.mock.patch.object(self.mod, "require_package", return_value=package):
            with self.assertRaisesRegex(RuntimeError, "Credit balance is too low"):
                self.mod.generate_text_with_usage("hello", "claude-code", "default")

    def test_claude_code_stream_exception_without_error_result_propagates(self):
        captured_options: dict = {}

        def messages(FakeAssistantMessage, FakeTextBlock, FakeResultMessage):
            yield FakeAssistantMessage([FakeTextBlock("partial")])
            raise Exception("transport died")

        package, _ = self._fake_claude_code_package(messages, captured_options)
        with unittest.mock.patch.object(self.mod, "require_package", return_value=package):
            with self.assertRaisesRegex(Exception, "transport died"):
                self.mod.generate_text_with_usage("hello", "claude-code", "default")

    def test_claude_code_synthetic_error_text_is_not_output(self):
        # A synthetic assistant message (error attribute set) carries an error
        # report as its text; it must not be returned as generated output.
        captured_options: dict = {}

        def messages(FakeAssistantMessage, FakeTextBlock, FakeResultMessage):
            return [
                FakeAssistantMessage([FakeTextBlock("some error")], error="billing_error"),
                FakeAssistantMessage([FakeTextBlock("real output")]),
                FakeResultMessage(None),
            ]

        package, _ = self._fake_claude_code_package(messages, captured_options)
        with unittest.mock.patch.object(self.mod, "require_package", return_value=package):
            result = self.mod.generate_text_with_usage("hello", "claude-code", "default")

        self.assertEqual(result.text, "real output")

    def test_claude_code_blanks_inherited_api_key(self):
        # Billing must stay on Claude Code's own login: an inherited
        # ANTHROPIC_API_KEY would silently hijack it, so the subprocess env
        # blanks the variable.
        captured_options: dict = {}

        def messages(FakeAssistantMessage, FakeTextBlock, FakeResultMessage):
            return [FakeResultMessage("ok")]

        package, _ = self._fake_claude_code_package(messages, captured_options)
        with unittest.mock.patch.object(self.mod, "require_package", return_value=package):
            self.mod.generate_text_with_usage("hello", "claude-code", "default")

        self.assertEqual(captured_options["env"], {"ANTHROPIC_API_KEY": ""})

    def test_claude_code_upload_allows_read_tool(self):
        captured_options: dict = {}

        def messages(FakeAssistantMessage, FakeTextBlock, FakeResultMessage):
            return [FakeResultMessage("file summary", usage={"input_tokens": 9, "output_tokens": 3})]

        package, _ = self._fake_claude_code_package(messages, captured_options)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "diagram.txt"
            target.write_text("content", encoding="utf-8")
            with unittest.mock.patch.object(self.mod, "require_package", return_value=package):
                result = self.mod.generate_with_upload_usage(
                    target, "Explain this file.", "claude-code", "default"
                )

        self.assertEqual(result.text, "file summary")
        self.assertEqual(captured_options["allowed_tools"], ["Read"])
        self.assertEqual(captured_options["tools"], ["Read"])
        self.assertIsNone(captured_options["max_turns"])

    def test_claude_code_requires_no_credential_env(self):
        env = os.environ.copy()
        env.pop("ANTHROPIC_API_KEY", None)
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            # Must not sys.exit: claude-code auth is the local Claude Code login.
            self.mod.require_credentials("claude-code")

    def test_claude_code_list_models_raises_with_guidance(self):
        with self.assertRaisesRegex(RuntimeError, "does not expose a model list"):
            self.mod.list_models("claude-code")

    def test_cache_prefix_blocks_split_and_filter(self):
        message = "abcdefgh"
        blocks = self.mod.cache_prefix_blocks(message, [5, 0, 999, 5])
        self.assertEqual(
            blocks,
            [
                {"type": "text", "text": "abcde", "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": "fgh"},
            ],
        )
        # No valid boundaries: plain string passthrough.
        self.assertEqual(self.mod.cache_prefix_blocks(message, []), message)
        self.assertEqual(self.mod.cache_prefix_blocks(message, [99]), message)
        self.assertEqual(self.mod.cache_prefix_blocks(message, None), message)

    def test_anthropic_cache_boundaries_split_blocks_and_count_cached_usage(self):
        captured: dict = {}

        class FakeMessages:
            def create(self, **kwargs):
                captured.update(kwargs)
                usage = type(
                    "FakeUsage",
                    (),
                    {
                        "input_tokens": 7,
                        "output_tokens": 3,
                        "cache_read_input_tokens": 90,
                        "cache_creation_input_tokens": 10,
                    },
                )()
                block = type("FakeBlock", (), {"type": "text", "text": "anthropic ok"})()
                return type("FakeResponse", (), {"content": [block], "usage": usage})()

        fake_anthropic = unittest.mock.Mock(
            Anthropic=lambda: unittest.mock.Mock(messages=FakeMessages())
        )
        message = "s" * 100
        with unittest.mock.patch.object(self.mod, "require_package", return_value=fake_anthropic):
            result = self.mod.generate_text_with_usage(
                message, "anthropic", "claude-sonnet-4-6", cache_boundaries=[30, 60]
            )

        content = captured["messages"][0]["content"]
        self.assertEqual(len(content), 3)
        self.assertEqual(content[0]["cache_control"], {"type": "ephemeral"})
        self.assertEqual(content[1]["cache_control"], {"type": "ephemeral"})
        self.assertNotIn("cache_control", content[2])
        self.assertEqual("".join(block["text"] for block in content), message)
        self.assertEqual(result.text, "anthropic ok")
        # input = uncached 7 + cache read 90 + cache write 10
        self.assertEqual(result.input_tokens, 107)
        self.assertEqual(result.output_tokens, 3)

    def test_llm_text_forwards_cache_prefix_chars(self):
        mod = load_nagent_llm_text_module()
        captured: dict = {}

        def fake_generate(message, provider, model, cache_boundaries=None, reasoning=None):
            captured["cache_boundaries"] = cache_boundaries
            captured["reasoning"] = reasoning
            return unittest.mock.Mock(text="ok", input_tokens=1, output_tokens=1)

        with tempfile.TemporaryDirectory() as tmp:
            prompt = Path(tmp) / "prompt.txt"
            prompt.write_text("hello", encoding="utf-8")
            argv = [
                "nagent-llm-text",
                "--file",
                str(prompt),
                "--cache-prefix-chars",
                "10",
                "--cache-prefix-chars",
                "20",
            ]
            with unittest.mock.patch.object(mod.sys, "argv", argv), \
                unittest.mock.patch.object(mod, "resolve_from_args", return_value=("anthropic", "m")), \
                unittest.mock.patch.object(mod, "generate_text_with_usage", fake_generate), \
                unittest.mock.patch.object(mod.sys, "stdout", io.StringIO()):
                mod.main()

        self.assertEqual(captured["cache_boundaries"], [10, 20])

    def test_gemini_provider_alias_resolves_to_google(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider, model = self.mod.resolve_settings(
                provider="gemini",
                config_path=Path(tmp) / "missing-config.json",
            )

        self.assertEqual(provider, "google")
        self.assertEqual(model, self.mod.default_model("google"))

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
