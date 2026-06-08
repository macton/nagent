# nagent

**nagent** means **not-an-agent**.

The word "agent" suggests continuity, intent, and memory that a typical LLM loop
does not actually provide. nagent is a small reference implementation. It shows
what terminal "agent-like" workflows are when you describe the mechanics instead
of the metaphor.

The claim is simple:

**The agent is not the thing. The data is the thing.**

nagent is a small reference example of a data-oriented approach to AI workflows.

The second claim follows from the first:

**Don't edit the output artifacts. Edit the prompt.**

If a generator produces output you do not like, fix the generator or the inputs
to that generator. Do not merely patch the generated output and leave the bad
input in place. In nagent, the conversation prompt is one of those inputs. If it
matters, it needs to be saveable, maintainable, organizable, and editable.

The LLM is temporary. The process is temporary. Sub-conversations are temporary.
Context windows are temporary. What survives is explicit data: conversations,
per-file conversations, root context files, repository history summaries,
historical coupling tables, artifact neighborhoods, file summaries, split
indexes, patch files, and other artifacts you can open in an editor.

A text file, an LLM, structured tags, and a loop are how this repo implements
that idea. They are not the idea.

```text
repository history
        +
root context
        +
conversation
        +
artifact-local memory
        +
artifact summary
        +
historical coupling
        +
user request
            ->
     LLM transformation
            ->
     updated artifacts
```

This README is a teaching document for programmers who want to understand the
reference example, the approach, and build their own version.

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

These are coordination tasks, not one-shot answers. nagent may read many files,
run commands, spawn sub-conversations for scoped work, and iterate. It does not
bypass permissions; it runs with the same access your user and filesystem allow.

---

## 1. Durable Work, Disposable Workers

**Idea** — Preserve work. Not processes.

```text
temporary worker
        |
        v
durable artifacts
        |
        v
next temporary worker
```

The data is more important than the code touching it. Behavior is a
transformation over explicit state. If state matters, put it in a file you can
inspect, diff, copy, and edit. Do not hide it in process memory and call that
"memory."


| Hidden state                      | Explicit artifact                                 |
| --------------------------------- | ------------------------------------------------- |
| Prompt state in a running process | Conversation files under the nagent root          |
| Private tool traces               | Request tags and result wrappers appended as text |
| In-memory scratch state           | Temp files, split segments, indexes, and patches  |
| Framework-managed memory          | User-editable files                               |


**Implementation** — `bin/nagent` stores conversations under
`~/.nagent/conversations/`. It appends user prompts, model responses, tool
results, parser corrections, interrupts, and sub-conversation results to the
conversation file. File-edit sessions get their own per-file conversations.
Large-file work creates split directories, `index.json`, segment files, summaries,
and patch artifacts.

**Example**

```text
artifact
    +
artifact-local memory
    +
historical artifacts
    +
user request
        ->
LLM transformation
        ->
updated artifacts
```

The Python process is a worker. The files are the system.

**Build your own:** decide which artifacts are source of truth before you design
"conversation behavior." Workers come and go. Data stays.

---

## 2. Text In, Text Out

**Idea** — The smallest useful primitive is: file in, text out.

LLMs forget. Therefore put the prompt in a file and treat the model as a
temporary function over that data.

**Implementation** — `bin/nagent-llm-text` reads a text file, resolves provider
and model settings, calls `generate_text_with_usage()` from
`bin/helpers/nagent_llm.py`, and prints plain text or JSON with token usage.
Provider support covers `openai`, `anthropic`, `google`, and `cursor`. Defaults
come from `NAGENT_CONFIG` or `~/.nagent/config.json`. CLI flags win.

`bin/nagent-llm-upload` is the sibling for artifacts that need upload APIs:
images, PDFs, office files, code documents. It rejects `.zip`, enforces a 50 MB
limit, returns text or JSON.

**Example**

```bash
echo "What is 2+2?" > question.txt
nagent-llm-text --file question.txt
```

Everything else in nagent is orchestration around this. Do not skip it.

**Build your own:** implement `generate_text(file) -> str` first. Boring.
Separate. Provider churn should not rewrite your loop.

---

## 3. Conversations Are Editable State

**Idea** — The conversation file is not chat history. It is working state.

Tool transcript. Correction channel. Continuation point. Mutable artifact. Memory
goes stale. Therefore let people save, load, summarize, edit, branch, trim,
copy, diff, version, and rewrite conversations.

**The conversation does not own its memory. The user does.**


| Session memory               | Artifact memory              |
| ---------------------------- | ---------------------------- |
| Belongs to a running session | Belongs to a file on disk    |
| Often opaque                 | Openable and diffable        |
| Dies with the process        | Survives worker replacement  |
| Optimized for chat UX        | Optimized for preserved work |


**Implementation** — `bin/nagent` names conversations with
`default_conversation_name()` from hostname and shell identity via
`default_pid()`. It migrates legacy root-level conversation files into
`conversations/`. Maintenance commands: `--save-conversation`,
`--load-conversation`, `--summarize`, `--edit-conversation`.

There are two forms of editing. Explicit editing goes through commands:
`--save-conversation`, `--load-conversation`, `--summarize`,
`--edit-conversation`. Implicit editing comes from the fact that conversations
are ordinary files: open them, trim them, rewrite them, diff them, copy them,
version them, script them. Delete stale tool spam, fix a bad assumption, replace
ten pages with one paragraph. `--edit-conversation` automates one path: archive
current file, run file-edit on the archive, load the result.

Root context is explicit too. `load_root_context()` reads `~/.nagent/context.yaml`
or `~/.nagent/context.md`. YAML can be a list or `{ "paths": [...] }`. Nested
`context.yaml` files expand recursively.

**Example**

```bash
nagent --status
nagent --save-conversation before-refactor
nagent --load-conversation before-refactor
nagent --summarize
nagent --edit-conversation "keep the decisions and remove obsolete logs"
```

**Build your own:** memory is a data structure on disk. Editing history is
maintenance, not corruption.

---

## 4. Teach The Model An Output Format

**Idea** — Free-form model output is hard to execute. Use a visible protocol.

The startup prompt lists the only tags the model may emit. The parser is strict:
recognized tags and whitespace. Nothing else.

**Implementation** — `build_initial_context()` and `create_initial_text()` in
`bin/nagent` assemble runtime context: instance facts, environment, git remotes,
discovered tool descriptions, context-management rules, write rules, large-file
guidance, the structured tag protocol, optional file-edit history, root context,
role instructions. The tag list and usage rules live inside `<initial_context>`,
so refreshed context carries the current protocol with it.
`parse_response()` parses with regex. `process_tags()` dispatches handlers.

Tags:


| Tag                                           | Meaning                                |
| --------------------------------------------- | -------------------------------------- |
| `<nagent-response>...</nagent-response>`      | Human response or child result.        |
| `<nagent-read path="..."/>`                   | Read a small file inline.              |
| `<nagent-file-read path="..."/>`              | Read a file; split first if needed.    |
| `<nagent-file-patch index="..."/>`            | Merge edited split segments via index. |
| `<nagent-write path="...">...</nagent-write>` | Write to an allowed path.              |
| `<nagent-shell>...</nagent-shell>`            | Run shell; append output.              |
| `<nagent-next>...</nagent-next>`              | Append a continuation prompt.          |
| `<nagent-conversation>...</nagent-conversation>` | Start an isolated sub-conversation. |


Handlers append `<nagent-read-result>`, `<nagent-file-read-result>`,
`<nagent-file-patch-result>`, `<nagent-write-result>`, `<nagent-shell-result>`,
`<nagent-conversation-result>`. These are not secret return values. They are
conversation data.

**Example**

```xml
<nagent-read path="README.md" />
<nagent-shell>python3 -m unittest discover -s tests -v</nagent-shell>
<nagent-response>Done.</nagent-response>
```

**Build your own:** put the contract in the prompt. Enforce it in a small parser.
If you cannot read the protocol, you cannot debug the system.

---

## 5. The Loop

**Idea** — "Agent behavior" is mostly: append, call, parse, act, append, repeat.

That pattern is the core loop. Heavier systems add infrastructure around the
same steps.

**Implementation** — Read this path:

```text
main()
  run_agent_loop()
    call_llm()
    parse_response()
    process_tags()
```

`run_agent_loop()` appends the user prompt, sends the whole conversation to
`nagent-llm-text --json`, appends valid output, processes tags, appends results,
loops when an action or `<nagent-next>` added state.

Parser retries are visible. Bad output goes into `<agent-response>` plus a
`<system>` correction. Up to `MAX_FORMAT_RETRIES` (3). Provider errors append
too. Failures become data, not invisible control flow.

`TokenStats` tracks turns, conversation input size, recursive input/output tokens.
No provider usage? Estimate from character count. Child `--json` output rolls up
into recursive totals.

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

---

## 6. Persistent Per-File Memory

**Idea** — One conversation grows too large. Attach memory to artifacts.

Work keeps coming back to the same files. Therefore give each file its own
persistent local memory.

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
conversation, delegates to `bin/nagent --file-edit`. Index:
`~/.nagent/conversations/file-index-{pid}.json`. Stable file ids from device +
inode via `file_id_for_path()`, not just paths. Rename with same inode? Still
works. Legacy path-only indexes normalize to `by_file_id`.

Per-file conversations hold prior investigations, dead ends, local assumptions,
edit history, git history blocks, summaries, split/patch state. Main conversation
stays smaller. Noise lives next to the artifact.

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

**Build your own:** when work orbits one artifact, store memory on that identity.
Session memory = what happened today. Artifact memory = what we learned about
this file.

---

## 7. Repository History As Data

**Idea** — A repo is not only the current tree. History is data too.

Transform git history into editing context for a target file. Not vague
"retrieval." Explicit transformation of historical artifacts into working input.

```text
git history
    ->
commit/file summaries
    ->
file-edit initial context
    ->
better edit decisions
```

**Implementation** — On file-edit start (with provider/model),
`file_edit_history_and_summary_block()` gathers git history.
`git_file_history()` reads recent commits. `summarize_new_file_commits()` asks
the LLM for one-line summaries of new commits; reuses cached summaries from prior
initial context. `format_file_history()` records editors, step history, co-edited
files, summarized commits.

`run_file_summary()` calls `nagent-file-summarize`; result goes in
`{file-summary}`. Injected with `{file-history}`. Hints, not commands.

**Example**

```text
{file-history}
File: src/foo.py

Individuals who edited this file:
- Alice <alice@example.com>: 3 commits

Step-by-step history:
- 2026-05-01 abc123 Alice: Adds validation.

Summarized commits:
- <full-hash> (abc123): Adds validation to foo parsing.
{/file-history}

{file-summary}
File: /repo/src/foo.py
Source: nagent-file-summarize

Implements foo parsing and validation.
{/file-summary}
```

**Build your own:** turn history into explicit context blocks. Cache summaries in
the durable conversation. Do not re-pay LLM cost for unchanged history.

---

## 8. Historical Coupling And Artifact Neighborhoods

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
        +-- split indexes
```

**Implementation** — `coedited_file_rows()` counts files in the same commits as
the target, labels high/medium/low co-edit rate. `format_file_history()` puts the
table in file-edit context and adds guidance: inspect high co-edit files when
the change may touch interfaces, tests, config, or paired code. High co-edit
files are candidates for inspection, not automatic edit targets. Do not edit
them unless the request or evidence requires it.

**Example**


| file              | commits together | historical co-edit rate |
| ----------------- | ---------------- | ----------------------- |
| `src/foo_test.py` | 7                | high (70%)              |
| `src/foo.h`       | 5                | medium (50%)            |


The table says "changed with this file." It does not say "must change now."

**Build your own:** compute neighborhoods from history. Present as inspection
guidance. Ground edits in the current request and current code, not historical
association alone.

---

## 9. Disposable Sub-Conversations

**Idea** — Exploration creates noise. Spawn disposable workers.

Sub-conversations are temporary nagent processes with isolated conversations.
Their lifetime does not matter. The artifact they return matters.


| Long-lived agent abstractions  | Disposable workers               |
| ------------------------------ | -------------------------------- |
| Identity is central            | Output artifact is central       |
| Shared context gets noisy      | Child context is isolated        |
| Parent absorbs all exploration | Parent gets a concise result     |
| Delegation implies personality | Delegation is context management |


**Implementation** — `<nagent-conversation>` is the protocol tag for delegated
sub-conversations. The parent starts `bin/nagent` with same root, provider, model,
config, pid; `--invocation delegated`; parent conversation recorded; UUID child
conversation; `--json`.
Parent appends `<nagent-conversation-result>` with child name, exit code, output,
stderr, token totals.

The child has its own conversation file. No shared context except explicit prompt
and result text.

**Example**

```xml
<nagent-conversation>
Inspect the split and patch tests. Return only the behaviors the README should explain.
</nagent-conversation>
```

**Build your own:** child loops for bounded investigation and noisy diagnostics.
Return a distilled artifact to the parent, not every intermediate step.

---

## 10. Controlled Writes

**Idea** — A loop that writes files needs explicit boundaries.

nagent is a reference implementation with conventions, not a sandbox. Shell runs
with your permissions. Structured writes are checked. That is not a security
boundary. Do not pretend it is.

**Implementation** — `file_edit_rules()` writes policy into initial context.
`validate_write_path()` and `execute_write()` enforce `<nagent-write>`.


| Mode              | Structured write boundary                                            |
| ----------------- | -------------------------------------------------------------------- |
| Main conversation | `/tmp`, `/var/tmp`, or `$TMPDIR` only.                               |
| Per-file edit     | Target file (by path or file id), or split segments for that source. |


Large-file rule: edit split segments for the target, merge with
`nagent-file-patch`. Rejected writes append
`<nagent-write-result status="error">` to the conversation.

**Example**

```xml
<nagent-write path="/tmp/nagent-note.txt">scratch note</nagent-write>
```

Same tag on `src/foo.py` in main mode? Rejected. Visible error. Use
`nagent-file-edit --file src/foo.py` for project edits.

**Build your own:** write boundaries in prompt and handler. Say where the line
is. Mean it.

---

## 11. Large Files As Explicit Artifacts

**Idea** — Big files exceed context. Split them. Do not pretend they fit.

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

**Implementation** — Inline reads cap at 64 KB in `bin/nagent`. `<nagent-file-read>`
calls `nagent-file-split` when larger. Split uses
`bin/helpers/nagent_file_split_lib.py` and type helpers for `txt`, `md`, `cpp`,
`py`, `xml`, `js`, `ts`, `json`, `yaml`, `go`, `rs`, `java`. Writes segment
files and `index.json`: source path, hash, size, line count, split type, target
bytes, natural flag, timestamps, segment count, line ranges.

Natural splitters prefer structure: headings, blank lines, Python defs, brace
depth, JSON/YAML depth, XML tags, declarations. `--refresh` rebuilds from index
after source changes.

`nagent-file-patch` validates source hash (unless `--force`), merges segments,
writes unified diff patch, applies merged source, refreshes index.
`--dry-run` / `--no-apply` for partial workflows.

`nagent-file-summarize`: small files inline; over 64 KB via
`nagent-file-split --summarize`; per-segment summaries in `index.json`; combined
summary returned.

**Example**

```bash
nagent-file-split --file src/big.py --output /tmp/big-split --json
# edit /tmp/big-split/big-0001.py
nagent-file-patch --index /tmp/big-split/index.json --json
nagent-file-summarize --file src/big.py --json
```

**Build your own:** chunking is a data structure. Index it. Hash the source.
Edit bounded segments. Emit a patch artifact.

---

## 12. Tool Discovery

**Idea** — Tool capability should be explicit data too.

No central registry. Tools describe themselves.

**Implementation** — `exit_on_description()` in `bin/helpers/nagent_cli.py` prints
path + description when `--description` is in `sys.argv`.
`collect_bin_tool_descriptions()` runs each executable in `bin/` with
`--description` and inserts results into initial context.


| Tool                    | Role                                           |
| ----------------------- | ---------------------------------------------- |
| `nagent`                | Main structured conversation loop.             |
| `nagent-llm-text`       | Send a text file to the configured LLM.        |
| `nagent-llm-upload`     | Upload a supported file with a prompt.         |
| `nagent-file-edit`      | Per-file conversation for one source file.     |
| `nagent-file-split`     | Split large file into segments + `index.json`. |
| `nagent-file-patch`     | Merge segments, write patch, validate hashes.  |
| `nagent-file-summarize` | Summarize inline or via split summaries.       |


**Example**

```bash
nagent --description
nagent-file-split --description
```

Startup prompt = executable descriptions + root context + environment + mode
rules. Even discovery is a data pipeline.

**Build your own:** tools emit capability text. Assemble prompts from that. Do
not maintain a hidden registry that drifts.

---

## 13. How This Differs From Frameworks

**Idea** — Own the data inputs. Keep them visible and editable.

nagent uses plain files, Python, subprocesses, structured text. The interesting
part is artifact management and explicit data flow, not tool calling by itself.
The point is not to argue against frameworks. The point is to keep the inputs to
the system out of an opaque layer that hides, rewrites, stores, or modifies the
data you are using. LLM providers already transform data enough. nagent keeps as
much control as it can by making prompts, conversations, tool results, summaries,
indexes, and patches transparent and editable.

**Implementation** — Read `bin/nagent`, `bin/helpers/`, thin wrappers in
`bin/`, tests in `tests/`. That is the system.


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



| Object graphs                                     | Data artifacts                         |
| ------------------------------------------------- | -------------------------------------- |
| Behavior distributed across services and objects. | Behavior is transformation over files. |
| State behind interfaces.                          | State in an editor buffer.             |
| Runtime topology is central.                      | Artifact shape is central.             |



| Retrieval                    | Preserved work                                                     |
| ---------------------------- | ------------------------------------------------------------------ |
| Find chunks at query time.   | Keep conversations, summaries, history, indexes as durable inputs. |
| Context as a service result. | Context as editable data.                                          |


**Example**

```text
conversation file
    -> LLM output with tags
    -> parser
    -> action handlers
    -> result wrappers appended to conversation file
```

**Build your own:** use a framework when it buys something concrete. If the
goal is to learn the data flow, start with files and transformations.

---

## 14. Build Your Own

**Idea** — Copy it, steal pieces, or reject it. Your call.

The minimal system is not mystical. Small loop over explicit state.

**Implementation** — Read in order:

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
bin/helpers/nagent_file_edit_lib.py
bin/helpers/nagent_file_split_lib.py
bin/helpers/nagent_file_patch_lib.py
bin/helpers/nagent_file_summarize_lib.py
```

Tests are executable notes: parser, conversation lifecycle, root context,
retries, tokens, sub-conversations, result wrappers, write validation, file ids,
file-edit index, git history, co-edited files, summaries, split/patch, uploads,
providers, tool descriptions, JSON output.

**Example**

1. `generate_text(file) -> str`
2. Growing conversation document
3. Initial context with the contract
4. Output format + parser
5. Handlers that append results to state
6. Loop after actions
7. Visible retry on malformed output
8. Child loops for delegation
9. Per-artifact memory
10. Repository history → context blocks
11. Split/index/patch for large files
12. Save/load/edit/summarize for memory maintenance

**Build your own:** preserve work before preserving workers. If you can inspect,
edit, copy, summarize, and replay the artifacts, the loop can stay small.

---

## Setup

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


| Provider    | Default model       | Credential environment variable      |
| ----------- | ------------------- | ------------------------------------ |
| `openai`    | `gpt-5.5`           | `OPENAI_API_KEY`                     |
| `anthropic` | `claude-sonnet-4-6` | `ANTHROPIC_API_KEY`                  |
| `google`    | `gemini-2.5-flash`  | `GOOGLE_API_KEY` or `GEMINI_API_KEY` |
| `cursor`    | `composer-2.5`      | `CURSOR_API_KEY`                     |


## Common Commands

```bash
nagent "your prompt here"
echo "prompt from stdin" | nagent
nagent "Use this instruction, then read stdin:" -
nagent --status --json
nagent --list-models --json
nagent --clear
nagent --save-conversation saved-copy
nagent --load-conversation saved-copy
nagent --summarize
nagent --edit-conversation "summarize useful parts and remove noise"
nagent --file-edit src/foo.py "make this change"
nagent --list-file-edits

nagent-llm-text --file question.txt --json
nagent-llm-upload --file diagram.png --prompt "Explain the diagram." --json
nagent-file-edit --file src/foo.py "add validation"
nagent-file-split --file src/big.py --output /tmp/big-split --json
nagent-file-patch --index /tmp/big-split/index.json --json
nagent-file-summarize --file src/big.py --json
```

`--help` for flags. `--description` for what a tool contributes to startup
context.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

Some tests mock providers. Live integration tests need real credentials.

## License

MIT — see [LICENSE](LICENSE).