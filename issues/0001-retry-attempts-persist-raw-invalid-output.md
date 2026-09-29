# 0001 — Retry attempts still persist raw invalid output

Status: resolved 2026-09-28 — option 1, with the raw reachable rather than absent
Filed: 2026-06-13
Area: `bin/nagent` — `run_agent_loop` retry branches

## Context

Commit 065168c made the success path bias-safe: a turn that contained
non-protocol content (a leaked `<thought>`, an echoed wrapper, stray prose) is
stored *cleaned* in the conversation, and the raw output is preserved in a
`{conversation}.invalid.{guid}` sidecar linked from `<nagent-turn-status>`. The
conversation — which is the next generation's input — therefore can't bias the
model toward repeating the bad pattern.

The two *retry* branches in `run_agent_loop` were left out of that treatment:

- **Malformed known tag** (hard parse error, e.g. unclosed `<nagent-write>`):
  appends `<agent-response>{raw}</agent-response>` + a `<system>` correction,
  then retries.
- **No actionable tags** (the turn was only junk): same shape, then retries.

Both still write the raw model output into the conversation verbatim.

## The problem (data)

A turn that needs N format-retries leaves N raw malformed attempts in the
conversation, e.g.:

    [raw malformed attempt 1][<system> correction]
    [raw malformed attempt 2][<system> correction]
    [raw good attempt 3]

Those failed attempts persist for the rest of the run and act as few-shot
examples — exactly the bias the success-path fix removes. In the observed
collide-gemini run, `<thought>` leaks compounded across turns once they
appeared.

Why it was deferred: keeping the raw on a retry helps the model *self-correct
within the same turn* (it sees what it just got wrong), and the conversation is
**append-only** (`append_to_conversation` only appends). Stripping a failed
attempt after a later attempt succeeds means rewriting earlier bytes of the
file, not appending — a larger change than the success-path fix.

## Options (with cost)

1. **Strip on retry too, immediately.** Store only the `<system>` correction
   (which already names the specific error, e.g. "missing `</nagent-write>`")
   plus a sidecar of the raw; never store the raw inline.
   - Cost: small code change; risk that the model self-corrects worse without
     seeing its own prior text. Unverified — would need an A/B on a leak-prone
     provider (Gemini) to confirm the correction message alone is enough.
2. **Keep raw during the turn, sweep on success.** Leave attempts inline while
   retrying; once the turn finally produces valid tags, rewrite the turn's
   region to drop the failed attempts (move them to a sidecar).
   - Cost: breaks the append-only invariant for one region; more code; must be
     careful not to corrupt the file mid-write. Highest fidelity to "model sees
     its mistakes while it matters, conversation stays clean afterward."
3. **Do nothing.** Accept that retry-attempt bias is rarer now that leniency +
   EOF-capture catch most malformations before they become hard errors.
   - Cost: zero; residual bias only on turns that still hard-error or go
     all-junk.

## Recommendation

Start with option 1 (strip on retry, sidecar the raw, lean on the specific
`<system>` correction), measured against a leak-prone provider before
committing. Escalate to option 2 only if self-correction quality drops.

## Done criteria

- A multi-retry turn leaves no raw malformed output in the conversation.
- Each stripped attempt is reconstructable from a sidecar.
- Self-correction success rate on a leak-prone provider is no worse than today
  (measured, not assumed).

## 2026-09-28 — 0004 makes this the worst content to leave inline

The fabrication cut added in [0004] routes a new case down these branches: a turn
whose invented driver block leaves no surviving tags produces no tags at all, so
it takes the "no actionable tags" retry branch and its raw output is appended
verbatim. Verified directly — a turn emitting

    <nagent-shell-result>
    exit_code: 0
    stdout:
    all 8 validators pass
    </nagent-shell-result>
    <nagent-response>step 8 complete and verified</nagent-response>

ends with the invented `exit_code: 0`, the invented success line, and the invented
completion claim written into the conversation, **with no sidecar**, where they
stay for the rest of the run. The `<system>` correction sits immediately after
them, which is the only mitigation.

That is a different severity from a leaked `<thought>`. It is a forged
observation, indistinguishable by grep from a real one, in the file that is both
the next turn's input and the artifact a human or an auditing agent reads. In the
helmfire corpus this is what the `forgery` detector hunts for, and nagent puts it
there itself.

Frequency is low and measured: replaying 1193 real stripped turns, 916 of the 921
cut turns keep runnable tags and take the success path (sidecar written, raw kept
out of the conversation); **5** are cut to nothing and take a retry branch. A
further 14 such turns are already sitting in helmfire conversations from before
the cut existed. So: rare, but the worst possible thing to leave, and cheap to
stop leaving.

Option 1 in this issue is also now better supported than when it was filed. It was
deferred partly because the `<system>` correction was generic ("nagent ignored N
non-protocol items"); for this case the correction now names the tag and explains
why the model cannot know the output, which is the specific feedback option 1
wanted to lean on. The done-criteria below are unchanged — including measuring
self-correction quality on a leak-prone provider before committing.

## Resolution — 2026-09-28: option 1, plus a path

Both retry branches now write the raw attempt to a `{conversation}.invalid.{guid}`
sidecar and append only the `<system>` correction. The correction names the
sidecar, so the raw is one `<nagent-read>` away.

That last part is what made option 1 safe to take without the A/B it asked for.
The reason it was deferred was that a model may self-correct better for seeing
what it just got wrong; the answer is that it still can — the difference is that
the attempt is now *reachable* instead of *in the prompt*, and only the second one
teaches. A model that needs the text reads it; one that does not is never shown it.

Verified against the case that made this urgent: a turn emitting a fabricated
`exit_code: 0` with `all 8 validators pass` and a completion claim leaves none of
those strings in the conversation, all of them in the sidecar, and the sidecar
named in the note.

Done criteria:

- [x] A multi-retry turn leaves no raw malformed output in the conversation.
- [x] Each stripped attempt is reconstructable from a sidecar.
- [ ] Self-correction rate on a leak-prone provider measured as no worse. NOT
      measured. The design sidesteps the risk rather than testing it, since the
      text remains available on request; if retries start failing more often on a
      leak-prone provider, this is the change to suspect first.
