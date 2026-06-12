# nagent

**nagent** means **not-an-agent**.

The word "agent" suggests continuity, intent, and memory that a typical LLM
loop does not actually provide. nagent is a small reference implementation.
It shows what terminal "agent-like" workflows are when you describe the
mechanics instead of the metaphor.

The claim is simple:

**The agent is not the thing. The data is the thing.**

nagent is a small reference example of a data-oriented approach to AI
workflows.

The second claim follows from the first:

**Don't edit the output artifacts. Edit the prompt.**

If a generator produces output you do not like, fix the generator or the
inputs to that generator. Do not patch the generated output and leave the bad
input in place. In nagent, the conversation is one of those inputs. If it
matters, it needs to be saveable, maintainable, organizable, and editable.

The LLM is temporary. The process is temporary. Sub-conversations are
temporary. Context windows are temporary. What survives is explicit data:
conversations, per-file conversations, campaign plans, checkpoints,
install/user/project/root context files, repository history summaries,
historical coupling tables, file summaries, split indexes, patch artifacts,
and a harvested knowledge store you can open in an editor.

A text file, an LLM, structured tags, and a loop are how this repo implements
that idea. They are not the idea.

This README teaches in order: how to build an agent-like interface; why
"agent" is the wrong name for what you built; why the conversation data must
be owned by you — at the right scope; what owning it as files makes possible;
the data-oriented principles underneath; the data structures that fall out of
those principles; and how all of this compares to frameworks. Stop anywhere
and you still leave with something true. Finish and you can build your own.

## What It Looks Like

One `nagent` prompt can run for many turns. Reads. Shell. Sub-conversations.
More reasoning. Everything gets appended to the conversation file. From the
terminal you typed one command. Under the hood the loop keeps going until the
model emits a final response.

```bash
nagent "Investigate why this Linux service fails to start. Read the unit file and related config, run diagnostic commands, explain the root cause, and propose a fix before changing anything."
```

```bash
nagent "Review this repository: identify the main entry points, run the test suite, fix the smallest failing test you find, and summarize what changed and why."
```

```bash
nagent "Plan the migration of this config format. Inspect the loader, tests, and examples, explain the risks, then make the smallest implementation change if the plan is sound."
```

These are coordination tasks, not one-shot answers. nagent may read many
files, run commands, spawn sub-conversations for scoped work, and iterate. It
does not bypass permissions; it runs with the same access your user and
filesystem allow.

---

# Part I — Build It

The claim of this part: an "agent-like" terminal interface is a small number
of visible mechanics. By the end you can sketch the whole implementation on a
whiteboard.

## 1. Text In, Text Out

**Idea** — The smallest useful primitive is: file in, text out.

LLMs forget. Therefore put the prompt in a file and treat the model as a
temporary function over that data.

**Implementation** — `bin/nagent-llm-text` reads a text file, resolves
provider and model settings, calls `generate_text_with_usage()` from
`bin/helpers/nagent_llm.py`, and prints plain text or JSON with token usage.
Providers: `openai`, `anthropic`, `google`, `cursor`, and `claude-code` —
which runs the prompt through your locally installed Claude Code via the
Claude Agent SDK and authenticates with Claude Code's own login, no API key
in the environment.

`bin/nagent-llm-upload` is the sibling for artifacts that need upload APIs:
images, PDFs, office files, code documents. It rejects `.zip`, enforces a
50 MB limit, returns text or JSON.

**Example**

```bash
echo "What is 2+2?" > question.txt
nagent-llm-text --file question.txt
```

Everything else in nagent is orchestration around this. Do not skip it.

**Build your own:** implement `generate_text(file) -> str` first. Boring.
Separate. Provider churn should not rewrite your loop.

## 2. Teach the Model an Output Format

**Idea** — Free-form model output is hard to execute. Use a visible protocol.

The startup prompt lists the only tags the model may emit. The parser is
strict: recognized tags and whitespace. Nothing else.

**Implementation** — `build_initial_context()` in `bin/nagent` assembles the
runtime context: role instructions and the structured tag protocol first,
then context-management and write rules, discovered tool descriptions, the
context layers, the knowledge digest — and instance facts and environment
last. The ordering is stable-to-volatile on purpose: request prefixes stay
byte-identical across conversations of the same mode. The tag list carries
its usage guidance inline and lives inside `<initial_context>`, so refreshed
context carries the current protocol with it.

The context also states the protocol rules outright, because they are the
failure modes that matter: tag bodies are raw text (no escaping; the first
matching close tag ends a body — the protocol is XML-ish, not XML); nothing
outside tags; and the loop contract — action results come back appended as
`<nagent-*-result>` blocks before the model is called again, so never
fabricate results, and an error result is data that should change the
approach, not provoke an identical retry. A strict XML parser would reject
valid output, so tokenization lives in a small explicit parser,
`bin/helpers/nagent_tags.py`, and `parse_response()` validates tag shapes on
top of it.

Tags:

| Tag                                              | Meaning                                |
| ------------------------------------------------ | -------------------------------------- |
| `<nagent-response>...</nagent-response>`         | Human response or child result.        |
| `<nagent-read path="..."/>`                      | Read a small file inline.              |
| `<nagent-file-read path="..."/>`                 | Read a file; split first if needed.    |
| `<nagent-file-patch index="..."/>`               | Merge edited split segments via index. |
| `<nagent-write path="...">...</nagent-write>`    | Write to an allowed path.              |
| `<nagent-shell>...</nagent-shell>`               | Run shell; append output.              |
| `<nagent-next>...</nagent-next>`                 | Append a continuation prompt.          |
| `<nagent-conversation>...</nagent-conversation>` | Start an isolated sub-conversation.    |

Handlers append `<nagent-read-result>`, `<nagent-file-read-result>`,
`<nagent-file-patch-result>`, `<nagent-write-result>`,
`<nagent-shell-result>`, `<nagent-conversation-result>`. These are not secret
return values. They are conversation data.

**Example**

```xml
<nagent-read path="README.md" />
<nagent-shell>python3 -m unittest discover -s tests -v</nagent-shell>
<nagent-response>Done.</nagent-response>
```

**Build your own:** put the contract in the prompt. Enforce it in a small
parser you wrote for the grammar you actually have. If you cannot read the
protocol, you cannot debug the system.

## 3. The Loop

**Idea** — "Agent behavior" is mostly: append, call, parse, act, append,
repeat.

**Implementation** — Read this path:

```text
main()
  run_agent_loop()
    call_llm()
    parse_response()
    process_tags()
```

`run_agent_loop()` appends the user prompt, sends the whole conversation file
to `nagent-llm-text --json`, appends valid output, processes tags, appends
results, loops when an action or `<nagent-next>` added state.

Failures become data, not invisible control flow. Malformed output goes into
the conversation with a `<system>` correction, up to `MAX_FORMAT_RETRIES`
(3). Provider errors append too. A read of an unreadable or binary file comes
back as an `error=` result tag instead of a crash.

Writes have explicit boundaries. In the main conversation, `<nagent-write>`
is allowed only under temp directories (`/tmp`, `/var/tmp`, `$TMPDIR`);
project files are edited through per-file conversations (Part VI). Say it
plainly: this is a convention-based reference implementation, not a sandbox.
`<nagent-shell>` runs with your user's permissions.

The loop passes the conversation's stable prefix boundaries to
`nagent-llm-text` (`--cache-prefix-chars`), and providers that cache on block
boundaries reuse the shared context each turn. `TokenStats` tracks turns,
conversation input size, and recursive input/output tokens; child `--json`
output rolls up into the parent's totals, and cached prompt tokens fold back
into the counts, so accounting still means "tokens sent". No provider usage?
Estimate from character count.

**Example**

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

**Build your own:** after every action, append to durable state and call the
model again. Do not stash retry logic in RAM and pretend that is fine.

## 4. Tool Discovery

**Idea** — Tool capability should be explicit data too.

No central registry. Tools describe themselves.

**Implementation** — `exit_on_description()` in `bin/helpers/nagent_cli.py`
prints path + description when `--description` is in `sys.argv`.
`collect_bin_tool_descriptions()` runs each executable with `--description`
and inserts the results into initial context. Discovery is layered: the
install `bin/`, then `~/.nagent/bin/`, then the project's `.nagent/bin/`,
deduplicated by basename with the most specific layer winning. Drop an
executable in `.nagent/bin/` and every conversation in that project knows it.
Nothing else to register.

| Tool                    | Role                                                |
| ----------------------- | --------------------------------------------------- |
| `nagent`                | Main structured conversation loop.                  |
| `nagent-llm-text`       | Send a text file to the configured LLM.             |
| `nagent-llm-upload`     | Upload a supported file with a prompt.              |
| `nagent-file-edit`      | Per-file conversation for one source file.          |
| `nagent-file-split`     | Split large file into segments + `index.json`.      |
| `nagent-file-patch`     | Merge segments, write patch, validate hashes.       |
| `nagent-file-summarize` | Summarize inline or via split summaries.            |
| `nagent-distill`        | Harvest, merge, and graduate knowledge; reclaim.    |
| `nagent-campaign`       | Operate campaigns: plans as data, driven in passes. |

**Example**

```bash
nagent --description
nagent-campaign --description
```

**Build your own:** tools emit capability text. Assemble prompts from that.
Do not maintain a hidden registry that drifts.

That is Part I. A primitive, a protocol, a parser, handlers, a loop, and
self-describing tools. You could build this in an afternoon. Now look at what
you built.

---

# Part II — Rename It

## 5. You Did Not Build an Agent

**Idea** — Nothing in Part I has continuity, intent, or memory of its own.

The process starts, transforms a file, and exits. The model is called fresh
every turn with the whole conversation as input. The "memory" is the file.
The "continuity" is the file. The "intent" is whatever the file says.
"Agent" imports all three and delivers none — the word points you at the
worker when everything that matters is in the artifacts.

```text
temporary worker
        |
        v
durable artifacts
        |
        v
next temporary worker
```

**Implementation** — `bin/nagent` stores conversations under the root's
`conversations/`. It appends user prompts, model responses, tool results,
parser corrections, interrupts, and sub-conversation results to the
conversation file. Kill the process mid-task and the file holds everything;
the next process picks it up. The Python process is a worker. The files are
the system.

| Hidden state                      | Explicit artifact                                 |
| --------------------------------- | ------------------------------------------------- |
| Prompt state in a running process | Conversation files under the nagent root          |
| Private tool traces               | Request tags and result wrappers appended as text |
| In-memory scratch state           | Temp files, split segments, indexes, and patches  |
| Framework-managed memory          | User-editable files                               |

**Build your own:** decide which artifacts are source of truth before you
design "conversation behavior." Workers come and go. Data stays. Call the
running loop a conversation, because that is what is on disk.

---

# Part III — Own the Data

## 6. Conversations Are Editable State — at the Right Scope

**Idea** — The conversation file is not chat history. It is working state,
it belongs to you, and it belongs *somewhere*: memory that belongs to a
project should live with the project.

Tool transcript. Correction channel. Continuation point. Mutable artifact.
Memory goes stale; therefore editing history is maintenance, not corruption.

**The conversation does not own its memory. The user does.**

| Session memory               | Artifact memory              |
| ---------------------------- | ---------------------------- |
| Belongs to a running session | Belongs to a file on disk    |
| Often opaque                 | Openable and diffable        |
| Dies with the process        | Survives worker replacement  |
| Optimized for chat UX        | Optimized for preserved work |

**Implementation** — Explicit maintenance commands:

- `--save-conversation NAME` is instant: a file copy plus an index entry.
  The index summary is extracted deterministically, zero LLM — the
  checkpoint's Intent line when one exists (already paid for), else the
  first user prompt truncated: your own words describing the task. The save
  name you chose is the rest of the metadata.
- `--summarize-conversation NAME` upgrades one index entry with a proper
  LLM summary, on demand — pay for the good version only when you want it.
  `nagent-distill --apply` backfills the rest as maintenance.
- `--load-conversation` / `--branch-conversation` archive the current file
  and copy a saved or named conversation into place.
- `--summarize` prints an LLM summary of the loaded conversation.
- `--edit-conversation "prompt"` archives the conversation, runs a file-edit
  session against the archive with your prompt, and loads the result.
- `--compact` is `--edit-conversation` driven by the user-editable guidance
  in `prompts/compact-conversation.md`.

Implicit maintenance comes from the fact that conversations are ordinary
files: open them, trim them, rewrite them, diff them, copy them, version
them, script them.

Ownership has scopes, and the root follows them. Project memory was trapped
in a personal dotdir; therefore, inside a git repository the default root is
`{toplevel}/.nagent` — conversations, knowledge, campaigns, and per-file
memory live with the repo and can be committed and shared (review first:
conversations contain tool output). `--root` overrides; outside a repo the
root is `~/.nagent`. A newly created root ships a `.gitignore` covering only
regenerable artifacts (`splits/`); committing the rest is deliberate.

The prompt-side inputs are yours too, in four layers, least personal first —
each a `context.yaml` (a list or `{ "paths": [...] }`, nested files expanding
recursively) or a `context.md`:

1. **Install** — the nagent folder itself; this repository ships
   `context.yaml` pointing at `context/data-oriented-design.md`.
2. **User** — `~/.nagent/context.*`, read in every run, everywhere.
3. **Project** — the git toplevel's `context.yaml`/`context.md`,
   instructions that travel with the repo.
4. **Root** — the resolved root's own context (the project's `.nagent/`).

More specific layers come later and can override; a layer whose directory
equals an earlier layer's is included once, not twice. The prompts under
`prompts/` (compaction, harvest, checkpoint, campaign) resolve through the
same layering — project `.nagent/prompts/`, then `~/.nagent/prompts/`, then
the install copy. Config resolves CLI flags → `NAGENT_CONFIG` → project
`.nagent/config.json` → `~/.nagent/config.json`.

**Example**

```bash
nagent --status
nagent --save-conversation before-refactor
nagent --branch-conversation before-refactor
nagent --compact
nagent --edit-conversation "keep the decisions and remove obsolete logs"
```

**Build your own:** memory is a data structure on disk. Give the user the
same rights over it that they have over any other file, because it is one —
and put it at the scope where it belongs.

---

# Part IV — Exploit the Files

The claim of this part: once state is files, problems that are hard with
opaque session state become easy. These are the opportunities you bought in
Part III.

## 7. Repository History as Data

**Idea** — A repo is not only the current tree. History is data too.

Repositories contain historical knowledge. Therefore transform git history
into editing context. Not vague "retrieval" — explicit transformation of
historical artifacts into working input.

```text
git history
    ->
commit/file summaries
    ->
file-edit initial context
    ->
better edit decisions
```

**Implementation** — On file-edit start,
`file_edit_history_and_summary_block()` gathers git history.
`git_file_history()` reads recent commits; `summarize_new_file_commits()`
asks the LLM for one-line summaries of new commits and reuses cached
summaries from prior initial context, so unchanged history is never re-paid.
`format_file_history()` records editors, step history, co-edited files, and
summarized commits. `run_file_summary()` adds a current-content summary.
Injected as `{file-history}` and `{file-summary}` blocks. Hints, not
commands.

**Build your own:** turn history into explicit context blocks. Cache the
summaries in the durable conversation. Do not re-pay LLM cost for unchanged
history.

## 8. Distill: Harvest, Merge, Graduate

**Idea** — Dead conversations accumulate, and deleting them loses what was
learned. Therefore: distill, then delete — and feed the distillate back in.

**Implementation** — `nagent-distill` scans the root and classifies every
artifact: live conversations, user-kept saves, prunable stale splits and
dead index entries, and harvest candidates — conversation archives,
delegated sub-conversations, per-file conversations whose target file is
gone, and a finished campaign's conversations (the plan files stay as the
record). Unknown is kept, never deleted.

For each harvest candidate, an LLM pass driven by the user-editable
`prompts/harvest-conversation.md` extracts facts, decisions, completed and
open tasks, open questions, and playbooks into category files under the
root's `knowledge/` — every bullet carrying provenance
(`[from: conversation, date]`). Notes tied to a specific file mirror into
`knowledge/files/{file_id}.md`. Deletion is gated on a sha256 entry in
`knowledge/ledger.json` proving the harvest happened; identical content
never pays the LLM twice.

A bounded `digest.md` (open tasks and questions first, newest first)
regenerates from the category files — never from raw conversations, so your
edits propagate — and is injected into every conversation's
`<initial_context>` as a `{knowledge}` block. Delete `digest.md` and
injection turns off. That is the whole switch.

Two maintenance passes keep the store healthy. `--merge` rewrites each
category file — dedup, merge, compress, provenance preserved — keeping the
previous content as `{file}.pre-merge`. `--graduate` answers the question
"why is this proven playbook still prose?": playbooks become `.draft` tools
or prompts under the root, and a finished campaign's `bin/` and `prompts/`
are staged the same way. Drafts are deliberately not executable — invisible
to tool discovery until you review, rename, and `chmod +x`. Knowledge
becomes capability, gated by review. Nothing lands silently.

Distill also backfills the saved-conversations index: entries whose summary
is missing or merely extracted get a proper LLM summary during `--apply` —
instant saves defer that cost to the maintenance pass, where it is visible.

Dry run is the default everywhere, with the estimated cost in tokens printed
before anyone pays it.

**Example**

```bash
nagent-distill                        # dry run: classify, estimate cost
nagent-distill --apply                # harvest into {root}/knowledge/, reclaim
nagent-distill --merge --apply        # dedup/compress the knowledge files
nagent-distill --graduate --apply     # draft proven playbooks as tools
```

**Build your own:** never delete an artifact you have not distilled, keep
the proof of distillation in data, and give knowledge a path to become a
tool — with the user as the gate.

## 9. Everything Else Files Buy You

**Idea** — The mundane wins add up.

- `diff` two conversation states to see exactly what an editing pass changed.
- `--branch-conversation` before a risky direction; come back if it fails.
- Script maintenance: cron a `--compact`, grep your knowledge store.
- Audit exactly what the model saw — the conversation file *is* the request.
- Point the same conversation file at a different provider and replay.

None of these required a feature. They required the state to be files.

**Build your own:** before building a feature, check whether `cat`, `diff`,
and `cp` already do it. With file-based state, they often do.

## 10. Project Memory Is Team Memory

**Idea** — The project-local root turns every opportunity above from
personal to shared.

Commit `.nagent/` and knowledge, per-file conversations, campaign plans, and
graduated tools in `.nagent/bin` arrive with `git clone`. A teammate's first
conversation starts from what the project already learned, and changes to
the project's memory are reviewable in the same pull request as the code
they describe. The artifacts compound across people, not just across
sessions.

Say the caveat plainly: conversations contain tool output and can contain
secrets — review before committing, like any other file. The choice stays
with you: the scaffolded `.gitignore` excludes only regenerable `splits/`;
everything else is deliberate.

**Build your own:** sharing memory should not need a memory service. A
directory in the repo and code review are the synchronization protocol.

---

# Part V — Name the Principles

## 11. Data-Oriented Design

**Idea** — You have been using these principles since Part I. Here are their
names.

- **The data is more important than the code operating on it.** The
  conversation file outlives every process that touches it (Part II).
- **Behavior is a transformation over explicit state.** The loop is
  append → transform → append (Part I).
- **Avoid hidden mutable state.** Retries, errors, and tool results are
  appended text, not control flow (Part I).
- **Separate durable artifacts from temporary execution.** Workers are
  disposable; artifacts are durable (Part II).
- **Optimize the shape, availability, and maintenance of the data.**
  Editable conversations, cached commit summaries, merged knowledge,
  project-scoped roots (Parts III–IV).

The whole system is one transformation:

```text
repository history
        +
install + user + project + root context
        +
conversation
        +
artifact-local memory
        +
artifact summary
        +
historical coupling
        +
harvested knowledge
        +
user request
            ->
     LLM transformation
            ->
     updated artifacts
```

| Object graphs                                     | Data artifacts                         |
| ------------------------------------------------- | -------------------------------------- |
| Behavior distributed across services and objects. | Behavior is transformation over files. |
| State behind interfaces.                          | State in an editor buffer.             |
| Runtime topology is central.                      | Artifact shape is central.             |

**Build your own:** when a design question stalls, stop asking what the
component should *do* and ask what the data *is* — its shape, its owner, its
lifetime, who edits it, and what transforms it.

---

# Part VI — The Data Structures That Fall Out

Four applied chapters. Each is the principles from Part V doing work.

## 12. Artifact Neighborhoods

**Idea** — A file lives in a neighborhood of related artifacts.

Files that change together in git history are hints: tests, headers, config,
paired implementation. High co-edit rate means "look here maybe." Not "edit
everything."

```text
target file
        |
        +-- historical summary
        +-- co-edited files
        +-- local conversation
        +-- per-file knowledge notes
        +-- split indexes
```

**Implementation** — `coedited_file_rows()` counts files appearing in the
same commits as the target and labels high/medium/low co-edit rates.
`format_file_history()` puts the table in file-edit context with guidance:
inspect high co-edit files when the change may touch interfaces, tests,
config, or paired code. Per-file knowledge notes harvested by
`nagent-distill` join the same neighborhood.

**Example**

| file              | commits together | historical co-edit rate |
| ----------------- | ---------------- | ----------------------- |
| `src/foo_test.py` | 7                | high (70%)              |
| `src/foo.h`       | 5                | medium (50%)            |

The table says "changed with this file." It does not say "must change now."
**High co-edit files are candidates for inspection, not automatic edit
targets.**

**Build your own:** compute neighborhoods from history. Present them as
inspection guidance. Ground edits in the current request and current code,
not historical association alone.

## 13. Managing Context and Large Files

**Idea** — Context windows are a budget. Spend it explicitly — and have a
safety net for the conversation that outgrows its window anyway.

```text
large source file
    ->
split index + segment files
    ->
bounded edits
    ->
patch artifact
    ->
updated source file
```

**Implementation** — Inline reads cap at 64 KB. `<nagent-file-read>` calls
`nagent-file-split` beyond that. Splitting uses language-aware natural
splitters (`txt`, `md`, `cpp`, `py`, `xml`, `js`, `ts`, `json`, `yaml`,
`go`, `rs`, `java`) that prefer structural boundaries and writes segment
files plus `index.json`: source path, hash, size, line ranges, split type.
`nagent-file-patch` validates the source hash (unless `--force`), merges
segments, writes a unified diff patch, applies it, and refreshes the index.
`nagent-file-summarize` handles small files inline and large ones
per-segment.

Conversation-side budget tools: `--compact` rewrites the conversation
against editable guidance; the knowledge digest is byte-capped before
injection; and `<nagent-conversation>` spawns a child nagent with an
isolated conversation file — the parent keeps coordination, the child keeps
the noise, and only the distilled result returns with its token totals
rolled up. Delegation is context management before it is parallelism.

| Long-lived agent abstractions  | Disposable workers               |
| ------------------------------ | -------------------------------- |
| Identity is central            | Output artifact is central       |
| Shared context gets noisy      | Child context is isolated        |
| Parent absorbs all exploration | Parent gets a concise result     |
| Delegation implies personality | Delegation is context management |

The safety net catches what decomposition cannot bound. Checkpoints: a
separate one-call writer — not the working model; asking a mid-task model to
also keep the log degrades both jobs — maintains
`{conversation}.checkpoint.md`, a fixed-schema, user-editable working-state
file. The cadence is wall-clock with a burst guard, computed from data on
disk (the checkpoint records its own timestamp and the conversation size):
fire after `checkpoint_interval_minutes` (default 60) when the conversation
has grown, or immediately after `checkpoint_max_new_kb` (default 256) of new
content regardless of time — a five-minute log-reading burst is exactly when
a stale checkpoint is worthless. An idle hour costs nothing. Your edits to
the checkpoint survive the next writer pass.

Rebuild: past `rebuild_at_kb` (default 384) the loop runs a synchronous
checkpoint (failure widens the raw tail instead of blocking), archives the
conversation, and assembles a fresh window — initial context + `{checkpoint}`
block + recent raw tail — deterministically, no LLM rewrite. A long task
becomes an inspectable chain of window files linked by checkpoints, and the
archives feed `nagent-distill`. Three config numbers, all verifiable with
`ls -l`.

The initial context also directs the model to exploit conversations as data:
reuse a named worker (`conversation-file="name"` continues that conversation
with its accumulated context), resume saved work (`conversation-name`),
author a worker's briefing under the temp write boundary and spawn a child
on it, hand off to a fresh sub-conversation when its own context is mostly
stale tool output, and — for a high-stakes decision — brief 2–3 workers plus
a judge, spending those tokens only when the decision warrants it.

**Example**

```bash
nagent-file-split --file src/big.py --output /tmp/big-split --json
# edit /tmp/big-split/big-0001.py
nagent-file-patch --index /tmp/big-split/index.json --json
```

**Build your own:** chunking is a data structure — index it, hash the
source, edit bounded segments, emit a patch artifact. Checkpoint working
state on a clock you can explain, rebuild deterministically, and keep every
window on disk.

## 14. Per-File Write Conversations

**Idea** — Work recurs around individual files. Give each file its own
persistent conversation — memory and write authority attached to the
artifact, not to a session.

```text
main conversation
        |
        +-- file A memory
        |
        +-- file B memory
        |
        +-- file C memory
```

**Implementation** — `bin/nagent-file-edit` resolves a file-specific
conversation and delegates to `bin/nagent --file-edit`. The index,
`conversations/file-index-{pid}.json`, keys files by stable file id
(device + inode via `file_id_for_path()`), so renames keep their memory. The
per-file conversation's initial context carries the file's history block,
commit summaries, current summary, and harvested knowledge notes.

Write authority is bounded per mode:

| Mode              | Structured write boundary                                             |
| ----------------- | --------------------------------------------------------------------- |
| Main conversation | `/tmp`, `/var/tmp`, or `$TMPDIR` only.                                |
| Per-file edit     | Target file (by path or file id), or split segments for that source.  |

Rejected writes append `<nagent-write-result status="error">` to the
conversation. The value of uniqueness: investigations, dead ends, and local
assumptions accumulate next to the artifact they concern; the main
conversation stays small; and the write boundary is a property of the file,
not of whoever happens to be running a session.

**Example**

```bash
nagent-file-edit --file src/foo.py "add error handling"
nagent --list-file-edits
```

**Build your own:** when work orbits one artifact, store memory on that
artifact's identity and scope write authority to it. Session memory = what
happened today. Artifact memory = what we learned about this file.

## 15. Campaigns: Plans as Operable Artifacts

**Idea** — After everything else became a file, the model's sense of what to
do next is the last hidden state: re-decided every turn, invisible,
degrading as context grows. Make the plan a first-class artifact and the
driver a deterministic transform over it.

Be precise about what is extracted. The model's non-determinism is not
removed; it is *relocated and bounded*. Selection, blocking, sequencing, and
completion mechanics become code reading a tree; the model is scoped to
narrow judgments — decompose *this* item, execute *this* item, judge *this*
condition — each with a curated context. The determinism boundary is exactly
the schema.

**Implementation** — A campaign lives at `{root}/campaigns/{slug}/`: a
hand-editable `index.yaml` spine (tree of item ids, statuses, `blocked_by`
edges, review thresholds, dispatch budget), per-item `items/{id}/item.yaml`
detail, and a per-item conversation — artifact-local memory where the
artifact is a unit of work, continuable across dispatches. The one-pass
driver, `nagent-campaign update`: merge worker results, route answered
questions, check completion conditions, gate decomposition proposals,
dispatch unblocked todo leaves, then exit. Four invariants are load-bearing:

- **One pass, then exit.** No resident process, no watch mode. Looping is
  your composition — a scheduler growing inside the tool means the design
  failed its own test.
- **One writer for the tree.** Workers return structured results
  (`result.json` in their own item dir); only the driver mutates the plan.
  LLMs produce data; code mutates artifacts.
- **Plan changes pass a review gate, not a cap.** Large projects must not be
  inhibited; you make an informed choice. Decomposition lands as proposals
  with their scope reported — items added, depth, estimated cost; changes
  within your thresholds auto-confirm; a new campaign's initial
  decomposition always waits. Edit the proposal file directly, then confirm.
- **The schema is the whole schema.** If the YAML needs a manual, the
  "interface is the editor" property is lost.

Completion is conditions, not claims: executable `test:` scripts in the
campaign's `tests/` (deterministic, preferred) and `judge:` prose only when
unavoidable. A premature "done" bounces back to `todo` by mechanism, not
exhortation. Open questions are first-class blockers: workers raise them,
they land in `questions.md`, you answer by editing the file, and the next
update routes the answer into the item's briefing.

The initial context directs the model to create campaigns for work that
outlives a conversation ("the plan must survive you"), injects an ambient
status block for active campaigns, and runs dispatched workers in a
dedicated `--campaign-item` mode carrying the contract; a campaign's own
`bin/` joins tool discovery for its workers.

**Example**

```yaml
name: Migrate config format
description: Replace the legacy loader with the new format.
status: active
review:
  auto_confirm_max_items: 5
  auto_confirm_max_depth: 2
dispatch:
  max_per_update: 4
items:
- id: 0001-inventory-call-sites
  status: done
- id: 0002-implement-new-loader
  status: todo
  blocked_by:
  - 0001-inventory-call-sites
```

```bash
nagent-campaign new "Migrate config format" --goal "Replace the loader."
nagent-campaign add migrate-config-format "Inventory call sites"
nagent-campaign update migrate-config-format --dry-run   # preview the pass
nagent-campaign update migrate-config-format             # merge, check, gate, dispatch
nagent-campaign review migrate-config-format             # pending proposals + scope
nagent-campaign confirm migrate-config-format            # accept the plan change
```

**Build your own:** plan-as-artifact plus a dumb driver beats
plan-as-program. If your orchestrator needs a runtime, your plan has stopped
being data.

---

# Part VII — How This Differs From Frameworks

## 16. Own the Inputs

**Idea** — Use a framework when it buys something concrete. The question to
ask first is who owns the data.

nagent uses plain files, Python, subprocesses, and structured text. The
interesting part is artifact management and explicit data flow, not tool
calling. The point is not "frameworks bad." The point is that the inputs to
the system — prompts, conversations, plans, tool results, summaries,
indexes, patches, harvested knowledge — should not be trapped inside an
opaque layer that hides, rewrites, stores, or modifies them beyond the
transformations LLM providers already perform. nagent keeps as much control
as it can by making every input transparent and editable.

| Framework-style system       | nagent                  |
| ---------------------------- | ----------------------- |
| hidden or managed state      | explicit files          |
| session memory               | artifact memory         |
| object/service graph         | data artifacts          |
| central tool registry        | executable descriptions |
| long-lived agent abstraction | disposable workers      |
| opaque orchestration         | visible transformations |

| Common term | nagent framing                      |
| ----------- | ----------------------------------- |
| memory      | editable artifact                   |
| retrieval   | preserved work / historical context |
| agent       | temporary transformation function   |
| context     | explicit input data                 |

| Retrieval                    | Preserved work                                                     |
| ---------------------------- | ------------------------------------------------------------------ |
| Find chunks at query time.   | Keep conversations, summaries, history, indexes as durable inputs. |
| Context as a service result. | Context as editable data.                                          |

**Build your own:** if the goal is to learn the data flow, start with files
and transformations. Adopt a framework when you can name the concrete thing
it buys you — and check what it costs you in ownership of your own inputs.

---

# Build Your Own

The minimal system is not mystical. A small loop over explicit state, built
in the same order this README taught it:

1. `generate_text(file) -> str`
2. A growing conversation document
3. Initial context that states the contract
4. An output format and a small strict parser
5. Handlers that append results back into state
6. Loop after actions
7. Visible retry on malformed output
8. Save/load/branch/edit/compact for conversation maintenance
9. A project-local root with layered context, prompts, tools, and config
10. Repository history → context blocks
11. Harvest dead conversations into a knowledge store; inject a bounded
    digest; merge it; graduate proven playbooks into tools
12. Per-artifact memory with stable ids and bounded write authority
13. Wall-clock checkpoints and deterministic rebuild into window chains
14. Plans as operable artifacts: a hand-editable tree, a one-pass driver, a
    review gate, completion conditions
15. Child loops for delegation

Code reading order:

```text
main()
  run_agent_loop()
    call_llm()
    parse_response()
    process_tags()
```

Then:

```text
bin/helpers/nagent_llm.py
bin/helpers/nagent_cli.py
bin/helpers/nagent_tags.py
bin/helpers/nagent_file_edit_lib.py
bin/helpers/nagent_file_split_lib.py
bin/helpers/nagent_file_patch_lib.py
bin/helpers/nagent_file_summarize_lib.py
bin/helpers/nagent_distill_lib.py
bin/helpers/nagent_campaign_lib.py
```

Tests are executable notes: parser and protocol, conversation lifecycle,
root and layer resolution, retries, tokens, sub-conversations, result
wrappers, write validation, file ids, file-edit index, git history,
co-edited files, summaries, split/patch, distill classification, harvest,
merge and graduate, campaign schema, driver, review gate and conditions,
checkpoint triggers and rebuild, providers, tool descriptions, JSON output.

---

# Setup

```bash
pip install -r requirements.txt
export PATH="$PWD/bin:$PATH"
mkdir -p ~/.nagent
cp config.example.json ~/.nagent/config.json
```

The root: inside a git repo, `{toplevel}/.nagent` (created on first use, with
a `.gitignore` covering `splits/`); outside, `~/.nagent`; `--root` overrides.

Config: CLI flags → `NAGENT_CONFIG` → project `.nagent/config.json` →
`~/.nagent/config.json`.

```json
{
  "provider": "openai",
  "model": "gpt-5.5",
  "checkpoint_interval_minutes": 60,
  "checkpoint_max_new_kb": 256,
  "rebuild_at_kb": 384
}
```

| Provider      | Default model       | Credential environment variable         |
| ------------- | ------------------- | --------------------------------------- |
| `openai`      | `gpt-5.5`           | `OPENAI_API_KEY`                        |
| `anthropic`   | `claude-sonnet-4-6` | `ANTHROPIC_API_KEY`                     |
| `google`      | `gemini-2.5-flash`  | `GOOGLE_API_KEY` or `GEMINI_API_KEY`    |
| `cursor`      | `composer-2.5`      | `CURSOR_API_KEY`                        |
| `claude-code` | `default`           | None — uses the local Claude Code login |

The `claude-code` provider runs prompts through the locally installed Claude
Code via the Claude Agent SDK, so authentication is whatever Claude Code is
logged in as (subscription or API key). The `default` model — same as
omitting `--model` — means Claude Code's own configured model; any Claude
model id or alias (`sonnet`, `opus`, `haiku`) overrides it. Tools are
disabled for plain text generation; `nagent-llm-upload` permits only the Read
tool so Claude Code can read the file locally.

# Common Commands

```bash
nagent "your prompt here"
echo "prompt from stdin" | nagent
nagent "Use this instruction, then read stdin:" -
nagent --status --json
nagent --list-models --json
nagent --list-conversations
nagent --clear
nagent --save-conversation saved-copy
nagent --summarize-conversation saved-copy
nagent --load-conversation saved-copy
nagent --branch-conversation saved-copy
nagent --summarize
nagent --compact
nagent --edit-conversation "summarize useful parts and remove noise"
nagent --file-edit src/foo.py "make this change"
nagent --list-file-edits

nagent-llm-text --file question.txt --json
nagent-llm-upload --file diagram.png --prompt "Explain the diagram." --json
nagent-file-edit --file src/foo.py "add validation"
nagent-file-split --file src/big.py --output /tmp/big-split --json
nagent-file-patch --index /tmp/big-split/index.json --json
nagent-file-summarize --file src/big.py --json

nagent-distill                        # dry run: classify artifacts, estimate harvest cost
nagent-distill --apply                # harvest knowledge into {root}/knowledge/, reclaim space
nagent-distill --apply --no-harvest   # reclaim only, no LLM pass
nagent-distill --merge --apply        # dedup/compress the knowledge files
nagent-distill --graduate --apply     # draft proven playbooks as tools/prompts

nagent-campaign new "Migrate config" --goal "Replace the loader."
nagent-campaign add migrate-config "Inventory call sites"
nagent-campaign update migrate-config --dry-run   # preview one driver pass
nagent-campaign update migrate-config             # merge, check, gate, dispatch
nagent-campaign review migrate-config             # inspect pending proposals
nagent-campaign confirm migrate-config            # accept the plan change
```

`--help` for flags. `--description` for what a tool contributes to startup
context.

# Tests

```bash
python3 -m unittest discover -s tests -v
```

Some tests mock providers. Live integration tests need real credentials.

# License

MIT — see [LICENSE](LICENSE).
