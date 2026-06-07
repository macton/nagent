#!/usr/bin/python3

import importlib.util
import io
import json
import os
import subprocess
import tempfile
import unittest
import unittest.mock
from importlib.machinery import SourceFileLoader
from pathlib import Path

BIN = Path(__file__).resolve().parent.parent / "bin"
HELPERS = BIN / "helpers"
NAGENT = BIN / "nagent"
NAGENT_FILE_EDIT = BIN / "nagent-file-edit"


def load_file_edit_lib():
    loader = SourceFileLoader("nagent_file_edit_lib", str(HELPERS / "nagent_file_edit_lib.py"))
    spec = importlib.util.spec_from_loader("nagent_file_edit_lib", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def load_nagent_module():
    loader = SourceFileLoader("nagent_mod", str(NAGENT))
    spec = importlib.util.spec_from_loader("nagent_mod", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class FileEditLibTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_file_edit_lib()

    def test_resolve_creates_and_reuses_conversation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "sample.py"
            source.write_text("print('hi')\n", encoding="utf-8")

            name1, path1, file_id1 = self.mod.resolve_file_edit_conversation(root, "42", source)
            name2, path2, file_id2 = self.mod.resolve_file_edit_conversation(root, "42", source)

            self.assertEqual(name1, name2)
            self.assertEqual(path1, source.resolve())
            self.assertEqual(file_id1, file_id2)
            self.assertRegex(file_id1, r"^\d+:\d+$")

            index = json.loads(self.mod.file_index_path(root, "42").read_text(encoding="utf-8"))
            entry = index["by_file_id"][file_id1]
            self.assertEqual(entry["conversation"], name1)
            self.assertEqual(entry["path"], str(source.resolve()))
            self.assertTrue(name1.startswith("sample-"))

    def test_resolve_appends_multiple_files_to_same_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "first.py"
            second = root / "second.py"
            first.write_text("first\n", encoding="utf-8")
            second.write_text("second\n", encoding="utf-8")

            first_name, _, first_id = self.mod.resolve_file_edit_conversation(root, "42", first)
            second_name, _, second_id = self.mod.resolve_file_edit_conversation(root, "42", second)

            index = json.loads(self.mod.file_index_path(root, "42").read_text(encoding="utf-8"))
            self.assertEqual(set(index["by_file_id"]), {first_id, second_id})
            self.assertEqual(index["by_file_id"][first_id]["conversation"], first_name)
            self.assertEqual(index["by_file_id"][second_id]["conversation"], second_name)
            self.assertEqual(index["by_file_id"][first_id]["path"], str(first.resolve()))
            self.assertEqual(index["by_file_id"][second_id]["path"], str(second.resolve()))

    def test_migrates_legacy_path_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "legacy.py"
            source.write_text("x\n", encoding="utf-8")
            index_path = self.mod.file_index_path(root, "7")
            index_path.parent.mkdir(parents=True, exist_ok=True)
            index_path.write_text(
                json.dumps({str(source.resolve()): "legacy-conv-name"}) + "\n",
                encoding="utf-8",
            )

            name, path, file_id = self.mod.resolve_file_edit_conversation(root, "7", source)
            self.assertEqual(name, "legacy-conv-name")
            self.assertEqual(path, source.resolve())
            self.assertIn(file_id, self.mod.load_file_index(index_path)["by_file_id"])

    def test_list_file_edits(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "one.py"
            source.write_text("x\n", encoding="utf-8")
            self.mod.resolve_file_edit_conversation(root, "55", source)
            payload = self.mod.list_file_edits(root, "55")
            self.assertEqual(payload["pid"], "55")
            self.assertEqual(len(payload["files"]), 1)
            self.assertEqual(payload["files"][0]["path"], str(source.resolve()))


class FileEditNagentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_nagent_module()

    def test_initial_context_includes_file_edit_rules(self):
        text = self.mod.create_initial_text(
            Path("/tmp/nagent-root"),
            NAGENT.resolve(),
            "user",
            "conv",
        )
        self.assertIn("Do not use shell commands to write files outside temp directories", text)
        self.assertIn("/tmp, /var/tmp, or $TMPDIR", text)
        self.assertIn("nagent-file-edit", text)
        self.assertIn("nagent-file-read", text)

    def test_file_edit_context_allows_specific_file(self):
        target = Path("/home/macton/nagent/bin/nagent")
        text = self.mod.create_initial_text(
            Path("/tmp/nagent-root"),
            NAGENT.resolve(),
            "user",
            "conv-file",
            file_edit_path=target,
            file_edit_id="2050:999",
        )
        self.assertIn(f"You may use <nagent-write> on this file: {target}", text)
        self.assertIn("segment files from a split of this file", text)
        self.assertIn("nagent-file-patch", text)
        context = text.split("</initial_context>", 1)[0]
        self.assertNotIn("Do not use shell commands to write files outside temp directories", context)

    def test_file_edit_context_includes_git_history_and_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            target = repo / "tracked.py"
            sibling = repo / "helper.py"
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)

            target.write_text("alpha\n", encoding="utf-8")
            subprocess.run(["git", "add", "tracked.py"], cwd=repo, check=True)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Alice",
                    "-c",
                    "user.email=alice@example.com",
                    "commit",
                    "-m",
                    "add tracked file",
                ],
                cwd=repo,
                check=True,
                capture_output=True,
                text=True,
            )

            target.write_text("alpha\nbeta\n", encoding="utf-8")
            sibling.write_text("helper\n", encoding="utf-8")
            subprocess.run(["git", "add", "tracked.py", "helper.py"], cwd=repo, check=True)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Bob",
                    "-c",
                    "user.email=bob@example.com",
                    "commit",
                    "-m",
                    "expand tracked file",
                ],
                cwd=repo,
                check=True,
                capture_output=True,
                text=True,
            )
            commits = subprocess.run(
                ["git", "log", "--format=%H", "--", "tracked.py"],
                cwd=repo,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.splitlines()
            summary_payload = {
                "summaries": [
                    {"commit": commits[0], "summary": "Adds beta behavior."},
                    {"commit": commits[1], "summary": "Creates the tracked file."},
                ]
            }
            fake_summary = repo / "fake-summary"
            fake_summary.write_text(
                "#!/usr/bin/python3\nimport json\nprint(json.dumps({'summary': 'Current file summary.'}))\n",
                encoding="utf-8",
            )
            fake_summary.chmod(0o755)

            with unittest.mock.patch.object(self.mod, "NAGENT_FILE_SUMMARIZE", fake_summary):
                with unittest.mock.patch.object(self.mod, "generate_text", return_value=json.dumps(summary_payload)):
                    text = self.mod.build_initial_context(
                        Path(tmp) / "nagent-root",
                        NAGENT.resolve(),
                        "user",
                        "conv-file",
                        file_edit_path=target,
                        file_edit_id="1:2",
                        provider="openai",
                        model="gpt-test",
                    )

            self.assertIn("{file-history}", text)
            self.assertIn("Alice <alice@example.com>", text)
            self.assertIn("Bob <bob@example.com>", text)
            self.assertIn("Creates the tracked file.", text)
            self.assertIn("Adds beta behavior.", text)
            self.assertIn("| helper.py | 1 |", text)
            self.assertIn("Use these files as hints.", text)
            self.assertIn("Do not edit them unless the user request or evidence requires it.", text)
            self.assertIn("{file-summary}", text)
            self.assertIn("Current file summary.", text)

    def test_file_edit_context_reuses_existing_history_until_new_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            target = repo / "tracked.py"
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)

            target.write_text("alpha\n", encoding="utf-8")
            subprocess.run(["git", "add", "tracked.py"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-m", "add tracked file"], cwd=repo, check=True, capture_output=True, text=True)
            first_commit = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            first_payload = {"summaries": [{"commit": first_commit, "summary": "Initial summary."}]}
            fake_summary = repo / "fake-summary"
            fake_summary.write_text(
                "#!/usr/bin/python3\nimport json\nprint(json.dumps({'summary': 'Summary v1.'}))\n",
                encoding="utf-8",
            )
            fake_summary.chmod(0o755)

            with unittest.mock.patch.object(self.mod, "NAGENT_FILE_SUMMARIZE", fake_summary):
                with unittest.mock.patch.object(self.mod, "generate_text", return_value=json.dumps(first_payload)):
                    previous = self.mod.build_initial_context(
                        Path(tmp) / "nagent-root",
                        NAGENT.resolve(),
                        "user",
                        "conv-file",
                        file_edit_path=target,
                        file_edit_id="1:2",
                        provider="openai",
                        model="gpt-test",
                    )

                with unittest.mock.patch.object(self.mod, "generate_text") as summarize_commits:
                    reused = self.mod.build_initial_context(
                        Path(tmp) / "nagent-root",
                        NAGENT.resolve(),
                        "user",
                        "conv-file",
                        file_edit_path=target,
                        file_edit_id="1:2",
                        provider="openai",
                        model="gpt-test",
                        previous_initial_context=previous,
                    )

            summarize_commits.assert_not_called()
            self.assertIn("Initial summary.", reused)
            self.assertIn("Summary v1.", reused)

            target.write_text("alpha\nbeta\n", encoding="utf-8")
            subprocess.run(["git", "add", "tracked.py"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-m", "expand tracked file"], cwd=repo, check=True, capture_output=True, text=True)
            second_commit = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            second_payload = {"summaries": [{"commit": second_commit, "summary": "Second summary."}]}
            fake_summary.write_text(
                "#!/usr/bin/python3\nimport json\nprint(json.dumps({'summary': 'Summary v2.'}))\n",
                encoding="utf-8",
            )

            with unittest.mock.patch.object(self.mod, "NAGENT_FILE_SUMMARIZE", fake_summary):
                with unittest.mock.patch.object(self.mod, "generate_text", return_value=json.dumps(second_payload)):
                    refreshed = self.mod.build_initial_context(
                        Path(tmp) / "nagent-root",
                        NAGENT.resolve(),
                        "user",
                        "conv-file",
                        file_edit_path=target,
                        file_edit_id="1:2",
                        provider="openai",
                        model="gpt-test",
                        previous_initial_context=previous,
                    )

            self.assertIn("Initial summary.", refreshed)
            self.assertIn("Second summary.", refreshed)
            self.assertIn("Summary v2.", refreshed)

    def test_execute_read_rejects_large_file(self):
        with tempfile.NamedTemporaryFile(mode="wb", delete=False) as handle:
            handle.write(b"x" * (self.mod.READ_SPLIT_THRESHOLD_BYTES + 1))
            path = Path(handle.name)
        try:
            result = self.mod.execute_read(str(path))
            self.assertIn("file too large", result)
            self.assertIn("nagent-file-read", result)
        finally:
            path.unlink(missing_ok=True)

    def test_execute_file_read_inline_for_small_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as handle:
            handle.write("small\n")
            path = Path(handle.name)
        try:
            result = self.mod.execute_file_read(str(path), Path("/tmp/nagent-root"))
            self.assertIn('mode="inline"', result)
            self.assertIn("small", result)
        finally:
            path.unlink(missing_ok=True)

    def test_execute_file_read_splits_large_file(self):
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".txt", delete=False) as handle:
            handle.write(b"x" * (self.mod.READ_SPLIT_THRESHOLD_BYTES + 1))
            path = Path(handle.name)
        try:
            fake_payload = {
                "index_path": "/tmp/splits/demo/index.json",
                "segment_count": 2,
                "segments": [
                    {
                        "segment_index": 0,
                        "start_line_num": 1,
                        "end_line_num": 100,
                        "path": "/tmp/splits/demo/seg-0.txt",
                    },
                    {
                        "segment_index": 1,
                        "start_line_num": 101,
                        "end_line_num": 200,
                        "path": "/tmp/splits/demo/seg-1.txt",
                    },
                ],
            }

            def fake_run(cmd, **kwargs):
                class Result:
                    returncode = 0
                    stdout = json.dumps(fake_payload)
                    stderr = ""
                return Result()

            with unittest.mock.patch.object(self.mod.subprocess, "run", fake_run):
                result = self.mod.execute_file_read(str(path), Path("/tmp/nagent-root"))

            self.assertIn('mode="split"', result)
            self.assertIn("/tmp/splits/demo/index.json", result)
            self.assertIn("nagent-file-patch", result)
        finally:
            path.unlink(missing_ok=True)

    def test_is_tmp_path_accepts_tmpdir(self):
        with tempfile.TemporaryDirectory() as tmp:
            nested = Path(tmp) / "nested" / "file.txt"
            nested.parent.mkdir(parents=True)
            nested.write_text("ok", encoding="utf-8")
            with unittest.mock.patch.dict(os.environ, {"TMPDIR": tmp}, clear=False):
                self.assertTrue(self.mod.is_tmp_path(nested))

    def test_execute_write_blocks_project_path(self):
        result = self.mod.execute_write("/etc/passwd", "nope")
        self.assertIn("nagent-file-edit", result)
        self.assertIn('status="error"', result)

    def test_execute_write_allows_tmp_path(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as tmp:
            target = Path(tmp) / "scratch.txt"
            result = self.mod.execute_write(str(target), "tmp ok")
            self.assertIn('status="ok"', result)
            self.assertEqual(target.read_text(encoding="utf-8"), "tmp ok")

    def test_execute_write_allows_renamed_file_edit_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "before.txt"
            target.write_text("before\n", encoding="utf-8")
            file_id = self.mod.file_id_for_path(target)
            renamed = Path(tmp) / "after.txt"
            target.rename(renamed)
            result = self.mod.execute_write(
                str(renamed),
                "after",
                file_edit_path=target,
                file_edit_id=file_id,
            )
            self.assertIn('status="ok"', result)
            self.assertEqual(renamed.read_text(encoding="utf-8"), "after")

    def test_execute_write_allows_split_segment_in_file_edit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "nagent-root"
            source = Path(tmp) / "big.txt"
            source.write_text("line\n" * 100, encoding="utf-8")
            split_dir = root / "splits" / "big-demo"
            split_dir.mkdir(parents=True)
            segment = split_dir / "big-0001.txt"
            segment.write_text("segment\n", encoding="utf-8")
            index_path = split_dir / "index.json"
            index_path.write_text(
                json.dumps(
                    {
                        "source_path": str(source.resolve()),
                        "segments": [{"path": str(segment.resolve()), "start_line_num": 1, "end_line_num": 1}],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            result = self.mod.execute_write(
                str(segment),
                "updated\n",
                file_edit_path=source,
                root=root,
            )
            self.assertIn('status="ok"', result)
            self.assertEqual(segment.read_text(encoding="utf-8"), "updated\n")

    def test_execute_file_patch(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "sample.txt"
            source.write_text("alpha\n\nbeta\n", encoding="utf-8")
            split_dir = Path(tmp) / "split"
            split_dir.mkdir()
            seg0 = split_dir / "sample-0001.txt"
            seg1 = split_dir / "sample-0002.txt"
            seg0.write_text("alpha\n\n", encoding="utf-8")
            seg1.write_text("beta\n", encoding="utf-8")
            index_path = split_dir / "index.json"
            index_path.write_text(
                json.dumps(
                    {
                        "source_path": str(source.resolve()),
                        "source_sha256": __import__("hashlib").sha256(source.read_bytes()).hexdigest(),
                        "segments": [
                            {"path": str(seg0.resolve()), "start_line_num": 1, "end_line_num": 2},
                            {"path": str(seg1.resolve()), "start_line_num": 3, "end_line_num": 3},
                        ],
                        "split_type": "txt",
                        "target_bytes": 32 * 1024,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            seg0.write_text("ALPHA\n\n", encoding="utf-8")
            result = self.mod.execute_file_patch(str(index_path))
            self.assertIn('status="ok"', result)
            self.assertIn('changed="true"', result)
            self.assertEqual(source.read_text(encoding="utf-8"), "ALPHA\n\nbeta\n")

    def test_execute_write_allows_file_edit_target(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as handle:
            handle.write("before\n")
            target = Path(handle.name)
        try:
            result = self.mod.execute_write(str(target), "after", file_edit_path=target)
            self.assertIn('status="ok"', result)
            self.assertEqual(target.read_text(encoding="utf-8"), "after")
        finally:
            target.unlink(missing_ok=True)


class FileEditCliTests(unittest.TestCase):
    def test_file_edit_delegates_to_nagent(self):
        loader = SourceFileLoader("nagent_file_edit_mod", str(NAGENT_FILE_EDIT))
        spec = importlib.util.spec_from_loader("nagent_file_edit_mod", loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "edit-me.txt"
            source.write_text("alpha\n", encoding="utf-8")
            fake_nagent = Path(tmp) / "fake-nagent"
            fake_nagent.write_text("#!/usr/bin/python3\nimport sys\nprint(' '.join(sys.argv[1:]))\n", encoding="utf-8")
            fake_nagent.chmod(0o755)
            module.NAGENT = fake_nagent

            with unittest.mock.patch.object(module.subprocess, "run") as mock_run:
                mock_run.return_value = unittest.mock.Mock(returncode=0)
                with unittest.mock.patch.object(
                    module.sys,
                    "argv",
                    [
                        "nagent-file-edit",
                        "--file",
                        str(source),
                        "--root",
                        str(Path(tmp) / "nagent-root"),
                        "--pid",
                        "99",
                        "make it beta",
                    ],
                ):
                    with self.assertRaises(SystemExit) as exited:
                        module.main()
                    self.assertEqual(exited.exception.code, 0)

                mock_run.assert_called_once()
                command = mock_run.call_args.args[0]
                self.assertIn("--file-edit", command)
                self.assertIn(str(source.resolve()), command)
                self.assertIn("--pid", command)
                self.assertIn("99", command)
                self.assertEqual(command[-1], "make it beta")

    def test_file_edit_json_output(self):
        loader = SourceFileLoader("nagent_file_edit_mod_json", str(NAGENT_FILE_EDIT))
        spec = importlib.util.spec_from_loader("nagent_file_edit_mod_json", loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "edit-me.txt"
            source.write_text("alpha\n", encoding="utf-8")
            root = Path(tmp) / "nagent-root"
            fake_nagent = Path(tmp) / "fake-nagent"
            fake_nagent.write_text("#!/usr/bin/python3\nimport sys\nprint('stub')\n", encoding="utf-8")
            fake_nagent.chmod(0o755)
            module.NAGENT = fake_nagent

            with unittest.mock.patch.object(module.subprocess, "run") as mock_run:
                mock_run.return_value = unittest.mock.Mock(
                    returncode=0,
                    stdout=json.dumps(
                        {
                            "exit_code": 0,
                            "conversation_path": "/tmp/conv",
                            "responses": ["done\n"],
                        }
                    ),
                    stderr="",
                )
                with unittest.mock.patch.object(
                    module.sys,
                    "argv",
                    [
                        "nagent-file-edit",
                        "--file",
                        str(source),
                        "--root",
                        str(root),
                        "--pid",
                        "99",
                        "--json",
                        "make it beta",
                    ],
                ):
                    with unittest.mock.patch.object(module.sys, "stdout", io.StringIO()) as stdout:
                        with self.assertRaises(SystemExit) as exited:
                            module.main()
                        self.assertEqual(exited.exception.code, 0)
                        payload = json.loads(stdout.getvalue())
                        self.assertEqual(payload["exit_code"], 0)
                        self.assertRegex(payload["file_id"], r"^\d+:\d+$")
                        self.assertEqual(payload["source_path"], str(source.resolve()))
                        self.assertIn("conversation_path", payload)
                        self.assertIn("nagent", payload)
                        self.assertEqual(payload["nagent"]["responses"], ["done\n"])

    def test_file_edit_json_appends_multiple_files_to_index(self):
        loader = SourceFileLoader("nagent_file_edit_mod_json_append", str(NAGENT_FILE_EDIT))
        spec = importlib.util.spec_from_loader("nagent_file_edit_mod_json_append", loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "nagent-root"
            first = Path(tmp) / "first.txt"
            second = Path(tmp) / "second.txt"
            first.write_text("alpha\n", encoding="utf-8")
            second.write_text("beta\n", encoding="utf-8")
            fake_nagent = Path(tmp) / "fake-nagent"
            fake_nagent.write_text(
                "#!/usr/bin/python3\nimport json\nprint(json.dumps({'exit_code': 0}))\n",
                encoding="utf-8",
            )
            fake_nagent.chmod(0o755)
            module.NAGENT = fake_nagent

            with unittest.mock.patch.object(module.subprocess, "run") as mock_run:
                mock_run.return_value = unittest.mock.Mock(
                    returncode=0,
                    stdout=json.dumps({"exit_code": 0}),
                    stderr="",
                )
                for source in (first, second):
                    with unittest.mock.patch.object(
                        module.sys,
                        "argv",
                        [
                            "nagent-file-edit",
                            "--file",
                            str(source),
                            "--root",
                            str(root),
                            "--pid",
                            "99",
                            "--json",
                            "touch",
                        ],
                    ):
                        with unittest.mock.patch.object(module.sys, "stdout", io.StringIO()):
                            with self.assertRaises(SystemExit) as exited:
                                module.main()
                            self.assertEqual(exited.exception.code, 0)

            index = json.loads((root / "conversations" / "file-index-99.json").read_text(encoding="utf-8"))
            paths = {entry["path"] for entry in index["by_file_id"].values()}
            self.assertEqual(paths, {str(first.resolve()), str(second.resolve())})


if __name__ == "__main__":
    unittest.main(verbosity=2)
