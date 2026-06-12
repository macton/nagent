# 0002: nagent-campaign — plans as operable artifacts

Status: proposed (tier 2 per context/data-oriented-design.md)
Sequence: after 0001 (campaigns live at the project root,
`.nagent/campaigns/`). 0003 and 0004 build on or defer to this.

## 1. Frame

**Problem.** For multi-step work, nagent's control flow is implicit model
judgment, re-made every turn: what's next, whether to decompose, whether to
delegate, whether it's done. None of that is inspectable, none of it is
durable, and all of it degrades as the conversation grows. A task tree
inside a checkpoint file would be an artifact, but not an *operable* one —
no code can advance it.

**Goal.** Make the plan a first-class artifact and the driver a
deterministic transform over it. The model's non-determinism is not removed;
it is **relocated and bounded**: selection, blocking, sequencing, and
completion mechanics become code reading a tree; the model is scoped to
narrow judgments — decompose *this* item, execute *this* item, judge *this*
condition — each with a curated context. The determinism boundary is exactly
the schema of the campaign files.

**Why this fits.** It is the same position the README argues (visible
transformations over opaque orchestration) applied to the one place nagent
is still opaque: the model's own sense of what to do next. It is also the
data-oriented answer to MiMo-Code's Dynamic Workflow — plan-as-artifact
instead of plan-as-program.

**What it absorbs.** Two mechanisms that would otherwise be standalone:
goal verification → completion conditions (two-tier: executable `test:`
checks preferred, bounded `judge:` calls only where prose is unavoidable;
a premature "done" is gated back to `todo` by the driver, not by
exhortation; a one-item campaign covers the non-campaign need), and the
task tree → `index.yaml` (0004's checkpoint schema carries no tree).
Decomposition is the first line of context control — bounded items produce
bounded conversations; 0004's checkpoint/rebuild is the safety net for what
decomposition cannot bound.

**Limit / plan B.** If the driver starts growing scheduler features
(priorities, retries, daemons), stop: the design has failed its own test.
Plan B is to keep only the artifact layout (a hand-maintained plan directory
the model is directed to read and update via the existing tags) and delete
the driver.

## 2. The data

### Layout

```
.nagent/campaigns/{slug}/
  index.yaml              # the spine: tree of item ids, statuses, edges
  conversations/          # campaign-level conversations: goal, status, ...
  questions.md            # open questions needing a human answer
  bin/                    # campaign-scoped tools (discovery path for items)
  prompts/                # campaign-scoped prompt overrides
  tests/                  # executable completion checks
  items/{item-id}/
    item.yaml             # per-item detail
    conversation          # the item's conversation (editable, continuable)
    proposal.yaml         # pending decomposition proposal (driver-managed)
```

### index.yaml — the spine

The spine stays small on purpose: tree shape, status, edges. Everything else
lives in the item directories.

```yaml
name: Migrate config format
description: One paragraph. What done means at campaign level.
status: active          # active | paused | done
completion:
  - test: tests/all-loaders-pass.sh     # executable — preferred
  - judge: "README documents the new format"   # judged — when prose is unavoidable
references:
  - src/config/loader.py
  - https://example.com/spec
review:
  auto_confirm_max_items: 5    # proposals adding more than this wait for review
  auto_confirm_max_depth: 2    # ...or deepening the tree beyond this
dispatch:
  max_per_update: 4            # informed-cost knob, not a plan-size cap
items:
  - id: 0001-inventory-callsites
    status: done
  - id: 0002-new-loader
    status: in-progress
    items:
      - id: 0002a-parser
        status: todo
      - id: 0002b-tests
        status: todo
        blocked_by: [0002a-parser]
  - id: 0003-migrate-docs
    status: question
```

Statuses: `todo`, `proposed`, `in-progress`, `blocked` (implied by
`blocked_by`, listed for hand-marking), `question`, `review`, `done`,
`failed`. Out-of-range behavior is explicit: a failed worker sets `failed`
and raises a question; nothing auto-retries.

### item.yaml — the detail

```yaml
id: 0002a-parser
description: Implement the new parser; accept old format behind a flag.
completion:
  - test: ../../tests/parser-roundtrip.sh
references:
  - src/config/loader.py
notes: |
  Free-form. The user and the driver both write here.
result: |
  Written by the driver from the worker's structured response.
```

### Hand-editability is a requirement, not a hope

Both YAML files must remain straightforward, hand-editable documents — if
the schema needs a manual, the "interface is the editor" property is lost.
This is enforced in two places: the schema above is the whole schema
(additions need a reason recorded in this file), and the campaign-mode
initial context directs the model explicitly: *index.yaml and item.yaml are
hand-edited by the user; keep entries terse, add no fields, and never
reformat what you did not change.*

### Conversations

- Campaign-level conversations live in `conversations/` (e.g. `goal`,
  `status`) — ordinary nagent conversations, continuable by name.
- Each item's `conversation` is the per-item worker: artifact-local memory
  where the artifact is a unit of work. Editable and continuable like any
  conversation; re-dispatching an item continues it with its accumulated
  context rather than cold-starting.

## 3. Invariants

These four are load-bearing. Changes that violate them are redesigns, not
patches.

1. **One pass, then exit.** `nagent-campaign update` performs a single
   bounded pass (phases below) and exits. No resident process, no watch
   mode, no priority queue. Looping is the user's composition (`watch`,
   cron, or running it again).
2. **One writer for the tree.** Workers never edit `index.yaml` or another
   item's files. Workers return structured results (final response and
   files inside their own item dir); the driver — single-threaded,
   deterministic code — merges them into the tree. LLMs produce data; code
   mutates artifacts. (Same contract as nagent-distill's harvest.)
3. **Plan changes pass a review gate, not a cap.** Large projects must not
   be inhibited; the user must be able to make an informed choice.
   Decomposition results land as *proposals* (`proposal.yaml`,
   status `proposed`), never directly in the tree. Proposals within the
   `review:` thresholds auto-confirm; anything larger — and the initial
   decomposition of a new campaign, always — waits. `update` reports the
   scope of pending proposals (items added, depth change, estimated dispatch
   cost in tokens) and does not dispatch into unconfirmed subtrees. The user
   reviews with `nagent-campaign review`, edits the proposal file directly
   if they want changes, and accepts with `confirm`.
4. **The schema is the whole schema.** Spine in `index.yaml`, detail in
   `items/{id}/item.yaml`, nothing else. Per-item files also keep git merges
   sane when collaborators touch different items.

## 4. The driver: one update pass

`nagent-campaign update {slug}` runs these phases in order, then exits:

1. **Merge** — collect structured results from item dirs written by workers
   since the last pass; update item statuses and `result:` fields. Pure
   code, no LLM.
2. **Check** — for items claiming done: run executable `test:` conditions
   (deterministic); call a bounded judge for `judge:` conditions. Pass →
   `done`. Fail → back to `todo` with the failure recorded in `notes:`.
3. **Propose** — for items marked for decomposition (by a worker's result
   or by the user), run decomposition workers; results land as
   `proposal.yaml`, status `proposed`.
4. **Review gate** — auto-confirm proposals within thresholds; report the
   scope of anything pending and stop short of it.
5. **Dispatch** — take unblocked `todo` items up to `max_per_update`; for
   each, author a briefing (campaign description + item.yaml + references +
   relevant questions answered) and run the item's conversation as a
   delegated sub-conversation. Campaign `bin/` and `prompts/` join the
   discovery/resolution path for these workers.
6. **Report** — print campaign status: tree summary, questions awaiting
   answers, pending proposals with scope, tokens spent this pass (existing
   TokenStats rollup).

`--dry-run` prints phases 1–5 as a plan with cost estimates and mutates
nothing — same convention as nagent-distill.

### Worker contract

An item worker receives an authored briefing and must end with a structured
result (the harvest-JSON pattern): claimed status, result summary, new open
questions, and optionally a decomposition proposal when the item judges
itself too big. The driver validates and merges. A worker that returns
garbage marks the item `failed` with the parse error in `notes:` — failure
as data.

### Open questions as first-class blockers

A worker that needs a human decision returns a question; the driver appends
it to `questions.md` (with the item id) and sets the item to `question`.
The user answers by editing the file; the next update routes the answer into
the item's briefing and unblocks it. The async human interface is a text
file, which is the point.

## 5. Initial context

Tool discovery alone does not change behavior; capabilities get used when
the context directs them (the conversations-as-data block exists for the
same reason). Three surfaces, plus the wiring:

**Every project conversation** gets a short "Campaigns" block:

- When the request is large, multi-step, or will outlive this conversation,
  create a campaign (`nagent-campaign new`) and decompose into it instead
  of holding the plan in your head — the plan must survive you.
- Drive campaigns through the CLI via <nagent-shell> (`add`, `status`,
  `update --dry-run` first when cost is unclear). Do not edit a campaign's
  index.yaml or item files directly from a main conversation.
- Asked about ongoing work? Check `nagent-campaign status` before
  answering from memory.

Plus ambient visibility, same pattern as the knowledge digest: when the
project has active campaigns, inject a one-line-per-campaign status block
(name, items todo/in-progress/done, open questions, pending proposals) into
initial context. Stale plans get surfaced instead of forgotten; the block
is regenerated from index.yaml — data, not narrative.

**Dispatched item workers** run in campaign-item mode (a `--campaign-item`
flag analogous to `--file-edit`) and their context carries the worker
contract:

- You are scoped to this item; the briefing is your task. Work only inside
  its boundaries.
- End with the structured result (claimed status, summary, new questions,
  optional decomposition proposal). Never edit index.yaml, item.yaml, or
  another item's files — the driver merges; you produce data.
- If the item is too big, propose decomposition rather than grinding; if
  you need a human decision, raise a question rather than guessing.
- Campaign `bin/` and `prompts/` are on your discovery path; campaign
  yaml files are hand-edited by the user — keep entries terse, add no
  fields, never reformat what you did not change.

**Campaign-level conversations** (`conversations/goal`, `status`) get the
campaign description and a pointer to the spine, nothing more — they are
ordinary conversations whose subject happens to be the campaign.

## 6. CLI surface

```
nagent-campaign new "name" [--description TEXT|-]   # skeleton + index.yaml
nagent-campaign list
nagent-campaign status {slug}                        # tree, questions, pending proposals
nagent-campaign add {slug} "description" [--parent ID] [--blocked-by ID]
nagent-campaign review {slug}                        # show pending proposals + scope
nagent-campaign confirm {slug} [--item ID]           # accept proposal(s)
nagent-campaign update {slug} [--dry-run] [--max-dispatch N]
```

No `edit` command: editing is the editor. `add` exists because appending a
valid tree node is the one mutation worth automating. All tools are
self-describing (`--description`) and join tool discovery, so conversations
can drive campaigns too.

## 7. Costs

- Driver phases 1, 4, 6 are pure code. LLM spend: decomposition workers
  (phase 3), judged conditions (phase 2), and dispatched item workers
  (phase 5) — all bounded per pass and printed in the report.
- Implementation: `bin/nagent-campaign` + `nagent_campaign_lib.py` +
  `prompts/campaign-decompose.md` / `campaign-item.md` + tests. Roughly the
  size of the distill feature (~500–700 lines). The schema work is the real
  work; the driver is deliberately dumb.

## 8. Simplification pass (what was removed)

- No scheduler state: no priorities, no retries, no daemon (invariant 1).
- No item editor UI: files + one `add` command.
- No hard plan-size caps: replaced by the review gate (invariant 3) — caps
  would inhibit large projects; review preserves informed choice.
- No cross-campaign coordination, no nested campaigns: a campaign tree is
  the nesting.
- No new memory system: item conversations are ordinary conversations;
  finished campaigns are harvested by nagent-distill like any dead
  conversation cluster, and campaign `bin/`/`prompts/` are graduation
  candidates.

## 9. Done criteria

- `new` → `add` → `update --dry-run` → `update` runs a two-item campaign to
  `done` with mocked workers; every state transition visible as a file diff.
- A decomposition exceeding the review thresholds parks as `proposal.yaml`,
  is reported with scope, is hand-edited, confirmed, and dispatched.
- A worker question blocks its item, surfaces in `status`, and an edit to
  `questions.md` unblocks it on the next update.
- An executable completion condition gates a false "done" claim back to
  `todo`.
- Interrupting `update` mid-pass loses nothing: re-running converges
  (merge is idempotent; dispatch re-runs only still-`todo` items).
- Hand-editing `index.yaml` (reorder, block, delete an item) is honored by
  the next update without complaint.
- Context surfaces (§5): a project conversation's initial context contains
  the Campaigns block, and the ambient status block appears when (and only
  when) the project has an active campaign; a `--campaign-item` worker's
  context contains the worker contract and its briefing; ordering tests
  cover the new blocks like the existing context-layer tests.

## 10. Open questions

- **Dispatch concurrency:** serial dispatch first (simplest, debuggable) or
  bounded parallel from day one? Leaning serial v1; the loop already proves
  sub-conversations compose.
- **Campaign bin/prompts scope:** join the discovery path only for that
  campaign's item workers (leaning yes) or for every conversation in the
  project while the campaign is active?
- **Question answer routing:** answers inline in `questions.md` vs per-item
  `notes:` — pick whichever survives real use; both are text edits.
- **Status reports:** should `update` also append a one-paragraph status to
  `conversations/status` (LLM call) or is the deterministic report enough?
  Start deterministic; add narrative only on demonstrated need.
- **Stale workers:** an item dispatched but never merged (killed worker) —
  re-dispatch policy after N updates, or surface as a question?
