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
conversations, per-file conversations, root and install context files,
repository history summaries, historical coupling tables, file summaries,
split indexes, patch artifacts, and a harvested knowledge store you can open
in an editor.

A text file, an LLM, structured tags, and a loop are how this repo implements
that idea. They are not the idea.

This README teaches in order: how to build an agent-like interface; why
"agent" is the wrong name for what you built; why the conversation data must
be owned by you; what owning it as files makes possible; the data-oriented
principles underneath; the data structures that fall out of those principles;
and how all of this compares to frameworks. Stop anywhere and you still leave
with something true. Finish and you can build your own.

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
in the environment. Defaults come from `NAGENT_CONFIG` or
`~/.nagent/config.json`. CLI flags win.

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
runtime context: instance facts, environment, git remotes, discovered tool
descriptions, context-management rules, write rules, large-file guidance, the
structured tag protocol, install and root context, the knowledge digest, role
instructions. The tag list and usage rules live inside `<initial_context>`,
so refreshed context carries the current protocol with it.

The protocol is XML-ish, not XML: tag bodies are raw text — shell commands
with `&&`, file contents, prompts — with no entity escaping, and the first
matching close tag ends a body. A strict XML parser would reject valid
output, so tokenization lives in a small explicit parser,
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

`TokenStats` tracks turns, conversation input size, and recursive
input/output tokens. Child `--json` output rolls up into the parent's totals,
including `--edit-conversation` and `--compact` children. No provider usage?
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
`collect_bin_tool_descriptions()` runs each executable in `bin/` with
`--description` and inserts the results into initial context. Add an
executable to `bin/` that answers `--description` and the loop knows about
it. Nothing else to register.

| Tool                    | Role                                              |
| ----------------------- | ------------------------------------------------- |
| `nagent`                | Main structured conversation loop.                |
| `nagent-llm-text`       | Send a text file to the configured LLM.           |
| `nagent-llm-upload`     | Upload a supported file with a prompt.            |
| `nagent-file-edit`      | Per-file conversation for one source file.        |
| `nagent-file-split`     | Split large file into segments + `index.json`.    |
| `nagent-file-patch`     | Merge segments, write patch, validate hashes.     |
| `nagent-file-summarize` | Summarize inline or via split summaries.          |
| `nagent-gc`             | Harvest knowledge from dead artifacts, reclaim.   |

**Example**

```bash
nagent --description
nagent-gc --description
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

**Implementation** — `bin/nagent` stores conversations under
`~/.nagent/conversations/`. It appends user prompts, model responses, tool
results, parser corrections, interrupts, and sub-conversation results to the
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

## 6. Conversations Are Editable State

**Idea** — The conversation file is not chat history. It is working state,
and it belongs to you.

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

- `--save-conversation NAME` copies the conversation and records it, with an
  LLM-generated summary, in a saved-conversations index. If the summary fails
  (no credentials, provider down), the save still completes — the index gets
  a visible "(summary unavailable)" marker instead of losing the entry.
- `--load-conversation` / `--branch-conversation` archive the current file
  and copy a saved or named conversation into place.
- `--summarize` prints an LLM summary of the loaded conversation.
- `--edit-conversation "prompt"` archives the conversation, runs a file-edit
  session against the archive with your prompt, and loads the result.
- `--compact` is `--edit-conversation` driven by the user-editable guidance
  in `prompts/compact-conversation.md`.

Implicit maintenance comes from the fact that conversations are ordinary
files: open them, trim them, rewrite them, diff them, copy them, version
them, script them. Delete stale tool spam, fix a bad assumption, replace ten
pages with one paragraph.

The prompt-side inputs are yours too. Root context: `load_root_context()`
reads `~/.nagent/context.yaml` or `context.md`; YAML can be a list or
`{ "paths": [...] }`; nested `context.yaml` files expand recursively. Install
context works the same way from the nagent folder itself (the parent of
`bin/`) and is injected before root context, so per-root context can override
what ships with the checkout — this repository ships `context.yaml` pointing
at `context/data-oriented-design.md`, the operating rules every conversation
starts with. The compaction and harvest prompts under `prompts/` resolve
root-first: put your own copy under `~/.nagent/prompts/` and it wins.

**Example**

```bash
nagent --status
nagent --save-conversation before-refactor
nagent --branch-conversation before-refactor
nagent --compact
nagent --edit-conversation "keep the decisions and remove obsolete logs"
```

**Build your own:** memory is a data structure on disk. Give the user the
same rights over it that they have over any other file, because it is one.

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

**Example**

```text
{file-history}
File: src/foo.py

Individuals who edited this file:
- Alice <alice@example.com>: 3 commits

Step-by-step history:
- 2026-05-01 abc123 Alice: Adds validation.
{/file-history}
```

**Build your own:** turn history into explicit context blocks. Cache the
summaries in the durable conversation. Do not re-pay LLM cost for unchanged
history.

## 8. Harvest Knowledge, Reclaim Space

**Idea** — Dead conversations accumulate, and deleting them loses what was
learned. Therefore: distill, then delete — and feed the distillate back in.

This is the strongest version of the "files create opportunities" argument.
Session state that other tools discard becomes compounding, user-editable
knowledge.

**Implementation** — `nagent-gc` scans the nagent root and classifies every
artifact: live conversations, user-kept saves, prunable stale splits and dead
index entries, and harvest candidates — conversation archives, delegated
sub-conversations, per-file conversations whose target file is gone. Unknown
is kept, never deleted.

For each harvest candidate, an LLM pass driven by the user-editable
`prompts/harvest-conversation.md` extracts facts, decisions, completed and
open tasks, open questions, and playbooks into category files under
`~/.nagent/knowledge/` — every bullet carrying provenance
(`[from: conversation, date]`). Notes tied to a specific file mirror into
`knowledge/files/{file_id}.md`. Deletion is gated on a sha256 entry in
`knowledge/ledger.json` proving the harvest happened; identical content never
pays the LLM twice.

A bounded `digest.md` (open tasks and questions first, newest first)
regenerates from the category files — never from raw conversations, so your
edits to the category files propagate — and is injected into every
conversation's `<initial_context>` as a `{knowledge}` block. Delete
`digest.md` and injection turns off. That is the whole switch.

Dry run is the default and prints the classification table plus the estimated
harvest cost in tokens before anyone pays it.

**Example**

```bash
nagent-gc                        # dry run: classify, estimate cost
nagent-gc --apply                # harvest into ~/.nagent/knowledge/, reclaim
nagent-gc --apply --no-harvest   # reclaim only, no LLM pass
```

**Build your own:** never delete an artifact you have not distilled, and
keep the proof of distillation in data. Make the distillate editable — the
user will know which "facts" are wrong before any model does.

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

---

# Part V — Name the Principles

## 10. Data-Oriented Design

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
- **Optimize the shape, availability, and maintenance of the data.** Editable
  conversations, cached commit summaries, harvested digests (Parts III–IV).

The whole system is one transformation:

```text
repository history
        +
install + root context
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

Three applied chapters. Each is the principles from Part V doing work.

## 11. Artifact Neighborhoods

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
config, or paired code. Per-file knowledge notes harvested by `nagent-gc`
join the same neighborhood.

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

## 12. Managing Context and Large Files

**Idea** — Context windows are a budget. Spend it explicitly.

Large files exceed context windows. Therefore split them into explicit
artifacts. Conversations grow too. Therefore compact them, bound the
knowledge digest, and push noisy exploration into disposable
sub-conversations.

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
splitters (`txt`, `md`, `cpp`, `py`, `xml`, `js`, `ts`, `json`, `yaml`, `go`,
`rs`, `java`) that prefer structural boundaries — headings, blank lines,
defs, brace depth — and writes segment files plus `index.json`: source path,
hash, size, line ranges, split type. `nagent-file-patch` validates the source
hash (unless `--force`), merges segments, writes a unified diff patch,
applies it, and refreshes the index. `--refresh` re-splits after the source
changes. `nagent-file-summarize` handles small files inline and large ones
per-segment with summaries stored in the index.

Conversation-side budget tools: `--compact` rewrites the conversation against
editable guidance; the knowledge digest is byte-capped before injection; and
`<nagent-conversation>` spawns a child nagent with an isolated conversation
file — the parent keeps coordination, the child keeps the noise, and only the
distilled result returns as a `<nagent-conversation-result>` with its token
totals rolled up. Delegation is context management before it is parallelism.

| Long-lived agent abstractions  | Disposable workers               |
| ------------------------------ | -------------------------------- |
| Identity is central            | Output artifact is central       |
| Shared context gets noisy      | Child context is isolated        |
| Parent absorbs all exploration | Parent gets a concise result     |
| Delegation implies personality | Delegation is context management |

**Example**

```bash
nagent-file-split --file src/big.py --output /tmp/big-split --json
# edit /tmp/big-split/big-0001.py
nagent-file-patch --index /tmp/big-split/index.json --json
```

```xml
<nagent-conversation>
Inspect the split and patch tests. Return only the behaviors the README should explain.
</nagent-conversation>
```

**Build your own:** chunking is a data structure — index it, hash the source,
edit bounded segments, emit a patch artifact. And give every noisy
investigation its own disposable conversation; return a distilled artifact,
not the noise.

## 13. Per-File Write Conversations

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
`~/.nagent/conversations/file-index-{pid}.json`, keys files by stable file id
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
nagent-file-edit --file src/foo.py --clear
nagent --list-file-edits
```

```json
{
  "by_file_id": {
    "2050:123456": {
      "file_id": "2050:123456",
      "path": "/repo/src/foo.py",
      "conversation": "foo-0c2f..."
    }
  }
}
```

**Build your own:** when work orbits one artifact, store memory on that
artifact's identity and scope write authority to it. Session memory = what
happened today. Artifact memory = what we learned about this file.

---

# Part VII — How This Differs From Frameworks

## 14. Own the Inputs

**Idea** — Use a framework when it buys something concrete. The question to
ask first is who owns the data.

nagent uses plain files, Python, subprocesses, and structured text. The
interesting part is artifact management and explicit data flow, not tool
calling. The point is not "frameworks bad." The point is that the inputs to
the system — prompts, conversations, tool results, summaries, indexes,
patches, harvested knowledge — should not be trapped inside an opaque layer
that hides, rewrites, stores, or modifies them beyond the transformations LLM
providers already perform. nagent keeps as much control as it can by making
every input transparent and editable.

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
9. Repository history → context blocks
10. Harvest dead conversations into a knowledge store; inject a bounded digest
11. Per-artifact memory with stable ids and bounded write authority
12. Split/index/patch for large files
13. Child loops for delegation

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
bin/helpers/nagent_gc_lib.py
```

Tests are executable notes: parser and protocol, conversation lifecycle, root
and install context, retries, tokens, sub-conversations, result wrappers,
write validation, file ids, file-edit index, git history, co-edited files,
summaries, split/patch, gc classification and harvest, providers, tool
descriptions, JSON output.

---

# Setup

```bash
pip install -r requirements.txt
export PATH="$PWD/bin:$PATH"
mkdir -p ~/.nagent
cp config.example.json ~/.nagent/config.json
```

Config: `NAGENT_CONFIG` or `~/.nagent/config.json`. CLI overrides config.

```json
{
  "provider": "openai",
  "model": "gpt-5.5"
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

nagent-gc                        # dry run: classify artifacts, estimate harvest cost
nagent-gc --apply                # harvest knowledge into ~/.nagent/knowledge/, reclaim space
nagent-gc --apply --no-harvest   # reclaim only, no LLM pass
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
