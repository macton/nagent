#!/usr/bin/env python3
"""Does a decide/classify answer get worse for being fortieth in the batch?

Issue 0003 question 2. NOT part of the unittest suite: it spends money and needs a
live key. One question set, known answers, the same items at four batch sizes,
scored per position.

    OPENROUTER_API_KEY=... python3 tests/live/decide_batch_scaling.py [model]

The items are deliberately trivial and unambiguous — each one states its own
answer — so a wrong answer cannot be a hard question. It can only be inattention.
That is the whole point: this measures whether position in the batch costs
accuracy, not whether the model can reason.
"""
import json
import os
import random
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "bin" / "helpers"))
from nagent_decide_lib import decide, load_request  # noqa: E402
from nagent_llm import generate_text_with_usage  # noqa: E402

MODEL = sys.argv[1] if len(sys.argv) > 1 else "anthropic/claude-opus-5"
PROVIDER = os.environ.get("BATCH_PROBE_PROVIDER", "openrouter")
SIZES = (5, 10, 25, 50)
COLOURS = ("red", "green", "blue")


def build(n, seed, hard=False):
    """Two difficulties on purpose.

    easy: the item states its answer. A miss can only be inattention, so this
    isolates position from difficulty — which is the question being asked.

    hard: the answer needs arithmetic and an elimination, and is still fully
    determined, so a miss is a real error rather than an ambiguity. Without a
    difficulty that can produce errors, a confidence number has nothing to be
    wrong about and question 1 cannot be measured at all.
    """
    rng = random.Random(seed)
    truth = [rng.choice(COLOURS) for _ in range(n)]
    if not hard:
        return truth, {
            "context": "Each item names its own colour. Report that colour.",
            "questions": {
                "colour": {
                    "question": "Which colour does this item name?",
                    "type": "choice",
                    "options": {c: f"the item named {c}" for c in COLOURS},
                }
            },
            "confidence": True,
            "items": [
                {"id": f"i{i:03d}", "context": f"This item's colour is {c}."}
                for i, c in enumerate(truth)
            ],
        }

    items = []
    for i, c in enumerate(truth):
        others = [x for x in COLOURS if x != c]
        a, b = rng.randint(11, 39), rng.randint(11, 39)
        # The colour is the one left after eliminating two, and which two depends
        # on the sum's parity — so the item cannot be answered by pattern-matching
        # a colour word out of it.
        items.append(
            {
                "id": f"i{i:03d}",
                "context": (
                    f"Counters: {a} and {b}. If their sum is even, this item is NOT "
                    f"{others[0]} and NOT {others[1]}. If their sum is odd, this item "
                    f"is NOT {others[0]} and NOT {others[1]}."
                ),
            }
        )
    return truth, {
        "context": (
            "Each item rules out two of the three colours. Work out which one is "
            "left and report it."
        ),
        "questions": {
            "colour": {
                "question": "Which colour is left after the eliminations?",
                "type": "choice",
                "options": {c: f"the remaining colour is {c}" for c in COLOURS},
            }
        },
        "confidence": True,
        "items": items,
    }


def run(n, seed, hard=False):
    truth, request = build(n, seed, hard)
    result = decide(
        load_request(json.dumps(request)),
        lambda text, boundaries: generate_text_with_usage(
            text, PROVIDER, MODEL, cache_boundaries=boundaries
        ),
    )
    got = {d["item"]: d["answers"]["colour"]["choice"] for d in result["decisions"]}
    conf = {d["item"]: d["answers"]["colour"].get("confidence") for d in result["decisions"]}
    hits = [got.get(f"i{i:03d}") == c for i, c in enumerate(truth)]
    return hits, conf, result


def main():
    print(f"provider={PROVIDER} model={MODEL}")
    buckets = {}
    for hard in (False, True):
        print(f"\n--- {'hard (needs elimination)' if hard else 'easy (answer is stated)'} ---")
        print(f"{'items':>6} {'correct':>9} {'accuracy':>9}   accuracy by quarter of the batch")
        for n in SIZES:
            hits, conf, _result = run(n, seed=n, hard=hard)
            q = [hits[i * n // 4 : (i + 1) * n // 4] for i in range(4)]
            quarters = "  ".join(
                f"Q{i+1} {sum(part)}/{len(part)}" if part else f"Q{i+1} -"
                for i, part in enumerate(q)
            )
            print(f"{n:>6} {sum(hits):>9} {sum(hits)/n:>8.0%}   {quarters}")
            if not all(hits):
                print(f"         wrong at positions: {[i for i, ok in enumerate(hits) if not ok]}")
            for i, ok in enumerate(hits):
                c = conf.get(f"i{i:03d}")
                if c is None:
                    continue
                key = round(min(0.999, max(0.0, c)) * 10) / 10
                hit, total = buckets.get(key, (0, 0))
                buckets[key] = (hit + int(ok), total + 1)

    print("\n--- question 1: does reported confidence separate right from wrong? ---")
    if not buckets:
        print("no confidence values returned; nothing to calibrate")
    else:
        for key in sorted(buckets):
            hit, total = buckets[key]
            print(f"  confidence ~{key:.1f}: {hit}/{total} correct ({hit/total:.0%})")
        distinct = len(buckets)
        wrong = sum(t - h for h, t in buckets.values())
        print(f"\n  {distinct} bucket(s) populated, {wrong} wrong answer(s) in total.")
        if wrong == 0:
            print("  With no errors there is nothing for confidence to separate: this run")
            print("  cannot calibrate the field either way. Report it as unmeasured, not good.")


if __name__ == "__main__":
    main()
