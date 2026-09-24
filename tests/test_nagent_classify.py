#!/usr/bin/python3

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BIN = ROOT / "bin"
NAGENT_CLASSIFY = BIN / "nagent-classify"
sys.path.insert(0, str(BIN / "helpers"))

from nagent_classify_lib import (  # noqa: E402
    CATEGORY_QID,
    EXIT_BAD_ANSWER,
    EXIT_BAD_REQUEST,
    MAX_ATTEMPTS,
    ClassifyError,
    DecideError,
    as_decide_request,
    assigned_categories,
    classify,
    load_request,
    render_classify_prompt,
    reshape,
    validate_inputs,
    validate_request,
)


class FakeResult:
    def __init__(self, text, input_tokens=100, output_tokens=20):
        self.text = text
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class Recorder:
    """A generate() stand-in that records the prompts it was handed."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts = []
        self.boundaries = []

    def __call__(self, text, cache_boundaries):
        self.prompts.append(text)
        self.boundaries.append(cache_boundaries)
        reply = self.replies.pop(0) if self.replies else "{}"
        return reply if isinstance(reply, FakeResult) else FakeResult(reply)


REQUEST = {
    "question": "Which lane can run this item's proof?",
    "context": "The gate owns the display, the GPU and real clients.",
    "constraints": ["A staging lane has no display, no GPU and no real client."],
    "categories": {"gate": "needs display, GPU or a real client", "staging": "headless only"},
    "inputs": [
        {"id": "#176", "text": "cursor moved quickly while firing"},
        {"id": "#110", "text": "crew-name relay; headless repro"},
    ],
}


def request(**overrides):
    merged = json.loads(json.dumps(REQUEST))
    merged.update(overrides)
    return merged


def decide_reply(*pairs):
    """A decide-shaped reply assigning each (input id, category-or-list)."""
    decisions = []
    for input_id, value in pairs:
        answer = {"choices": value} if isinstance(value, list) else {"choice": value}
        decisions.append({"item": input_id, "answers": {CATEGORY_QID: answer}})
    return json.dumps({"decisions": decisions})


GOOD = decide_reply(("#176", "gate"), ("#110", "staging"))


# --------------------------------------------------------------------------- #
# request validation -- every failure here costs zero tokens
# --------------------------------------------------------------------------- #


class RequestValidationTests(unittest.TestCase):
    def test_minimal_request_normalizes(self):
        parsed = validate_request(REQUEST)
        self.assertEqual([name for name, _ in parsed["categories"]], ["gate", "staging"])
        self.assertEqual([row["id"] for row in parsed["inputs"]], ["#176", "#110"])
        self.assertFalse(parsed["multi_label"])
        self.assertTrue(parsed["rationale"])
        self.assertTrue(parsed["confidence"])

    def test_non_object_request_is_rejected(self):
        for raw in ([], "x", 3, None):
            with self.assertRaises(ClassifyError):
                validate_request(raw)

    def test_unknown_top_level_key_is_rejected_by_name(self):
        with self.assertRaisesRegex(ClassifyError, "categorys"):
            validate_request(request(categorys={}))

    def test_question_is_required_and_says_why(self):
        for value in (None, "", "   ", 3):
            raw = request()
            raw["question"] = value
            with self.assertRaisesRegex(ClassifyError, "high WHAT"):
                validate_request(raw)

    def test_question_missing_entirely_is_rejected(self):
        raw = request()
        del raw["question"]
        with self.assertRaises(ClassifyError):
            validate_request(raw)

    def test_categories_are_required(self):
        raw = request()
        del raw["categories"]
        with self.assertRaisesRegex(ClassifyError, "closed set"):
            validate_request(raw)

    def test_a_single_category_is_rejected(self):
        with self.assertRaisesRegex(ClassifyError, "classifies nothing"):
            validate_request(request(categories=["only"]))

    def test_categories_accept_a_bare_list(self):
        parsed = validate_request(request(categories=["a", "b"]))
        self.assertEqual(parsed["categories"], [("a", None), ("b", None)])

    def test_duplicate_category_is_rejected(self):
        with self.assertRaisesRegex(ClassifyError, "duplicate"):
            validate_request(request(categories=["a", " a"]))

    def test_category_errors_surface_as_classify_errors(self):
        # normalize_labels lives in the decide library; its rejections must reach the
        # caller as this tool's error type so one handler covers them.
        with self.assertRaises(ClassifyError):
            validate_request(request(categories="a,b"))

    def test_inputs_are_required(self):
        raw = request()
        del raw["inputs"]
        with self.assertRaisesRegex(ClassifyError, r"'inputs' is required"):
            validate_request(raw)

    def test_empty_inputs_is_a_legal_batch_of_zero(self):
        parsed = validate_request(request(inputs=[]))
        self.assertEqual(parsed["inputs"], [])

    def test_bare_string_inputs_are_numbered_from_one(self):
        parsed = validate_request(request(inputs=["first", "second"]))
        self.assertEqual([row["id"] for row in parsed["inputs"]], ["1", "2"])
        self.assertEqual(parsed["inputs"][0]["text"], "first")

    def test_numeric_input_ids_become_strings(self):
        parsed = validate_request(request(inputs=[{"id": 176, "text": "x"}]))
        self.assertEqual(parsed["inputs"][0]["id"], "176")

    def test_null_id_falls_back_to_the_position(self):
        parsed = validate_request(request(inputs=[{"id": None, "text": "x"}]))
        self.assertEqual(parsed["inputs"][0]["id"], "1")

    def test_duplicate_input_id_is_rejected(self):
        with self.assertRaisesRegex(ClassifyError, "duplicate"):
            validate_request(request(inputs=[{"id": "a", "text": "x"}, {"id": "a", "text": "y"}]))

    def test_unknown_input_key_is_rejected(self):
        with self.assertRaisesRegex(ClassifyError, "unknown key"):
            validate_request(request(inputs=[{"id": "a", "body": "x"}]))

    def test_empty_input_text_is_rejected(self):
        # An input with nothing in it cannot be classified, and a model asked to do it
        # anyway would invent a basis. Refuse instead.
        for text in (None, "", "   "):
            with self.assertRaisesRegex(ClassifyError, "must not be empty"):
                validate_request(request(inputs=[{"id": "a", "text": text}]))

    def test_structured_input_text_is_rendered(self):
        parsed = validate_request(request(inputs=[{"id": "a", "text": {"title": "x", "n": 1}}]))
        self.assertEqual(parsed["inputs"][0]["text"], "title: x\nn: 1")

    def test_non_list_inputs_is_rejected(self):
        with self.assertRaises(ClassifyError):
            validate_request(request(inputs="a,b"))

    def test_flag_fields_must_be_boolean(self):
        for field in ("multi_label", "rationale", "confidence"):
            with self.assertRaisesRegex(ClassifyError, field):
                validate_request(request(**{field: "yes"}))

    def test_load_request_reports_bad_json_with_the_request_exit_code(self):
        with self.assertRaises(ClassifyError) as caught:
            load_request("{not json")
        self.assertEqual(caught.exception.exit_code, EXIT_BAD_REQUEST)

    def test_validate_inputs_is_usable_alone(self):
        self.assertEqual(validate_inputs(["a"]), [{"id": "1", "text": "a"}])


# --------------------------------------------------------------------------- #
# translation to a decide request
# --------------------------------------------------------------------------- #


class TranslationTests(unittest.TestCase):
    def test_single_label_becomes_one_choice_question(self):
        translated = as_decide_request(validate_request(REQUEST))
        self.assertEqual(len(translated["questions"]), 1)
        question = translated["questions"][0]
        self.assertEqual(question["id"], CATEGORY_QID)
        self.assertEqual(question["type"], "choice")
        self.assertEqual(question["question"], REQUEST["question"])
        self.assertEqual([name for name, _ in question["options"]], ["gate", "staging"])

    def test_multi_label_becomes_a_multi_question(self):
        translated = as_decide_request(validate_request(request(multi_label=True)))
        self.assertEqual(translated["questions"][0]["type"], "multi")

    def test_inputs_become_items_in_order(self):
        translated = as_decide_request(validate_request(REQUEST))
        self.assertTrue(translated["batched"])
        self.assertEqual([item["id"] for item in translated["items"]], ["#176", "#110"])
        self.assertEqual(translated["items"][0]["context"], "cursor moved quickly while firing")

    def test_category_descriptions_survive_translation(self):
        translated = as_decide_request(validate_request(REQUEST))
        self.assertEqual(
            translated["questions"][0]["options"],
            [("gate", "needs display, GPU or a real client"), ("staging", "headless only")],
        )

    def test_output_switches_pass_through(self):
        translated = as_decide_request(validate_request(request(rationale=False, confidence=False)))
        self.assertFalse(translated["rationale"])
        self.assertFalse(translated["confidence"])

    def test_absent_context_and_constraints_translate_to_nothing(self):
        raw = request()
        del raw["context"]
        del raw["constraints"]
        translated = as_decide_request(validate_request(raw))
        self.assertEqual(translated["context"], "")
        self.assertEqual(translated["constraints"], [])

    def test_prompt_carries_the_question_categories_and_inputs(self):
        prompt, boundary = render_classify_prompt(validate_request(REQUEST))
        self.assertIn(REQUEST["question"], prompt)
        self.assertIn('"gate" — needs display, GPU or a real client', prompt)
        self.assertIn("#176", prompt)
        # Shared evidence goes once for the whole input set -- that is the saving.
        self.assertEqual(prompt.count("The gate owns the display"), 1)
        # The volatile inputs sit after the cacheable prefix.
        self.assertNotIn("<items>", prompt[:boundary])


# --------------------------------------------------------------------------- #
# reshaping: rows and the inverse index
# --------------------------------------------------------------------------- #


class ReshapeTests(unittest.TestCase):
    def setUp(self):
        self.request = validate_request(REQUEST)

    def decisions(self, *pairs):
        return [
            {
                "item": input_id,
                "answers": {
                    CATEGORY_QID: {
                        "type": "multi" if isinstance(value, list) else "choice",
                        "confidence": 0.8,
                        "why": "because",
                        **({"choices": value} if isinstance(value, list) else {"choice": value}),
                    }
                },
            }
            for input_id, value in pairs
        ]

    def test_rows_keep_request_order_and_carry_both_shapes(self):
        rows, _ = reshape(self.request, self.decisions(("#176", "gate"), ("#110", "staging")))
        self.assertEqual([row["input"] for row in rows], ["#176", "#110"])
        self.assertEqual(rows[0]["category"], "gate")
        self.assertEqual(rows[0]["categories"], ["gate"])
        self.assertEqual(rows[0]["confidence"], 0.8)
        self.assertEqual(rows[0]["why"], "because")

    def test_buckets_are_the_inverse_index(self):
        _, buckets = reshape(self.request, self.decisions(("#176", "gate"), ("#110", "staging")))
        self.assertEqual(buckets, {"gate": ["#176"], "staging": ["#110"]})

    def test_every_declared_category_is_a_bucket_even_when_empty(self):
        # An empty bucket is a result: nothing was classified as staging.
        _, buckets = reshape(self.request, self.decisions(("#176", "gate"), ("#110", "gate")))
        self.assertEqual(buckets, {"gate": ["#176", "#110"], "staging": []})

    def test_buckets_list_ids_in_request_order(self):
        rows = self.decisions(("#110", "gate"), ("#176", "gate"))
        _, buckets = reshape(self.request, rows)
        self.assertEqual(buckets["gate"], ["#110", "#176"])

    def test_multi_label_rows_null_the_single_category(self):
        parsed = validate_request(request(multi_label=True))
        rows, buckets = reshape(parsed, self.decisions(("#176", ["gate", "staging"]), ("#110", ["staging"])))
        self.assertIsNone(rows[0]["category"])
        self.assertEqual(rows[0]["categories"], ["gate", "staging"])
        self.assertEqual(buckets, {"gate": ["#176"], "staging": ["#176", "#110"]})

    def test_rows_and_buckets_cannot_disagree(self):
        rows, buckets = reshape(self.request, self.decisions(("#176", "gate"), ("#110", "gate")))
        from_rows = sorted(
            (row["input"], name) for row in rows for name in row["categories"]
        )
        from_buckets = sorted(
            (input_id, name) for name, ids in buckets.items() for input_id in ids
        )
        self.assertEqual(from_rows, from_buckets)

    def test_assigned_categories_reads_either_answer_shape(self):
        self.assertEqual(assigned_categories({"choice": "gate"}), ["gate"])
        self.assertEqual(assigned_categories({"choices": ["gate", "staging"]}), ["gate", "staging"])


# --------------------------------------------------------------------------- #
# the whole transform
# --------------------------------------------------------------------------- #


class ClassifyTests(unittest.TestCase):
    def setUp(self):
        self.request = validate_request(REQUEST)

    def test_a_whole_input_set_is_classified_from_one_call(self):
        recorder = Recorder(GOOD)
        result = classify(self.request, recorder)
        self.assertEqual(len(recorder.prompts), 1)
        self.assertEqual(result["attempts"], 1)
        self.assertEqual(result["buckets"], {"gate": ["#176"], "staging": ["#110"]})
        self.assertEqual([row["category"] for row in result["classified"]], ["gate", "staging"])

    def test_usage_and_corrections_pass_through(self):
        recorder = Recorder(FakeResult(GOOD, input_tokens=310, output_tokens=44))
        result = classify(self.request, recorder)
        self.assertEqual((result["input_tokens"], result["output_tokens"]), (310, 44))
        self.assertEqual(result["corrections"], [])

    def test_a_category_outside_the_set_is_rejected_and_retried(self):
        recorder = Recorder(decide_reply(("#176", "Gate"), ("#110", "staging")), GOOD)
        result = classify(self.request, recorder)
        self.assertEqual(result["attempts"], 2)
        self.assertEqual(len(result["corrections"]), 1)
        self.assertIn("'Gate'", result["corrections"][0])
        self.assertIn("<correction>", recorder.prompts[1])

    def test_an_invented_category_never_reaches_the_output(self):
        recorder = Recorder(decide_reply(("#176", "lane-gate"), ("#110", "staging")))
        with self.assertRaises(DecideError) as caught:
            classify(self.request, recorder, max_attempts=1)
        self.assertEqual(caught.exception.exit_code, EXIT_BAD_ANSWER)

    def test_a_dropped_input_is_rejected_not_returned_partial(self):
        recorder = Recorder(decide_reply(("#176", "gate")))
        with self.assertRaisesRegex(DecideError, "no decision for item"):
            classify(self.request, recorder, max_attempts=1)

    def test_an_invented_input_is_rejected(self):
        recorder = Recorder(decide_reply(("#176", "gate"), ("#110", "staging"), ("#999", "gate")))
        with self.assertRaisesRegex(DecideError, "unknown item"):
            classify(self.request, recorder, max_attempts=1)

    def test_giving_up_reports_every_reason(self):
        recorder = Recorder("no", "still no", "nope")
        with self.assertRaises(DecideError) as caught:
            classify(self.request, recorder)
        self.assertIn(f"after {MAX_ATTEMPTS} attempts", str(caught.exception))

    def test_multi_label_accepts_several_categories_per_input(self):
        parsed = validate_request(request(multi_label=True))
        recorder = Recorder(decide_reply(("#176", ["gate", "staging"]), ("#110", ["staging"])))
        result = classify(parsed, recorder)
        self.assertEqual(result["classified"][0]["categories"], ["gate", "staging"])
        self.assertEqual(result["buckets"]["staging"], ["#176", "#110"])

    def test_single_label_refuses_a_list_answer(self):
        recorder = Recorder(decide_reply(("#176", ["gate", "staging"]), ("#110", "staging")))
        with self.assertRaises(DecideError):
            classify(self.request, recorder, max_attempts=1)

    def test_an_empty_input_set_makes_no_call_and_costs_nothing(self):
        recorder = Recorder(GOOD)
        result = classify(validate_request(request(inputs=[])), recorder)
        self.assertEqual(recorder.prompts, [])
        self.assertEqual(result["classified"], [])
        self.assertEqual(result["input_tokens"], 0)
        self.assertEqual(result["attempts"], 0)
        # The buckets still describe the declared set, so a consumer that indexes
        # into them does not have to special-case the empty run.
        self.assertEqual(result["buckets"], {"gate": [], "staging": []})

    def test_trailers_off_null_the_fields_but_keep_the_layout(self):
        parsed = validate_request(request(rationale=False, confidence=False))
        result = classify(parsed, Recorder(GOOD))
        row = result["classified"][0]
        self.assertIsNone(row["confidence"])
        self.assertIsNone(row["why"])
        self.assertEqual(row["category"], "gate")

    def test_the_cache_boundary_reaches_the_provider(self):
        recorder = Recorder(GOOD)
        classify(self.request, recorder)
        self.assertEqual(recorder.boundaries[0], [render_classify_prompt(self.request)[1]])

    def test_a_large_input_set_is_still_one_call(self):
        many = [{"id": f"#{n}", "text": f"item {n}"} for n in range(40)]
        parsed = validate_request(request(inputs=many))
        recorder = Recorder(decide_reply(*((f"#{n}", "gate") for n in range(40))))
        result = classify(parsed, recorder)
        self.assertEqual(len(recorder.prompts), 1)
        self.assertEqual(len(result["classified"]), 40)
        self.assertEqual(len(result["buckets"]["gate"]), 40)


# --------------------------------------------------------------------------- #
# the executable
# --------------------------------------------------------------------------- #


def run_cli(*args, stdin=""):
    return subprocess.run(
        [sys.executable, str(NAGENT_CLASSIFY), *args],
        input=stdin,
        capture_output=True,
        text=True,
    )


class CliTests(unittest.TestCase):
    def test_description_names_the_tool_and_its_shape(self):
        result = run_cli("--description")
        self.assertEqual(result.returncode, 0)
        self.assertIn("nagent-classify", result.stdout)
        self.assertIn("buckets", result.stdout)
        # It has to say when to reach for the other tool, or the two overlap.
        self.assertIn("nagent-decide", result.stdout)

    def test_dry_run_renders_the_prompt_without_a_provider(self):
        result = run_cli("--dry-run", stdin=json.dumps(REQUEST))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("#176", result.stdout)
        self.assertIn('"gate"', result.stdout)

    def test_prompt_out_matches_the_rendered_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "prompt.txt"
            result = run_cli("--dry-run", "--prompt-out", str(out), stdin=json.dumps(REQUEST))
            self.assertEqual(out.read_text(encoding="utf-8"), result.stdout)

    def test_input_file_and_stdin_agree(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "request.json"
            path.write_text(json.dumps(REQUEST), encoding="utf-8")
            self.assertEqual(
                run_cli("--dry-run", "--input", str(path)).stdout,
                run_cli("--dry-run", stdin=json.dumps(REQUEST)).stdout,
            )

    def test_a_bad_request_exits_2_and_names_the_field(self):
        raw = request()
        del raw["categories"]
        result = run_cli("--dry-run", stdin=json.dumps(raw))
        self.assertEqual(result.returncode, EXIT_BAD_REQUEST)
        self.assertIn("categories", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_invalid_json_exits_2(self):
        result = run_cli("--dry-run", stdin="{nope")
        self.assertEqual(result.returncode, EXIT_BAD_REQUEST)

    def test_a_missing_input_file_exits_1(self):
        result = run_cli("--dry-run", "--input", "/nonexistent/request.json")
        self.assertEqual(result.returncode, 1)

    def test_zero_attempts_is_rejected(self):
        result = run_cli("--attempts", "0", stdin=json.dumps(REQUEST))
        self.assertEqual(result.returncode, EXIT_BAD_REQUEST)

    def test_an_empty_input_set_prints_empty_buckets_without_a_provider(self):
        # No provider is configured here, so reaching exit 0 proves nothing was sent.
        result = run_cli(stdin=json.dumps(request(inputs=[])))
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["classified"], [])
        self.assertEqual(payload["buckets"], {"gate": [], "staging": []})
        self.assertEqual(payload["attempts"], 0)


class ToolDiscoveryTests(unittest.TestCase):
    def test_the_loop_discovers_nagent_classify_by_running_it(self):
        sys.path.insert(0, str(BIN / "helpers"))
        from nagent_cli import collect_bin_tool_descriptions

        self.assertIn("nagent-classify", collect_bin_tool_descriptions(BIN))


if __name__ == "__main__":
    unittest.main()
