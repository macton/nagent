# 0003 — nagent-decide: open questions

Status: open
Filed: 2026-09-22
Area: `bin/nagent-decide`, `bin/helpers/nagent_decide_lib.py`

These are the design questions the first implementation deliberately did not
answer, each with what would settle it. None blocks use.

## 1. `confidence` is a self-report and nothing calibrates it

The output carries `confidence` in `[0,1]`, clamped, documented as the model's
own estimate. kev (the interface this is modelled on) derives its confidence and
its `probabilities` from token logits; `generate_text_with_usage` returns text,
so there is nothing to derive from here.

`"confidence": false` in the request drops the field (it is `null` in the output
then, since the answer layout is fixed), so a caller who does not want an
uncalibrated number need not carry one. It remains on by default.

The risk is that scripts threshold on it — route anything under 0.7 to nagent —
and that threshold is tuned against a number with no established relationship to
correctness.

**What would settle it:** run the `examples/monitor-github` requests enough
times to get a distribution, bucket the answers by reported confidence, and
measure the hit rate per bucket against `expected.json`. If the buckets do not
separate, either drop the field or rename it so no one thresholds on it. Until
that measurement exists, no claim about its usefulness should be made.

## 2. Batch size is unbounded and its effect on accuracy is unmeasured

One request can carry any number of items and they all go in one call. The
measured runs used 5 and 6 items and scored 34/34 on `gpt-5.5`. Nothing is known
about 50 items, or about whether late items in a long list degrade — the shape
of failure the runbook itself records for a different subject ("a truncated
LIST looks like a short list").

The grid check catches a *dropped* item, so silent truncation fails loudly. It
does not catch an item answered carelessly because it was fortieth.

**What would settle it:** the same question set over a synthetic batch of
5/10/25/50 items with known answers, scored per position. If accuracy falls with
position, the fix is a caller-visible chunk size, not a hidden one.

## 3. Only the `anthropic` branch honours the cache boundary

`render_prompt` returns a boundary offset at the end of the last stable section
and `decide` passes it on every call. `cache_prefix_blocks` is only consulted by
the `anthropic` branch of `generate_text_with_usage`; for every other provider
the offset is computed and discarded.

That is not wrong — the ordering it implies (instructions, constraints,
evidence, questions, then items) is the right ordering regardless — but the
saving it is meant to buy is currently unavailable on the providers the examples
were measured on.

**What would settle it:** whether `openai`, `together` and `openrouter` expose a
prefix-cache control on their wire formats. If they do, it belongs in
`nagent_llm.py` next to `cache_prefix_blocks`, not here.

## 4. No end-to-end test of the CLI's success path against a real provider seam

`tests/test_nagent_decide.py` covers `decide()` against an injected `generate`,
and covers the executable's `--dry-run`, error and empty-batch paths. The one
uncovered line of the executable is the real `generate_text_with_usage` call.

Covering it would mean a provider-injection seam in production code that exists
only for the test. That was judged not worth it: `examples/monitor-github`
exercises the path live, and its results are committed under `runs/`.

**What would settle it:** if the CLI grows any logic between `load_request` and
`decide`, the calculus changes and the seam is worth adding.
