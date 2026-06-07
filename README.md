# nagent

**nagent** means **not-an-agent**.

nagent is a small reference implementation of agent-like terminal workflows. Its
central claim is not that the agent is smart or durable. The claim is:

**The persistent object is not the agent. The persistent object is the work.**

LLMs are temporary. Processes are temporary. Sub-agents are temporary. Context
windows are temporary. The durable part of the system is explicit data:
conversations, per-file conversations, root context files, repository history
summaries, historical coupling data, artifact neighborhoods, file summaries,
split indexes, and patch artifacts.

A text file, an LLM, structured tags, and a loop are the implementation of this
idea, not the idea itself.

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
architecture and build their own version.

---

## 1. Durable Work, Disposable Workers

**Idea** - The system preserves work, not processes.

```text
temporary worker
        |
        v
durable artifacts
        |
        v
next temporary worker
```

nagent is data-oriented. The data is more important than the code operating on
it. Behavior is a transformation over explicit state. Important state should be
inspectable, editable, and durable; it should not hide inside process memory.

| Hidden state | Explicit artifact |
| --- | --- |
| Prompt state in a running process | Conversation files under the nagent root |
| Private tool traces | Request tags and result wrappers appended as text |
| In-memory scratch state | Temp files, split segments, indexes, and patches |
| Framework-managed memory | User-editable files |

**Implementation** - `bin/nagent` stores conversations under
`~/.nagent/conversations/`. It appends user prompts, model responses, tool
results, parser corrections, interrupts, and child-agent results to the
conversation file. File-edit sessions create their own per-file conversations.
Large-file operations create split directories, `index.json` files, segment
files, summaries, and patch files.

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

The running Python process is just a worker over these artifacts.

**Build your own:** decide which files are the source of truth before designing
agent behavior. Make workers disposable and artifacts durable.

---

## 2. Text In, Text Out

**Idea** - The smallest useful primitive is text generation from a file.

LLMs forget. Therefore: put the prompt in a file and treat the model as a
temporary transformation function.

**Implementation** - `bin/nagent-llm-text` reads a text file, resolves provider
and model settings, calls `generate_text_with_usage()` from
`bin/helpers/nagent_llm.py`, and prints either plain text or JSON with token
usage. Provider support lives behind a small abstraction for `openai`,
`anthropic`, `google`, and `cursor`. Defaults come from `NAGENT_CONFIG` or
`~/.nagent/config.json`, with CLI flags overriding config.

`bin/nagent-llm-upload` is the adjacent primitive for artifacts that are better
handled through provider upload APIs, such as images, PDFs, office files, and
code documents. It rejects `.zip` archives, checks a 50 MB limit, and returns
text or JSON.

**Example**

```bash
echo "What is 2+2?" > question.txt
nagent-llm-text --file question.txt
```

Everything else in nagent is orchestration around this primitive.

**Build your own:** implement `generate_text(file) -> str` first. Keep it boring
enough that provider changes do not affect the rest of the architecture.

---

## 3. Conversations Are Editable State

**Idea** - The conversation file is not chat history. It is working state.

It is a tool transcript, correction channel, continuation point, and editable
artifact. Memory becomes stale. Therefore: allow conversations to be saved,
loaded, summarized, edited, branched, trimmed, copied, diffed, versioned, and
rewritten.

**The agent does not own its memory. The user does.**

| Session memory | Artifact memory |
| --- | --- |
| Belongs to a running session | Belongs to a file on disk |
| Often opaque | Openable and diffable |
| Expires with the process or service | Survives worker replacement |
| Optimized for conversation | Optimized for preserved work |

**Implementation** - `bin/nagent` creates conversation names with
`default_conversation_name()`, based on hostname and a shell identity from
`default_pid()`. It migrates older root-level conversation files into
`conversations/`. It exposes explicit maintenance commands:
`--save-conversation`, `--load-conversation`, `--summarize`, and
`--edit-conversation`.

Direct conversation-file editing is also part of the design. Because a
conversation is an ordinary file, you can open it in an editor and remove stale
tool output, rewrite a misleading assumption, or replace a long exchange with a
short note. `--edit-conversation` automates one version of that by archiving the
current conversation, running a file-edit session on the archived file, and then
loading the edited result.

Root context is explicit state too. `load_root_context()` reads
`~/.nagent/context.yaml` or `~/.nagent/context.md`. YAML context can be a list or
contain `paths:`, and nested `context.yaml` files are expanded recursively.

**Example**

```bash
nagent --status
nagent --save-conversation before-refactor
nagent --load-conversation before-refactor
nagent --summarize
nagent --edit-conversation "keep the decisions and remove obsolete logs"
```

**Build your own:** make memory a mutable data structure on disk. Treat editing
history as maintenance, not corruption.

---

## 4. Teach The Model An Output Format

**Idea** - Free-form model output is hard to execute. Use a visible protocol.

The startup prompt teaches the model the only tags it may emit. The parser is
strict: a valid response contains only recognized tags and whitespace.

**Implementation** - `build_initial_context()` and `create_initial_text()` in
`bin/nagent` generate runtime context: instance facts, environment, git remote
information, discovered tool descriptions, context-management rules, write
rules, large-file guidance, optional file-edit history, root context, and role
instructions. `parse_response()` parses the protocol with regular expressions.
`process_tags()` dispatches each tag to a handler.

Available tags:

| Tag | Meaning |
| --- | --- |
| `<nagent-response>...</nagent-response>` | Print a human response or return a child result. |
| `<nagent-read path="..."/>` | Read a small file inline. |
| `<nagent-file-read path="..."/>` | Read a file, splitting it first if needed. |
| `<nagent-file-patch index="..."/>` | Merge edited split segments through an index. |
| `<nagent-write path="...">...</nagent-write>` | Write content to an allowed path. |
| `<nagent-shell>...</nagent-shell>` | Run shell commands and append output. |
| `<nagent-next>...</nagent-next>` | Append a continuation prompt. |
| `<nagent-agent>...</nagent-agent>` | Delegate to a child nagent process. |

Handlers append result wrappers such as `<nagent-read-result>`,
`<nagent-file-read-result>`, `<nagent-file-patch-result>`,
`<nagent-write-result>`, `<nagent-shell-result>`, and
`<nagent-agent-result>`. These are not hidden return values; they become
conversation data.

**Example**

```xml
<nagent-read path="README.md" />
<nagent-shell>python3 -m unittest discover -s tests -v</nagent-shell>
<nagent-response>Done.</nagent-response>
```

**Build your own:** make the protocol plain enough to inspect. Put the contract
in the prompt and enforce it in a small parser.

---

## 5. The Loop

**Idea** - "Agent behavior" is mostly append, call, parse, act, append, repeat.

**Implementation** - The important reading path is:

```text
main()
  run_agent_loop()
    call_llm()
    parse_response()
    process_tags()
```

`run_agent_loop()` appends the user prompt, sends the whole conversation file to
`nagent-llm-text --json`, appends valid model output, processes tags, appends
results, and loops whenever an action or `<nagent-next>` added new state.

Parser retries are visible state. If `parse_response()` rejects the output,
`run_agent_loop()` appends the invalid response inside `<agent-response>`, then
appends a `<system>` correction telling the model to respond only with valid
nagent tags. It retries up to `MAX_FORMAT_RETRIES`, currently 3. Provider
errors are appended similarly. Failures become data, not invisible control flow.

`TokenStats` tracks turn count, current conversation input tokens, recursive
input tokens, and recursive output tokens. If provider usage is unavailable,
nagent estimates by character count. Child-agent JSON output contributes to the
recursive totals.

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

**Build your own:** after every action, append the result to durable state and
loop. Do not hide important errors or retry corrections in memory.

---

## 6. Persistent Per-File Memory

**Idea** - One conversation grows too large. Attach memory to artifacts.

Repeated work accumulates around individual files. Therefore: give each file
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

**Implementation** - `bin/nagent-file-edit` resolves a file-specific
conversation, then delegates to `bin/nagent --file-edit`. The index lives at
`~/.nagent/conversations/file-index-{pid}.json`. It uses stable file ids from
device and inode via `file_id_for_path()`, not just paths. If a file is renamed
but has the same inode, file-edit mode can still recognize it. Legacy path-only
indexes are normalized into the current `by_file_id` shape.

Per-file conversations preserve previous investigations, failed attempts, local
assumptions, file-specific context, editing history, historical context, and
large-file split/patch state. This keeps the main conversation smaller because
noisy local work stays near the artifact.

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

**Build your own:** when work keeps returning to the same artifact, store memory
beside that artifact's identity. Session memory answers "what happened today";
artifact memory answers "what have we learned about this file?"

---

## 7. Repository History As Data

**Idea** - A repository is not only the current file tree. Its history is also a
durable artifact.

Repository history can be transformed into editing context. This is not generic
retrieval. It is explicit transformation of historical artifacts into working
context for a target file.

```text
git history
    ->
commit/file summaries
    ->
file-edit initial context
    ->
better artifact-local edit decisions
```

**Implementation** - When a file-edit conversation starts and provider/model
settings are available, `file_edit_history_and_summary_block()` gathers git
history for the target file. `git_file_history()` reads recent commits.
`summarize_new_file_commits()` asks the LLM for one-sentence summaries of new
commits and reuses previous summaries found in the existing initial context.
`format_file_history()` records people who edited the file, step-by-step commit
history, files edited in the same commits, and summarized commits.

`run_file_summary()` calls `nagent-file-summarize` and stores a current file
summary in a `{file-summary}` block. The result is injected into the file-edit
initial context along with `{file-history}`. Historical context is a hint, not a
command.

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

**Build your own:** turn history into explicit context blocks. Cache summaries
inside the durable conversation so unchanged history is not repeatedly
re-summarized.

---

## 8. Historical Coupling And Artifact Neighborhoods

**Idea** - A file exists within a neighborhood of related artifacts.

Historical coupling can identify likely companion files, related tests, related
headers, related configuration, and frequently co-edited implementation files.
High co-edit files are candidates for inspection, not automatic edit targets.

```text
target file
        |
        +-- historical summary
        +-- co-edited files
        +-- local conversation
        +-- split indexes
```

**Implementation** - `coedited_file_rows()` counts files changed in the same
commits as the target file, then computes a high/medium/low historical co-edit
rate. `format_file_history()` places the table in the file-edit context and
adds guidance: inspect high-likelihood co-edited files when the requested change
may affect interfaces, tests, config, or paired code, but do not edit them
without evidence.

**Example**

| file | commits together | historical co-edit rate |
| --- | ---: | --- |
| `src/foo_test.py` | 7 | high (70%) |
| `src/foo.h` | 5 | medium (50%) |

The table says "changed with this file"; it does not say "must be changed now."

**Build your own:** compute artifact neighborhoods from historical artifacts,
then present them as inspection guidance. Keep the edit decision grounded in the
current request and current code.

---

## 9. Disposable Sub-Agents

**Idea** - Exploration creates noise. Use disposable workers.

Sub-agents are temporary nagent processes with isolated conversations. Their
lifetime is not important; the useful artifact they return is important.

| Long-lived agents | Disposable workers |
| --- | --- |
| Identity is central | Output artifact is central |
| Shared context can become noisy | Child context is isolated |
| Parent absorbs all exploration | Parent receives a concise result |
| Delegation implies personality | Delegation is context management |

**Implementation** - `<nagent-agent>` is handled by `execute_agent()`. The
parent starts `bin/nagent` with the same root, provider, model, config, and pid,
sets `--invocation delegated`, records the parent conversation, gives the child
a UUID-based conversation name, and requests `--json`. The parent appends a
`<nagent-agent-result>` containing the child conversation name, exit code,
returned output, stderr, and token totals.

The child has its own private conversation file. Parent and child do not share
context except through explicit prompt and result text.

**Example**

```xml
<nagent-agent>
Inspect the split and patch tests. Return only the behaviors the README should explain.
</nagent-agent>
```

**Build your own:** use child loops for bounded investigation, noisy diagnostics,
or parallel work. Return a distilled artifact to the parent, not every scratch
step.

---

## 10. Controlled Writes

**Idea** - A loop that can write files needs explicit boundaries.

nagent is a convention-based reference implementation, not a hardened sandbox.
Shell commands are powerful and run with normal OS permissions. Structured
writes are checked, but this is not a security boundary.

**Implementation** - `file_edit_rules()` writes the policy into the initial
context. `validate_write_path()` and `execute_write()` enforce it for
`<nagent-write>`.

| Mode | Structured write boundary |
| --- | --- |
| Main conversation | May write only under `/tmp`, `/var/tmp`, or `$TMPDIR`. |
| Per-file edit | May write the target file, the same file by stable file id, or split segments for that source. |

The large-file rule is integrated with file-edit mode: split segment files from
the target source may be edited, then merged through `nagent-file-patch`.
Rejected writes append `<nagent-write-result status="error">` to the
conversation.

**Example**

```xml
<nagent-write path="/tmp/nagent-note.txt">scratch note</nagent-write>
```

In normal mode, the same tag targeting `src/foo.py` is rejected with a visible
write-result error. Use `nagent-file-edit --file src/foo.py` for project edits.

**Build your own:** put write boundaries in both the prompt and the action
handler. Say plainly where the boundary ends.

---

## 11. Large Files As Explicit Artifacts

**Idea** - Large files exceed context windows. Create split/index/patch
artifacts instead of pretending the file is small.

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

**Implementation** - Inline reads are capped at 64 KB in `bin/nagent`.
`<nagent-file-read>` calls `nagent-file-split` when a file is larger. The split
tool uses `bin/helpers/nagent_file_split_lib.py` and type-specific helper
executables for `txt`, `md`, `cpp`, `py`, `xml`, `js`, `ts`, `json`, `yaml`,
`go`, `rs`, and `java`. It writes segment files and an `index.json` containing
source path, source hash, source size, line count, split type, target bytes,
natural-mode flag, creation time, segment count, and line ranges.

Natural splitters prefer structure: markdown headings, blank lines, Python
top-level definitions, brace depth for C-like languages, JSON/YAML depth, XML
tags, and language declarations. `--refresh` rebuilds segments from an existing
index after the source changes.

`nagent-file-patch` validates the source hash unless `--force` is used, merges
segment files, writes a unified diff patch artifact, optionally applies the
merged source, and refreshes index line numbers and hash. `--dry-run` writes the
patch without changing source or index. `--no-apply` writes the patch and
refreshes metadata without modifying the source.

`nagent-file-summarize` summarizes small files inline. For files over 64 KB, it
delegates to `nagent-file-split --summarize`, stores per-segment summaries in
`index.json`, and returns a combined summary.

**Example**

```bash
nagent-file-split --file src/big.py --output /tmp/big-split --json
# edit /tmp/big-split/big-0001.py
nagent-file-patch --index /tmp/big-split/index.json --json
nagent-file-summarize --file src/big.py --json
```

**Build your own:** make chunking a durable data structure. Store the index,
hash the source, edit bounded segment files, and write a patch artifact.

---

## 12. Tool Discovery

**Idea** - Tool capability should also be explicit data.

There is no central registry in nagent. Tools describe themselves.

**Implementation** - `exit_on_description()` in `bin/helpers/nagent_cli.py`
prints a tool's resolved path and description when `--description` appears in
`sys.argv`. `collect_bin_tool_descriptions()` iterates over executable files in
`bin/`, runs each with `--description`, and inserts successful descriptions into
the generated initial context.

Top-level tools currently described this way:

| Tool | Role |
| --- | --- |
| `nagent` | Main structured conversation loop. |
| `nagent-llm-text` | Send a text file to the configured LLM. |
| `nagent-llm-upload` | Upload a supported file with a prompt. |
| `nagent-file-edit` | Run a per-file conversation for one source file. |
| `nagent-file-split` | Split a large file into segment files and `index.json`. |
| `nagent-file-patch` | Merge edited segments, write a patch, validate hashes. |
| `nagent-file-summarize` | Summarize small files inline or large files through splits. |

**Example**

```bash
nagent --description
nagent-file-split --description
```

The startup prompt is assembled from executable descriptions, root context,
environment facts, and mode-specific rules. Even tool discovery is a data
pipeline.

**Build your own:** let tools emit their own capability descriptions. Build the
prompt from those descriptions instead of maintaining a hidden registry.

---

## 13. How This Differs From Frameworks

**Idea** - This is a different architectural style, not a claim that frameworks
are bad.

nagent uses plain files, Python, subprocesses, and structured text. The novel
part is artifact management and explicit data flow, not tool calling.

**Implementation** - The whole system is readable through `bin/nagent`, the
helper modules in `bin/helpers/`, thin command wrappers in `bin/`, and tests in
`tests/`.

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

| Object graphs | Data artifacts |
| --- | --- |
| Behavior is distributed across services and objects. | Behavior is a transformation over files. |
| State often lives behind interfaces. | State can be opened in an editor. |
| Runtime topology is central. | Artifact shape is central. |

| Retrieval | Preserved work |
| --- | --- |
| Find matching chunks at query time. | Keep conversations, summaries, history, and indexes as durable inputs. |
| Context appears as a service result. | Context appears as editable data. |

**Example**

```text
conversation file
    -> LLM output with tags
    -> parser
    -> action handlers
    -> result wrappers appended to conversation file
```

**Build your own:** use a framework when it buys something concrete. If the goal
is to learn the architecture, start with files and transformations.

---

## 14. Build Your Own

**Idea** - The architecture can be copied, modified, or rejected piece by piece.

The minimal system is not mystical. It is a small loop over explicit state.

**Implementation** - Read the code in this order:

```text
main()
  run_agent_loop()
    call_llm()
    parse_response()
    process_tags()
```

Then read:

```text
bin/helpers/nagent_llm.py
bin/helpers/nagent_cli.py
bin/helpers/nagent_file_edit_lib.py
bin/helpers/nagent_file_split_lib.py
bin/helpers/nagent_file_patch_lib.py
bin/helpers/nagent_file_summarize_lib.py
```

The tests are useful architecture notes. They cover parser behavior,
conversation lifecycle, root context loading, retry behavior, token accounting,
sub-agent isolation, result wrappers, write validation, stable file ids,
per-file edit indexing, git history context, people who edited a file,
co-edited files, file summaries, split metadata, natural splitting, refresh,
patch merging, hash validation, summary storage, upload classification, provider
configuration, tool descriptions, setup paths, and CLI JSON output.

**Example**

1. Implement `generate_text(file) -> str`.
2. Keep a growing conversation document.
3. Generate initial context that states the contract.
4. Define an output format and parser.
5. Write action handlers that append results back into state.
6. Loop after actions.
7. Retry malformed output with visible corrections.
8. Add child loops for delegated work.
9. Add per-artifact memory.
10. Transform repository history into artifact context.
11. Add split/index/patch for large files.
12. Add save/load/edit/summarize tools for memory maintenance.

**Build your own:** preserve work before preserving workers. If you can inspect,
edit, copy, summarize, and replay the important artifacts, the agent loop can
stay small.

---

## Setup

```bash
pip install -r requirements.txt
export PATH="$PWD/bin:$PATH"
mkdir -p ~/.nagent
cp config.example.json ~/.nagent/config.json
```

Configuration loads from `NAGENT_CONFIG` or `~/.nagent/config.json`. CLI flags
override config values.

```json
{
  "provider": "openai",
  "model": "gpt-5.5"
}
```

| Provider | Default model | Credential environment variable |
| --- | --- | --- |
| `openai` | `gpt-5.5` | `OPENAI_API_KEY` |
| `anthropic` | `claude-sonnet-4-6` | `ANTHROPIC_API_KEY` |
| `google` | `gemini-2.5-flash` | `GOOGLE_API_KEY` or `GEMINI_API_KEY` |
| `cursor` | `composer-2.5` | `CURSOR_API_KEY` |

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

Use `--help` for current flags. Use `--description` to see the description a
tool contributes to startup context.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

Some tests mock provider calls. Live integration tests call configured LLM
providers and require matching credentials.
