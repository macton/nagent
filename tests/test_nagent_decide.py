#!/usr/bin/python3

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BIN = ROOT / "bin"
NAGENT_DECIDE = BIN / "nagent-decide"
sys.path.insert(0, str(BIN / "helpers"))

from nagent_decide_lib import (  # noqa: E402
    EXIT_BAD_ANSWER,
    EXIT_BAD_REQUEST,
    MAX_ATTEMPTS,
    DecideError,
    decide,
    load_request,
    normalize_labels,
    parse_json_object,
    render_context,
    render_prompt,
    validate_answers,
    validate_request,
)


class FakeResult:
    def __init__(self, text, input_tokens=100, output_tokens=20):
        self.text = text
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class Recorder:
    """A generate() stand-in: hands back scripted replies and records the prompts
    it was given, so a test can assert on what was actually sent."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts = []
        self.boundaries = []

    def __call__(self, text, cache_boundaries):
        self.prompts.append(text)
        self.boundaries.append(cache_boundaries)
        reply = self.replies.pop(0) if self.replies else "{}"
        return reply if isinstance(reply, FakeResult) else FakeResult(reply)


CHOICE_REQUEST = {
    "context": "The item needs two clients and a display.",
    "constraints": ["A staging lane has no display, no GPU and no real client."],
    "questions": {
        "lane": {
            "question": "Which lane?",
            "type": "choice",
            "options": {"gate": "owns display and clients", "staging": "headless only"},
        }
    },
}


def batched(**overrides):
    request = json.loads(json.dumps(CHOICE_REQUEST))
    request["items"] = [
        {"id": "#176", "context": "cursor moved quickly while firing"},
        {"id": "#193", "context": "muzzle offset, headless repro"},
    ]
    request.update(overrides)
    return request


# --------------------------------------------------------------------------- #
# closed answer sets
# --------------------------------------------------------------------------- #


class NormalizeLabelsTests(unittest.TestCase):
    def test_list_of_names_has_no_descriptions(self):
        self.assertEqual(normalize_labels(["a", "b"], "o"), [("a", None), ("b", None)])

    def test_object_keeps_declared_order_and_descriptions(self):
        labels = normalize_labels({"gate": "owns clients", "staging": None}, "o")
        self.assertEqual(labels, [("gate", "owns clients"), ("staging", None)])

    def test_names_are_stripped(self):
        self.assertEqual(normalize_labels([" a "], "o"), [("a", None)])

    def test_blank_description_becomes_none(self):
        self.assertEqual(normalize_labels({"a": "   "}, "o"), [("a", None)])

    def test_empty_set_is_rejected(self):
        for spec in ([], {}):
            with self.assertRaises(DecideError):
                normalize_labels(spec, "o")

    def test_duplicate_name_is_rejected(self):
        with self.assertRaisesRegex(DecideError, "duplicate"):
            normalize_labels(["a", " a"], "o")

    def test_non_string_name_is_rejected(self):
        for spec in ([1], [""], [None]):
            with self.assertRaises(DecideError):
                normalize_labels(spec, "o")

    def test_wrong_container_is_rejected(self):
        with self.assertRaises(DecideError):
            normalize_labels("a,b", "o")

    def test_non_string_description_is_rejected(self):
        with self.assertRaises(DecideError):
            normalize_labels({"a": 3}, "o")


class RenderContextTests(unittest.TestCase):
    def test_string_passes_through(self):
        self.assertEqual(render_context("  hello  "), "hello")

    def test_none_is_empty(self):
        self.assertEqual(render_context(None), "")

    def test_object_becomes_labeled_lines(self):
        self.assertEqual(render_context({"repo": "helmfire", "cycle": 12}), "repo: helmfire\ncycle: 12")

    def test_array_becomes_bullets(self):
        self.assertEqual(render_context(["a", "b"]), "- a\n- b")

    def test_nested_object_is_indented_under_its_key(self):
        rendered = render_context({"issue": {"number": 176, "title": "drops shots"}})
        self.assertEqual(rendered, "issue:\n  number: 176\n  title: drops shots")

    def test_booleans_render_as_json_words(self):
        self.assertEqual(render_context({"ok": True, "bad": False}), "ok: true\nbad: false")


# --------------------------------------------------------------------------- #
# request validation -- every failure here costs zero tokens
# --------------------------------------------------------------------------- #


class RequestValidationTests(unittest.TestCase):
    def test_minimal_request_is_a_batch_of_one_with_a_null_id(self):
        request = validate_request(CHOICE_REQUEST)
        self.assertFalse(request["batched"])
        self.assertEqual([item["id"] for item in request["items"]], [None])
        self.assertTrue(request["rationale"])

    def test_questions_keep_declared_order(self):
        request = validate_request(
            {
                "questions": {
                    "b": {"question": "?", "type": "choice", "options": ["x", "y"]},
                    "a": {"question": "?", "type": "choice", "options": ["x", "y"]},
                }
            }
        )
        self.assertEqual([q["id"] for q in request["questions"]], ["b", "a"])

    def test_non_object_request_is_rejected(self):
        for raw in ([], "x", 3, None):
            with self.assertRaises(DecideError):
                validate_request(raw)

    def test_unknown_top_level_key_is_rejected_by_name(self):
        with self.assertRaisesRegex(DecideError, "questionz"):
            validate_request({"questions": CHOICE_REQUEST["questions"], "questionz": {}})

    def test_missing_or_empty_questions_is_rejected(self):
        for raw in ({}, {"questions": {}}, {"questions": []}):
            with self.assertRaisesRegex(DecideError, "questions"):
                validate_request(raw)

    def test_blank_question_id_is_rejected(self):
        with self.assertRaises(DecideError):
            validate_request({"questions": {"  ": {"question": "?", "type": "choice", "options": ["a", "b"]}}})

    def test_options_are_required(self):
        with self.assertRaisesRegex(DecideError, "closed set"):
            validate_request({"questions": {"q": {"question": "?", "type": "choice"}}})

    def test_unknown_question_key_is_rejected(self):
        with self.assertRaisesRegex(DecideError, "unknown key"):
            validate_request(
                {"questions": {"q": {"question": "?", "type": "choice", "option": ["a", "b"]}}}
            )

    def test_unknown_type_is_rejected(self):
        with self.assertRaisesRegex(DecideError, "type"):
            validate_request({"questions": {"q": {"question": "?", "type": "rank", "options": ["a", "b"]}}})

    def test_single_option_choice_is_rejected(self):
        with self.assertRaisesRegex(DecideError, "not a decision"):
            validate_request({"questions": {"q": {"question": "?", "type": "choice", "options": ["a"]}}})

    def test_multi_accepts_a_single_option(self):
        request = validate_request({"questions": {"q": {"question": "?", "type": "multi", "options": ["a"]}}})
        self.assertEqual(request["questions"][0]["options"], [("a", None)])

    def test_score_requires_levels(self):
        with self.assertRaisesRegex(DecideError, "levels"):
            validate_request({"questions": {"q": {"question": "?", "type": "score", "options": ["a"]}}})

    def test_score_needs_at_least_two_levels(self):
        with self.assertRaisesRegex(DecideError, "scale"):
            validate_request(
                {"questions": {"q": {"question": "?", "type": "score", "options": ["a"], "levels": ["hi"]}}}
            )

    def test_levels_on_a_non_score_question_is_rejected(self):
        with self.assertRaisesRegex(DecideError, "only .* 'score'"):
            validate_request(
                {
                    "questions": {
                        "q": {"question": "?", "type": "choice", "options": ["a", "b"], "levels": ["x", "y"]}
                    }
                }
            )

    def test_non_string_constraint_is_rejected(self):
        with self.assertRaises(DecideError):
            validate_request({"questions": CHOICE_REQUEST["questions"], "constraints": [1]})

    def test_non_bool_rationale_is_rejected(self):
        with self.assertRaises(DecideError):
            validate_request({"questions": CHOICE_REQUEST["questions"], "rationale": "yes"})

    def test_rationale_and_confidence_are_both_on_by_default(self):
        request = validate_request(CHOICE_REQUEST)
        self.assertTrue(request["rationale"])
        self.assertTrue(request["confidence"])

    def test_non_bool_confidence_is_rejected(self):
        for value in ("yes", 1, None):
            with self.assertRaises(DecideError):
                validate_request({"questions": CHOICE_REQUEST["questions"], "confidence": value})

    def test_string_items_are_numbered_from_one(self):
        request = validate_request({**CHOICE_REQUEST, "items": ["first", "second"]})
        self.assertEqual([item["id"] for item in request["items"]], ["1", "2"])
        self.assertEqual(request["items"][0]["context"], "first")

    def test_numeric_item_ids_become_strings(self):
        request = validate_request({**CHOICE_REQUEST, "items": [{"id": 176, "context": "x"}]})
        self.assertEqual(request["items"][0]["id"], "176")

    def test_an_explicit_null_id_falls_back_to_the_position(self):
        request = validate_request({**CHOICE_REQUEST, "items": [{"id": None, "context": "x"}]})
        self.assertEqual(request["items"][0]["id"], "1")

    def test_duplicate_item_id_is_rejected(self):
        with self.assertRaisesRegex(DecideError, "duplicate"):
            validate_request({**CHOICE_REQUEST, "items": [{"id": "a"}, {"id": "a"}]})

    def test_unknown_item_key_is_rejected(self):
        with self.assertRaisesRegex(DecideError, "unknown key"):
            validate_request({**CHOICE_REQUEST, "items": [{"id": "a", "body": "x"}]})

    def test_empty_items_list_is_a_batch_of_zero(self):
        request = validate_request({**CHOICE_REQUEST, "items": []})
        self.assertTrue(request["batched"])
        self.assertEqual(request["items"], [])

    def test_item_context_may_be_structured(self):
        request = validate_request({**CHOICE_REQUEST, "items": [{"id": "a", "context": {"n": 1}}]})
        self.assertEqual(request["items"][0]["context"], "n: 1")

    def test_load_request_reports_bad_json_as_a_request_error(self):
        with self.assertRaises(DecideError) as caught:
            load_request("{not json")
        self.assertEqual(caught.exception.exit_code, EXIT_BAD_REQUEST)


# --------------------------------------------------------------------------- #
# prompt rendering
# --------------------------------------------------------------------------- #


class RenderPromptTests(unittest.TestCase):
    def test_stable_sections_precede_the_boundary_and_items_follow_it(self):
        prompt, boundary = render_prompt(validate_request(batched()))
        head, tail = prompt[:boundary], prompt[boundary:]
        self.assertIn("<constraints>", head)
        self.assertIn("<evidence>", head)
        self.assertIn("<questions>", head)
        self.assertNotIn("<items>", head)
        self.assertIn("<items>", tail)
        self.assertIn("#176", tail)

    def test_shared_evidence_appears_once_for_a_whole_batch(self):
        prompt, _ = render_prompt(validate_request(batched()))
        self.assertEqual(prompt.count("The item needs two clients and a display."), 1)

    def test_option_names_are_quoted_and_descriptions_follow(self):
        # The quotes are load-bearing: an unquoted `name — description` line was
        # measured answering with the whole line, which reads correct and fails
        # every string comparison a script makes. See examples/monitor-github.
        prompt, _ = render_prompt(validate_request(CHOICE_REQUEST))
        self.assertIn('"gate" — owns display and clients', prompt)
        self.assertIn('"staging" — headless only', prompt)
        self.assertIn("quoted name only", prompt)

    def test_contract_names_every_item_and_question_id(self):
        prompt, _ = render_prompt(validate_request(batched()))
        self.assertIn("exactly these question ids: lane", prompt)
        self.assertIn("in this order: #176, #193", prompt)

    def test_unbatched_contract_asks_for_a_null_item(self):
        prompt, _ = render_prompt(validate_request(CHOICE_REQUEST))
        self.assertIn('"item": null', prompt)
        self.assertNotIn("<items>", prompt)

    def test_rationale_off_drops_the_why_field_from_the_contract(self):
        prompt, _ = render_prompt(validate_request({**CHOICE_REQUEST, "rationale": False}))
        self.assertIn('Do not include a "why" field', prompt)
        self.assertNotIn('"why": "..."', prompt)

    def test_confidence_off_drops_the_field_from_the_contract(self):
        prompt, _ = render_prompt(validate_request({**CHOICE_REQUEST, "confidence": False}))
        self.assertIn('Do not include a "confidence" field', prompt)
        self.assertNotIn('"confidence": 0.0', prompt)
        self.assertIn('"why": "..."', prompt)

    def test_both_trailers_off_asks_for_the_bare_decision(self):
        prompt, _ = render_prompt(
            validate_request({**CHOICE_REQUEST, "confidence": False, "rationale": False})
        )
        self.assertIn('choice: {"choice": "<one quoted option name>"}', prompt)
        self.assertNotIn('"confidence"', prompt.split("Answer shape")[1])
        self.assertNotIn('"why"', prompt.split("Answer shape")[1])

    def test_each_trailer_is_independent_in_every_shape(self):
        request = validate_request(
            {
                "questions": {
                    "c": {"question": "?", "type": "choice", "options": ["a", "b"]},
                    "m": {"question": "?", "type": "multi", "options": ["a", "b"]},
                    "s": {"question": "?", "type": "score", "options": ["a"], "levels": ["lo", "hi"]},
                },
                "rationale": False,
            }
        )
        prompt, _ = render_prompt(request)
        shapes = prompt.split("Answer shape")[1]
        self.assertEqual(shapes.count('"confidence": 0.0'), 3)
        self.assertNotIn('"why"', shapes)

    def test_only_the_shapes_in_use_are_described(self):
        prompt, _ = render_prompt(validate_request(CHOICE_REQUEST))
        self.assertIn("choice: {", prompt)
        self.assertNotIn("scores", prompt)

    def test_score_levels_render_ordered_lowest_first(self):
        prompt, _ = render_prompt(
            validate_request(
                {
                    "questions": {
                        "u": {
                            "question": "?",
                            "type": "score",
                            "options": ["urgency"],
                            "levels": ["can-wait", "this-week", "today"],
                        }
                    }
                }
            )
        )
        self.assertIn('1. "can-wait"', prompt)
        self.assertIn('3. "today"', prompt)

    def test_missing_evidence_omits_the_block(self):
        prompt, _ = render_prompt(validate_request({"questions": CHOICE_REQUEST["questions"]}))
        self.assertNotIn("<evidence>", prompt)
        self.assertNotIn("<constraints>", prompt)


# --------------------------------------------------------------------------- #
# reply parsing
# --------------------------------------------------------------------------- #


class ParseJsonObjectTests(unittest.TestCase):
    def test_bare_object(self):
        self.assertEqual(parse_json_object('{"a": 1}'), {"a": 1})

    def test_fenced_object(self):
        self.assertEqual(parse_json_object('```json\n{"a": 1}\n```'), {"a": 1})

    def test_object_wrapped_in_prose(self):
        self.assertEqual(parse_json_object('Sure!\n{"a": 1}\nHope that helps.'), {"a": 1})

    def test_top_level_array_is_rejected(self):
        with self.assertRaises(DecideError):
            parse_json_object("[1, 2]")

    def test_empty_reply_is_rejected(self):
        for text in ("", "   ", None):
            with self.assertRaises(DecideError):
                parse_json_object(text)

    def test_prose_only_is_rejected(self):
        with self.assertRaisesRegex(DecideError, "no JSON object"):
            parse_json_object("I would pick the gate lane.")

    def test_rejection_exits_on_the_answer_code(self):
        with self.assertRaises(DecideError) as caught:
            parse_json_object("nope")
        self.assertEqual(caught.exception.exit_code, EXIT_BAD_ANSWER)


# --------------------------------------------------------------------------- #
# answer validation -- the closed set is enforced here or nowhere
# --------------------------------------------------------------------------- #


def reply(answers, item=None):
    return {"decisions": [{"item": item, "answers": answers}]}


class ChoiceAnswerTests(unittest.TestCase):
    def setUp(self):
        self.request = validate_request(CHOICE_REQUEST)

    def test_declared_option_is_accepted(self):
        decisions = validate_answers(
            self.request, reply({"lane": {"choice": "gate", "confidence": 0.9, "why": "needs clients"}})
        )
        self.assertEqual(decisions[0]["item"], None)
        self.assertEqual(decisions[0]["answers"]["lane"]["choice"], "gate")
        self.assertEqual(decisions[0]["answers"]["lane"]["confidence"], 0.9)
        self.assertEqual(decisions[0]["answers"]["lane"]["why"], "needs clients")
        self.assertEqual(decisions[0]["answers"]["lane"]["type"], "choice")

    def test_option_outside_the_set_is_rejected_not_coerced(self):
        with self.assertRaisesRegex(DecideError, "must be one of"):
            validate_answers(self.request, reply({"lane": {"choice": "the gate lane"}}))

    def test_case_and_whitespace_variants_are_rejected(self):
        for value in ("Gate", " gate", "gate "):
            with self.assertRaises(DecideError):
                validate_answers(self.request, reply({"lane": {"choice": value}}))

    def test_missing_choice_is_rejected(self):
        with self.assertRaises(DecideError):
            validate_answers(self.request, reply({"lane": {"confidence": 1.0}}))

    def test_non_object_answer_is_rejected(self):
        with self.assertRaisesRegex(DecideError, "must be an object"):
            validate_answers(self.request, reply({"lane": "gate"}))

    def test_absent_confidence_and_why_are_null(self):
        answer = validate_answers(self.request, reply({"lane": {"choice": "gate"}}))[0]["answers"]["lane"]
        self.assertIsNone(answer["confidence"])
        self.assertIsNone(answer["why"])

    def test_confidence_is_clamped_into_range(self):
        for raw, expected in ((1.7, 1.0), (-2, 0.0), (0.5, 0.5)):
            answer = validate_answers(self.request, reply({"lane": {"choice": "gate", "confidence": raw}}))
            self.assertEqual(answer[0]["answers"]["lane"]["confidence"], expected)

    def test_unparseable_confidence_is_null_not_a_failure(self):
        for raw in ("high", True, None, [0.5]):
            answer = validate_answers(self.request, reply({"lane": {"choice": "gate", "confidence": raw}}))
            self.assertIsNone(answer[0]["answers"]["lane"]["confidence"])

    def test_confidence_off_nulls_the_field_but_keeps_the_key(self):
        request = validate_request({**CHOICE_REQUEST, "confidence": False})
        answer = validate_answers(request, reply({"lane": {"choice": "gate", "confidence": 0.9}}))
        answer = answer[0]["answers"]["lane"]
        self.assertIn("confidence", answer)
        self.assertIsNone(answer["confidence"])
        self.assertEqual(answer["choice"], "gate")

    def test_rationale_off_nulls_a_volunteered_why(self):
        request = validate_request({**CHOICE_REQUEST, "rationale": False})
        answer = validate_answers(request, reply({"lane": {"choice": "gate", "why": "because"}}))
        self.assertIsNone(answer[0]["answers"]["lane"]["why"])

    def test_both_off_still_yields_the_full_answer_layout(self):
        request = validate_request({**CHOICE_REQUEST, "rationale": False, "confidence": False})
        answer = validate_answers(request, reply({"lane": {"choice": "gate"}}))[0]["answers"]["lane"]
        self.assertEqual(answer, {"type": "choice", "confidence": None, "why": None, "choice": "gate"})

    def test_turning_a_trailer_off_never_rejects_an_answer(self):
        # The trailers are soft everywhere: dropping them must not turn a valid
        # decision into a retry.
        request = validate_request({**CHOICE_REQUEST, "rationale": False, "confidence": False})
        for raw in ({"choice": "gate"}, {"choice": "gate", "confidence": 3}, {"choice": "gate", "why": ""}):
            self.assertEqual(
                validate_answers(request, reply({"lane": raw}))[0]["answers"]["lane"]["choice"], "gate"
            )

    def test_blank_why_is_null(self):
        answer = validate_answers(self.request, reply({"lane": {"choice": "gate", "why": "  "}}))
        self.assertIsNone(answer[0]["answers"]["lane"]["why"])


class MultiAnswerTests(unittest.TestCase):
    def setUp(self):
        self.request = validate_request(
            {
                "questions": {
                    "pre": {
                        "question": "?",
                        "type": "multi",
                        "options": ["step-audit", "step-165", "step-228"],
                    }
                }
            }
        )

    def test_subset_is_accepted(self):
        answer = validate_answers(self.request, reply({"pre": {"choices": ["step-audit", "step-228"]}}))
        self.assertEqual(answer[0]["answers"]["pre"]["choices"], ["step-audit", "step-228"])

    def test_duplicates_collapse_to_a_set_in_declared_reply_order(self):
        answer = validate_answers(
            self.request, reply({"pre": {"choices": ["step-228", "step-audit", "step-228"]}})
        )
        self.assertEqual(answer[0]["answers"]["pre"]["choices"], ["step-228", "step-audit"])

    def test_one_stray_entry_rejects_the_whole_answer(self):
        with self.assertRaisesRegex(DecideError, "step-999"):
            validate_answers(self.request, reply({"pre": {"choices": ["step-audit", "step-999"]}}))

    def test_empty_selection_is_rejected(self):
        with self.assertRaises(DecideError):
            validate_answers(self.request, reply({"pre": {"choices": []}}))

    def test_bare_string_instead_of_a_list_is_rejected(self):
        with self.assertRaises(DecideError):
            validate_answers(self.request, reply({"pre": {"choices": "step-audit"}}))


class ScoreAnswerTests(unittest.TestCase):
    def setUp(self):
        self.request = validate_request(
            {
                "questions": {
                    "u": {
                        "question": "?",
                        "type": "score",
                        "options": ["#176", "#193"],
                        "levels": ["can-wait", "this-week", "today"],
                    }
                }
            }
        )

    def test_every_option_scored_yields_labels_and_indices(self):
        answer = validate_answers(
            self.request, reply({"u": {"scores": {"#176": "today", "#193": "can-wait"}}})
        )[0]["answers"]["u"]
        self.assertEqual(answer["scores"], {"#176": "today", "#193": "can-wait"})
        self.assertEqual(answer["level_index"], {"#176": 2, "#193": 0})

    def test_level_index_survives_both_trailers_being_off(self):
        request = validate_request(
            {
                "questions": {
                    "u": {
                        "question": "?",
                        "type": "score",
                        "options": ["#176"],
                        "levels": ["can-wait", "this-week", "today"],
                    }
                },
                "rationale": False,
                "confidence": False,
            }
        )
        answer = validate_answers(request, reply({"u": {"scores": {"#176": "today"}}}))[0]["answers"]["u"]
        self.assertEqual(answer["level_index"], {"#176": 2})

    def test_scores_are_emitted_in_declared_option_order(self):
        answer = validate_answers(
            self.request, reply({"u": {"scores": {"#193": "today", "#176": "can-wait"}}})
        )[0]["answers"]["u"]
        self.assertEqual(list(answer["scores"]), ["#176", "#193"])

    def test_a_missing_option_is_rejected(self):
        with self.assertRaisesRegex(DecideError, "missing option"):
            validate_answers(self.request, reply({"u": {"scores": {"#176": "today"}}}))

    def test_an_unknown_option_is_rejected(self):
        with self.assertRaisesRegex(DecideError, "unknown option"):
            validate_answers(
                self.request,
                reply({"u": {"scores": {"#176": "today", "#193": "today", "#999": "today"}}}),
            )

    def test_a_level_outside_the_scale_is_rejected(self):
        with self.assertRaisesRegex(DecideError, "must be one of"):
            validate_answers(self.request, reply({"u": {"scores": {"#176": "urgent", "#193": "today"}}}))

    def test_a_numeric_level_is_rejected_rather_than_mapped(self):
        with self.assertRaises(DecideError):
            validate_answers(self.request, reply({"u": {"scores": {"#176": 3, "#193": 1}}}))

    def test_non_object_scores_is_rejected(self):
        with self.assertRaises(DecideError):
            validate_answers(self.request, reply({"u": {"scores": ["today", "today"]}}))


class GridCoverageTests(unittest.TestCase):
    def setUp(self):
        self.request = validate_request(batched())

    def good(self):
        return {
            "decisions": [
                {"item": "#176", "answers": {"lane": {"choice": "gate"}}},
                {"item": "#193", "answers": {"lane": {"choice": "staging"}}},
            ]
        }

    def test_full_grid_is_accepted_in_request_item_order(self):
        decisions = validate_answers(self.request, self.good())
        self.assertEqual([d["item"] for d in decisions], ["#176", "#193"])
        self.assertEqual(decisions[1]["answers"]["lane"]["choice"], "staging")

    def test_reply_item_order_does_not_matter(self):
        payload = self.good()
        payload["decisions"].reverse()
        decisions = validate_answers(self.request, payload)
        self.assertEqual([d["item"] for d in decisions], ["#176", "#193"])
        self.assertEqual(decisions[0]["answers"]["lane"]["choice"], "gate")

    def test_numeric_item_ids_in_the_reply_match_string_ids(self):
        request = validate_request({**CHOICE_REQUEST, "items": [{"id": 176, "context": "x"}]})
        decisions = validate_answers(
            request, {"decisions": [{"item": 176, "answers": {"lane": {"choice": "gate"}}}]}
        )
        self.assertEqual(decisions[0]["item"], "176")

    def test_a_lone_unbatched_answer_is_accepted_whatever_id_it_carries(self):
        # One decision was asked for and one came back: the id cannot be ambiguous,
        # so accepting it saves a correction round on an unmistakable reply.
        request = validate_request(CHOICE_REQUEST)
        for item in ("1", 1, "decision", None):
            decisions = validate_answers(
                request, {"decisions": [{"item": item, "answers": {"lane": {"choice": "gate"}}}]}
            )
            self.assertEqual(decisions[0]["item"], None)
            self.assertEqual(decisions[0]["answers"]["lane"]["choice"], "gate")

    def test_an_unbatched_reply_with_two_entries_is_still_rejected(self):
        request = validate_request(CHOICE_REQUEST)
        with self.assertRaises(DecideError):
            validate_answers(
                request,
                {
                    "decisions": [
                        {"item": "a", "answers": {"lane": {"choice": "gate"}}},
                        {"item": "b", "answers": {"lane": {"choice": "staging"}}},
                    ]
                },
            )

    def test_a_dropped_item_is_rejected_not_returned_partial(self):
        payload = self.good()
        payload["decisions"].pop()
        with self.assertRaisesRegex(DecideError, "no decision for item"):
            validate_answers(self.request, payload)

    def test_an_invented_item_is_rejected(self):
        payload = self.good()
        payload["decisions"].append({"item": "#999", "answers": {"lane": {"choice": "gate"}}})
        with self.assertRaisesRegex(DecideError, "unknown item"):
            validate_answers(self.request, payload)

    def test_two_decisions_for_one_item_are_rejected(self):
        payload = self.good()
        payload["decisions"].append({"item": "#176", "answers": {"lane": {"choice": "staging"}}})
        with self.assertRaisesRegex(DecideError, "two decisions"):
            validate_answers(self.request, payload)

    def test_a_missing_question_is_rejected(self):
        request = validate_request(
            {
                "questions": {
                    "lane": CHOICE_REQUEST["questions"]["lane"],
                    "block": {"question": "?", "type": "choice", "options": ["work", "blocked"]},
                }
            }
        )
        with self.assertRaisesRegex(DecideError, "no answer for question"):
            validate_answers(request, reply({"lane": {"choice": "gate"}}))

    def test_an_invented_question_is_rejected(self):
        with self.assertRaisesRegex(DecideError, "unknown question"):
            validate_answers(
                self.request,
                {
                    "decisions": [
                        {"item": "#176", "answers": {"lane": {"choice": "gate"}, "extra": {"choice": "x"}}},
                        {"item": "#193", "answers": {"lane": {"choice": "gate"}}},
                    ]
                },
            )

    def test_decisions_must_be_a_list(self):
        with self.assertRaisesRegex(DecideError, "'decisions' must be a list"):
            validate_answers(self.request, {"decisions": {"#176": {}}})

    def test_answers_must_be_an_object(self):
        with self.assertRaisesRegex(DecideError, "'answers' must be an object"):
            validate_answers(
                self.request,
                {"decisions": [{"item": "#176", "answers": ["gate"]}, {"item": "#193", "answers": {}}]},
            )

    def test_error_names_the_item_it_came_from(self):
        payload = self.good()
        payload["decisions"][1]["answers"]["lane"]["choice"] = "nope"
        with self.assertRaisesRegex(DecideError, r"item #193"):
            validate_answers(self.request, payload)


# --------------------------------------------------------------------------- #
# the whole transform: retries, usage accounting, the empty batch
# --------------------------------------------------------------------------- #

GOOD = '{"decisions": [{"item": null, "answers": {"lane": {"choice": "gate", "confidence": 0.8}}}]}'


class DecideTests(unittest.TestCase):
    def setUp(self):
        self.request = validate_request(CHOICE_REQUEST)

    def test_a_clean_run_reports_no_corrections(self):
        result = decide(self.request, Recorder(GOOD))
        self.assertEqual(result["corrections"], [])

    def test_corrections_record_why_each_attempt_was_rejected(self):
        recorder = Recorder('{"decisions": [{"item": null, "answers": {"lane": {"choice": "GATE"}}}]}', GOOD)
        result = decide(self.request, recorder)
        self.assertEqual(len(result["corrections"]), 1)
        self.assertIn("'GATE'", result["corrections"][0])

    def test_first_try_success_reports_one_attempt_and_its_usage(self):
        recorder = Recorder(FakeResult(GOOD, input_tokens=420, output_tokens=31))
        result = decide(self.request, recorder)
        self.assertEqual(result["attempts"], 1)
        self.assertEqual(result["input_tokens"], 420)
        self.assertEqual(result["output_tokens"], 31)
        self.assertEqual(result["decisions"][0]["answers"]["lane"]["choice"], "gate")

    def test_the_cache_boundary_is_passed_through_to_the_provider(self):
        recorder = Recorder(GOOD)
        decide(self.request, recorder)
        boundary = render_prompt(self.request)[1]
        self.assertEqual(recorder.boundaries[0], [boundary])

    def test_a_bad_answer_is_corrected_and_retried(self):
        recorder = Recorder('{"decisions": [{"item": null, "answers": {"lane": {"choice": "GATE"}}}]}', GOOD)
        result = decide(self.request, recorder)
        self.assertEqual(result["attempts"], 2)
        self.assertIn("<correction>", recorder.prompts[1])
        self.assertIn("'GATE'", recorder.prompts[1])

    def test_the_correction_is_appended_after_the_cached_prefix(self):
        recorder = Recorder("nonsense", GOOD)
        decide(self.request, recorder)
        prompt, boundary = render_prompt(self.request)
        self.assertEqual(recorder.prompts[1][:boundary], prompt[:boundary])
        self.assertEqual(recorder.boundaries[1], [boundary])

    def test_each_correction_accumulates_so_the_model_sees_both_failures(self):
        recorder = Recorder("nonsense", '{"decisions": [{"item": null, "answers": {}}]}', GOOD)
        decide(self.request, recorder)
        self.assertIn("attempt 1:", recorder.prompts[2])
        self.assertIn("attempt 2:", recorder.prompts[2])

    def test_usage_sums_over_every_attempt(self):
        recorder = Recorder(FakeResult("nope", 100, 5), FakeResult(GOOD, 140, 30))
        result = decide(self.request, recorder)
        self.assertEqual((result["input_tokens"], result["output_tokens"]), (240, 35))

    def test_giving_up_raises_with_every_reason_and_the_answer_exit_code(self):
        recorder = Recorder("no", "still no", "nope")
        with self.assertRaises(DecideError) as caught:
            decide(self.request, recorder)
        self.assertEqual(caught.exception.exit_code, EXIT_BAD_ANSWER)
        self.assertIn(f"after {MAX_ATTEMPTS} attempts", str(caught.exception))
        self.assertEqual(len(recorder.prompts), MAX_ATTEMPTS)

    def test_attempts_is_honoured(self):
        recorder = Recorder("no", "no", GOOD)
        with self.assertRaises(DecideError):
            decide(self.request, recorder, max_attempts=2)
        self.assertEqual(len(recorder.prompts), 2)

    def test_an_empty_batch_makes_no_call_and_costs_nothing(self):
        recorder = Recorder(GOOD)
        result = decide(validate_request({**CHOICE_REQUEST, "items": []}), recorder)
        self.assertEqual(
            result,
            {
                "decisions": [],
                "input_tokens": 0,
                "output_tokens": 0,
                "attempts": 0,
                "corrections": [],
            },
        )
        self.assertEqual(recorder.prompts, [])

    def test_missing_usage_fields_do_not_break_accounting(self):
        class Bare:
            text = GOOD

        result = decide(self.request, lambda text, boundaries: Bare())
        self.assertEqual((result["input_tokens"], result["output_tokens"]), (0, 0))

    def test_a_whole_batch_is_answered_from_one_call(self):
        recorder = Recorder(
            '{"decisions": ['
            '{"item": "#176", "answers": {"lane": {"choice": "gate"}}},'
            '{"item": "#193", "answers": {"lane": {"choice": "staging"}}}]}'
        )
        result = decide(validate_request(batched()), recorder)
        self.assertEqual(len(recorder.prompts), 1)
        self.assertEqual([d["answers"]["lane"]["choice"] for d in result["decisions"]], ["gate", "staging"])


# --------------------------------------------------------------------------- #
# the executable: exit codes and JSON on stdout
# --------------------------------------------------------------------------- #


def run_cli(*args, stdin=""):
    return subprocess.run(
        [sys.executable, str(NAGENT_DECIDE), *args],
        input=stdin,
        capture_output=True,
        text=True,
    )


class CliTests(unittest.TestCase):
    def test_description_names_the_tool_path(self):
        result = run_cli("--description")
        self.assertEqual(result.returncode, 0)
        self.assertIn("nagent-decide", result.stdout)
        self.assertIn("closed set", result.stdout)

    def test_dry_run_renders_the_prompt_without_a_provider(self):
        result = run_cli("--dry-run", stdin=json.dumps(batched()))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("<questions>", result.stdout)
        self.assertIn("#176", result.stdout)

    def test_prompt_out_writes_the_generators_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "prompt.txt"
            result = run_cli("--dry-run", "--prompt-out", str(out), stdin=json.dumps(CHOICE_REQUEST))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(out.read_text(encoding="utf-8"), result.stdout)

    def test_input_file_and_stdin_render_the_same_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            request = Path(tmp) / "request.json"
            request.write_text(json.dumps(CHOICE_REQUEST), encoding="utf-8")
            from_file = run_cli("--dry-run", "--input", str(request))
            from_stdin = run_cli("--dry-run", stdin=json.dumps(CHOICE_REQUEST))
            self.assertEqual(from_file.stdout, from_stdin.stdout)

    def test_trailers_can_be_turned_off_through_the_executable(self):
        request = {**CHOICE_REQUEST, "rationale": False, "confidence": False}
        result = run_cli("--dry-run", stdin=json.dumps(request))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Do not include a "confidence" field', result.stdout)
        self.assertIn('Do not include a "why" field', result.stdout)

    def test_a_non_bool_confidence_exits_2_through_the_executable(self):
        result = run_cli("--dry-run", stdin=json.dumps({**CHOICE_REQUEST, "confidence": "no"}))
        self.assertEqual(result.returncode, EXIT_BAD_REQUEST)
        self.assertIn("confidence", result.stderr)

    def test_a_bad_request_exits_2_and_names_the_field(self):
        result = run_cli("--dry-run", stdin='{"questions": {"q": {"question": "?", "type": "choice"}}}')
        self.assertEqual(result.returncode, EXIT_BAD_REQUEST)
        self.assertIn("options", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_invalid_json_exits_2(self):
        result = run_cli("--dry-run", stdin="{nope")
        self.assertEqual(result.returncode, EXIT_BAD_REQUEST)

    def test_a_missing_input_file_exits_1(self):
        result = run_cli("--dry-run", "--input", "/nonexistent/request.json")
        self.assertEqual(result.returncode, 1)

    def test_zero_attempts_is_rejected(self):
        result = run_cli("--attempts", "0", stdin=json.dumps(CHOICE_REQUEST))
        self.assertEqual(result.returncode, EXIT_BAD_REQUEST)

    def test_an_empty_batch_prints_no_decisions_without_touching_a_provider(self):
        # No provider is configured in the test environment, so a call would fail:
        # reaching exit 0 is itself the proof that nothing was sent.
        result = run_cli(stdin=json.dumps({**CHOICE_REQUEST, "items": []}))
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["decisions"], [])
        self.assertEqual(payload["input_tokens"], 0)
        self.assertEqual(payload["attempts"], 0)


class ToolDiscoveryTests(unittest.TestCase):
    def test_the_loop_discovers_nagent_decide_by_running_it(self):
        sys.path.insert(0, str(BIN / "helpers"))
        from nagent_cli import collect_bin_tool_descriptions

        described = collect_bin_tool_descriptions(BIN)
        self.assertIn("nagent-decide", described)


if __name__ == "__main__":
    unittest.main()
