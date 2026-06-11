# Design: nagent-gc — artifact reclamation with knowledge harvest

Status: implemented (tier 2 per prompts/data-oriented-design.md) —
`bin/nagent-gc`, `bin/helpers/nagent_gc_lib.py`,
`prompts/harvest-conversation.md`, context injection in `bin/nagent`,
tests in `tests/test_nagent_gc.py`. Open questions in §8 remain open.

## 1. Frame

**Problem.** Durable artifacts accumulate without bound under the nagent root:
conversation archives from `--clear`/`--load-conversation`/`--edit-conversation`,
split directories, stale file-index entries. Deleting them blindly throws away
the knowledge embedded in them — decisions made, tasks finished and unfinished,
facts learned, processes discovered. Today the only options are hoard or lose.

**Why it matters.** The project's claim is "preserve work, not workers." Right
now preservation means hoarding raw transcripts nobody re-reads. The valuable
part of an old conversation is a few hundred bytes of distilled knowledge
buried in hundreds of KB of tool spam.

**Goal.** One explicit transform: bulky dead artifacts → small, categorized,
user-editable knowledge artifacts + reclaimed space. The knowledge artifacts
must be (1) surfaceable to the user and (2) injectable into nagent context.

**Limit / plan B.** If harvest cost (one LLM pass per dead conversation)
routinely exceeds the value of what it extracts, fall back to deletion-only GC
with a dry-run listing. Harvest is per-run optional (`--no-harvest`), so plan B
is a flag, not a rewrite.

## 2. The data

### Input inventory (what exists under a root today)

| Artifact                                  | Created by                                 | Class      |
| ----------------------------------------- | ------------------------------------------ | ---------- |
| `conversations/latest-{host}-{pid}`       | normal runs                                | live       |
| `conversations/{slug}-{uuid}` (per-file)  | file-edit sessions                         | live       |
| `conversations/{name}-{uuid}` (archives)  | `archive_conversation()` on clear/load/edit| dead       |
| `conversations/index-saved-*.json` + saves| `--save-conversation`                      | user-kept  |
| `conversations/file-index-{pid}.json`     | file-edit index                            | live index |
| `splits/{slug}-{uuid}/`                   | `<nagent-file-read>` of large files        | regenerable|

Characteristics: plain text, KB–MB each. Archives are immutable once written.
Conversation text is structured (`<user-prompt>`, `<agent-response>`,
`<nagent-*-result>`, `<system>`), so some facts are extractable without an LLM
(commands run, files touched, final responses); semantic items (decisions,
open questions) need an LLM pass.

`ASSUMPTION:` archives dominate reclaimable bytes in real roots — affects
whether splits need harvest at all (design says no: splits are regenerable
from source, harvest applies only to conversations). Verify against a real
`~/.nagent` before building.

### Garbage classification (explicit, per artifact)

- **prune (no harvest):** split dirs whose `source_sha256` no longer matches
  the source or whose source is gone; file-index entries whose file id and
  path both no longer resolve; saved-conversations index entries whose path is
  gone.
- **harvest + delete:** conversation archives, and per-file conversations
  whose target file no longer exists.
- **never touched:** live conversations, saved conversations, anything the
  ledger does not positively classify. Unknown → keep. Out-of-range behavior
  is keep-and-report, never delete.

### Output: the knowledge store

```
~/.nagent/knowledge/
  ledger.json        # what was harvested/deleted: path, sha256, date, counts, status
  facts.md           # durable facts about systems, repos, environments
  decisions.md       # decisions + the why
  tasks.md           # "## Open" and "## Done" sections
  questions.md       # open questions
  playbooks.md       # discovered processes, command sequences, tool usage
  digest.md          # bounded auto-rollup for context injection (regenerated)
  files/{file_id}.md # per-file knowledge, keyed like file-index entries
```

Every item is one markdown bullet with provenance:

```markdown
- The staging deploy requires VPN; `deploy.sh` fails silently without it.
  [from: latest-host-1234-a3f2, 2026-06-11]
```

**The user owns these files.** Editing or deleting items is maintenance, same
rule as conversations (README §3). `digest.md` regenerates from the category
files — never from raw conversations — so user edits propagate and survive.

## 3. Transform

```
inventory scan (stat + hashes, no LLM)
    -> classify: live | user-kept | prune | harvest+delete
    -> [dry-run stops here: print table + estimated harvest cost]
    -> harvest each candidate (LLM, JSON contract, prompts/harvest-conversation.md)
    -> merge items into category files (append + provenance; file-scoped items
       also mirrored to knowledge/files/{file_id}.md)
    -> regenerate digest.md (deterministic: newest-first concat, byte-capped)
    -> reclaim: delete pruned + harvested artifacts, write ledger entries
    -> report: counts per category, bytes reclaimed, failures
```

Contracts at the boundaries:

- **Harvest prompt** (`prompts/harvest-conversation.md`, user-editable, resolved
  root-first like the compact prompt) returns only JSON:
  ```json
  {"facts": [{"statement": "...", "detail": "..."}],
   "decisions": [...], "tasks_done": [...], "tasks_open": [...],
   "questions": [...], "playbooks": [{"name": "...", "steps": "..."}],
   "files": [{"path": "...", "note": "..."}]}
  ```
  Empty arrays are valid and expected (most archives contain nothing worth
  keeping — say so in the prompt). Parsed with the same fence-tolerant pattern
  as `parse_llm_summary_json`. Invalid JSON after one retry → artifact is
  **kept**, ledger records `harvest-failed`, run continues. Failures are data.
- **Deletion gate:** an artifact is deleted only when the ledger holds its
  sha256 with status `harvested` (or the run passed `--no-harvest`). The
  ledger is the proof-of-distillation; no entry, no delete.
- **Batch-first:** the harvester takes the full candidate list; one
  conversation is a batch of one.
- **Oversized conversations** (> 64KB, same threshold as everywhere else) go
  through the existing split-summarize machinery first and the harvest prompt
  consumes the summary; > 1MB is skipped with an explicit `too-large` ledger
  status. No silent truncation.

## 4. Surfacing

**To the user:**

- `nagent-gc` (self-describing executable in `bin/`, so it appears in tool
  discovery and the loop itself can run it): **dry-run by default.** Prints
  the classification table — path, size, age, class — plus the estimated
  harvest cost in tokens (`estimate_token_count` over candidate bytes).
  Nothing is mutated without `--apply`.
- `nagent-gc --apply` runs the full transform and prints the report.
- The category files are the interface: they are markdown in a fixed place.
  `nagent --status` gains one line: knowledge item counts + root size, so
  growth is visible before it is a problem.

**Into context (the "when appropriate" rule, v1 = simplest explicit rule):**

- **Global:** `build_initial_context()` includes `digest.md` verbatim when it
  exists, inside a `{knowledge}` block — same mechanics as root context. The
  digest is byte-capped at generation time (default 4KB ≈ 1k tokens), so
  inclusion cost is fixed and stated. Deleting `digest.md` turns injection
  off; that is the whole off-switch.
- **Per-file:** file-edit sessions include `knowledge/files/{file_id}.md` next
  to the existing `{file-history}`/`{file-summary}` blocks. Keyed by file id,
  so renames keep their knowledge, same as the file-index.
- **Priority inside the digest:** open tasks and open questions first, newest
  first — they restore cross-worker continuity, which is the README's pitch;
  facts and playbooks fill the remaining budget.
- v2 (only with evidence the always-on digest is too noisy): relevance
  filtering by cwd/repo overlap and recency decay. Not built until a real
  digest exceeds its budget in practice.

## 5. Costs

- Inventory + classify: O(artifacts) stats and hashes, no LLM — milliseconds.
- Harvest: one LLM call per dead conversation, input ≈ bytes/4 tokens
  (a 200KB archive ≈ 50k tokens in, ~1k out). This is the dominant cost and
  it is visible in the dry run before anyone pays it. `--max-harvest-bytes`
  caps a single run; the ledger makes the work resumable and never repaid
  (same do-it-once pattern as the commit-summary cache).
- Digest regeneration: deterministic concat + truncate, no LLM.
- Build cost: one new executable + lib + prompt + tests, ~300–500 lines.

## 6. Simplification pass (what was removed)

1. *Not do it at all?* Deletion-only GC rejected — harvest is the stated
   requirement — but it survives as `--no-harvest`.
2. *Only once?* Ledger keyed by sha256: an unchanged source is never
   re-harvested. Digest regenerates from category files, never re-reads
   conversations.
3. *Fewer times?* Only artifacts classified `harvest+delete` get an LLM pass.
   Live and saved conversations are never harvested.
4. *Approximate?* Digest is a truncated concat, not an LLM rewrite. Dedup of
   harvested items is exact-string only in v1; semantic merge deferred (open
   question below).
5. *Constrain further?* Fixed category set matching the request (facts,
   decisions, tasks, questions, playbooks, per-file notes). No free-form
   ontology, no embeddings, no retrieval index — the store is small enough to
   include whole or open in an editor.

## 7. Done criteria

- Dry run on a copy of a real `~/.nagent` classifies every artifact, with
  zero artifacts mutated.
- `--apply` on that copy: bytes reclaimed reported; every deleted path has a
  ledger entry with matching sha256; category files gain items with
  provenance; a malformed-JSON harvest (forced via mocked provider) keeps the
  artifact and records `harvest-failed`.
- A fresh `nagent` conversation's `<initial_context>` contains the digest;
  removing `digest.md` removes it; a file-edit session shows its
  `files/{file_id}.md` content.
- Disprovable claim: if dry-run cost estimates on real roots show harvest
  regularly costing >10× the tokens of the knowledge it returns, the harvest
  default flips to off and this design is revised.

## 8. Open questions

- **Scope of the store:** knowledge is global per root; file-index is per-pid.
  Cross-pid sharing is the point of harvesting — but does the ledger need
  per-pid views for `--status`?
- **Dedup/merge:** when does append-only become unreadable? Candidate trigger:
  category file > N items → offer an LLM merge pass (reusing the
  `--edit-conversation` machinery on the category file).
- **Tombstone vs delete:** `tar` dead conversations into a cold archive
  instead of deleting (reclaims namespace, keeps raw data)? Costs disk;
  default could be delete with `--archive-to PATH` opt-in.
- **Saved conversations:** never GC'd by design here — should very old saved
  copies at least surface in the dry-run report as "user-kept, aging"?
- **Digest budget:** 4KB is a guess. Measure real initial-context sizes
  (tool descriptions ≈ 2.5KB today) before fixing the number.
