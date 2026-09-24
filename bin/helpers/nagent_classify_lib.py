#!/usr/bin/python3
"""Constrained classification: an input set and a category set in, a category per
input out.

RELATIONSHIP TO nagent-decide

A classification is one decision shape: N inputs against ONE closed category set,
asked on one stated dimension. So this does not reimplement any of it. A validated
classify request is translated into a validated `nagent-decide` request carrying a
single `choice` (or `multi`) question, and the decide library's prompt renderer,
answer validator and correction loop run unchanged. The enforcement guarantee is
therefore identical: a category outside the declared set is rejected and retried,
never coerced to the nearest one.

What this adds is the data shape, which is the reason it is a separate tool rather
than a documented way to call the other one:

  - the request declares the category set ONCE, not per question
  - the output is a flat row per input, not a question grid to walk
  - the output also carries the INVERSE index (`buckets`), because bucketing the
    inputs is what a caller does next, and every declared category is a key even
    when nothing landed in it — an empty bucket is a result, not a gap

BATCH TRANSFORM CONTRACT

  Input (one JSON object):
    question     REQUIRED  str                          the dimension being classified
                                                        on; required because a set like
                                                        {high, medium, low} does not
                                                        state "high WHAT", and a wrong
                                                        dimension fails silently
    categories   REQUIRED  [str] | {name: description}   the closed set, >= 2 members
    inputs       REQUIRED  [str] | [{id, text}]          what to classify; [] is a
                                                        legal batch of zero
    context      optional  str | object | array          shared evidence, sent once
    constraints  optional  [str]                         rules every answer respects
    multi_label  optional  bool (default false)          true allows several categories
                                                        per input
    rationale    optional  bool (default true)           collect a one-line reason
    confidence   optional  bool (default true)           collect a self-reported 0..1

  Output (one JSON object):
    classified   [{input, category, categories[], confidence, why}]
                 one row per input, in request order. Layout is fixed: `category`
                 is the single assignment and is null in multi_label mode;
                 `categories` is always the full assigned list (length 1 in
                 single-label mode). `confidence` and `why` are null when the
                 request turned them off.
    buckets      {category: [input id, ...]}
                 the inverse index. Every declared category is present; a category
                 nothing was assigned to maps to an empty list. Ids appear in
                 request order.

  Ownership/lifetime: every value is derived from this one request and one model
  reply. Nothing is cached or carried between calls.

OUT-OF-RANGE BEHAVIOUR (explicit at every boundary)

  Malformed request .................. ClassifyError(exit 2), nothing is sent
  Fewer than 2 categories ............ exit 2 (a one-category set classifies nothing)
  Category outside the set ........... correction retry, then exit 3, never coerced
  Missing/extra/duplicate input id ... correction retry, then exit 3
  Empty `inputs` ..................... no call, empty `classified`, all buckets empty
  Field the request turned off ....... null in the output, even if volunteered

NOT BUILT (deliberately, for want of an observed need)
  - a confidence threshold that routes low-confidence inputs elsewhere: `confidence`
    is an uncalibrated self-report (see issues/0003) and nothing should branch on it
    until that is measured. The caller has the number and can decide.
  - min/max labels per input in multi_label mode: callers can count the list.
  - a reserved "unknown"/"other" category: the caller adds one as an explicit member
    when the classification has one, which keeps the escape hatch in the data.
  - hierarchical or nested categories: no observed need, and a two-level scheme is
    two calls whose second one's category set depends on the first's answer.
"""

import json

from nagent_decide_lib import (  # noqa: F401  (EXIT_* re-exported for the CLI)
    EXIT_BAD_ANSWER,
    EXIT_BAD_REQUEST,
    EXIT_OK,
    EXIT_PROVIDER,
    MAX_ATTEMPTS,
    DecideError,
    decide,
    load_request_json,
    normalize_constraints,
    normalize_labels,
    render_context,
    render_prompt,
)
from nagent_decide_lib import validate_request as validate_decide_request

CLASSIFY_KEYS = frozenset(
    {
        "context",
        "constraints",
        "question",
        "categories",
        "inputs",
        "multi_label",
        "rationale",
        "confidence",
    }
)
INPUT_KEYS = frozenset({"id", "text"})

# The single question the translated decide request carries. Internal: it appears in
# the rendered prompt but never in this tool's input or output.
CATEGORY_QID = "category"


class ClassifyError(DecideError):
    """A rejected request. Subclasses DecideError so one handler in the CLI covers
    both this tool's own rejections and the ones the shared decide path raises."""


def validate_inputs(spec) -> list[dict]:
    """The input set as [{id, text}] in declared order.

    A bare string is the text and takes its 1-based position as its id. An empty
    list is a legal batch of zero, which is how "nothing arrived this cycle"
    classifies to nothing without a call."""
    if spec is None:
        raise ClassifyError("request: 'inputs' is required (use [] to classify nothing)")
    if not isinstance(spec, list):
        raise ClassifyError("inputs: must be a list of strings or of {id, text} objects")

    rows: list[dict] = []
    seen: set[str] = set()
    for index, entry in enumerate(spec):
        if isinstance(entry, str):
            input_id, text = str(index + 1), entry
        elif isinstance(entry, dict):
            unknown = sorted(set(entry) - INPUT_KEYS)
            if unknown:
                raise ClassifyError(
                    f"inputs[{index}]: unknown key(s) {', '.join(unknown)}; allowed: id, text"
                )
            raw_id = entry.get("id")
            input_id = str(index + 1 if raw_id is None else raw_id).strip()
            text = entry.get("text")
        else:
            raise ClassifyError(f"inputs[{index}]: must be a string or an object of {{id, text}}")
        if not input_id:
            raise ClassifyError(f"inputs[{index}]: 'id' must not be empty")
        if input_id in seen:
            raise ClassifyError(f"inputs[{index}]: duplicate id {input_id!r}")
        rendered = render_context(text)
        if not rendered:
            raise ClassifyError(f"inputs[{index}] ({input_id}): 'text' must not be empty")
        seen.add(input_id)
        rows.append({"id": input_id, "text": rendered})
    return rows


def validate_request(raw) -> dict:
    """The whole request, checked before a token is sent. Every failure here is a
    caller bug, reported by field and path with nothing sent."""
    if not isinstance(raw, dict):
        raise ClassifyError("request: must be a JSON object")
    unknown = sorted(set(raw) - CLASSIFY_KEYS)
    if unknown:
        raise ClassifyError(
            f"request: unknown key(s) {', '.join(unknown)}; allowed: {', '.join(sorted(CLASSIFY_KEYS))}"
        )

    question = raw.get("question")
    if not isinstance(question, str) or not question.strip():
        raise ClassifyError(
            "request: 'question' must be a non-empty string naming the dimension being "
            "classified on (a set like {high, medium, low} does not say high WHAT)"
        )

    if "categories" not in raw:
        raise ClassifyError("request: 'categories' is required — the closed set every answer comes from")
    try:
        categories = normalize_labels(raw["categories"], "categories")
    except DecideError as exc:
        raise ClassifyError(str(exc)) from exc
    if len(categories) < 2:
        raise ClassifyError("categories: need at least 2 members; a one-category set classifies nothing")

    for field in ("multi_label", "rationale", "confidence"):
        if field in raw and not isinstance(raw[field], bool):
            raise ClassifyError(f"request: '{field}' must be true or false")

    try:
        constraints = normalize_constraints(raw.get("constraints"), "constraints")
    except DecideError as exc:
        raise ClassifyError(str(exc)) from exc

    return {
        "question": question.strip(),
        "categories": categories,
        "inputs": validate_inputs(raw.get("inputs")),
        "context": render_context(raw.get("context")),
        "constraints": constraints,
        "multi_label": bool(raw.get("multi_label", False)),
        "rationale": bool(raw.get("rationale", True)),
        "confidence": bool(raw.get("confidence", True)),
    }


def load_request(text: str) -> dict:
    try:
        raw = load_request_json(text)
    except DecideError as exc:
        raise ClassifyError(str(exc), exc.exit_code) from exc
    return validate_request(raw)


# --------------------------------------------------------------------------- #
# classify request -> decide request
# --------------------------------------------------------------------------- #


def as_decide_request(request: dict) -> dict:
    """The equivalent nagent-decide request, validated by the decide library.

    Re-validating through that validator is deliberate: it is the contract
    enforcement point, so a translation bug here cannot produce a request the
    decide path would have refused. Nothing in this function can fail validation
    given a request that passed `validate_request`, so a DecideError escaping it is
    an internal defect rather than caller error."""
    return validate_decide_request(
        {
            "context": request["context"] or None,
            "constraints": request["constraints"] or None,
            "questions": {
                CATEGORY_QID: {
                    "question": request["question"],
                    "type": "multi" if request["multi_label"] else "choice",
                    "options": {name: description for name, description in request["categories"]},
                }
            },
            "items": [{"id": row["id"], "context": row["text"]} for row in request["inputs"]],
            "rationale": request["rationale"],
            "confidence": request["confidence"],
        }
    )


def render_classify_prompt(request: dict) -> tuple[str, int]:
    """(prompt text, cache boundary offset) for the translated request."""
    return render_prompt(as_decide_request(request))


# --------------------------------------------------------------------------- #
# decide answers -> classify output
# --------------------------------------------------------------------------- #


def assigned_categories(answer: dict) -> list[str]:
    """The categories in one validated answer, whichever shape it came back in.
    Membership was already enforced by the decide validator."""
    if "choices" in answer:
        return list(answer["choices"])
    return [answer["choice"]]


def reshape(request: dict, decisions: list[dict]) -> tuple[list[dict], dict]:
    """(classified rows, buckets).

    Both views are built in one pass over the decisions, in request order, so the
    rows and the inverse index cannot disagree. Every declared category is a bucket
    key whether or not anything landed in it."""
    rows: list[dict] = []
    buckets: dict[str, list[str]] = {name: [] for name, _ in request["categories"]}

    for entry in decisions:
        answer = entry["answers"][CATEGORY_QID]
        categories = assigned_categories(answer)
        rows.append(
            {
                "input": entry["item"],
                # Fixed layout: single-label callers read `category`, multi-label
                # callers read `categories`, and both keys are always present.
                "category": None if request["multi_label"] else categories[0],
                "categories": categories,
                "confidence": answer["confidence"],
                "why": answer["why"],
            }
        )
        for name in categories:
            buckets[name].append(entry["item"])

    return rows, buckets


def classify(request: dict, generate, max_attempts: int = MAX_ATTEMPTS) -> dict:
    """Run one validated request to a checked classification.

    `generate(prompt_text, cache_boundaries)` has the same shape
    `generate_text_with_usage` returns, which is the seam tests drive.

    An empty input set classifies nothing and makes no call: usage is zero,
    `attempts` is 0, and every bucket is present and empty. That is the cheapest
    correct answer for a cycle that found nothing to classify."""
    if not request["inputs"]:
        return {
            "classified": [],
            "buckets": {name: [] for name, _ in request["categories"]},
            "input_tokens": 0,
            "output_tokens": 0,
            "attempts": 0,
            "corrections": [],
        }

    result = decide(as_decide_request(request), generate, max_attempts=max_attempts)
    rows, buckets = reshape(request, result["decisions"])
    return {
        "classified": rows,
        "buckets": buckets,
        "input_tokens": result["input_tokens"],
        "output_tokens": result["output_tokens"],
        "attempts": result["attempts"],
        "corrections": result["corrections"],
    }
