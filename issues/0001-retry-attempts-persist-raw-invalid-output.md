# 0001 — Retry attempts still persist raw invalid output

Status: open
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
