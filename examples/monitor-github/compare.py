#!/usr/bin/python3
"""Measure nagent-decide against the nagent loop on the same decisions.

Both sides get byte-identical information: the nagent side is handed the exact
prompt nagent-decide renders (`--dry-run`), so the only difference between them
is the machinery, not the evidence. Tokens are the provider's own counts on both
sides -- nagent-decide prints them, and nagent records them in its
<nagent-turn-status> line.

  compare.py --provider anthropic --model claude-sonnet-5
  compare.py --decide-only --model claude-haiku-4-5-20251001

Nothing here is estimated. A number that could not be read from a provider
response is reported as null.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
BIN = HERE.parent.parent / "bin"
REQUESTS = ("triage.json", "batch.json", "clarify.json")
TURN_RE = re.compile(r'tokens_in_total="(\d+)"\s+tokens_out_total="(\d+)"')

NAGENT_TASK = """\
Answer the decision request below. Do not read any files, run any commands, or use
any tool: everything you need is in this message. Reply with the JSON object the
request asks for, as your <nagent-response>, and nothing else.

"""

# The controlled comparison hands nagent the same excerpted evidence nagent-decide
# renders, which measures the loop's FLOOR: an empty conversation, one turn, no
# runbook. --runbook measures what a real cycle actually pays, by putting the whole
# standing runbook in front of the same decision, which is where that cycle's rules
# live. One flag, two honest numbers; neither is estimated.
RUNBOOK_TASK = """\
You are running one cycle of the standing task below. Apply it to the decision
request that follows. Do not read any files, run any commands, or use any tool.
Reply with the JSON object the request asks for, as your <nagent-response>, and
nothing else.

<runbook>
{runbook}
</runbook>

"""


def answer_value(answer):
    """The decided value, whatever the question type."""
    for key in ("choice", "choices", "scores"):
        if key in answer:
            return answer[key]
    return None


DESCRIPTION_SUFFIX = re.compile(r"\s+[—-]\s+.*$", re.DOTALL)


def loosen(value):
    """The same value with any trailing " — description" stripped off each name.

    An unconstrained model routinely answers with the whole listing line ("gate —
    the lane about to gate; owns the display..."). That is the right DECISION in an
    unusable FORM: every string comparison a script makes against it fails. Scoring
    loosely as well as strictly separates the two, so the comparison reports whether
    the machinery was right and whether its output could be used, rather than
    conflating them."""
    if isinstance(value, str):
        return DESCRIPTION_SUFFIX.sub("", value).strip().strip('"')
    if isinstance(value, list):
        return [loosen(entry) for entry in value]
    if isinstance(value, dict):
        return {loosen(key): loosen(entry) for key, entry in value.items()}
    return value


def flatten(decisions):
    """decisions -> {item_id: {qid: value}} for scoring."""
    return {
        entry["item"]: {qid: answer_value(answer) for qid, answer in entry["answers"].items()}
        for entry in decisions
    }


def matches(got, want):
    """One expectation against one answer. A list expectation is a set of allowed
    values, unless the answer is itself a list, in which case it is the answer. A
    dict expectation (a score answer) is checked per option, so one option can allow
    a range of levels while another is pinned."""
    if isinstance(want, dict):
        if not isinstance(got, dict) or set(got) != set(want):
            return False
        return all(matches(got[key], want[key]) for key in want)
    if isinstance(want, list) and not isinstance(got, list):
        return got in want
    return got == want


def score(actual, expected, loose=False):
    """(checks, hits, misses). A `_`-prefixed expectation key is a note. A
    `<qid>_includes` key requires membership rather than equality, for the multi
    questions where the runbook names a test that must fire without ruling out
    others."""
    checks = hits = 0
    misses = []
    for item_id, wanted in expected.items():
        if item_id.startswith("_"):
            continue
        got_item = actual.get(item_id, {})
        for key, want in wanted.items():
            if key.endswith("_includes"):
                qid = key[: -len("_includes")]
                got = got_item.get(qid)
                if loose:
                    got, want = loosen(got), loosen(want)
                checks += 1
                if isinstance(got, list) and all(entry in got for entry in want):
                    hits += 1
                else:
                    misses.append(f"{item_id}.{qid}: wanted to include {want}, got {got}")
                continue
            got = got_item.get(key)
            if loose:
                got, want = loosen(got), loosen(want)
            checks += 1
            if matches(got, want):
                hits += 1
            else:
                misses.append(f"{item_id}.{key}: wanted {want}, got {got}")
    return checks, hits, misses


def bare_variant(request_path, out_dir):
    """The same request with both output trailers off, so the cost of `rationale`
    and `confidence` can be measured instead of guessed at."""
    request = json.loads(request_path.read_text(encoding="utf-8"))
    request["rationale"] = False
    request["confidence"] = False
    path = out_dir / f"{request_path.stem}.bare.json"
    path.write_text(json.dumps(request, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def run_decide(request_path, provider, model, out_dir, bare=False):
    if bare:
        request_path = bare_variant(request_path, out_dir)
    started = time.monotonic()
    result = subprocess.run(
        [
            str(BIN / "nagent-decide"),
            "--input",
            str(request_path),
            "--provider",
            provider,
            "--model",
            model,
            "--prompt-out",
            str(out_dir / f"{request_path.stem}.prompt.txt"),
        ],
        capture_output=True,
        text=True,
    )
    elapsed = time.monotonic() - started
    if result.returncode != 0:
        return {"ok": False, "error": result.stderr.strip(), "exit": result.returncode, "seconds": elapsed}
    payload = json.loads(result.stdout)
    (out_dir / f"{request_path.stem}.decide.json").write_text(result.stdout, encoding="utf-8")
    return {
        "ok": True,
        "seconds": elapsed,
        "input_tokens": payload["input_tokens"],
        "output_tokens": payload["output_tokens"],
        "attempts": payload["attempts"],
        "answers": flatten(payload["decisions"]),
    }


def run_nagent(request_path, provider, model, out_dir, root, runbook=None):
    """The same prompt through the whole loop, in a throwaway root so it cannot
    touch a real conversation. With `runbook`, the standing document is carried in
    front of it, which is the real cycle's input rather than a distilled excerpt."""
    prompt_path = out_dir / f"{request_path.stem}.prompt.txt"
    if not prompt_path.is_file():
        rendered = subprocess.run(
            [str(BIN / "nagent-decide"), "--input", str(request_path), "--dry-run"],
            capture_output=True,
            text=True,
            check=True,
        )
        prompt_path.write_text(rendered.stdout, encoding="utf-8")

    task = NAGENT_TASK if runbook is None else RUNBOOK_TASK.format(runbook=runbook)
    conversation = f"compare-{request_path.stem}" + ("-runbook" if runbook else "")
    env = dict(os.environ, NAGENT_DECIDE_COMPARE="1")
    started = time.monotonic()
    result = subprocess.run(
        [
            str(BIN / "nagent"),
            "--root",
            str(root),
            "--conversation",
            conversation,
            "--provider",
            provider,
            "--model",
            model,
            "-",
        ],
        input=task + prompt_path.read_text(encoding="utf-8"),
        capture_output=True,
        text=True,
        env=env,
    )
    elapsed = time.monotonic() - started
    (out_dir / f"{request_path.stem}.nagent{'-runbook' if runbook else ''}.txt").write_text(
        result.stdout + "\n--- stderr ---\n" + result.stderr, encoding="utf-8"
    )

    conversation_file = root / "conversations" / conversation
    tokens_in = tokens_out = None
    if conversation_file.is_file():
        matches = TURN_RE.findall(conversation_file.read_text(encoding="utf-8", errors="replace"))
        if matches:
            tokens_in, tokens_out = int(matches[-1][0]), int(matches[-1][1])

    answers = {}
    parsed = None
    try:
        from nagent_decide_lib import parse_json_object

        parsed = parse_json_object(result.stdout)
    except Exception:
        parsed = None
    if isinstance(parsed, dict) and isinstance(parsed.get("decisions"), list):
        for entry in parsed["decisions"]:
            if isinstance(entry, dict) and isinstance(entry.get("answers"), dict):
                item_id = entry.get("item")
                answers[None if item_id is None else str(item_id)] = {
                    qid: answer_value(answer) if isinstance(answer, dict) else answer
                    for qid, answer in entry["answers"].items()
                }

    return {
        "ok": result.returncode == 0 and bool(answers),
        "exit": result.returncode,
        "seconds": elapsed,
        "input_tokens": tokens_in,
        "output_tokens": tokens_out,
        "parsed": bool(answers),
        "answers": answers,
    }


def scores(run, wanted):
    """(checks, strict hits, loose hits, strict misses)."""
    answers = run.get("answers", {})
    checks, hits, misses = score(answers, wanted)
    _, loose_hits, _ = score(answers, wanted, loose=True)
    return checks, hits, loose_hits, misses


def print_row(label, run, checks, hits, loose_hits, misses):
    if not run.get("ok"):
        detail = run.get("error") or f"exit {run.get('exit')}"
        if run.get("parsed") is False:
            detail = "reply was not a parseable decision object"
        print(f"  {label:<14} FAILED  {detail}")
        return
    tokens_in = run.get("input_tokens")
    tokens_out = run.get("output_tokens")
    total = None if tokens_in is None or tokens_out is None else tokens_in + tokens_out
    usable = "" if hits == loose_hits else f" (decision right {loose_hits}/{checks}, form unusable)"
    print(
        f"  {label:<14} {hits}/{checks} usable{usable}   "
        f"in={tokens_in if tokens_in is not None else '?'} "
        f"out={tokens_out if tokens_out is not None else '?'} "
        f"total={total if total is not None else '?'}   "
        f"{run['seconds']:.1f}s"
        + (f"   attempts={run['attempts']}" if "attempts" in run else "")
    )
    for miss in misses:
        print(f"                 x {miss}")


LABELS = {"decide": "nagent-decide", "nagent": "nagent", "nagent_runbook": "nagent+runbook"}


def rescore(out_dir, expected) -> int:
    path = out_dir / "summary.json"
    summary = json.loads(path.read_text(encoding="utf-8"))
    totals = {key: [0, 0, 0, 0, 0] for key in LABELS}
    for name, entry in summary["requests"].items():
        print(f"\n{name}")
        for key, label in LABELS.items():
            run = entry.get(key)
            if run is None:
                continue
            checks, hits, loose_hits, misses = scores(run, expected[name])
            print_row(label, run, checks, hits, loose_hits, misses)
            run.update({"checks": checks, "hits": hits, "loose_hits": loose_hits, "misses": misses})
            if run.get("ok") and run.get("input_tokens") is not None:
                totals[key] = [
                    totals[key][0] + run["input_tokens"],
                    totals[key][1] + run["output_tokens"],
                    totals[key][2] + checks,
                    totals[key][3] + hits,
                    totals[key][4] + loose_hits,
                ]
    print("\n--- totals (provider-reported tokens) ---")
    for key, (tin, tout, checks, hits, loose) in totals.items():
        if checks:
            print(
                f"  {LABELS[key]:<14} in={tin} out={tout} total={tin + tout}   "
                f"{hits}/{checks} usable, {loose}/{checks} decided right"
            )
    summary["totals"] = {
        key: {
            "input_tokens": tin,
            "output_tokens": tout,
            "checks": checks,
            "hits": hits,
            "loose_hits": loose,
        }
        for key, (tin, tout, checks, hits, loose) in totals.items()
        if checks
    }
    path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nrescored {path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--provider", default="anthropic")
    parser.add_argument("--model", default="claude-sonnet-5")
    parser.add_argument("--out", default=None, help="Directory for prompts, replies and the summary.")
    parser.add_argument(
        "--rescore",
        action="store_true",
        help="Re-score the saved summary.json in --out against expected.json; make no calls.",
    )
    parser.add_argument("--decide-only", action="store_true", help="Skip the nagent side.")
    parser.add_argument(
        "--bare",
        action="store_true",
        help='Run the decide side with "rationale" and "confidence" off, to measure what they cost.',
    )
    parser.add_argument("--nagent-only", action="store_true", help="Skip the nagent-decide side.")
    parser.add_argument(
        "--runbook",
        help=(
            "Path to the standing runbook. Adds a third row per request: the same decision "
            "through nagent with the whole runbook in front of it, which is what a real "
            "cycle pays."
        ),
    )
    parser.add_argument(
        "--runbook-requests",
        default="triage.json",
        help="Comma-separated requests to run the runbook row for (default: triage.json).",
    )
    args = parser.parse_args()

    sys.path.insert(0, str(BIN / "helpers"))
    out_dir = Path(args.out).expanduser() if args.out else HERE / f"runs/{args.provider}-{args.model}"
    out_dir.mkdir(parents=True, exist_ok=True)
    root = out_dir / "nagent-root"
    if root.exists():
        shutil.rmtree(root)

    expected = json.loads((HERE / "expected.json").read_text(encoding="utf-8"))

    if args.rescore:
        return rescore(out_dir, expected)

    runbook = None
    if args.runbook:
        runbook = Path(args.runbook).expanduser().read_text(encoding="utf-8", errors="replace")
        print(f"runbook: {args.runbook} ({len(runbook)} chars)")
    runbook_requests = {name.strip() for name in args.runbook_requests.split(",") if name.strip()}
    summary = {"provider": args.provider, "model": args.model, "requests": {}}
    totals = {"decide": [0, 0, 0, 0, 0], "nagent": [0, 0, 0, 0, 0]}  # in, out, checks, hits, loose

    for name in REQUESTS:
        request_path = HERE / name
        wanted = expected[name]
        print(f"\n{name}  ({len(request_path.read_text(encoding='utf-8'))} bytes of request)")
        entry = {}

        if not args.nagent_only:
            run = run_decide(request_path, args.provider, args.model, out_dir, bare=args.bare)
            checks, hits, loose_hits, misses = scores(run, wanted)
            print_row("nagent-decide", run, checks, hits, loose_hits, misses)
            entry["decide"] = {
                **run,
                "checks": checks,
                "hits": hits,
                "loose_hits": loose_hits,
                "misses": misses,
            }
            if run.get("ok"):
                totals["decide"] = [
                    totals["decide"][0] + run["input_tokens"],
                    totals["decide"][1] + run["output_tokens"],
                    totals["decide"][2] + checks,
                    totals["decide"][3] + hits,
                    totals["decide"][4] + loose_hits,
                ]

        if not args.decide_only:
            run = run_nagent(request_path, args.provider, args.model, out_dir, root)
            checks, hits, loose_hits, misses = scores(run, wanted)
            print_row("nagent", run, checks, hits, loose_hits, misses)
            entry["nagent"] = {
                **run,
                "checks": checks,
                "hits": hits,
                "loose_hits": loose_hits,
                "misses": misses,
            }
            if run.get("ok") and run["input_tokens"] is not None:
                totals["nagent"] = [
                    totals["nagent"][0] + run["input_tokens"],
                    totals["nagent"][1] + run["output_tokens"],
                    totals["nagent"][2] + checks,
                    totals["nagent"][3] + hits,
                    totals["nagent"][4] + loose_hits,
                ]

        if runbook is not None and name in runbook_requests:
            run = run_nagent(request_path, args.provider, args.model, out_dir, root, runbook=runbook)
            checks, hits, loose_hits, misses = scores(run, wanted)
            print_row("nagent+runbook", run, checks, hits, loose_hits, misses)
            entry["nagent_runbook"] = {
                **run,
                "checks": checks,
                "hits": hits,
                "loose_hits": loose_hits,
                "misses": misses,
            }

        summary["requests"][name] = entry

    print("\n--- totals (provider-reported tokens) ---")
    for label, (tin, tout, checks, hits, loose) in totals.items():
        if checks:
            print(
                f"  {label:<14} in={tin} out={tout} total={tin + tout}   "
                f"{hits}/{checks} usable, {loose}/{checks} decided right"
            )
    if totals["decide"][2] and totals["nagent"][2]:
        decide_total = totals["decide"][0] + totals["decide"][1]
        nagent_total = totals["nagent"][0] + totals["nagent"][1]
        if decide_total:
            print(f"  nagent / nagent-decide tokens: {nagent_total / decide_total:.2f}x")

    summary["totals"] = {
        label: {
            "input_tokens": tin,
            "output_tokens": tout,
            "checks": checks,
            "hits": hits,
            "loose_hits": loose,
        }
        for label, (tin, tout, checks, hits, loose) in totals.items()
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nwrote {out_dir}/summary.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
