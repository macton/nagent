# Breaking a standing runbook into decisions

`../../../helmfire/documents/monitor-github.md` is a standing task: poll GitHub
every 30 minutes, implement what is new, prove it, push it, close the issues.
It is 18,063 lines and 1,272,905 characters — about 320,000 tokens, measured
below as 322,851 input tokens on one call.

Almost none of that is instructions for *doing* the work. It is accumulated
rulings on **decisions**: which item is next, is this blocked or is it work,
which lane can prove it, does this candidate join the batch, is this filing a
question or a defect the design already settles. Each one has an answer set
that can be written down before the question is asked. That makes it a lookup,
not reasoning — and a lookup does not need the runbook in front of it, only the
rules that bear on it.

## The three requests

| file | runbook sections | questions | items |
| --- | --- | --- | --- |
| `triage.json` | §3 blocked-vs-work, §1a lane matching | `state`, `lane` | 6 queue items |
| `batch.json` | §3 coupling test, §1a gate sizing | `batch`, `coupling`, `attribution` | 5 candidates against an anchor |
| `clarify.json` | §6 ambiguity, convention vs. transcription | `verdict`, `goes_to_matt`, `confidence_in_corpus` | 5 `Clarify:` filings |

Each carries a few hundred words of the runbook's own rules as `context`, the
hard rules as `constraints`, and the closed answer set as `options`. The
runbook's recorded rulings become the option descriptions: "blocked means an
unanswered question, art that does not exist, or a decision that is the user's
to make" is not prose to be re-read every cycle, it is four option names.

What is **not** here is deliberate. Ordering by issue number, "is this SHA in
`.monitor-state`", and pagination are `sort -n`, `grep` and `--paginate`. They
are not decisions and routing them through a model would be strictly worse.

## The two classification requests

Two of the runbook's dimensions are classifications rather than multi-question
decisions, so they are also expressed for `nagent-classify` — same evidence, same
ground truth, flatter shape:

| file | dimension | mode | inputs | categories |
| --- | --- | --- | --- | --- |
| `lane-classify.json` | which lane can run this item's proof (§1a) | single-label | 6 | 2 |
| `coupling-classify.json` | which coupling tests fire against the anchor (§3) | multi-label | 5 | 7 |

`lane-classify.json` carries only the one §1a context entry that bears on the
lane, not the three §3 entries about blocked-versus-work that `triage.json`
needs. That trimming is the point of the tool: send the evidence that applies to
the question being asked.

```bash
../../bin/nagent-classify --input lane-classify.json
../../bin/nagent-classify --input coupling-classify.json
```

Both score against the same `expected.json` entries the decide requests use —
`lane` from `triage.json`, `coupling` from `batch.json`:

| model | tokens | correct |
| --- | --- | --- |
| `gpt-5.5` | 3,698 | 9/9 |
| `gemini-2.5-flash` | 3,316 | 9/9 |

First attempt in every case. The `buckets` index came back right too, including
`shared-validator` and `repins-same-validators` as empty — nothing was assigned
to them, which is a result rather than a gap.

One thing this is **not** evidence for: `gemini-2.5-flash` got `#194`'s
`shared-fixture` right here, where the same model answered `none` for it through
`batch.json`. The requests differ (trimmed context, one question instead of
three), it is a single sample, and it says nothing about either tool being more
accurate than the other.

## Ground truth

`expected.json` holds the expected answers, and every one is a ruling the
runbook records for itself or a direct consequence of a rule it states — #176
belongs to the gate lane because the runbook says scheduling it to staging
"came back with two correctly-attributed dead ends and zero new measurements";
#103 and #110 are work because "a written spec means there is nothing left to
decide". An expectation is a list where the runbook's text admits more than one
defensible answer, and a question is omitted for an item where the evidence
deliberately does not settle it.

Two expectations were **wrong and the model was right**, which is recorded in
`expected.json` rather than quietly fixed:

- **#220 batching.** Expected `should`; answered `no`. §1a says to keep a
  behaviour change separate from a large mechanical move — the rule settles it
  and was missing from the evidence. The rule was added; the expectation became
  `no`.
- **#220 attribution.** Expected `yes`; answered `no`. A 42-identifier rename
  across the sim shares `step-audit` with everything, so a red there could
  belong to either change. The answer was internally consistent with its own
  `no` on batching. The expectation was dropped as unsettled.

## Running it

```bash
# both paths, same evidence
./compare.py --provider openai --model gpt-5.5

# add the row a real cycle actually pays
./compare.py --provider openai --model gpt-5.5 --runbook ../../../helmfire/documents/monitor-github.md

# the decision path alone, on a cheap model
./compare.py --provider google --model gemini-2.5-flash --decide-only

# re-derive the scores from a saved run, no calls
./compare.py --provider openai --model gpt-5.5 --rescore
```

The comparison is controlled: the `nagent` side is handed the **exact prompt**
`nagent-decide` renders (`--dry-run`), so the information is byte-identical and
only the machinery differs. Tokens are the provider's own counts on both sides —
`nagent-decide` prints them, `nagent` records them in its `<nagent-turn-status>`
line. Nothing is estimated; a number that could not be read from a response is
reported as null.

`--runbook` is the uncontrolled row, and it is the honest one: the same decision
with the whole standing document in front of it, which is where that cycle's
rules actually live.

Every run writes its rendered prompts, raw replies and a `summary.json` under
`runs/{provider}-{model}/`. That directory is **gitignored**: the artifacts are
regenerable by re-running the commands above, and regenerating them is the only
way to confirm the numbers below still hold on a given model. The numbers in
this file are what the committed requests produced on the dates the runs were
made.

## Results

`openai` / `gpt-5.5`, 34 scored checks:

| path | input | output | total | usable | decided right |
| --- | --- | --- | --- | --- | --- |
| `nagent-decide` | 4,425 | 4,866 | **9,291** | 34/34 | 34/34 |
| `nagent`, same evidence | 23,908 | 2,571 | **26,479** | 34/34 | 34/34 |
| `nagent` + whole runbook (triage only, 10 checks) | 322,851 | 966 | **323,817** | 10/10 | 10/10 |

`google` / `gemini-2.5-flash`, decision path only: **7,841** tokens, 33/34. The
one miss is `#194`'s coupling set — it answered `none` where the item states the
candidate is proven on the same three-client fixture.

Read the two ratios separately, because they answer different questions:

- **2.85x** is the loop's floor against identical evidence: an empty
  conversation, one turn, no tools. It is what the protocol, the tool
  descriptions and the initial context cost before any real work accumulates.
- **172x** (323,817 against 1,885 for the same ten decisions) is what the real
  cycle pays, because the real cycle is holding the runbook.

## What the two output fields cost

`--bare` re-runs the decide side with `"rationale": false` and
`"confidence": false`, which is the only way to say what they cost rather than
guess:

| model | both on | both off | total delta | output tokens | correct |
| --- | --- | --- | --- | --- | --- |
| `gpt-5.5` | 9,291 | **9,076** | −2.3% | 4,866 → 4,808 | 34/34 both |
| `gemini-2.5-flash` | 7,841 | **5,877** | −25% | 3,059 → 1,261 | 33/34 → 34/34 |

The fields are a real lever on a non-reasoning model — 59% off the output
tokens — and almost nothing on a reasoning one, where reasoning tokens dominate
the output and two short fields disappear beside them. The `gpt-5.5` breakdown
shows it plainly: `triage`, which needs little reasoning, fell 658 → 390 output
tokens, while `batch` and `clarify` barely moved.

The `gemini` accuracy difference (its one `#194` coupling miss is absent from
the bare run) is a single sample. It is not evidence that dropping the fields
helps, and it is not evidence that keeping them hurts.

```bash
./compare.py --provider google --model gemini-2.5-flash --decide-only --bare \
    --out runs/google-gemini-2.5-flash-bare
```

## The failure it prevents

The first run scored `nagent` at **0/35**. Every decision was correct. Every
answer looked like this:

```json
"lane": "gate — the lane about to gate; owns the display, the GPU and real clients"
```

The option name with its description pasted on. A human reads that as correct.
`if answer == "gate"` reads it as false, and says nothing. `nagent-decide`
rejected the same mistake and corrected it — which is what its `attempts=2`
recorded on that run.

The scorer now reports both dimensions (`usable` and `decided right`) so the two
never get conflated again.

Then the repo's rule applied: when output is wrong, fix the generator. The
prompt was rendering options as `name — description`, which invites copying the
line. Quoting every option name fixed it — retries went to zero, `nagent-decide`
fell from 22,548 tokens to 9,291, and `nagent` began complying too.

That is the honest conclusion. A well-rendered prompt gets a usable answer out
of the plain loop most of the time. The difference is that "most of the time"
is unchecked and fails silently, while `nagent-decide` checks every answer
against the set the caller declared and fails loudly.
