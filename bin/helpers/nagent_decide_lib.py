#!/usr/bin/python3
"""Constrained decisions: a JSON request in, a JSON answer set out.

BATCH TRANSFORM CONTRACT

  Input  (one JSON object, the request):
    context      optional  str | object | array | null   shared evidence, rendered
                                                         as labeled text
    constraints  optional  [str]                         rules every answer must respect
    questions    REQUIRED  {qid: question}               1..N questions, declared order
    items        optional  [str] | [{id, context}]       the batch; absent means one
                                                         context-only decision, []
                                                         means zero decisions
    rationale    optional  bool (default true)           collect a one-line reason
    confidence   optional  bool (default true)           collect a self-reported 0..1

  question:
    question     REQUIRED  str                           the question text
    type         REQUIRED  "choice" | "multi" | "score"
    options      REQUIRED  [str] | {name: description}    the closed answer set
    levels       score only, REQUIRED there               ordered scale, lowest first
    constraints  optional  [str]                          rules for this question only

  Output (one JSON object):
    decisions    [{item, answers}]                        always a list; one entry per
                                                          item, in request order
    answers      {qid: answer}                            every declared qid, always

  answer by type (layout is fixed; `confidence` and `why` are always present and
  are null when the request turned them off):
    choice  {type, choice, confidence, why}
    multi   {type, choices[], confidence, why}
    score   {type, scores{option: level}, level_index{option: int}, confidence, why}

  `rationale` and `confidence` are the two levers on output cost: each adds a field
  per answer, so turning both off asks for the bare decision. They are on by default
  because an unexplained decision is unauditable, and a caller that has measured its
  own case is the one who should trade that away.

  Ownership/lifetime: every value in the output is derived from this one request and
  one model reply. Nothing is cached, stored, or carried between calls.

  Valid ranges: option names in an answer are members of that question's declared
  option set, compared exactly. `level` names are members of `levels`. `level_index`
  is the 0-based position in `levels`. `confidence` is a number in [0.0, 1.0] — a
  model SELF-REPORT, not a calibrated or measured probability.

OUT-OF-RANGE BEHAVIOUR (explicit at every boundary)

  Malformed request .................. DecideError(exit 2), nothing is sent
  Reply is not a JSON object ......... correction retry, then DecideError(exit 3)
  Missing/extra item or question id .. correction retry, then DecideError(exit 3)
    (one exception: an unbatched request that gets back exactly one decision takes
     it whatever id it carries — with one decision asked for and one returned, the
     id cannot be ambiguous, and a retry there buys nothing)
  Answer outside the option set ...... correction retry, then DecideError(exit 3)
    (never coerced to the nearest option — a wrong answer that looks valid is the
     one failure this tool exists to prevent)
  Field the request turned off ....... null in the output, even if volunteered
  `confidence` absent or unparseable . null in the output, no retry
  `confidence` outside [0,1] ......... clamped into range, no retry (it is a
                                       self-report, and the declared range is the
                                       contract)
  `why` absent ....................... null in the output, no retry

NOT BUILT (deliberately, for want of an observed need)
  - a `rank` type: no decision in the sampled runbook ranks a set; ordering there is
    mechanical (`sort -n`) with a single "does this block throughput" override, which
    is a `choice`.
  - a `bool`/`noul` type: it is `choice` with two options.
  - min/max cardinality on `multi`: callers can count the returned list.
  - token probabilities: `generate_text_with_usage` returns text, so any distribution
    here would be model-written prose presented as a measurement.
  - abstention: the caller adds an explicit option ("insufficient-evidence") when the
    decision has one. That keeps the escape hatch in the data instead of in a flag.
"""

import json
import re

QUESTION_TYPES = ("choice", "multi", "score")
QUESTION_KEYS = frozenset({"question", "type", "options", "levels", "constraints"})
REQUEST_KEYS = frozenset({"context", "constraints", "questions", "items", "rationale", "confidence"})
ITEM_KEYS = frozenset({"id", "context"})

# Attempts, not retries: one call plus two corrections. Mirrors MAX_FORMAT_RETRIES
# in bin/nagent, which also budgets three visible tries before giving up.
MAX_ATTEMPTS = 3

EXIT_OK = 0
EXIT_PROVIDER = 1
EXIT_BAD_REQUEST = 2
EXIT_BAD_ANSWER = 3


class DecideError(Exception):
    """A rejected request or an unusable reply. `exit_code` is the process status."""

    def __init__(self, message: str, exit_code: int = EXIT_BAD_REQUEST) -> None:
        super().__init__(message)
        self.exit_code = exit_code


# --------------------------------------------------------------------------- #
# request -> validated request
# --------------------------------------------------------------------------- #


def normalize_labels(spec, what: str) -> list[tuple[str, str | None]]:
    """A closed answer set as [(name, description|None)] in declared order.

    Accepts a list of names or a {name: description} object; a null description
    means "the name speaks for itself". Anything else, an empty set, a duplicate
    name, or a non-string name is rejected."""
    if isinstance(spec, dict):
        pairs = list(spec.items())
    elif isinstance(spec, list):
        pairs = [(name, None) for name in spec]
    else:
        raise DecideError(f"{what}: must be a list of names or an object of name -> description")

    seen: set[str] = set()
    labels: list[tuple[str, str | None]] = []
    for name, description in pairs:
        if not isinstance(name, str) or not name.strip():
            raise DecideError(f"{what}: every name must be a non-empty string")
        name = name.strip()
        if name in seen:
            raise DecideError(f"{what}: duplicate name {name!r}")
        if description is not None and not isinstance(description, str):
            raise DecideError(f"{what}: description for {name!r} must be a string or null")
        text = description.strip() if isinstance(description, str) else ""
        seen.add(name)
        labels.append((name, text or None))
    if not labels:
        raise DecideError(f"{what}: must not be empty")
    return labels


def normalize_constraints(spec, what: str) -> list[str]:
    if spec is None:
        return []
    if not isinstance(spec, list):
        raise DecideError(f"{what}: must be a list of strings")
    out: list[str] = []
    for entry in spec:
        if not isinstance(entry, str) or not entry.strip():
            raise DecideError(f"{what}: every constraint must be a non-empty string")
        out.append(entry.strip())
    return out


def render_context(value, depth: int = 0) -> str:
    """Evidence as labeled text. A string passes through untouched; an object
    becomes `key: value` lines and an array becomes `- value` lines, so a caller
    can hand over whatever shape its data already has."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    pad = "  " * depth
    if isinstance(value, dict):
        lines = []
        for key, item in value.items():
            rendered = render_context(item, depth + 1)
            if "\n" in rendered:
                lines.append(f"{pad}{key}:\n{rendered}")
            else:
                lines.append(f"{pad}{key}: {rendered}")
        return "\n".join(lines)
    if isinstance(value, list):
        lines = []
        for item in value:
            rendered = render_context(item, depth + 1)
            lines.append(f"{pad}- {rendered.lstrip()}" if "\n" not in rendered else f"{pad}-\n{rendered}")
        return "\n".join(lines)
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def validate_question(qid: str, spec) -> dict:
    if not isinstance(spec, dict):
        raise DecideError(f"questions.{qid}: must be an object")
    unknown = sorted(set(spec) - QUESTION_KEYS)
    if unknown:
        raise DecideError(
            f"questions.{qid}: unknown key(s) {', '.join(unknown)}; "
            f"allowed: {', '.join(sorted(QUESTION_KEYS))}"
        )
    text = spec.get("question")
    if not isinstance(text, str) or not text.strip():
        raise DecideError(f"questions.{qid}: 'question' must be a non-empty string")
    qtype = spec.get("type")
    if qtype not in QUESTION_TYPES:
        raise DecideError(
            f"questions.{qid}: 'type' must be one of {', '.join(QUESTION_TYPES)} (got {qtype!r})"
        )
    if "options" not in spec:
        raise DecideError(f"questions.{qid}: 'options' is required — every answer comes from a closed set")
    options = normalize_labels(spec["options"], f"questions.{qid}.options")
    if qtype == "choice" and len(options) < 2:
        raise DecideError(
            f"questions.{qid}: a 'choice' needs at least 2 options; one option is not a decision"
        )

    levels: list[tuple[str, str | None]] = []
    if qtype == "score":
        if "levels" not in spec:
            raise DecideError(f"questions.{qid}: 'levels' is required for type 'score' (ordered, lowest first)")
        levels = normalize_labels(spec["levels"], f"questions.{qid}.levels")
        if len(levels) < 2:
            raise DecideError(f"questions.{qid}: 'levels' needs at least 2 levels to be a scale")
    elif "levels" in spec:
        raise DecideError(f"questions.{qid}: 'levels' applies only to type 'score'")

    return {
        "id": qid,
        "question": text.strip(),
        "type": qtype,
        "options": options,
        "levels": levels,
        "constraints": normalize_constraints(spec.get("constraints"), f"questions.{qid}.constraints"),
    }


def validate_items(spec) -> tuple[list[dict], bool]:
    """(items, batched). No `items` key is one context-only decision — a batch of
    one, with a null id. An empty list is a batch of zero: a legitimate request
    that answers nothing and costs nothing."""
    if spec is None:
        return [{"id": None, "context": ""}], False
    if not isinstance(spec, list):
        raise DecideError("items: must be a list of strings or of {id, context} objects")

    items: list[dict] = []
    seen: set[str] = set()
    for index, entry in enumerate(spec):
        if isinstance(entry, str):
            item_id, context = str(index + 1), entry
        elif isinstance(entry, dict):
            unknown = sorted(set(entry) - ITEM_KEYS)
            if unknown:
                raise DecideError(
                    f"items[{index}]: unknown key(s) {', '.join(unknown)}; allowed: id, context"
                )
            raw_id = entry.get("id")
            item_id = str(index + 1 if raw_id is None else raw_id).strip()
            context = entry.get("context")
        else:
            raise DecideError(f"items[{index}]: must be a string or an object of {{id, context}}")
        if not item_id:
            raise DecideError(f"items[{index}]: 'id' must not be empty")
        if item_id in seen:
            raise DecideError(f"items[{index}]: duplicate id {item_id!r}")
        seen.add(item_id)
        items.append({"id": item_id, "context": render_context(context)})
    return items, True


def validate_request(raw) -> dict:
    """The whole request, checked before a single token is sent. Every failure
    here is a caller bug, so it is reported by name and path and nothing is sent."""
    if not isinstance(raw, dict):
        raise DecideError("request: must be a JSON object")
    unknown = sorted(set(raw) - REQUEST_KEYS)
    if unknown:
        raise DecideError(
            f"request: unknown key(s) {', '.join(unknown)}; allowed: {', '.join(sorted(REQUEST_KEYS))}"
        )
    questions = raw.get("questions")
    if not isinstance(questions, dict) or not questions:
        raise DecideError("request: 'questions' must be a non-empty object of question-id -> question")
    for qid in questions:
        if not isinstance(qid, str) or not qid.strip():
            raise DecideError("questions: every question id must be a non-empty string")

    rationale = raw.get("rationale", True)
    if not isinstance(rationale, bool):
        raise DecideError("request: 'rationale' must be true or false")
    confidence = raw.get("confidence", True)
    if not isinstance(confidence, bool):
        raise DecideError("request: 'confidence' must be true or false")

    items, batched = validate_items(raw.get("items"))
    return {
        "context": render_context(raw.get("context")),
        "constraints": normalize_constraints(raw.get("constraints"), "constraints"),
        "questions": [validate_question(qid.strip(), questions[qid]) for qid in questions],
        "items": items,
        "batched": batched,
        "rationale": rationale,
        "confidence": confidence,
    }


def load_request_json(text: str) -> dict:
    """The request object from a file a model wrote.

    Tolerates a ```json fence and surrounding prose for the same reason
    parse_json_object does for replies: the file is model output, models fence
    JSON, and a fence carries no meaning that stripping it could lose. Anything
    that is not a JSON object is still rejected, with the request exit code."""
    try:
        return parse_json_object(text)
    except DecideError as exc:
        raise DecideError(f"request: {exc}".replace("request: reply:", "request:"), EXIT_BAD_REQUEST) from exc


def load_request(text: str) -> dict:
    return validate_request(load_request_json(text))


# --------------------------------------------------------------------------- #
# validated request -> prompt
# --------------------------------------------------------------------------- #

PREAMBLE = """\
You are a decision function. You are given evidence, constraints, and a fixed set of
questions. Every question has a closed set of allowed answers.

- Every option is listed in quotes. Answer with the quoted name only, copied exactly,
  character for character — never the description after it, never a name you invented,
  translated, abbreviated or combined.
- Decide from the evidence given. Do not assume facts that are not in it. When the
  evidence is thin, say so through the option you pick, not by answering something
  that was not asked.
"""

CONFIDENCE_RULE = (
    '- "confidence" is your own estimate, 0.0 to 1.0, that the answer is right given\n'
    "  this evidence.\n"
)
NO_CONFIDENCE_RULE = '- Do not include a "confidence" field.\n'
WHY_RULE = '- "why" is at most 25 words and names the evidence that decided it.\n'
NO_WHY_RULE = '- Do not include a "why" field.\n'

# The decided value per type, and the two optional trailers. Assembled rather than
# written out, so a shape cannot drift from the rules above it.
SHAPE_FIELDS = {
    "choice": '"choice": "<one quoted option name>"',
    "multi": '"choices": ["<quoted option name>", ...]',
    "score": '"scores": {"<quoted option name>": "<quoted level name>", ...}',
}


def shape_for(qtype: str, request: dict) -> str:
    fields = [SHAPE_FIELDS[qtype]]
    if request["confidence"]:
        fields.append('"confidence": 0.0')
    if request["rationale"]:
        fields.append('"why": "..."')
    return "{" + ", ".join(fields) + "}"


def _labels_block(labels: list[tuple[str, str | None]], bullet: str = "    - ") -> str:
    """Every name is quoted exactly as it must appear in the reply. An unquoted
    `name — description` line invites a model to answer with the whole line, which
    reads correct to a human and fails every string comparison a script makes."""
    lines = []
    for name, description in labels:
        lines.append(f'{bullet}"{name}"' + (f" — {description}" if description else ""))
    return "\n".join(lines)


def render_questions(request: dict) -> str:
    blocks = []
    for question in request["questions"]:
        lines = [f"[{question['id']}] type={question['type']}", f"  question: {question['question']}"]
        if question["type"] == "score":
            lines.append("  options (give every one a level):")
        elif question["type"] == "multi":
            lines.append("  options (pick one or more):")
        else:
            lines.append("  options (pick exactly one):")
        lines.append(_labels_block(question["options"]))
        if question["levels"]:
            lines.append("  levels (ordered, lowest first):")
            lines.append(
                "\n".join(
                    f'    {index + 1}. "{name}"' + (f" — {description}" if description else "")
                    for index, (name, description) in enumerate(question["levels"])
                )
            )
        if question["constraints"]:
            lines.append("  constraints:")
            lines.append("\n".join(f"    - {entry}" for entry in question["constraints"]))
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def render_contract(request: dict) -> str:
    qids = [question["id"] for question in request["questions"]]
    types = sorted({question["type"] for question in request["questions"]})
    lines = [
        "Reply with one JSON object and nothing else — no prose, no code fence.",
        '{"decisions": [{"item": <item id>, "answers": {"<question id>": <answer>}}]}',
        "",
        "Answer shape by question type:",
    ]
    for qtype in types:
        lines.append(f"  {qtype}: {shape_for(qtype, request)}")
    lines.append("")
    lines.append(f"Every 'answers' object carries exactly these question ids: {', '.join(qids)}")
    if request["batched"]:
        ids = ", ".join(item["id"] for item in request["items"])
        lines.append(f"'decisions' carries exactly one entry per item id, in this order: {ids}")
    else:
        lines.append("'decisions' carries exactly one entry, with \"item\": null.")
    return "\n".join(lines)


def render_prompt(request: dict) -> tuple[str, int]:
    """(prompt text, cache boundary offset).

    Order is stable-first: the instructions, constraints, evidence and question
    definitions change between cycles rarely; the items change every time. The
    boundary sits at the end of the last stable section, so a provider that caches
    on prefixes reuses everything above it across a run."""
    rules = PREAMBLE
    rules += CONFIDENCE_RULE if request["confidence"] else NO_CONFIDENCE_RULE
    rules += WHY_RULE if request["rationale"] else NO_WHY_RULE
    sections = [rules.strip()]
    if request["constraints"]:
        sections.append(
            "<constraints>\n"
            + "\n".join(f"- {entry}" for entry in request["constraints"])
            + "\n</constraints>"
        )
    if request["context"]:
        sections.append(f"<evidence>\n{request['context']}\n</evidence>")
    sections.append(f"<questions>\n{render_questions(request)}\n</questions>")

    stable = "\n\n".join(sections)
    boundary = len(stable)

    tail = []
    if request["batched"]:
        blocks = [
            "Answer every question once per item, from that item's own evidence plus the "
            "shared evidence above."
        ]
        for item in request["items"]:
            blocks.append(f"[{item['id']}]\n{item['context']}" if item["context"] else f"[{item['id']}]")
        tail.append("<items>\n" + "\n\n".join(blocks) + "\n</items>")
    tail.append(render_contract(request))
    return stable + "\n\n" + "\n\n".join(tail) + "\n", boundary


def render_corrections(corrections: list[str]) -> str:
    lines = [
        "<correction>",
        "Your previous reply was rejected. Fix it and reply again with the JSON object only.",
    ]
    for index, reason in enumerate(corrections, start=1):
        lines.append(f"  attempt {index}: {reason}")
    lines.append("</correction>")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# reply -> validated decisions
# --------------------------------------------------------------------------- #

FENCE_RE = re.compile(r"```(?:json)?\s*(.+?)```", re.DOTALL)


def parse_json_object(text: str) -> dict:
    """The JSON object in a model reply. A bare object is the common case; a fenced
    block and an object wrapped in prose are both accepted because they are what
    models actually emit. Anything else is rejected rather than guessed at."""
    if not isinstance(text, str) or not text.strip():
        raise DecideError("reply: empty", EXIT_BAD_ANSWER)
    candidates = [text.strip()]
    fenced = FENCE_RE.search(text)
    if fenced:
        candidates.append(fenced.group(1).strip())
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        candidates.append(text[start : end + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
        raise DecideError("reply: top-level JSON value is not an object", EXIT_BAD_ANSWER)
    raise DecideError("reply: no JSON object found", EXIT_BAD_ANSWER)


def read_confidence(raw):
    """A self-report, clamped into [0,1]. Absent or unparseable is null, not a
    failure — the decision itself is the deliverable, the confidence is a hint."""
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    return round(min(1.0, max(0.0, float(raw))), 4)


def read_why(raw):
    return raw.strip() if isinstance(raw, str) and raw.strip() else None


def validate_answer(request: dict, question: dict, raw, where: str) -> dict:
    if not isinstance(raw, dict):
        raise DecideError(f"{where}: answer must be an object", EXIT_BAD_ANSWER)
    names = [name for name, _ in question["options"]]
    # Fixed layout: both trailer keys are always present, so every consumer has one
    # path. A field the request turned off is null even if the model volunteered it --
    # the request said not to collect it, and honouring that is the contract.
    answer = {
        "type": question["type"],
        "confidence": read_confidence(raw.get("confidence")) if request["confidence"] else None,
        "why": read_why(raw.get("why")) if request["rationale"] else None,
    }

    if question["type"] == "choice":
        choice = raw.get("choice")
        if choice not in names:
            raise DecideError(
                f"{where}: 'choice' must be one of [{', '.join(names)}] (got {choice!r})",
                EXIT_BAD_ANSWER,
            )
        answer["choice"] = choice
        return answer

    if question["type"] == "multi":
        choices = raw.get("choices")
        if not isinstance(choices, list) or not choices:
            raise DecideError(f"{where}: 'choices' must be a non-empty list", EXIT_BAD_ANSWER)
        seen: list[str] = []
        for choice in choices:
            if choice not in names:
                raise DecideError(
                    f"{where}: 'choices' entry must be one of [{', '.join(names)}] (got {choice!r})",
                    EXIT_BAD_ANSWER,
                )
            if choice not in seen:
                seen.append(choice)
        answer["choices"] = seen
        return answer

    scores = raw.get("scores")
    if not isinstance(scores, dict):
        raise DecideError(f"{where}: 'scores' must be an object of option -> level", EXIT_BAD_ANSWER)
    level_names = [name for name, _ in question["levels"]]
    missing = [name for name in names if name not in scores]
    if missing:
        raise DecideError(f"{where}: 'scores' is missing option(s): {', '.join(missing)}", EXIT_BAD_ANSWER)
    extra = [str(name) for name in scores if name not in names]
    if extra:
        raise DecideError(f"{where}: 'scores' has unknown option(s): {', '.join(extra)}", EXIT_BAD_ANSWER)
    for name in names:
        if scores[name] not in level_names:
            raise DecideError(
                f"{where}: score for {name!r} must be one of [{', '.join(level_names)}] "
                f"(got {scores[name]!r})",
                EXIT_BAD_ANSWER,
            )
    answer["scores"] = {name: scores[name] for name in names}
    answer["level_index"] = {name: level_names.index(scores[name]) for name in names}
    return answer


def validate_answers(request: dict, reply: dict) -> list[dict]:
    """Every answer checked against its own closed set, and the item/question grid
    checked for exact coverage. A partial grid is a rejected reply, not a partial
    result: a caller that scripts on a missing key would read it as a decision."""
    decisions = reply.get("decisions")
    if not isinstance(decisions, list):
        raise DecideError("reply: 'decisions' must be a list", EXIT_BAD_ANSWER)

    expected = [item["id"] for item in request["items"]]
    if not request["batched"] and len(decisions) == 1 and isinstance(decisions[0], dict):
        decisions = [{**decisions[0], "item": None}]

    by_id: dict[str | None, dict] = {}
    for index, entry in enumerate(decisions):
        if not isinstance(entry, dict):
            raise DecideError(f"reply: decisions[{index}] must be an object", EXIT_BAD_ANSWER)
        raw_id = entry.get("item")
        item_id = None if raw_id is None else str(raw_id).strip()
        if item_id in by_id:
            raise DecideError(f"reply: two decisions for item {item_id!r}", EXIT_BAD_ANSWER)
        by_id[item_id] = entry

    unknown = [str(key) for key in by_id if key not in expected]
    if unknown:
        raise DecideError(f"reply: unknown item id(s): {', '.join(unknown)}", EXIT_BAD_ANSWER)
    absent = [str(key) for key in expected if key not in by_id]
    if absent:
        raise DecideError(f"reply: no decision for item(s): {', '.join(absent)}", EXIT_BAD_ANSWER)

    qids = [question["id"] for question in request["questions"]]
    out = []
    for item in request["items"]:
        entry = by_id[item["id"]]
        label = f"item {item['id']}" if item["id"] is not None else "decision"
        answers = entry.get("answers")
        if not isinstance(answers, dict):
            raise DecideError(f"reply: {label}: 'answers' must be an object", EXIT_BAD_ANSWER)
        stray = [str(key) for key in answers if key not in qids]
        if stray:
            raise DecideError(f"reply: {label}: unknown question id(s): {', '.join(stray)}", EXIT_BAD_ANSWER)
        gone = [qid for qid in qids if qid not in answers]
        if gone:
            raise DecideError(f"reply: {label}: no answer for question(s): {', '.join(gone)}", EXIT_BAD_ANSWER)
        out.append(
            {
                "item": item["id"],
                "answers": {
                    question["id"]: validate_answer(
                        request, question, answers[question["id"]], f"{label}: {question['id']}"
                    )
                    for question in request["questions"]
                },
            }
        )
    return out


# --------------------------------------------------------------------------- #
# the whole transform
# --------------------------------------------------------------------------- #


def decide(request: dict, generate, max_attempts: int = MAX_ATTEMPTS) -> dict:
    """Run one validated request to a checked answer set.

    `generate(prompt_text, cache_boundaries)` returns an object with `.text`,
    `.input_tokens` and `.output_tokens` — the same shape `generate_text_with_usage`
    returns, which is the only caller in production and the seam tests drive.

    A batch of zero items answers nothing and makes no call: usage is zero and
    `attempts` is 0. That is the common case in a poller that found no work, and it
    is the cheapest correct answer there is."""
    if not request["items"]:
        return {
            "decisions": [],
            "input_tokens": 0,
            "output_tokens": 0,
            "attempts": 0,
            "corrections": [],
        }

    prompt, boundary = render_prompt(request)
    corrections: list[str] = []
    input_tokens = 0
    output_tokens = 0

    for attempt in range(1, max_attempts + 1):
        text = prompt if not corrections else f"{prompt}\n{render_corrections(corrections)}\n"
        result = generate(text, [boundary])
        input_tokens += int(getattr(result, "input_tokens", 0) or 0)
        output_tokens += int(getattr(result, "output_tokens", 0) or 0)
        try:
            decisions = validate_answers(request, parse_json_object(result.text))
        except DecideError as exc:
            corrections.append(str(exc))
            continue
        return {
            "decisions": decisions,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "attempts": attempt,
            "corrections": corrections,
        }

    raise DecideError(
        f"reply: unusable after {max_attempts} attempts: " + "; ".join(corrections),
        EXIT_BAD_ANSWER,
    )
