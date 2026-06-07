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
NAGENT_FILE_PATCH = BIN / "nagent-file-patch"


def load_patch_lib():
    sys_path_insert = str(HELPERS)
    loader = SourceFileLoader("nagent_file_patch_lib", str(HELPERS / "nagent_file_patch_lib.py"))
    spec = importlib.util.spec_from_loader("nagent_file_patch_lib", loader)
    module = importlib.util.module_from_spec(spec)
    import sys

    sys.path.insert(0, sys_path_insert)
    try:
        loader.exec_module(module)
    finally:
        if sys.path and sys.path[0] == sys_path_insert:
            sys.path.pop(0)
    return module


def split_with_cli(source: Path, output_dir: Path, target_bytes: int = 512) -> Path:
    result = subprocess.run(
        [
            str(NAGENT_FILE_SPLIT),
            "--file",
            str(source),
            "--output",
            str(output_dir),
            "--target-bytes",
            str(target_bytes),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr)
    return Path(result.stdout.strip())


class FilePatchLibTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_patch_lib()

    def test_merge_and_refresh_line_numbers(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "sample.txt"
            source.write_text("one\n" * 400 + "\n" + "two\n" * 400 + "three\n", encoding="utf-8")
            output_dir = Path(tmp) / "split"
            index_path = split_with_cli(source, output_dir)
            index = json.loads(index_path.read_text(encoding="utf-8"))
            self.assertGreaterEqual(len(index["segments"]), 2)

            first_segment = Path(index["segments"][0]["path"])
            first_segment.write_text(
                first_segment.read_text(encoding="utf-8").replace("one\n", "ONE\n"),
                encoding="utf-8",
            )

            merged = self.mod.merge_segments(index["segments"])
            self.assertIn("ONE\n", merged)
            self.assertIn("three\n", merged)

            refreshed = self.mod.refresh_line_numbers(index["segments"])
            self.assertEqual(refreshed[0]["start_line_num"], 1)
            self.assertLess(refreshed[0]["end_line_num"], refreshed[1]["start_line_num"])

    def test_make_unified_patch_is_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "sample.txt"
            original = "alpha\n" * 10 + "beta\n" * 10
            updated = "alpha\n" * 10 + "BETA\n" * 10
            patch = self.mod.make_unified_patch(source, original, updated)
            self.assertIn("-beta", patch)
            self.assertIn("+BETA", patch)
            self.assertNotIn("-alpha", patch)

    def test_hash_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "sample.txt"
            source.write_text("alpha\n\nbeta\n", encoding="utf-8")
            output_dir = Path(tmp) / "split"
            index_path = split_with_cli(source, output_dir, target_bytes=32 * 1024)
            source.write_text("changed externally\n", encoding="utf-8")

            with self.assertRaises(ValueError):
                self.mod.apply_segment_patches(index_path)


class FilePatchCliTests(unittest.TestCase):
    def test_applies_segment_edits_and_updates_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "sample.txt"
            source.write_text("alpha\n" * 400 + "\n" + "beta\n", encoding="utf-8")
            output_dir = Path(tmp) / "split"
            index_path = split_with_cli(source, output_dir)
            index = json.loads(index_path.read_text(encoding="utf-8"))
            self.assertGreaterEqual(len(index["segments"]), 2)
            old_hash = index["source_sha256"]

            Path(index["segments"][0]["path"]).write_text(
                Path(index["segments"][0]["path"]).read_text(encoding="utf-8").replace("alpha\n", "ALPHA\n"),
                encoding="utf-8",
            )

            result = subprocess.run(
                [str(NAGENT_FILE_PATCH), "--index", str(index_path), "--json"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["changed"])
            self.assertTrue(payload["patch_path"].endswith(".patch"))

            updated = source.read_text(encoding="utf-8")
            self.assertTrue(updated.startswith("ALPHA\n"))
            self.assertIn("beta\n", updated)

            updated_index = json.loads(index_path.read_text(encoding="utf-8"))
            self.assertNotEqual(updated_index["source_sha256"], old_hash)
            self.assertEqual(updated_index["segment_count"], len(updated_index["segments"]))

    def test_dry_run_does_not_modify_source_or_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "sample.txt"
            source.write_text("alpha\n\nbeta\n", encoding="utf-8")
            output_dir = Path(tmp) / "split"
            index_path = split_with_cli(source, output_dir, target_bytes=32 * 1024)
            index_before = index_path.read_text(encoding="utf-8")
            segment_path = json.loads(index_before)["segments"][0]["path"]

            Path(segment_path).write_text("changed\n\n", encoding="utf-8")

            result = subprocess.run(
                [str(NAGENT_FILE_PATCH), "--index", str(index_path), "--dry-run"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(source.read_text(encoding="utf-8"), "alpha\n\nbeta\n")
            self.assertEqual(index_path.read_text(encoding="utf-8"), index_before)

    def test_no_changes_json_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "sample.txt"
            source.write_text("alpha\n\nbeta\n", encoding="utf-8")
            output_dir = Path(tmp) / "split"
            index_path = split_with_cli(source, output_dir, target_bytes=32 * 1024)

            result = subprocess.run(
                [str(NAGENT_FILE_PATCH), "--index", str(index_path), "--json"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertFalse(payload["changed"])
            self.assertIsNone(payload["patch_path"])

    def test_force_ignores_hash_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "sample.txt"
            source.write_text("alpha\n\nbeta\n", encoding="utf-8")
            output_dir = Path(tmp) / "split"
            index_path = split_with_cli(source, output_dir, target_bytes=32 * 1024)
            index = json.loads(index_path.read_text(encoding="utf-8"))
            Path(index["segments"][0]["path"]).write_text("CHANGED\n\n", encoding="utf-8")
            source.write_text("other\n", encoding="utf-8")

            result = subprocess.run(
                [str(NAGENT_FILE_PATCH), "--index", str(index_path), "--force", "--json"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["changed"])
            self.assertEqual(source.read_text(encoding="utf-8"), "CHANGED\n\n")


if __name__ == "__main__":
    unittest.main(verbosity=2)
