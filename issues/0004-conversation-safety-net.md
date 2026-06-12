# 0004: Conversation safety net — checkpoints, rebuild, best-of-N direction

Status: proposed (tier 2 per context/data-oriented-design.md)
Sequence: after 0001 (prompt layering). Deliberately **after** 0002:
campaigns are the first line of context control — decomposition produces
bounded items and bounded conversations. This issue covers what remains: a
single item's debugging marathon that outgrows its window, and non-campaign
conversations that have nothing else. Informed by Xiaomi's MiMo-Code
(mimo.xiaomi.com/blog/mimo-code-long-horizon).

## 1. Checkpoint: live working state, written by a disposable worker

A delegated writer sub-conversation — not the working model; asking a
mid-task model to also keep the log degrades both jobs — reads the
conversation file and maintains `conversations/{name}.checkpoint.md`: a
fixed-schema, user-editable artifact.

Schema: intent, next action, constraints, current work, involved files,
discoveries, errors and fixes, decisions, notes. **No task tree** — that is
the campaign's job (0002, `index.yaml`).

Trigger: wall-clock cadence with a burst guard, both computed from data on
disk — the checkpoint records its own timestamp and the conversation's byte
size at the time it was written. Fire when
`elapsed > checkpoint_interval_minutes` (default 60) **and** the
conversation has grown since the last checkpoint (no idle no-op LLM calls),
**or** when it has grown by more than `checkpoint_max_new_kb` (default 256)
regardless of time — bursts are when checkpoints earn their keep, and time
and context consumption are uncorrelated in exactly the wrong direction.
Wall-clock is the primary cadence because it is exact, provider-independent,
and legible ("it's been an hour"); token-percentage triggers were an
approximation of an approximation (estimated counts, per-provider
tokenizers, a hand-picked budget). A conversation resumed after a long gap
fires on its first turn — the un-checkpointed tail of the prior session is
precisely what recovery wants. Prompt:
`prompts/checkpoint-conversation.md`, resolved through the 0001 layered
order so projects and campaigns can specialize it.

## 2. Rebuild: conversations as a chain of bounded windows

Rebuild is the one trigger that stays a size question — "approaching the
context window" has no time answer — but it is plain bytes of the
conversation file (`rebuild_at_kb`, default sized to mirror MiMo's ~65K
tokens until measured otherwise): exact, visible with `ls -l`, no tokenizer
estimate. Past the threshold, the loop **runs a synchronous checkpoint
first** (rebuild correctness never depends on cadence — this resolves the
freshness question below), archives the conversation, and writes a fresh
one = initial context + current checkpoint + the last N bytes of raw tail,
then continues. Deterministic assembly — no LLM call beyond the checkpoint,
unlike `--compact`. The archive stays on disk for `nagent-distill`; a long
conversation becomes an inspectable chain of windows linked by checkpoints,
each window a file. The tail size is a config knob, not an architecture
decision.

Config, three numbers in units `ls -l` can verify:

```json
{
  "checkpoint_interval_minutes": 60,
  "checkpoint_max_new_kb": 256,
  "rebuild_at_kb": 384
}
```

## 3. Best-of-N as direction, not machinery

One addition to the conversations-as-data context block: for a high-stakes
decision, spawn 2–3 workers on the same authored briefing plus a judge
worker to compare results. No engine, no flag; the model spends the tokens
only when warranted. (MiMo's measured economics: +10–20% quality at 4–5×
tokens — justified at decision points, not per turn.) Within a campaign,
the natural unit is one item briefed to multiple workers plus a judge.

## 4. Rejected (and why, in this design's terms)

- SQLite history/FTS store: trades greppable, diffable text files for an
  opaque database. `grep` over committed conversations is the retrieval
  engine.
- A standalone `--goal` judge: absorbed by campaign completion conditions
  (0002); a one-item campaign covers the non-campaign need.

## 5. Costs

~250 lines plus the checkpoint prompt; one LLM call per threshold
crossing; rebuild itself is free (string assembly).

## 6. Done criteria

- A conversation pushed past `rebuild_at_kb` produces: a synchronous
  checkpoint, an archived window, a fresh window containing the
  checkpoint, and a completed task — every artifact openable in an editor.
- The cadence triggers fire correctly: elapsed interval + growth fires;
  elapsed interval without growth does not (no idle LLM calls); a burst
  past `checkpoint_max_new_kb` fires regardless of elapsed time; a resumed
  conversation with an un-checkpointed tail fires on its first turn.
- A user edit to the checkpoint file between triggers survives the next
  writer pass (the writer updates fields; it does not regenerate the file
  wholesale).
- Best-of-N direction appears in initial context; no new machinery.

## 7. Open questions

- **Synchronous checkpoint failure at rebuild:** the pre-rebuild
  checkpoint can itself fail (provider down). Fall back to a larger raw
  tail, or refuse to rebuild and continue with a warning? Leaning larger
  tail — rebuild must not be blockable by a provider outage.
- **Interval defaults:** 60 minutes / 256KB are guesses; revisit after
  real long-horizon use.
