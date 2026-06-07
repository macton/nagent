#!/usr/bin/python3

import importlib.util
import json
import subprocess
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path

BIN = Path(__file__).resolve().parent.parent / "bin"
HELPERS = BIN / "helpers"
NAGENT_FILE_SPLIT = BIN / "nagent-file-split"


def load_split_lib():
    loader = SourceFileLoader("nagent_file_split_lib", str(HELPERS / "nagent_file_split_lib.py"))
    spec = importlib.util.spec_from_loader("nagent_file_split_lib", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class FileSplitLibTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_split_lib()

    def test_read_lines_preserves_crlf(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.txt"
            path.write_bytes(b"line1\r\n\r\nline2\n")
            lines = self.mod.read_lines(path)
            self.assertEqual([text for _, text in lines], ["line1\r\n", "\r\n", "line2\n"])

    def test_build_index_includes_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.py"
            path.write_text("def one():\n    return 1\n", encoding="utf-8")
            output_dir = Path(tmp) / "out"
            output_dir.mkdir()
            segments = self.mod.split_to_segments(
                path,
                output_dir,
                target_bytes=32 * 1024,
                score_break=self.mod.py_score,
            )
            index = self.mod.build_index(path, segments, "py", 32 * 1024, natural=False)
            self.assertEqual(index["split_type"], "py")
            self.assertEqual(index["target_bytes"], 32 * 1024)
            self.assertFalse(index["natural"])
            self.assertEqual(index["segment_count"], len(segments))
            self.assertEqual(index["source_line_count"], 2)
            self.assertEqual(len(index["source_sha256"]), 64)
            self.assertIn("created_at", index)
            self.assertEqual(index["segments"][0]["segment_index"], 1)

    def test_txt_splits_on_blank_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.txt"
            blocks = ["block-a\n"] * 500 + ["\n"] + ["block-b\n"] * 500
            path.write_text("".join(blocks), encoding="utf-8")
            output_dir = Path(tmp) / "out"
            output_dir.mkdir()
            segments = self.mod.split_to_segments(
                path,
                output_dir,
                target_bytes=4096,
                score_break=self.mod.blank_line_score,
            )
            self.assertGreaterEqual(len(segments), 2)
            contents = [
                Path(segment["path"]).read_text(encoding="utf-8") for segment in segments
            ]
            self.assertTrue(all("block-a" in content or "block-b" in content for content in contents))

    def test_natural_mode_splits_each_paragraph(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.txt"
            path.write_text("para-a\n\npara-b\n\npara-c\n", encoding="utf-8")
            lines = self.mod.read_lines(path)
            chunks = self.mod.chunk_lines(
                lines,
                target_bytes=32 * 1024,
                score_break=self.mod.blank_line_score,
                natural=True,
            )
            self.assertEqual(len(chunks), 3)

    def test_cpp_keeps_small_function_together(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.cpp"
            path.write_text(
                "int foo() {\n  return 1;\n}\n\nint bar() {\n  return 2;\n}\n",
                encoding="utf-8",
            )
            output_dir = Path(tmp) / "out"
            output_dir.mkdir()
            segments = self.mod.split_to_segments(
                path,
                output_dir,
                target_bytes=32 * 1024,
                score_break=self.mod.cpp_score,
            )
            self.assertEqual(len(segments), 1)
            content = Path(segments[0]["path"]).read_text(encoding="utf-8")
            self.assertIn("int foo()", content)
            self.assertIn("int bar()", content)

    def test_detects_common_extension_variants(self):
        cases = {
            "sample.c": "cpp",
            "sample.h": "cpp",
            "sample.hpp": "cpp",
            "sample.hxx": "cpp",
            "sample.yml": "yaml",
            "sample.html": "xml",
            "sample.xhtml": "xml",
            "sample.json5": "json",
            "sample.pyi": "py",
            "sample.mdx": "md",
        }
        for filename, expected in cases.items():
            with self.subTest(filename=filename):
                self.assertEqual(self.mod.detect_split_type(Path(filename)), expected)

    def test_normalizes_extension_aliases_to_helper_types(self):
        cases = {
            "hpp": "cpp",
            ".h": "cpp",
            "yml": "yaml",
            ".html": "xml",
            "tsx": "ts",
            "jsonc": "json",
        }
        for split_type, expected in cases.items():
            with self.subTest(split_type=split_type):
                self.assertEqual(self.mod.normalize_split_type(split_type), expected)


class FileSplitCliTests(unittest.TestCase):
    def test_end_to_end_writes_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "notes.txt"
            source.write_text("alpha\n\nbeta\n", encoding="utf-8")
            output_dir = Path(tmp) / "split-out"

            result = subprocess.run(
                [
                    str(NAGENT_FILE_SPLIT),
                    "--file",
                    str(source),
                    "--output",
                    str(output_dir),
                    "--split",
                    "txt",
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            index_path = Path(result.stdout.strip())
            self.assertEqual(index_path, output_dir / "index.json")

            index = json.loads(index_path.read_text(encoding="utf-8"))
            self.assertEqual(index["source_path"], str(source.resolve()))
            self.assertGreaterEqual(len(index["segments"]), 1)
            self.assertIn("source_sha256", index)
            self.assertIn("segment_count", index)
            segment = index["segments"][0]
            self.assertIn("segment_index", segment)
            self.assertTrue(Path(segment["path"]).is_file())

    def test_json_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "notes.txt"
            source.write_text("alpha\n", encoding="utf-8")
            output_dir = Path(tmp) / "split-out"

            result = subprocess.run(
                [
                    str(NAGENT_FILE_SPLIT),
                    "--file",
                    str(source),
                    "--output",
                    str(output_dir),
                    "--json",
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["split_type"], "txt")
            self.assertEqual(payload["index_path"], str((output_dir / "index.json").resolve()))

    def test_target_bytes_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "notes.txt"
            source.write_text("line\n" * 200, encoding="utf-8")
            output_dir = Path(tmp) / "split-out"

            result = subprocess.run(
                [
                    str(NAGENT_FILE_SPLIT),
                    "--file",
                    str(source),
                    "--output",
                    str(output_dir),
                    "--target-bytes",
                    "256",
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            index = json.loads((output_dir / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(index["target_bytes"], 256)
            self.assertGreater(index["segment_count"], 1)

    def test_refresh_rebuilds_segments(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "notes.txt"
            source.write_text("alpha\n", encoding="utf-8")
            output_dir = Path(tmp) / "split-out"
            subprocess.run(
                [str(NAGENT_FILE_SPLIT), "--file", str(source), "--output", str(output_dir)],
                check=True,
                capture_output=True,
                text=True,
            )
            source.write_text("alpha\nbeta\n", encoding="utf-8")

            result = subprocess.run(
                [str(NAGENT_FILE_SPLIT), "--refresh", str(output_dir / "index.json"), "--json"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["source_line_count"], 2)
            merged = "".join(
                Path(segment["path"]).read_text(encoding="utf-8") for segment in payload["segments"]
            )
            self.assertEqual(merged, source.read_text(encoding="utf-8"))

    def test_autodetects_js_splitter(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "sample.js"
            source.write_text("export function one() {\n  return 1;\n}\n", encoding="utf-8")
            output_dir = Path(tmp) / "split-out"

            result = subprocess.run(
                [str(NAGENT_FILE_SPLIT), "--file", str(source), "--output", str(output_dir), "--json"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["split_type"], "js")

    def test_split_flag_accepts_extension_alias(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "sample.txt"
            source.write_text("int one() {\n  return 1;\n}\n", encoding="utf-8")
            output_dir = Path(tmp) / "split-out"

            result = subprocess.run(
                [
                    str(NAGENT_FILE_SPLIT),
                    "--file",
                    str(source),
                    "--output",
                    str(output_dir),
                    "--split",
                    "hpp",
                    "--json",
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["split_type"], "cpp")

    def test_missing_file_errors(self):
        result = subprocess.run(
            [str(NAGENT_FILE_SPLIT), "--file", "/nonexistent/file.txt"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("file not found", result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
