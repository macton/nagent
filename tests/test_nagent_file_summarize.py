#!/usr/bin/python3

import importlib.util
import io
import json
import subprocess
import tempfile
import unittest
import unittest.mock
from importlib.machinery import SourceFileLoader
from pathlib import Path

BIN = Path(__file__).resolve().parent.parent / "bin"
HELPERS = BIN / "helpers"
NAGENT_FILE_SUMMARIZE = BIN / "nagent-file-summarize"
NAGENT_FILE_SPLIT = BIN / "nagent-file-split"


def load_summarize_lib():
    loader = SourceFileLoader("nagent_file_summarize_lib", str(HELPERS / "nagent_file_summarize_lib.py"))
    spec = importlib.util.spec_from_loader("nagent_file_summarize_lib", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class FileSummarizeLibTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_summarize_lib()

    def test_build_summary_prompt_includes_path(self):
        prompt = self.mod.build_summary_prompt("/tmp/sample.py", "def main(): pass\n")
        self.assertIn("/tmp/sample.py", prompt)
        self.assertIn("def main(): pass", prompt)

    def test_combined_summary_from_index(self):
        index = {
            "segments": [
                {"start_line_num": 1, "end_line_num": 10, "summary": "Intro section."},
                {"start_line_num": 11, "end_line_num": 20, "summary": "Main logic."},
            ]
        }
        combined = self.mod.combined_summary_from_index(index)
        self.assertIn("Lines 1-10: Intro section.", combined)
        self.assertIn("Lines 11-20: Main logic.", combined)

    def test_add_summaries_to_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            seg_a = Path(tmp) / "demo-0001.txt"
            seg_b = Path(tmp) / "demo-0002.txt"
            seg_a.write_text("alpha\n", encoding="utf-8")
            seg_b.write_text("beta\n", encoding="utf-8")
            fake_summarize = Path(tmp) / "fake-summarize"
            fake_summarize.write_text(
                "#!/usr/bin/python3\nimport json, sys\nprint(json.dumps({'summary': 'stub summary'}))\n",
                encoding="utf-8",
            )
            fake_summarize.chmod(0o755)
            index = {
                "segments": [
                    {"segment_index": 1, "start_line_num": 1, "end_line_num": 1, "path": str(seg_a)},
                    {"segment_index": 2, "start_line_num": 2, "end_line_num": 2, "path": str(seg_b)},
                ]
            }
            updated = self.mod.add_summaries_to_index(
                index,
                "openai",
                "gpt-test",
                None,
                fake_summarize,
            )
            self.assertEqual(updated["segments"][0]["summary"], "stub summary")
            self.assertEqual(updated["segments"][1]["summary"], "stub summary")
            self.assertIn("Lines 1-1: stub summary", updated["summary"])


class FileSummarizeCliTests(unittest.TestCase):
    def test_inline_summarize_json(self):
        loader = SourceFileLoader("nagent_file_summarize_mod", str(NAGENT_FILE_SUMMARIZE))
        spec = importlib.util.spec_from_loader("nagent_file_summarize_mod", loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "small.txt"
            source.write_text("hello world\n", encoding="utf-8")

            with unittest.mock.patch.object(
                module,
                "summarize_file_path",
                return_value="A short greeting file.",
            ):
                with unittest.mock.patch.object(
                    module,
                    "resolve_from_args",
                    return_value=("openai", "gpt-test"),
                ):
                    with unittest.mock.patch.object(
                        module.sys,
                        "argv",
                        [
                            "nagent-file-summarize",
                            "--file",
                            str(source),
                            "--json",
                        ],
                    ):
                        with unittest.mock.patch.object(module.sys, "stdout", io.StringIO()) as stdout:
                            module.main()
                            payload = json.loads(stdout.getvalue())
                            self.assertEqual(payload["mode"], "inline")
                            self.assertEqual(payload["summary"], "A short greeting file.")

    def test_large_file_delegates_to_split(self):
        loader = SourceFileLoader("nagent_file_summarize_mod2", str(NAGENT_FILE_SUMMARIZE))
        spec = importlib.util.spec_from_loader("nagent_file_summarize_mod2", loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "big.txt"
            source.write_text("x" * (module.SUMMARIZE_THRESHOLD_BYTES + 1), encoding="utf-8")
            fake_payload = {
                "index_path": str(Path(tmp) / "split" / "index.json"),
                "summary": "Lines 1-100: part one.\n\nLines 101-200: part two.",
                "segment_count": 2,
                "segments": [
                    {"segment_index": 1, "summary": "part one."},
                    {"segment_index": 2, "summary": "part two."},
                ],
            }

            with unittest.mock.patch.object(
                module,
                "summarize_via_split",
                return_value={
                    "mode": "split",
                    "file": str(source.resolve()),
                    "size_bytes": source.stat().st_size,
                    "index_path": fake_payload["index_path"],
                    "summary": fake_payload["summary"],
                    "segment_count": 2,
                    "segments": fake_payload["segments"],
                    "provider": "openai",
                    "model": "gpt-test",
                },
            ):
                with unittest.mock.patch.object(
                    module,
                    "resolve_from_args",
                    return_value=("openai", "gpt-test"),
                ):
                    with unittest.mock.patch.object(
                        module.sys,
                        "argv",
                        [
                            "nagent-file-summarize",
                            "--file",
                            str(source),
                            "--json",
                        ],
                    ):
                        with unittest.mock.patch.object(module.sys, "stdout", io.StringIO()) as stdout:
                            module.main()
                            payload = json.loads(stdout.getvalue())
                            self.assertEqual(payload["mode"], "split")
                            self.assertEqual(payload["segment_count"], 2)


class FileSplitSummarizeTests(unittest.TestCase):
    def test_split_summarize_adds_segment_summaries(self):
        loader = SourceFileLoader("nagent_file_split_mod", str(NAGENT_FILE_SPLIT))
        spec = importlib.util.spec_from_loader("nagent_file_split_mod", loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "sample.txt"
            source.write_text("alpha\n\nbeta\n", encoding="utf-8")
            output_dir = Path(tmp) / "out"
            fake_summarize = Path(tmp) / "fake-summarize"
            fake_summarize.write_text(
                "#!/usr/bin/python3\nimport json\nprint(json.dumps({'summary': 'segment summary'}))\n",
                encoding="utf-8",
            )
            fake_summarize.chmod(0o755)
            module.NAGENT_FILE_SUMMARIZE = fake_summarize

            with unittest.mock.patch.object(module, "run_splitter") as mock_split:
                seg = output_dir / "sample-0001.txt"
                output_dir.mkdir(parents=True)
                seg.write_text("alpha\n\nbeta\n", encoding="utf-8")
                mock_split.return_value = [
                    {
                        "segment_index": 1,
                        "start_line_num": 1,
                        "end_line_num": 3,
                        "path": str(seg),
                    }
                ]
                index = module.split_file(
                    source,
                    output_dir,
                    "txt",
                    32 * 1024,
                    False,
                    summarize=True,
                    provider="openai",
                    model="gpt-test",
                )

            self.assertEqual(index["segments"][0]["summary"], "segment summary")
            self.assertIn("segment summary", index["summary"])
            saved = json.loads((output_dir / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["segments"][0]["summary"], "segment summary")


if __name__ == "__main__":
    unittest.main(verbosity=2)
