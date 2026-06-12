# 0003: nagent-distill passes — merge and graduate

Status: proposed (tier 1–2 per context/data-oriented-design.md)
Sequence: after 0001 (rename, project `.nagent/bin`). `--graduate` gets
richer after 0002 (finished campaigns as a source), but does not block on
it.

## 1. Frame

The harvest design left two gaps open: knowledge category files grow
append-only until they are unreadable, and proven playbooks stay prose when
they should become tools. Both are distillation jobs, which is why the tool
carries that name after 0001.

## 2. The passes

### `nagent-distill --merge`

LLM rewrite of each knowledge category file: dedup, merge, compress,
preserving provenance. Reuses the edit-conversation machinery (archive the
file, run a file-edit session against it with a merge prompt, load the
result) — no new mechanism. Digest regenerates afterward, so user edits and
merges propagate identically.

### `nagent-distill --graduate`

Scan `playbooks.md` — and, after 0002, finished campaigns' `bin/` and
`prompts/` directories — for recurring or proven artifacts. Draft each
candidate as:

- a self-describing executable in the project's `.nagent/bin/` when it is
  a command sequence (tool discovery then injects it into every future
  conversation in the project — zero registration), or
- a `prompts/` file when it is guidance rather than commands.

Drafts are left for the user to review and commit; nothing lands silently.
Knowledge becomes a tool. A finished campaign is also a harvest source like
any dead conversation cluster: its item conversations feed the knowledge
categories.

## 3. Costs

~Half a day. LLM cost per pass is visible in the dry run, same convention
as harvest. Merge passes are user-triggered, not scheduled — when a
category file is annoying to read, run the pass.

## 4. Done criteria

- `--merge` shrinks a seeded duplicate-heavy category file while keeping
  every distinct fact and its provenance; the digest reflects the merge.
- `--graduate` emits a reviewable draft tool from a recurring playbook,
  and (after 0002) from a finished campaign's `bin/`; the draft answers
  `--description` and appears in tool discovery once the user commits it.
- Dry run prints planned actions and estimated cost; nothing mutates.

## 5. Open questions

- **Merge trigger:** stay user-triggered, or report category-file sizes in
  `nagent --status` so growth is visible before it is a problem? Start
  with the status line; it is data, not a scheduler.
- **Cross-layer knowledge promotion:** when does a project fact graduate
  to `~/.nagent/knowledge` (user-global)? MiMo distills upward on a
  schedule; deferred until the project layer proves itself.
