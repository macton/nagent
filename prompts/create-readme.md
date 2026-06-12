# Prep

Read bin/nagent.
Run --description on every executable in bin/ (this includes nagent-distill
and nagent-campaign).
Read the helper modules under bin/helpers/ — including nagent_tags.py and
nagent_distill_lib.py — and the tests when more detail is needed.
Read context.yaml and context/ at the repository root.

Ground every claim in the implementation that actually exists. Do not rely
only on this prompt or on an existing README. Do not invent features.

# Create the nagent README

Write `README.md` for the `nagent` project.

The README is not marketing material and not API documentation. It is a
**progressive teaching document**: each part earns the next. A reader who
stops halfway should still leave with something true and useful; a reader who
finishes should be able to build their own version and explain why it is
shaped this way.

---

# Core Thesis

The README communicates one central idea:

**The agent is not the thing. The data is the thing.**

nagent is a small reference example of a data-oriented approach to AI
workflows. Do not describe it as an architecture or as a framework.

The introduction must also call out this claim:

**Don't edit the output artifacts. Edit the prompt.**

Meaning: when a generator produces output you do not like, fix the generator
or the inputs to that generator. Do not merely patch the generated output. In
nagent, the conversation is one of those inputs. To improve generation, that
input must be saveable, maintainable, organizable, and editable.

LLMs are temporary. Processes are temporary. Sub-conversations are temporary.
Context windows are temporary. The durable part of the system is explicit
data: conversations, per-file conversations, install/project/root context files,
repository history summaries, historical coupling tables, artifact
neighborhoods, file summaries, split indexes, patch artifacts, and the
harvested knowledge store. The loop exists to transform those artifacts.

A text file, an LLM, structured tags, and a loop are the implementation of
this idea, not the idea itself.

---

# The Teaching Arc

This is the organizing principle of the entire README. The numbered sections
must follow this progression, in this order. Each part opens by stating the
claim it teaches and closes having earned it — the reader should be able to
say what they now know that they did not know one part earlier.

**Part I — Build it.** *Teach: how to implement an agent-like interface.*
Strip the mystery first. An "agent-like" terminal interface is a small number
of visible mechanics: a text-in/text-out primitive, an output format the model
is taught, a parser that enforces it, action handlers, and a loop that appends
everything back into one growing document. By the end of Part I the reader can
sketch the whole implementation on a whiteboard.

**Part II — Rename it.** *Teach: 'agent' is not the right metaphor.*
Only after the mechanics are on the table, make the argument: nothing in
Part I has continuity, intent, or memory of its own. "Agent" imports all
three and delivers none. What actually exists is a conversation document and
a disposable transformation loop over it. Workers are temporary; artifacts
are durable. Rename the parts for what they are.

**Part III — Own the data.** *Teach: conversation data must be managed and
owned by the user — at the right scope.* The conversation is not chat
history trapped in a session; it is working state in a file the user owns.
Editing it is maintenance, not corruption. Cover both explicit maintenance
commands and implicit file editing. Then teach that ownership has scopes:
memory that belongs to a project was trapped in a personal dotdir, therefore
the root moves into the repository — what a project learned travels with the
project, and personal rules (`~/.nagent`) still apply everywhere. The
prompt-side inputs the user owns arrive in the same layers: install, user,
project, root — each one a directory of plain files, each overridable by the
more specific one.

**Part IV — Exploit the files.** *Teach: state as file artifacts creates real
opportunities that are otherwise difficult.* This is the payoff argument.
Because everything is a file, capabilities fall out that opaque session state
cannot offer: transforming git history into editing context; distilling dead
conversations into a durable knowledge store that feeds back into every
future conversation; diffing, branching, versioning, and scripting
conversations; replaying and auditing what happened. And because the root is
project-local, the artifacts compound across people, not just across
sessions: commit `.nagent/` and a collaborator's first conversation already
knows what yours learned — knowledge, per-file memory, and graduated tools
in `.nagent/bin` arrive with `git clone`, reviewable in the same pull
requests as the code they describe. Show concrete problems that become easy.

**Part V — Name the principles.** *Teach: data-oriented principles.* The
reader has now used the principles without naming them. Name them: the data
is more important than the code operating on it; behavior is transformation
over explicit state; avoid hidden mutable state; separate durable artifacts
from temporary execution; optimize the shape, availability, and maintenance
of the data. Connect each principle back to a mechanism the reader has
already seen.

**Part VI — The data structures that fall out.** Four applied chapters, each
a worked example of the principles:

- *Artifact neighborhoods* — a file lives among related artifacts: its
  historical coupling table, co-edited files, summaries, local conversation,
  per-file knowledge notes, split indexes. Teach the approach and the value:
  neighborhoods are computed from history and presented as inspection
  guidance, never as edit mandates.
- *Managing context and large files* — context windows are a budget. Teach
  the explicit responses: inline-read thresholds, split/index/patch for
  large files, summaries, conversation compaction, the bounded knowledge
  digest, and sub-conversations as context isolation (the parent keeps
  coordination; the child keeps the noise; the result comes back distilled).
- *Per-file write conversations* — every file gets its own persistent
  conversation, keyed by stable file id, carrying its own initial context
  (history, summaries, knowledge notes) and its own bounded write authority.
  Teach why uniqueness matters: artifact-local memory accumulates where the
  work recurs, the main conversation stays small, and write boundaries
  attach to the artifact rather than to a session.
- *Campaigns: plans as operable artifacts* — the model's sense of what to do
  next is the last hidden state; the campaign makes the plan a hand-editable
  tree the user owns and the driver deterministic code that advances it.
  Teach the relocation of non-determinism into bounded judgments, the review
  gate as informed choice instead of caps, and completion conditions instead
  of completion claims.

**Part VII — Compare to frameworks.** *Teach: what this approach trades
against framework-style systems.* Not "frameworks bad." The point is data
ownership and visibility: inputs to the system should not be trapped inside
an opaque layer that hides, rewrites, stores, or modifies the data being
used, beyond the unavoidable transformations LLM providers already perform.

Close the README with the **Build your own** recipe and the practical
sections (setup, providers, common commands, tests).

---

# Terminology Rules

- Prefer **conversation** for a running nagent loop and its durable state.
- Prefer **sub-conversation** for delegated child work.
- Do not loosely call nagent conversations "agents" or delegated work
  "sub-agents."
- Keep **nagent** unchanged; it is the system name; it means **not-an-agent**.
- The thesis line and Part II/Part VII comparisons may use the word "agent"
  when explaining the confusing term rather than naming the approach.
- The delegation protocol tag is `<nagent-conversation>`, not `<nagent-agent>`.
- Prefer "historical co-edit rate" or "changed with this file" over ambiguous
  phrases such as "likelihood of same-commit edit."

---

# Voice

Write in the voice of **Mike Acton**: direct, engineer-to-engineer, skeptical
of hype and mystification, data-oriented first.

- Be direct and straightforward. Call things for what they are — and for what
  they are not. Name the gap between marketing language and actual behavior.
- Stay respectful. Directness is not snideness. Blunt negations of hype are
  fine — "not mystical", "do not pretend they fit", "they are not the idea."
  Avoid mocking the reader, sneering at people who use other tools, dismissive
  names for their work, or insults dressed as personality.
- Problem → therefore → design decision. Do not bury the reasoning.
- The data is more important than the code operating on it. Behavior is
  transformation over explicit state.
- Short, punchy sentences when they clarify. Longer when the mechanism needs
  room.
- Call out hidden state vs explicit artifacts; disposable workers vs durable
  files.
- Do not hedge endlessly. If something is a convention and not a sandbox, say
  so.
- **Build your own:** notes should sound like advice from someone who has
  shipped systems, not documentation boilerplate.

The central thesis line must appear prominently in the introduction.

---

# Introduction Examples

After the core thesis and before Part I, include a short **What It Looks
Like** block with two or three examples of non-trivial tasks.

- Use only the `nagent` command in these examples. Do not name helper CLIs.
- Choose tasks that imply multiple turns: reading files, running shell
  commands, delegating to sub-conversations, iterating until done, or pausing
  to explain a plan before editing.
- Frame expectations: one terminal prompt can trigger a long internal loop
  while the conversation file accumulates the work.
- Do not oversell autonomy. nagent follows the loop and obeys normal OS and
  filesystem permissions.

---

# Audience

Programmers who know basic Python and command-line tools, are curious how
conversation loops actually work, appreciate explicit state and inspectable
systems, may want to build a small tool without a framework, and understand
why durable artifacts can matter more than runtime behavior. Do not assume
the reader knows nagent's internals.

---

# Teaching Strategy

Within the arc, teach each mechanism through a reduction:

```text
Problem -> Observation -> Design decision -> Implementation -> Transferable pattern
```

Use these reductions where they belong in the arc:

- LLMs forget. Therefore: put memory in files. (Parts I, III)
- Free-form output is hard to execute. Therefore: teach the model a visible
  protocol and enforce it with a small parser. (Part I)
- One conversation grows too large. Therefore: attach memory to artifacts.
  (Parts IV, VI)
- Repeated work accumulates around individual files. Therefore: give each
  file its own persistent conversation. (Part VI)
- Repositories contain historical knowledge. Therefore: transform git history
  into editing context. (Parts IV, VI)
- Exploration creates noise. Therefore: use disposable sub-conversations.
  (Part VI)
- Large files exceed context windows. Therefore: create explicit
  split/index/patch artifacts. (Part VI)
- Memory becomes stale. Therefore: allow conversations to be edited,
  summarized, branched, compacted, and rewritten. (Part III)
- Project memory trapped in a personal dotdir cannot travel or be shared.
  Therefore: default the root into the repository, and keep personal rules
  in a user layer that applies everywhere. (Parts III, IV)
- A multi-step plan lives in the model's head: re-decided every turn,
  invisible, degrading as context grows. Therefore: make the plan an
  operable artifact and the driver deterministic code over it. (Part VI)
- A model will claim "done"; a claim is not a check. Therefore: gate
  completion on conditions — executable tests preferred, judged prose only
  when unavoidable. (Part VI)
- Dead conversations accumulate, and deleting them loses what was learned.
  Therefore: harvest knowledge into editable category files, gate deletion on
  the harvest, and inject a bounded digest back into context. (Part IV)

---

# Section Requirements

Organize the main body as numbered sections grouped under the arc's parts.
Each major numbered section must include:

1. **Idea** — the design idea, stated as the claim it teaches.
2. **Implementation** — where and how nagent implements it.
3. **Example** — a command, tag, table, or pseudocode block.
4. **Build your own:** — the reusable pattern.

## Part I sections

**Text in, text out.** The smallest useful primitive: file in, text out.
`bin/nagent-llm-text`, `generate_text_with_usage()` in
`bin/helpers/nagent_llm.py`. Provider support covers `openai`, `anthropic`,
`google`, `cursor`, and `claude-code` (which runs through the locally
installed Claude Code via the Claude Agent SDK and uses Claude Code's own
login — no API key in the environment; model `default` means Claude Code's
configured model). `bin/nagent-llm-upload` is the sibling for files that need
upload APIs. Everything else is orchestration around this primitive.

```bash
echo "What is 2+2?" > question.txt
nagent-llm-text --file question.txt
```

**Teach the model an output format.** The startup prompt lists the only tags
the model may emit, with per-tag guidance inline; the tag list and rules live
inside `<initial_context>`, so refreshed context carries the current protocol
with it. The context states the protocol rules explicitly: tag bodies are raw
text (no escaping; the first matching close tag ends a body), nothing outside
tags, and — the loop contract — action results come back appended as
`<nagent-*-result>` blocks before the model is called again, so it must never
fabricate results, and an error result is data that should change the
approach. The context is ordered stable-to-volatile (role and protocol first,
instance facts and environment last) so request prefixes stay byte-identical
across conversations of the same mode. Tokenization lives in the shared
parser `bin/helpers/nagent_tags.py`; `parse_response()` validates tag shapes
and is strict — recognized tags and whitespace, nothing else. Include the tag
table:

- `<nagent-response>...</nagent-response>`
- `<nagent-read path="..."/>`
- `<nagent-file-read path="..."/>`
- `<nagent-file-patch index="..."/>`
- `<nagent-write path="...">...</nagent-write>`
- `<nagent-shell>...</nagent-shell>`
- `<nagent-next>...</nagent-next>`
- `<nagent-conversation>...</nagent-conversation>`

Explain result wrappers appended by handlers, and that they are conversation
data, not hidden return values.

**The loop.** Append/call/parse/act/append/repeat:

```text
append user prompt to conversation file
loop:
    response = send conversation file to LLM
    append response to conversation file
    if response contains action tags:
        run those actions
        append results to conversation file
        continue loop
    if response contains <nagent-response>:
        print it and stop
```

Code path: `main()` → `run_agent_loop()` → `call_llm()` → `parse_response()`
→ `process_tags()`. Malformed output triggers visible correction turns (up to
`MAX_FORMAT_RETRIES`); provider errors append too. Failures become data, not
hidden control flow. Reads of unreadable files come back as error result tags
for the same reason. Token/status accounting at a high level (`TokenStats`,
recursive rollup from children; cached prompt tokens fold back into input
counts). The loop passes stable prefix boundaries to `nagent-llm-text`
(`--cache-prefix-chars`) so providers that cache on block boundaries reuse
the shared context each turn. Controlled writes in main mode: structured
writes go to temp directories only; explain that this is convention, not a
sandbox, and that shell runs with the user's permissions.

**Tool discovery.** No central registry. Every executable in bin/ describes
itself via `--description`; the startup prompt is assembled from that output
plus context files and environment. Even tool capability is surfaced as data.

## Part II section

**You did not build an agent.** Durable work, disposable workers:

```text
temporary worker -> durable artifacts -> next temporary worker
```

The Python process is a worker. The files are the system. "Agent" suggests
continuity, intent, and memory that the loop does not have; the conversation
file is where all three actually live. Include the hidden state vs explicit
artifact table.

## Part III section

**Conversations are editable state — and the user owns them.** The
conversation file is working state, tool transcript, correction channel,
continuation point, and mutable artifact. Use this line or equivalent:

**The conversation does not own its memory. The user does.**

Explicit maintenance: `--save-conversation` (with summarized index),
`--load-conversation`, `--branch-conversation`, `--summarize`,
`--edit-conversation`, `--compact` (rewrites the conversation against the
user-editable compaction prompt). Implicit maintenance: conversations are
ordinary files — open, trim, rewrite, diff, copy, version, script.

The root is project-local: inside a git repository the default root is
`{toplevel}/.nagent` — conversations, knowledge, and per-file memory live
with the repo and can be committed and shared (with the review-first secrets
caveat); `--root` overrides; outside a repo the root is `~/.nagent`; a newly
created root ships a `.gitignore` covering `splits/` only.

User-owned prompt-side inputs come in four layers, least personal first,
each a `context.yaml` (recursive expansion) or `context.md`: install (the
nagent folder — this repository ships one pointing at
`context/data-oriented-design.md`), user (`~/.nagent`, read in every run),
project (the git toplevel), and root (the project's `.nagent`). A layer
whose directory equals an earlier layer's is included once. The prompts
(compaction, harvest) resolve project root → user → install; tools are
discovered from install `bin/` + `~/.nagent/bin/` + project `.nagent/bin/`
with the most specific layer shadowing by basename; config resolves CLI →
`NAGENT_CONFIG` → project `.nagent/config.json` → `~/.nagent/config.json`.

## Part IV sections

**Repository history as data.** History is not retrieval; it is explicit
transformation of historical artifacts into working input: file history,
commit summaries (cached in the conversation so unchanged history is never
re-paid), file summaries, people who edited the file. Diagram:

```text
git history -> commit/file summaries -> file-edit initial context -> better edit decisions
```

Historical context is a hint, not a command.

**Harvest knowledge; reclaim space.** `nagent-distill` classifies artifacts
(live / user-kept / prune / harvest+delete; unknown is kept, never deleted),
distills dead conversations through a user-editable harvest prompt into
category files under the root's `knowledge/` — facts, decisions, tasks
(open/done), questions, playbooks, per-file notes — every item carrying
provenance. Deletion is gated on a sha256 ledger entry proving the harvest
happened. A bounded `digest.md` regenerates from the category files (user
edits propagate; deleting it turns injection off) and is injected into every
conversation's initial context; per-file notes join file-edit context. Dry
run by default with an estimated harvest cost in tokens before anyone pays
it. This section is the strongest "files create opportunities" example:
session state that would have been discarded becomes compounding,
user-editable knowledge.

**Everything else files buy you.** Brief, concrete: diff two conversation
states; branch a conversation before a risky direction; script maintenance;
audit exactly what the model saw; replay a prompt against a different
provider by pointing the same file at it.

**Project memory is team memory.** The project-local root turns every
opportunity above from personal to shared: commit `.nagent/` and knowledge,
per-file conversations, and graduated tools in `.nagent/bin` arrive with
`git clone`; a teammate's first conversation starts from what the project
already learned, and changes to the project's memory are reviewable in the
same pull request as the code. State the caveat plainly: conversations
contain tool output — review before committing, like any other file. Note
the choice stays with the user: the scaffolded `.gitignore` excludes only
regenerable `splits/`; everything else is deliberate.

## Part V section

**Data-oriented principles.** Name the principles and tie each to a mechanism
already shown. Include the transformation model diagram:

```text
repository history + root context + conversation + artifact-local memory
  + artifact summary + historical coupling + harvested knowledge + user request
    -> LLM transformation -> updated artifacts
```

Emphasize: state explicit, inspectable, editable; not hidden in process
memory; transformations visible; artifacts outlive processes; workers
disposable; artifacts durable.

## Part VI sections

**Artifact neighborhoods.** A file lives in a neighborhood of related
artifacts. `coedited_file_rows()` computes co-edit counts and rates from the
same commits; `format_file_history()` presents the table with guidance.
Include the neighborhood diagram and an example table:

| file | commits together | historical co-edit rate |
| --- | ---: | --- |
| src/foo_test.py | 7 | high (70%) |
| src/foo.h | 5 | medium (50%) |

Use this phrase or equivalent: **High co-edit files are candidates for
inspection, not automatic edit targets.** Per-file knowledge notes
(`knowledge/files/{file_id}.md`) are part of the neighborhood.

**Managing context and large files.** Context windows are a budget; respond
explicitly: inline reads cap at 64KB; `<nagent-file-read>` auto-splits via
language-aware natural splitters into segment files plus `index.json` (source
path, hash, line ranges); edits target segments; `nagent-file-patch`
validates the source hash, merges, writes a unified diff patch, refreshes the
index. Summaries via `nagent-file-summarize` (split-summarize over 64KB).
Conversation-side: `--compact`, the bounded knowledge digest, and disposable
sub-conversations as context isolation — parent keeps coordination, child
keeps noisy exploration, parent receives a distilled result. Delegation is
context management before it is parallelism.

The initial context directs the model to exploit conversations as data, not
just spawn them: reuse a *named worker* (`conversation-file="name"` continues
that conversation with its accumulated context — a specialist that gets
cheaper to call), resume a saved conversation (`conversation-name`), *author*
a worker's context by writing a curated briefing under /tmp and spawning a
child on it, and hand off to a fresh sub-conversation with a distilled brief
when its own conversation has become mostly stale tool output — the safe
self-compaction. It is also told the conversation persists and the user may
edit it between runs: the current file is the source of truth. Diagram:

```text
large source file -> split index + segment files -> bounded edits -> patch artifact -> updated source file
```

**Per-file write conversations.** Each edited file gets its own persistent
conversation, found via stable file ids (device:inode — renames keep their
memory) in `conversations/file-index-{pid}.json`. Its initial context carries
the file's history block, summary, and knowledge notes. Write authority in a
file-edit session is bounded to the target file and its split segments;
project files are not writable from the main conversation. Show the example
commands and a small `by_file_id` JSON sample. The value: memory accumulates
where work recurs; the main conversation stays small; the write boundary is a
property of the artifact, not of a session.

**Campaigns: plans as operable artifacts.** Open with the claim: after
everything else became a file, the model's sense of what to do next is the
last hidden state — re-decided every turn, invisible, degrading as context
grows. A campaign makes the plan a first-class artifact and the driver a
deterministic transform over it. Be precise about what is extracted: the
model's non-determinism is not removed, it is *relocated and bounded* —
selection, blocking, sequencing, and completion mechanics become code
reading a tree; the model is scoped to narrow judgments (decompose this
item, execute this item, judge this condition), each with a curated
context. The determinism boundary is exactly the schema.

Implementation to cover: `{root}/campaigns/{slug}/` with a hand-editable
`index.yaml` spine (tree of item ids, statuses, `blocked_by` edges, review
thresholds, dispatch budget) and per-item `items/{id}/item.yaml` detail plus
a per-item conversation — artifact-local memory where the artifact is a unit
of work, continuable across dispatches. The one-pass driver
(`nagent-campaign update`): merge worker results, route answered questions,
check completion conditions, gate decomposition proposals, dispatch
unblocked todo leaves, then exit — no resident process; looping is the
user's composition. Teach the four invariants as design decisions:

- One pass, then exit — no scheduler growing inside the tool.
- One writer for the tree — workers return structured results
  (`result.json` in their own item dir); only the driver mutates the plan.
  LLMs produce data; code mutates artifacts.
- Plan changes pass a *review gate*, not a cap — large projects must not be
  inhibited; the user makes an informed choice. Proposals park with their
  scope (items added, depth, estimated cost); within-threshold changes
  auto-confirm; a new campaign's initial decomposition always waits. The
  user edits the proposal file directly and confirms.
- The schema is the whole schema — if the YAML needs a manual, the
  "interface is the editor" property is lost.

Completion is conditions, not claims: executable `test:` scripts in the
campaign's `tests/` (deterministic, preferred) and `judge:` prose only when
unavoidable; a premature "done" bounces back to `todo` by mechanism, not
exhortation. Open questions are first-class blockers: workers raise them,
they land in `questions.md`, the user answers by editing the file, the next
update routes the answer into the item's briefing. The initial context
directs the model to create campaigns for work that outlives a conversation,
injects an ambient status block for active campaigns, and gives dispatched
workers the contract in a dedicated `--campaign-item` mode; campaign-scoped
`bin/` joins tool discovery for that campaign's workers.

Include an `index.yaml` example (a small tree with one blocked item) and a
command sequence: `new` → `add` → `update --dry-run` → `update` → `review`
→ `confirm`. End **Build your own:** with the transferable pattern —
plan-as-artifact plus a dumb driver beats plan-as-program; if your
orchestrator needs a runtime, your plan has stopped being data.

## Part VII section

**How this differs from frameworks.** Do not market against frameworks. Use
a framework when it buys something concrete. The argument is ownership and
visibility of the inputs. Include both tables:

| Framework-style system | nagent |
| --- | --- |
| hidden or managed state | explicit files |
| session memory | artifact memory |
| object/service graph | data artifacts |
| central tool registry | executable descriptions |
| long-lived agent abstraction | disposable workers |
| opaque orchestration | visible transformations |

| Common term | nagent framing |
| --- | --- |
| memory | editable artifact |
| retrieval | preserved work / historical context |
| agent | temporary transformation function |
| context | explicit input data |

## Closing sections

**Build your own.** A compact recipe in arc order: implement
`generate_text(file) -> str`; keep a growing conversation document; generate
initial context that states the contract; define an output format and a small
strict parser; write action handlers that append results back into state;
loop after actions; retry malformed output with visible corrections; make the
conversation saveable/loadable/editable/compactable; transform repository
history into artifact context; harvest dead conversations into a knowledge
store and inject a bounded digest; add per-artifact memory with stable ids
and bounded write authority; add split/index/patch for large files; add child
loops for delegation. Include the code reading order and the helper-module
list (nagent_llm.py, nagent_cli.py, nagent_tags.py, nagent_file_edit_lib.py,
nagent_file_split_lib.py, nagent_file_patch_lib.py,
nagent_file_summarize_lib.py, nagent_distill_lib.py). Tests are executable notes.

**Setup / Common Commands / Tests.** Ground in the current implementation:
pip install, PATH, the project-local root default
(`{git-toplevel}/.nagent`, `--root` override, `~/.nagent` outside repos,
scaffolded `.gitignore`), config resolution (CLI → `NAGENT_CONFIG` →
project `.nagent/config.json` → `~/.nagent/config.json`), the provider
table including `claude-code` (default model `default`, no credential env
var — uses the local Claude Code login), the common command list including
`--status`, `--list-models`, `--list-conversations`,
`--branch-conversation`, `--compact`, `nagent-distill`
dry-run/apply/no-harvest, the `nagent-campaign` subcommands
(new/add/status/review/confirm/update --dry-run), and the unittest
invocation.


---

# Required Concept Checklist

Verify the README explicitly explains all of these:

- [ ] durable explicit state
- [ ] editable conversations; direct conversation-file editing
- [ ] conversation maintenance commands incl. branch and compact
- [ ] project-local root default; committed/shareable project memory
- [ ] context in four layers (install/user/project/root) with dedup;
      layered prompts, tools (`.nagent/bin` shadowing), and config
- [ ] artifact-local memory; per-file conversations; stable file ids
- [ ] bounded write authority per mode (temp-only vs per-file)
- [ ] repository history as data; commit summaries; file summaries; editors
- [ ] historical coupling; co-edited files; artifact neighborhoods
- [ ] knowledge harvest: gc classification, ledger gate, category files,
      provenance, digest injection, per-file notes, dry-run cost estimate
- [ ] large-file split/index/patch; natural splitters; hash validation
- [ ] disposable workers; sub-conversation isolation as context management
- [ ] visible protocol; shared tag parser; parser retries as visible state
- [ ] protocol rules in context: raw bodies, loop contract (results appended,
      never fabricate), errors as data; stable-to-volatile context ordering
- [ ] conversations-as-data direction: named workers, authored briefings,
      handoff when noisy, user may edit between runs
- [ ] campaigns: plans as operable artifacts; non-determinism relocated and
      bounded; review gate as informed choice; conditions over claims;
      single-writer tree; per-item conversations; ambient status + direction
      in context
- [ ] result wrappers as conversation data
- [ ] tool discovery through executable descriptions
- [ ] provider abstraction incl. claude-code via Claude Code login
- [ ] token accounting and recursive rollup
- [ ] explicit transformation pipelines

---

# Required Diagrams

Include at least: the transformation model (Part V), the context model
(main conversation with per-file memories), the artifact neighborhood
(Part VI), durable-work/disposable-workers (Part II), and the large-file
pipeline (Part VI). Adapt wording freely.

```text
main conversation
        |
        +-- file A memory
        |
        +-- file B memory
        |
        +-- file C memory
```

```text
target file
        |
        +-- historical summary
        +-- co-edited files
        +-- local conversation
        +-- per-file knowledge notes
        +-- split indexes
```

---

# Required Tables

Include tables for: hidden state vs explicit artifacts; session memory vs
artifact memory; retrieval vs preserved work; long-lived agent abstractions
vs disposable workers; object graphs vs data artifacts; framework-style
systems vs nagent; the tag protocol; the co-edit example; the provider table.

---

# Style Rules

Target 3000–6000 words. Keep the Mike Acton voice throughout. Keep the README
readable in one sitting. Short sections, concrete examples, diagrams where
helpful, Markdown tables for reference material, horizontal rules between
major sections when they help. Prefer **Build your own:** notes over
implementation trivia. Mention source files and functions only when they help
the reader find the implementation. Do not overstate safety. Do not describe
nagent as a product or an autonomous intelligence. Teach the data flow, why
the state is explicit, and why artifacts matter more than workers.

---

# Final Self-Review Checklist

- [ ] The introduction states **The agent is not the thing. The data is the
      thing.** and **Don't edit the output artifacts. Edit the prompt.** in
      Mike Acton's direct, data-oriented voice — plain and honest, cutting
      through hype without mocking readers or other approaches.
- [ ] The introduction includes **What It Looks Like** with two or three
      multi-turn `nagent`-only examples.
- [ ] The body follows the teaching arc in order: build it → rename it → own
      the data → exploit the files → name the principles → neighborhoods,
      context/large files, per-file conversations → frameworks.
- [ ] Each part opens with the claim it teaches; by the end of each part the
      reader has demonstrably gained that claim.
- [ ] Part I alone is enough for the reader to implement an agent-like
      interface.
- [ ] Part II makes the metaphor argument only after the mechanics are shown.
- [ ] Every major feature is justified by a reduction
      (problem → therefore → design).
- [ ] Every major numbered section ends with **Build your own:**.
- [ ] Every design claim is grounded in the current implementation — including
      knowledge harvest (nagent-distill), install context, the shared tag parser,
      compaction, branching, and the claude-code provider.
- [ ] Novelty is attributed to data flow and artifact management, not tool
      calling.
- [ ] Historical coupling is presented as inspection guidance, not an edit
      mandate.
- [ ] The framework comparison emphasizes transparent, editable data inputs
      instead of arguing that frameworks are bad.
- [ ] The reader could build a minimal version after reading.
