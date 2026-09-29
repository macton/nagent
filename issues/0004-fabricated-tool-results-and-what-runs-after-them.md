# 0004 — Fabricated tool results, and the actions nagent runs after them

Status: resolved 2026-09-28 — candidates 1-4 implemented, plus an exit gate; candidate 5 (role separation) left as a filed experiment
Filed: 2026-09-28
Area: `bin/nagent` — `parse_response` / `process_tags` / `ignored_correction`;
`bin/helpers/nagent_llm.py` — no `stop_sequences` on any provider

## The data

Measured over the helmfire corpus at `/home/macton/helmfire/.nagent/conversations`:
1206 conversations (104 MB) and the 1193 `*.invalid.*` sidecars they produced.
Every number below is counted, not estimated.

Sidecars by what the model emitted (categories overlap):

| turns | share | non-protocol content |
|------:|------:|----------------------|
|   824 | 69.1% | fabricated a tool **result** tag |
|   767 | 64.3% | echoed nagent's own `<nagent-turn-status>` telemetry |
|   219 | 18.4% | other prose / code fences |
|    68 |  5.7% | harness scaffolding leak (`</assistant>`, `</invoke>`, `human`) |
|     5 |  0.4% | reasoning leak (`<thinking>`, `<thought>`) |

Of the fabricated-result turns, **693 assert `exit_code: 0`** — invented success.
307 of 1206 conversations (25%) have at least one stripped turn; the worst has 28.

Which driver tags get fabricated, all occurrences:

    1066  <nagent-shell-result        57  <nagent-read-result
    1022  <nagent-turn-status         38  <nagent-write-result
      34  <nagent-conversation-result  2  <nagent-file-read-result

Where the fabrication sits inside the turn — this is the load-bearing part:

| turns | what the turn looks like |
|------:|--------------------------|
|   939 | fabricated driver output at all |
|   930 | **99%** of those: a *real* action tag came first, then the model wrote the result it expected |
|   696 | **74%** of those: it then emitted *more* action tags, downstream of output it invented |
|     9 | pure fabrication, no real action in the turn |

The fabrication begins at a median 27% of the way through the turn, so most of
each affected generation is reasoning built on an invented observation.

## The problem

`parse_response` collects every valid tag in a turn regardless of where it sits
relative to ignored content, and `process_tags` runs them in order. The invented
result tag is stripped to a sidecar; the actions the model chose *because of it*
are not. Replaying all 1193 stripped turns through the parser — which validates and
dedupes, unlike the regex count this issue first carried — 921 turns contain a
fabrication, and the tags that ran after it are:

    189  <nagent-shell>      20  <nagent-read>      3  <nagent-conversation>
     77  <nagent-response>    4  <nagent-write>   347  total
     54  <nagent-next>

(An earlier draft said 1124 shells, counting textual occurrences including
malformed and duplicated ones. The parseable figure is 189. The response count
barely moved, 86 to 77, and it is the one that matters.)

The second row is the serious one: **77 runs ended with a terminal
`<nagent-response>` composed after the model had fabricated its own tool
output.** That is the shape of both fabricated-completion incidents recorded in
`helmfire/prompts/execute-campaign-step.md` §0b, where an orchestrator reported
step 7 and then step 8 "complete and verified" with invented specifics and no
such work on disk.

Two contributing facts:

- **No provider is sent a stop sequence.** `grep stop_sequences` over
  `nagent_llm.py` returns nothing. A ReAct-style loop conventionally stops
  generation at the observation marker precisely so observations can only come
  from execution; nagent lets the model generate straight through the boundary.
- **The correction never names the failure.** `ignored_correction()` says
  "nagent ignored N non-protocol items in your previous turn; respond only with
  valid nagent tags." Its docstring argues that quoting the offending pattern
  would bias the model toward repeating it — a reasonable prior, but with up to
  28 repeats in a single conversation the current wording is not preventing
  repetition either — of the 244 conversations that fabricated a result tag, 155
  (64%) fabricated another one later in the same conversation. Whether naming the
  failure would do better is untested in both directions.

## Why it happens (mechanism, not misbehaviour)

The conversation file is sent as **one user message** containing an interleaved
transcript of model turns, driver results and telemetry. The model is not
answering inside a role structure; it is completing a document that visibly
alternates speakers. Continuing past its own turn into the next speaker's lines
is the locally likely continuation, which is why the two largest categories are
the driver's two output shapes — `<nagent-shell-result>` and the telemetry line
nobody asked it to write. Research on chat-template injection reports the same
root cause from the attack side: models parse turn boundaries from formatting
cues rather than semantics, so template-shaped text inside content is treated as
real turns (`arXiv:2509.22830`).

This is not a scale problem. The closed-world tool-hallucination work measures
fabrication concentrating on the unconstrained free-text invocation surface
versus a schema-enforced one (34 vs 3) across ten hosted models, and finds a 675B
model fabricating at the rate of a 7–8B one (`arXiv:2609.19425`).

Nor is it fixable by asking the model to check itself: intrinsic self-correction
without an external signal degrades reasoning performance (`arXiv:2310.01798`),
and the self-correction methods that do work supply a verification signal from
outside the model's own judgement (`arXiv:2405.14092`). That is the same
conclusion §0b of the helmfire playbook reached from two incidents: "the
orchestrator cannot be its own verifier."

## What was implemented

Candidates 1, 2, 3 and 4 below, plus the prompt fix, the spill in the addendum, and
an exit gate that was not in the original list:

- **`--hook-per-response` / `hook_per_response`** — a command that must exit 0
  before a `<nagent-response>` is accepted as final. It runs against the tree, its
  `<hook-per-response exit_code="N">` block is appended, and on failure the answer
  is dropped and the loop continues with a `<system>` note pointing at that block.
  Bounded by `MAX_RESPONSE_GATE_REFUSALS` (3) because a gate can be unsatisfiable
  and an unbounded retry there spends money until someone notices. This is the only
  check in the loop that does not read something the model produced, which is the
  property helmfire's own detector table says is the one that has never been wrong.
- **`stop_sequences`** — `<nagent-shell-result`, `<nagent-turn-status`,
  `<nagent-read-result`, `<nagent-write-result`: 98% of the 2219 fabricated-tag
  occurrences, and four is Anthropic's limit. Sent on the anthropic path and on the
  OpenAI-compatible chat path. Belt and braces with candidate 1: the loop refuses
  to act on what follows a fabrication, this stops it being generated or billed.

Three things found while implementing:

- Cutting on any occurrence of a driver tag is wrong. A model *discussing* the
  protocol — in backticks, or quoting the tag list in the initial context, which
  carries `<nagent-turn-status ... />` verbatim — would lose its real work. The
  rule is now "at the start of a line", which the corpus supports: 912 of 940
  fabrications sit there, mentions do not. The 28 that do not are preceded on the
  line by other junk and are left running.
- `scan_tag_document` mixed sub-document offsets into its outer result when it
  unwrapped an echoed `<agent-response>` frame, so any comparison of a node's
  position against an ignored span's was comparing two coordinate systems.
  `TagNode` now carries `content_start` and the recursion shifts what it returns.
  Fixing it *raised* the count of tags this change stops from running, 263 to 347.
- A stop sequence can leave a *partial* one behind. Measured live against Together,
  a reply asked to fabricate came back ending `...</nagent-shell>\n<nagent-shell` —
  the prefix of the stop sequence. `<nagent-shell` is a known tag name with no
  `>`, so the parser hard-errors and discards the whole turn, including the real
  action before it: stopping the fabrication would have cost more than allowing
  it. `strip_trailing_stop_prefix()` trims a proper prefix off the end, longest
  first, and the live reply now parses as the action alone.

## Candidate changes, cheapest first

1. **Stop the turn at the first fabricated driver tag** (loop-only, no provider
   dependency, works on `claude-code`). Truncate the executed tag list at the
   first ignored result/telemetry tag instead of running past it, and say so in
   the correction. Directly addresses the 696 turns that acted on invented
   output and the 86 that ended a run on it. Cost: one comparison in
   `process_tags` dispatch plus a `parse_response` signature that reports the
   offset. Risk: a turn that *did* do real work loses its later tags — but those
   tags are exactly the ones chosen from a false premise.
2. **Send `stop_sequences`** where the provider supports it (anthropic, google,
   together/openrouter; not the `claude-code` SDK path, which is the configured
   default here — check before relying on it). Anthropic allows 4. By measured
   frequency the right four are `<nagent-shell-result`, `<nagent-turn-status`,
   `<nagent-read-result`, `<nagent-write-result`, covering 1066+1022+57+38 of
   2219 occurrences (98%). This truncates generation *at* the boundary, so the
   real action (present in 99% of these turns) survives and nothing downstream
   is generated or paid for.
3. **Name the failure in the correction.** "You wrote a `<nagent-shell-result>`.
   Only nagent writes result blocks; you cannot know a command's output until it
   is appended. Re-emit only the action." Cheap, and the repeat rate makes it
   measurable.
4. **Count it in the telemetry.** The stripped-turn count and fabricated-result
   count belong on `<nagent-turn-status>` and in `TokenStats`, the way
   `cache_read_total` now is. Without that, every measurement above requires
   post-hoc grepping of sidecars, which is why this went uncounted for months.
5. **Role separation** (experiment, not a patch). Send the conversation as
   alternating user/assistant messages so the model's own turns are assistant
   turns and results are user turns, removing the continuation affordance at its
   root. Large change: it touches every provider adapter and the cache-boundary
   design, and `<initial_context>` refresh assumes one blob.

## Experiments to run

The sidecar corpus is already the eval set, and the baseline is above. Metric per
run: stripped turns / total turns, fabricated-result turns / total turns, and
actions executed downstream of a fabrication.

- **A — stop sequences on/off.** Same campaign step, same model, `--provider
  anthropic` (needs API credit; the machine this was measured on has none).
  Prediction: fabricated-result turns fall to ~0 and the real action survives.
  Falsified if turns instead end with no usable tag, i.e. the stop fires before
  any action.
- **B — truncate-at-fabrication on/off.** Provider-independent, runnable today on
  `claude-code`. Measure actions executed after a fabrication (baseline: 1124
  shells, 86 responses) and whether step outcomes get better or merely shorter.
- **C — correction wording.** Baseline vs. naming the failure. Metric: repeat
  fabrications *within* the same conversation (baseline: 155 of the 244
  conversations that fabricated at least once, 64%, did it again). This is the one
  place the "don't echo the bad pattern" prior is actually testable.
- **D — role separation.** Prototype on one provider against a fixed set of
  replayed conversations before touching the adapters.

## Sources

- `arXiv:2609.19425` — Closed-World Resolution Against Tool Hallucination in LLM
  Agents (surface comparison 34 vs 3; scale does not help; registry + signature
  resolution).
- `arXiv:2509.18970` — LLM-based Agents Suffer from Hallucinations: a survey. Its
  execution/perception categories are what is measured here: agents that "claim
  to have completed certain sub-stages... but in reality, they have not," and
  internal observations deviating from the environment. No quantitative
  mitigation rates are reported, which is why the experiments above are local.
- `arXiv:2310.01798` — LLMs Cannot Self-Correct Reasoning Yet.
- `arXiv:2405.14092` — Self-correction works with external key-condition
  verification (+6.8 EM open-domain QA, +14.1 arithmetic).
- `arXiv:2509.22830` — ChatInject: models parse turn boundaries from formatting
  cues, so template-shaped content is treated as real turns.

---

## Addendum: reconciled against `helmfire/documents/hallucinations.md`

That document is a better record than this one, and it moves what is written above
from "the problem" to "one third of the problem". It catalogues three classes; the
sidecar corpus can only see the first.

| class | example | can a sidecar see it? | count on record |
|---|---|---|---|
| protocol-violating fabrication | model writes `<nagent-shell-result> exit_code: 0` | **yes** — stripped, sidecar'd | 824 turns, 693 asserting success |
| protocol-valid semantic fabrication | phantom SHAs `a7c93e5`, `5d6ad8e`, `c3e8a15`; `validators/` (no such directory) | **no** — well-formed prose | 12 `phantom_sha` escalations, 09-24→09-28 |
| instrument error read as an answer | `$?` after a pipe measuring `tail`; `ps \| grep -c` counting a log path in another argv; a glob that matched nothing reported as "zero lines" | **no** — no model involved | 11 supervisor errors, 3 of them from `tail` |

The class this issue measures is the one nagent already detects, and therefore the
least dangerous. The expensive shape is the document's: "accurate investigations
with fabricated conclusions bolted on" — a runner that read the ratchet's *true*
values (`grew 1294448 -> 1299661`) and invented the commit that would have acted
on them. Its conclusion about detectors is the design constraint for anything
built here:

> The contract is the one that has earned trust, because it asks the tree rather
> than the runner. Every other detector reads something the runner produced.

Any detector added to nagent must read the tree. A `<nagent-verify>` tag whose
body the model writes would be another thing the runner produced.

### A rule in the playbook is false about nagent, and may be causal

`helmfire/prompts/execute-campaign-step.md` tells every runner:

> **The nagent shell TRUNCATES long stdout in what you see.** A command that
> prints more than ~20 lines will show you a clipped middle — you may not realize
> output is missing and will hallucinate what "wasn't there." For any
> listing/dump longer than a screen, redirect to a file and read it back.

`execute_shell` (`bin/nagent:1539`) does not truncate. It appends `exit_code`,
then all of stdout, then all of stderr. Measured over the 5549 driver-appended
`<nagent-shell-result>` blocks in the corpus: p50 1,993 chars, p90 10,287, p99
35,515, max **246,429**, with a smooth tail and no ceiling anywhere. What
truncates is the terminal display for the human, not the model's input.

Two costs. The workaround spends two extra turns per listing. The larger one is
that the rule tells the model, in its standing instructions, that its own
observations arrive silently incomplete — which is a licence to fill the gap, and
gap-filling is the failure being fought. The document's own "self-reported
forgery" entry describes exactly that sequence from the other end: "A malformed
tool tag produced no tool result, and the model's own continuation filled the
gap."

This is a hypothesis, not a measurement: the rule's removal has not been tested
against fabrication rate. It is cheap to test and it is the only candidate here
that might *reduce* prompt size while reducing fabrication.

### The one silent truncation that is real

`file_commit_detail()` (`bin/nagent:471`) clips each `git show` to
`stdout[:12000]` with no marker, so a per-commit diff in a file-edit history block
can end mid-hunk with nothing saying so. That is the environment actually behaving
the way the playbook wrongly describes the shell as behaving. It should carry an
explicit `[... truncated N of M bytes ...]` line — the document's rule 6, that a
report must be conditional on its result.

### Added experiment

- **E — remove the false truncation rule.** Delete the shell-truncation paragraph
  and its redirect-to-file workaround from the runner prompt; hold everything else
  fixed. Metrics: fabricated-result turns per run, `phantom_sha` escalations per
  day, and turns per step (the workaround's cost). Prediction: no rise in either
  fabrication metric and a fall in turns per step. A rise in fabrication would be
  the interesting result — it would mean the rule's wrong premise was doing real
  work by making the model distrust its context, which is worth knowing before any
  other prompt is written this way.
