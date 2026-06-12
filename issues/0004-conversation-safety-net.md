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

Trigger: fractions of a new `context_budget_tokens` config (defaults
20% / 45% / 70%; `TokenStats.conversation_input_tokens` is the signal —
proactive, because model capability degrades under high context
utilization, not just at the limit). Prompt:
`prompts/checkpoint-conversation.md`, resolved through the 0001 layered
order so projects and campaigns can specialize it.

## 2. Rebuild: conversations as a chain of bounded windows

Past the final threshold, the loop archives the conversation and writes a
fresh one = initial context + current checkpoint + the last N bytes of raw
tail, then continues. Deterministic assembly — no LLM call, unlike
`--compact`. The archive stays on disk for `nagent-distill`; a long
conversation becomes an inspectable chain of windows linked by checkpoints,
each window a file. Default assembled-window budget mirrors MiMo's ~65K
tokens until measured otherwise; the tail size is a config knob, not an
architecture decision.

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

- A conversation pushed past `context_budget_tokens` produces: checkpoint
  file(s) at the configured thresholds, an archived window, a fresh window
  containing the checkpoint, and a completed task — every artifact
  openable in an editor.
- A user edit to the checkpoint file between thresholds survives the next
  writer pass (the writer updates fields; it does not regenerate the file
  wholesale).
- Best-of-N direction appears in initial context; no new machinery.

## 7. Open questions

- **Checkpoint freshness at rebuild:** rebuild assumes a recent
  checkpoint; if the writer worker failed, rebuild must either trigger one
  synchronously or fall back to a larger raw tail. Decide here.
- **Writer cadence vs cost:** three thresholds per window is a guess;
  measure how stale the 70% checkpoint is in practice before adding more.
