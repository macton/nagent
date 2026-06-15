#!/usr/bin/python3

import importlib.util
import io
import json
import sys
import tempfile
import unittest
import unittest.mock
from datetime import datetime, timedelta, timezone
from pathlib import Path

BIN = Path(__file__).resolve().parent.parent / "bin"
NAGENT = BIN / "nagent"


def load_nagent_module():
    from importlib.machinery import SourceFileLoader

    loader = SourceFileLoader("nagent_mod_safety_tests", str(NAGENT))
    spec = importlib.util.spec_from_loader("nagent_mod_safety_tests", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


NOW = datetime(2026, 6, 12, 12, 0, 0, tzinfo=timezone.utc)
SETTINGS = {
    "checkpoint_interval_minutes": 60,
    "checkpoint_max_new_kb": 256,
    "rebuild_at_kb": 384,
}


class TriggerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_nagent_module()

    def test_no_checkpoint_yet_fires_only_past_burst_size(self):
        small = 10 * 1024
        large = 300 * 1024
        self.assertFalse(self.mod.checkpoint_due(None, small, NOW, SETTINGS))
        self.assertTrue(self.mod.checkpoint_due(None, large, NOW, SETTINGS))

    def test_elapsed_interval_with_growth_fires(self):
        meta = (NOW - timedelta(minutes=61), 1000)
        self.assertTrue(self.mod.checkpoint_due(meta, 2000, NOW, SETTINGS))

    def test_elapsed_interval_without_growth_does_not_fire(self):
        meta = (NOW - timedelta(hours=10), 2000)
        self.assertFalse(self.mod.checkpoint_due(meta, 2000, NOW, SETTINGS))

    def test_burst_fires_regardless_of_elapsed_time(self):
        meta = (NOW - timedelta(minutes=5), 1000)
        burst = 1000 + 257 * 1024
        self.assertTrue(self.mod.checkpoint_due(meta, burst, NOW, SETTINGS))

    def test_within_interval_and_small_growth_does_not_fire(self):
        meta = (NOW - timedelta(minutes=30), 1000)
        self.assertFalse(self.mod.checkpoint_due(meta, 2000, NOW, SETTINGS))

    def test_interval_zero_disables_checkpoints(self):
        settings = dict(SETTINGS, checkpoint_interval_minutes=0)
        meta = (NOW - timedelta(hours=10), 0)
        self.assertFalse(self.mod.checkpoint_due(meta, 10**7, NOW, settings))

    def test_rebuild_due_on_size_and_disabled_at_zero(self):
        self.assertFalse(self.mod.rebuild_due(384 * 1024, SETTINGS))
        self.assertTrue(self.mod.rebuild_due(384 * 1024 + 1, SETTINGS))
        self.assertFalse(self.mod.rebuild_due(10**9, dict(SETTINGS, rebuild_at_kb=0)))

    def test_meta_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "conv.checkpoint.md"
            path.write_text(
                self.mod.format_checkpoint("conv", 1234, "## Intent\n- work", NOW),
                encoding="utf-8",
            )
            meta = self.mod.parse_checkpoint_meta(path)
            self.assertEqual(meta, (NOW, 1234))
        self.assertIsNone(self.mod.parse_checkpoint_meta(Path(tmp) / "missing"))

    def test_load_safety_settings_defaults_and_overrides(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.json"
            config.write_text(
                json.dumps({"provider": "openai", "rebuild_at_kb": 100}), encoding="utf-8"
            )
            settings = self.mod.load_safety_settings(config)
            self.assertEqual(settings["rebuild_at_kb"], 100)
            self.assertEqual(settings["checkpoint_interval_minutes"], 60)
            self.assertEqual(settings["checkpoint_max_new_kb"], 256)


class WriteCheckpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_nagent_module()

    def _llm(self):
        return self.mod.LlmSettings(provider="openai", model="m")

    def test_first_checkpoint_composes_header_and_body(self):
        with tempfile.TemporaryDirectory() as tmp:
            conversation = Path(tmp) / "conv"
            conversation.write_text("history " * 100, encoding="utf-8")
            captured = {}

            def fake_generate(prompt, provider, model):
                captured["prompt"] = prompt
                return "## Intent\n- finish the loader\n## Next action\n- run tests"

            with unittest.mock.patch.object(self.mod, "generate_text", fake_generate):
                path = self.mod.write_checkpoint(conversation, Path(tmp), self._llm(), now=NOW)

            content = path.read_text(encoding="utf-8")
            self.assertTrue(content.startswith("# Checkpoint: conv\n"))
            self.assertIn(f"updated: {NOW.isoformat()}", content)
            self.assertIn(f"conversation_chars: {len(conversation.read_text(encoding='utf-8'))}", content)
            self.assertIn("- finish the loader", content)
            self.assertIn("(none)", captured["prompt"])  # no previous checkpoint

    def test_update_sends_previous_with_user_edits_and_delta_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            conversation = Path(tmp) / "conv"
            old_content = "OLD-ACTIVITY " * 50
            conversation.write_text(old_content, encoding="utf-8")
            path = self.mod.checkpoint_path(conversation)
            path.write_text(
                self.mod.format_checkpoint(
                    "conv", len(old_content), "## Intent\n- USER-EDITED-LINE", NOW
                ),
                encoding="utf-8",
            )
            conversation.write_text(old_content + "NEW-ACTIVITY", encoding="utf-8")
            captured = {}

            def fake_generate(prompt, provider, model):
                captured["prompt"] = prompt
                return "## Intent\n- USER-EDITED-LINE\n- plus the new thing"

            with unittest.mock.patch.object(self.mod, "generate_text", fake_generate):
                self.mod.write_checkpoint(conversation, Path(tmp), self._llm(), now=NOW)

            self.assertIn("USER-EDITED-LINE", captured["prompt"])
            self.assertIn("NEW-ACTIVITY", captured["prompt"])
            self.assertNotIn("OLD-ACTIVITY", captured["prompt"])  # delta, not the whole file

    def test_bodyless_writer_output_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            conversation = Path(tmp) / "conv"
            conversation.write_text("history", encoding="utf-8")
            with unittest.mock.patch.object(self.mod, "generate_text", lambda *a: "no sections"):
                with self.assertRaises(RuntimeError):
                    self.mod.write_checkpoint(conversation, Path(tmp), self._llm(), now=NOW)


class SafetyNetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_nagent_module()

    def _llm(self):
        return self.mod.LlmSettings(provider="openai", model="m")

    def test_checkpoint_failure_never_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            conversation = Path(tmp) / "conv"
            conversation.write_text("x" * (300 * 1024), encoding="utf-8")
            settings = dict(SETTINGS, rebuild_at_kb=0)  # checkpoint path only

            def broken_generate(*args):
                raise RuntimeError("provider down")

            stderr = io.StringIO()
            with unittest.mock.patch.object(self.mod, "generate_text", broken_generate), \
                unittest.mock.patch.object(sys, "stderr", stderr):
                self.mod.run_safety_net(conversation, Path(tmp), self._llm(), settings, now=NOW)

            self.assertIn("checkpoint failed", stderr.getvalue())

    def test_safety_net_llm_work_runs_under_a_spinner(self):
        # A large conversation triggers an LLM call (rebuild or checkpoint) at
        # the top of the loop, before the main call_llm spinner. Without its own
        # spinner the run looks frozen on startup, so both paths must show one.
        def fake_generate(prompt, provider, model):
            return "## Intent\n- ok\n## Next action\n- go"

        # Rebuild path: size over rebuild_at_kb.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "conversations").mkdir()
            conversation = root / "conversations" / "conv"
            context = "<initial_context>\nrules\n</initial_context>\n"
            conversation.write_text(context + "x" * (400 * 1024), encoding="utf-8")
            spinner = unittest.mock.MagicMock()
            with unittest.mock.patch.object(self.mod, "generate_text", fake_generate), \
                unittest.mock.patch.object(self.mod, "wait_spinner", spinner):
                self.mod.run_safety_net(conversation, root, self._llm(), SETTINGS, now=NOW)
            messages = [c.args[0] for c in spinner.call_args_list]
            self.assertTrue(any("Rebuilding" in m for m in messages), messages)

        # Checkpoint path: rebuild disabled, burst over checkpoint_max_new_kb.
        with tempfile.TemporaryDirectory() as tmp:
            conversation = Path(tmp) / "conv"
            conversation.write_text("y" * (300 * 1024), encoding="utf-8")
            settings = dict(SETTINGS, rebuild_at_kb=0)
            spinner = unittest.mock.MagicMock()
            with unittest.mock.patch.object(self.mod, "generate_text", fake_generate), \
                unittest.mock.patch.object(self.mod, "wait_spinner", spinner):
                self.mod.run_safety_net(conversation, Path(tmp), self._llm(), settings, now=NOW)
            messages = [c.args[0] for c in spinner.call_args_list]
            self.assertTrue(any("Checkpointing" in m for m in messages), messages)

    def test_rebuild_archives_and_assembles_fresh_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "conversations").mkdir()
            conversation = root / "conversations" / "conv"
            context = "<initial_context>\nstable rules\nInstance:\n- c\n</initial_context>\n"
            body = "".join(f"<agent-response>\nstep {i}\n</agent-response>\n" for i in range(20000))
            conversation.write_text(context + body, encoding="utf-8")
            original_size = len(context + body)
            self.assertGreater(original_size, 384 * 1024)

            def fake_generate(prompt, provider, model):
                return "## Intent\n- keep going\n## Next action\n- step 20000"

            with unittest.mock.patch.object(self.mod, "generate_text", fake_generate):
                self.mod.run_safety_net(conversation, root, self._llm(), SETTINGS, now=NOW)

            fresh = conversation.read_text(encoding="utf-8")
            self.assertTrue(fresh.startswith("<initial_context>"))
            self.assertIn("{checkpoint}", fresh)
            self.assertIn("- keep going", fresh)
            self.assertIn("Conversation rebuilt at", fresh)
            self.assertIn("step 19999", fresh)  # recent tail survives
            self.assertLess(len(fresh), original_size // 2)

            archives = list(conversation.parent.glob("conv-*"))
            archives = [a for a in archives if not a.name.endswith(".checkpoint.md")]
            self.assertEqual(len(archives), 1)
            self.assertEqual(len(archives[0].read_text(encoding="utf-8")), original_size)

            # Checkpoint meta reset to the fresh window so growth math works.
            meta = self.mod.parse_checkpoint_meta(self.mod.checkpoint_path(conversation))
            self.assertEqual(meta[1], len(fresh))

    def test_rebuild_widens_tail_when_sync_checkpoint_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "conversations").mkdir()
            conversation = root / "conversations" / "conv"
            context = "<initial_context>\nrules\n</initial_context>\n"
            body = "".join(f"line {i}\n" for i in range(80000))
            conversation.write_text(context + body, encoding="utf-8")

            def broken_generate(*args):
                raise RuntimeError("provider down")

            stderr = io.StringIO()
            with unittest.mock.patch.object(self.mod, "generate_text", broken_generate), \
                unittest.mock.patch.object(sys, "stderr", stderr):
                self.mod.run_safety_net(conversation, root, self._llm(), SETTINGS, now=NOW)

            fresh = conversation.read_text(encoding="utf-8")
            self.assertIn("widening raw tail", stderr.getvalue())
            self.assertNotIn("{checkpoint}", fresh)
            # 4x tail: content from ~256KB back survives, not just 64KB.
            tail_body = fresh.split("</system>", 1)[1]
            self.assertGreater(len(tail_body), self.mod.REBUILD_TAIL_CHARS * 2)

    def test_rebuild_refuses_without_context_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            conversation = Path(tmp) / "conv"
            conversation.write_text("x" * (400 * 1024), encoding="utf-8")
            with unittest.mock.patch.object(self.mod, "generate_text", lambda *a: "## Intent"):
                result = self.mod.rebuild_conversation(conversation, Path(tmp), self._llm(), now=NOW)
            self.assertIsNone(result)
            self.assertEqual(len(conversation.read_text(encoding="utf-8")), 400 * 1024)

    def test_loop_runs_safety_net_each_turn(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "conversations").mkdir()
            conversation = root / "conversations" / "conv"
            conversation.write_text(
                "<initial_context>\nrules\n</initial_context>\n", encoding="utf-8"
            )
            calls = []

            def fake_run(cmd, **kwargs):
                payload = {
                    "response": "<nagent-response>ok</nagent-response>",
                    "input_tokens": 1,
                    "output_tokens": 1,
                }
                return unittest.mock.Mock(returncode=0, stdout=json.dumps(payload), stderr="")

            def fake_safety(conv, r, llm, settings, **kwargs):
                calls.append(len(conv.read_text(encoding="utf-8")))

            with unittest.mock.patch.object(self.mod.subprocess, "run", fake_run), \
                unittest.mock.patch.object(self.mod, "run_safety_net", fake_safety):
                code, responses = self.mod.run_agent_loop(
                    conversation,
                    root,
                    self._llm(),
                    "hello",
                    "4242",
                    safety_settings=SETTINGS,
                )

            self.assertEqual(code, 0)
            self.assertEqual(responses, ["ok"])
            self.assertEqual(len(calls), 1)
            # Each turn records a driver status line with time and token totals.
            self.assertIn("<nagent-turn-status ", conversation.read_text(encoding="utf-8"))

    def test_turn_status_block_carries_utc_and_token_totals(self):
        stats = self.mod.TokenStats()
        stats.add_llm_turn(input_tokens=120, output_tokens=30)
        stats.add_llm_turn(input_tokens=200, output_tokens=45)
        block = self.mod.turn_status_block(stats, NOW)
        self.assertEqual(
            block,
            '<nagent-turn-status utc="2026-06-12T12:00:00Z" turn="2" '
            'tokens_in_total="320" tokens_out_total="75" />',
        )

    def test_invalid_content_is_stripped_to_a_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "conversations").mkdir()
            conversation = root / "conversations" / "conv"
            conversation.write_text(
                "<initial_context>\nrules\n</initial_context>\n", encoding="utf-8"
            )

            def fake_run(cmd, **kwargs):
                # A leaked <thought> alongside the real final response.
                payload = {
                    "response": "<thought\nEverything done. Reporting.<nagent-response>all good</nagent-response>",
                    "input_tokens": 5,
                    "output_tokens": 5,
                }
                return unittest.mock.Mock(returncode=0, stdout=json.dumps(payload), stderr="")

            with unittest.mock.patch.object(self.mod.subprocess, "run", fake_run), \
                unittest.mock.patch.object(self.mod, "run_safety_net", lambda *a, **k: None):
                code, responses = self.mod.run_agent_loop(
                    conversation, root, self._llm(), "go", "4242", safety_settings=SETTINGS
                )

            self.assertEqual(code, 0)
            self.assertEqual(responses, ["all good"])
            convo = conversation.read_text(encoding="utf-8")
            # The conversation is clean: no leaked tag, only the valid response.
            self.assertNotIn("<thought", convo)
            self.assertIn("<nagent-response>all good</nagent-response>", convo)
            # The status line links to a sidecar holding the raw output.
            self.assertIn('invalid="', convo)
            sidecars = list((root / "conversations").glob("conv.invalid.*"))
            self.assertEqual(len(sidecars), 1)
            raw = sidecars[0].read_text(encoding="utf-8")
            self.assertIn("<thought", raw)  # the rejected content is reconstructable
            self.assertIn("all good", raw)

    def test_duplicate_tags_collapsed_in_conversation_without_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "conversations").mkdir()
            conversation = root / "conversations" / "conv"
            conversation.write_text(
                "<initial_context>\nrules\n</initial_context>\n", encoding="utf-8"
            )

            def fake_run(cmd, **kwargs):
                # Stutter: the same final response emitted three times.
                payload = {
                    "response": "<nagent-response>done</nagent-response>" * 3,
                    "input_tokens": 5,
                    "output_tokens": 5,
                }
                return unittest.mock.Mock(returncode=0, stdout=json.dumps(payload), stderr="")

            with unittest.mock.patch.object(self.mod.subprocess, "run", fake_run), \
                unittest.mock.patch.object(self.mod, "run_safety_net", lambda *a, **k: None):
                code, responses = self.mod.run_agent_loop(
                    conversation, root, self._llm(), "go", "4242", safety_settings=SETTINGS
                )

            self.assertEqual(code, 0)
            self.assertEqual(responses, ["done"])  # collapsed to one
            convo = conversation.read_text(encoding="utf-8")
            self.assertEqual(convo.count("<nagent-response>done</nagent-response>"), 1)
            self.assertIn("collapsed 2 duplicate tags", convo)
            # Pure dedup is loss-free: no sidecar written.
            self.assertEqual(list((root / "conversations").glob("conv.invalid.*")), [])

    def test_best_of_n_direction_in_initial_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            text = self.mod.build_initial_context(Path(tmp), NAGENT.resolve(), "user", "conv")
        self.assertIn("High-stakes decision?", text)
        self.assertIn("judge worker", text)


if __name__ == "__main__":
    unittest.main()
