# 0003 — nagent-decide / nagent-classify: open questions

Status: resolved 2026-09-28 — 2, 3 and 4 answered; 1 answered as 'not knowable yet' and documented as such
Filed: 2026-09-22
Area: `bin/nagent-decide`, `bin/nagent-classify`, and their `_lib.py` files

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

This now covers `nagent-classify` as well, and more sharply: an input set is the
natural thing to grow, and a caller with 200 rows to sort will hand over 200.
The live classify measurements used 6 and 5 inputs. A 40-input set is exercised
only against a mock, which proves the reshaping and the grid check scale, not
that the model's attention does.

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

---

# Resolutions — 2026-09-28

## 1. `confidence` — measured, and it cannot be calibrated from what exists

Scored every answer in the committed `examples/monitor-github/runs/` against
`expected.json`, reusing that example's own matcher so the comparison is the one
the example makes (`tests/live/decide_confidence_calibration.py`, which spends
nothing). 68 answers carry a confidence value:

    low (<0.90)         1/1   correct
    mid (0.90-0.96)    22/23  correct  (96%)
    high (>=0.97)      44/44  correct  (100%)

The buckets are ordered the right way and that is all that can be said, because
there is exactly **one** wrong answer in the whole corpus. An ordering resting on
n=1 is not calibration, and quoting those percentages as if it were would be the
precise failure this issue was filed to avoid.

So the field keeps its name and its default, and the docs now say what is true:
`nagent_decide_lib`'s header carries **DO NOT THRESHOLD ON IT**, this measurement,
and the fact that `"confidence": false` drops it. That is the "rename it so no one
thresholds on it" branch, executed as documentation rather than a rename, because
the name is accurate — it is the model's confidence — and only its authority was
ever in question. Settling it properly still needs the example requests run enough
times to accumulate tens of errors; the script is there to re-run when they are.

## 2. Batch size — measured to 50 items, no positional decay

`tests/live/decide_batch_scaling.py` against `anthropic/claude-opus-5`: the same
question set at 5, 10, 25 and 50 items, with known answers, scored by quarter of
the batch, at two difficulties. The easy variant states its own answer, so a miss
can only be inattention; the hard variant needs arithmetic and an elimination, so
a miss is a real error.

    easy  5/5  10/10  25/25  50/50     every quarter clean
    hard  5/5  10/10  25/25  50/50     every quarter clean

180/180. Nothing suggests a late item is answered more carelessly at these sizes,
so no chunk size is introduced — a hidden one was never wanted and a caller-visible
one has nothing to fix. What remains unknown is above 50 and on weaker models; the
script takes a model argument and a caller with 200 rows should run it before
trusting the answer, which is a cheaper habit than a parameter nobody tuned.

## 3. Cache boundary — answered per provider, and one of them now honours it

- **openrouter**: forwards `cache_control` on content blocks to Anthropic-family
  models. Measured 2026-09-28 against `anthropic/claude-opus-5` on a 12572-token
  conversation — no markers read 0 tokens, a marker at the context boundary read
  7917, all three read 12570. So it is implemented:
  `_forwards_anthropic_cache_control(model)` gates it on the `anthropic/` prefix,
  and any other model on that provider gets a plain string rather than a block
  shape its upstream may reject.
- **openai**: no breakpoint control exists. It caches long prompt prefixes
  automatically, so the only thing that buys a hit is the stable-first ordering
  `render_prompt` already produces. The offset is computed and dropped, which costs
  nothing; the comment in `nagent_llm.py` now says so instead of leaving it
  looking like an oversight.
- **together**: exposes no prefix-cache control on its wire format. Nothing to
  mark, and the comment says that rather than "ignored".

So the answer to "whether they expose a prefix-cache control" is: one of the three
does, it is wired up and measured, and the other two are documented with the reason.

## 4. CLI provider seam — covered, with no production seam added

The question was whether covering the executable's real `generate_text_with_usage`
call requires a provider-injection seam in production code. It does not. The test
now loads `bin/nagent-decide` as a module and patches the symbol *it* imported,
which is a test-only concern and leaves the executable exactly as shipped
(`CliProviderSeamTests`). Two tests: that the CLI forwards provider, model,
reasoning and the cache boundary, and that a provider exception becomes
`EXIT_PROVIDER`.

The trigger this issue named — "if the CLI grows any logic between `load_request`
and `decide`" — had in fact been met (the empty-batch short-circuit and
`--prompt-out` both sit there), which is a second reason not to have left the line
uncovered. The boundary assertion also pins what the ordering is *for*: the
evidence lands before the offset and the items after it.
