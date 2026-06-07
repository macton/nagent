# nagent

**nagent** means **not-an-agent**.

nagent is a small, readable reference implementation of agent-like terminal
workflows: **a text file, an LLM, structured tags, and a loop**.

Those are mechanisms, not the idea. The idea is that the persistent object is
not the agent. The persistent object is the work.

LLMs are temporary. Processes are temporary. Context windows are temporary. The
durable part of nagent is explicit data: conversations, per-file conversations,
root context files, split indexes, summaries, and patch artifacts. The loop
exists to transform those artifacts.

This README is a teaching document for programmers who want to understand the
architecture and build their own version. It is not marketing material.

## What It Looks Like

```bash
nagent "Inspect this repository and explain how it works."
nagent "Update README.md after reading the source and tests."
nagent --status
nagent --clear
nagent --save-conversation before-readme
nagent --load-conversation before-readme
nagent --summarize
nagent --edit-conversation "remove stale tool output and keep the useful decisions"
nagent --file-edit README.md "tighten the architecture section"
nagent --list-file-edits
```

The command may perform several LLM calls, read files, run shell commands,
delegate to child processes, and print a final response. The work is still
anchored in ordinary files.

---

## 1. Durable Work, Disposable Workers

The central reduction is simple:

```text
temporary worker
      |
      v
durable artifact -> LLM transformation -> durable artifact
```

nagent does not try to make the process durable. It makes the work durable.

The main process can exit. A child process can fail. The model can forget what it
said five turns ago. The useful state remains in files that can be opened,
diffed, edited, copied, summarized, or loaded into another run.

In data-oriented terms:

| Principle | In nagent |
| --- | --- |
| State should be explicit. | Conversation files, file indexes, split indexes, summaries, and patches are visible on disk. |
| State should be inspectable. | Tool requests and tool results are appended as text. |
| State should be editable. | Conversation history can be saved, loaded, summarized, edited, or rewritten directly. |
| Behavior transforms data. | The loop reads an artifact, asks an LLM for a transformation, applies actions, and appends results. |
| Temporary execution is separate from durable state. | LLM calls and subprocesses are interchangeable workers over durable artifacts. |

This is why "agent" is the wrong persistent noun. The persistent object is the
work artifact.

**Build your own:** decide which files are the durable source of truth before
you design any agent behavior. Treat processes and models as temporary
transform functions.

---

## 2. Text In, Text Out

The smallest primitive is not an agent loop. It is a function:

```text
generate_text(file) -> text
```

In this repository, that primitive is `bin/nagent-llm-text`. It reads a text
file, resolves a provider and model, sends the file contents to the LLM, and
prints the response. With `--json`, it also returns usage data:

```bash
nagent-llm-text --file question.txt
nagent-llm-text --file question.txt --json
```

Provider-specific code lives in `bin/helpers/nagent_llm.py`. It supports
`openai`, `anthropic`, `google`, and `cursor`; resolves defaults from
`NAGENT_CONFIG` or `~/.nagent/config.json`; checks credentials; lists models;
and normalizes usage counts when providers expose them.

There is also `bin/nagent-llm-upload` for files that are better handled as
provider uploads, such as images, PDFs, office documents, CSV/JSON/text/code
files, and related formats. It rejects archives such as `.zip`, enforces a 50 MB
limit, and returns text or JSON.

Everything else is orchestration around text generation.

**Build your own:** start with one boring command that sends a file to a model
and returns text. Add orchestration only after that primitive is easy to test.

---

## 3. Conversations Are Editable State

Observation: LLMs forget.

Therefore: put memory in files.

nagent stores conversations under the root directory, normally:

```text
~/.nagent/conversations/latest-{hostname}-{pid}
```

The conversation file is not merely chat history. It is:

| Role | Meaning |
| --- | --- |
| Working state | The current prompt, prior model output, and accumulated tool results. |
| Tool transcript | Reads, writes, shell commands, child results, and errors are visible. |
| Correction channel | Invalid model output and retry instructions are appended for the next turn. |
| Continuation point | A later invocation can keep working from the same file. |
| Editable artifact | The user can save, load, trim, branch, rewrite, or summarize it. |

Explicit editing commands:

```bash
nagent --save-conversation saved-copy
nagent --load-conversation saved-copy
nagent --summarize
nagent --edit-conversation "keep the decisions and remove obsolete logs"
```

Implicit editing is just as important. Because the conversation is an ordinary
file, it can be opened, edited, trimmed, rewritten, diffed, copied, versioned,
or scripted. The agent does not own its memory. The user does.

Startup context is explicit too. `load_root_context()` reads
`~/.nagent/context.yaml` or `~/.nagent/context.md`. A YAML file can be a list or
contain `paths:`; nested `context.yaml` files are expanded recursively. That
root context is inserted into the generated initial context before the role
instructions.

Default conversation naming is intentionally mundane. `default_pid()` prefers a
GNU screen `STY`/`WINDOW` pair, then `BASHPID`, then the parent process id.
`default_conversation_name()` combines that id with the hostname.

**Build your own:** make memory a mutable data structure on disk. Let users
rewrite history when the history has become less useful than a clean summary.

---

## 4. Teach The Model An Output Format

Observation: free-form model output is hard to execute safely.

Therefore: teach the model a small output language.

`create_initial_text()` and `build_initial_context()` generate the runtime
prompt. It includes environment facts, git context, root context, tool
descriptions, write rules, large-file guidance, role instructions, and the
allowed tags.

The parser contract in `parse_response()` is strict: a response must contain
only nagent tags and whitespace. Unexpected text is a parse error.

Allowed request tags:

| Tag | Meaning |
| --- | --- |
| `<nagent-response>...</nagent-response>` | Print a response to the human, or return a result to the parent. |
| `<nagent-read path="..."/>` | Read a small file inline. |
| `<nagent-file-read path="..."/>` | Read a file, splitting it first if it exceeds the inline limit. |
| `<nagent-file-patch index="..."/>` | Merge edited split segments back into their source file. |
| `<nagent-write path="...">...</nagent-write>` | Write content to an allowed path. |
| `<nagent-shell>...</nagent-shell>` | Run shell commands and append stdout, stderr, and exit code. |
| `<nagent-next>...</nagent-next>` | Append a continuation prompt to the same conversation. |
| `<nagent-agent>...</nagent-agent>` | Start a delegated child nagent process. |

The action handlers append result wrappers:

```xml
<nagent-read-result path="...">...</nagent-read-result>
<nagent-file-read-result path="..." mode="split" ...>...</nagent-file-read-result>
<nagent-file-patch-result index="..." status="ok" ... />
<nagent-write-result path="..." status="ok" />
<nagent-shell-result>
exit_code: 0
stdout:
...
</nagent-shell-result>
<nagent-agent-result conversation="..." tokens_in="..." tokens_out="...">...</nagent-agent-result>
```

`clean_user_output()` strips accidental whole-response wrappers or a single
surrounding markdown fence before printing human-visible output. The protocol is
text, but it still has a contract.

**Build your own:** use structured text before reaching for a framework schema.
Keep the grammar small enough that the parser is easy to inspect.

---

## 5. The Loop

Observation: "agent behavior" is mostly repetition.

Therefore: make the repetition visible.

The main path is:

```text
main()
  run_agent_loop()
    append <user-prompt>
    call_llm()
    parse_response()
    process_tags()
```

The algorithm is:

```text
append the user prompt to the conversation

loop:
    send the conversation file to the LLM
    parse the LLM response as nagent tags

    if parsing fails:
        append the bad response
        append a format correction
        retry

    append the valid model response
    execute requested actions
    append action results

    if actions or next prompts were appended:
        continue

    print responses
    stop
```

Malformed output retries are data, not hidden control flow. On parser failure,
`run_agent_loop()` appends the invalid response and a `<system>` correction,
then tries again up to `MAX_FORMAT_RETRIES`, currently 3. LLM provider errors
are appended in the same way. If retries are exhausted, the loop returns an
error response.

Failures become visible state. They are part of the work artifact.

Token accounting is deliberately simple. `TokenStats` tracks turn count,
conversation input tokens, recursive input tokens, and recursive output tokens.
`nagent-llm-text --json` supplies usage when available; otherwise nagent falls
back to a rough character estimate. Child agent JSON output contributes to the
recursive totals. Direct user runs print a final status line unless the run is
not user-direct or `NAGENT_NO_SPINNER=1` disables the spinner.

**Build your own:** after every action, append the result to durable state and
call the model again. Do not keep important loop state only in memory.

---

## 6. Persistent Per-File Memory

Observation: one conversation grows too large.

Therefore: attach memory to artifacts.

Observation: repeated work accumulates around individual files.

Therefore: give each file persistent local memory.

Most coding agents remember sessions. nagent remembers artifacts.

`nagent-file-edit` runs nagent against a single file with a dedicated
conversation. The lower-level implementation is `nagent --file-edit PATH`; the
wrapper resolves the per-file conversation and delegates to the main command.

```bash
nagent-file-edit --file src/foo.py "add validation"
nagent-file-edit --file src/foo.py --clear
nagent --list-file-edits
```

Per-file conversations preserve:

| Artifact-local memory | Why it matters |
| --- | --- |
| Previous attempts | Avoid repeating a failed fix. |
| Failed commands | Keep local debugging history out of the parent conversation. |
| Local assumptions | Record file-specific decisions near the artifact. |
| Editing history | Continue work on the same file later. |
| Split/patch context | Allow large-file segment edits inside the file-edit write boundary. |

Stable file ids come from device and inode in `file_id_for_path()`. The index is
stored as JSON under:

```text
~/.nagent/conversations/file-index-{pid}.json
```

That index maps `file_id` to the resolved path and conversation name. Legacy
path-only indexes are normalized when loaded. If a file is renamed but has the
same inode, the edit session can still recognize it.

Artifact-local memory keeps the main conversation small. The parent can say
"edit this file"; the file conversation stores the noisy local work.

**Build your own:** when work repeatedly targets the same artifact, move memory
to that artifact. Preserve useful work, not chat for its own sake.

---

## 7. Disposable Sub-Agents

Observation: exploration creates noise.

Therefore: use disposable sub-agents.

A sub-agent is just another nagent process with a private conversation:

```xml
<nagent-agent>
Inspect the file split tests. Return only the behaviors the README should mention.
</nagent-agent>
```

`execute_agent()` starts the child with the same root, provider, model, config,
and pid. It sets `--invocation delegated`, records the parent conversation name,
uses a UUID-based child conversation name, and requests `--json` output. The
parent appends only the useful returned response and token totals in a
`<nagent-agent-result>`.

The child's lifetime is not important. Its transcript may contain exploratory
commands, dead ends, and local context. The parent keeps coordination and
decisions.

Delegation is primarily context management. It prevents the parent conversation
from filling with logs that are useful only while investigating one question.

**Build your own:** spawn child loops for bounded research or execution. Return
a summary artifact to the parent, not the whole noisy transcript.

---

## 8. Controlled Writes

Observation: a loop that can write files needs boundaries.

Therefore: make write boundaries explicit.

nagent has two structured write modes:

| Mode | Structured write rule |
| --- | --- |
| Main conversation mode | `<nagent-write>` may write only under `/tmp`, `/var/tmp`, or `$TMPDIR`. |
| Per-file edit mode | `<nagent-write>` may write the target file, the same file by stable file id after rename, or split segments associated with that target. |

The rules are generated into the initial context by `file_edit_rules()` and
enforced by `validate_write_path()` and `execute_write()`.

This is a convention-based reference implementation, not a hardened sandbox.
Shell commands still run as subprocesses with normal OS permissions. The prompt
tells the model not to use shell commands to write project files, and structured
writes are checked, but this is not a security boundary.

The reason the rule exists is architectural: writes should be visible,
restricted by mode, and represented as data. A failed write appends a
`<nagent-write-result status="error">` wrapper to the conversation.

**Build your own:** put write policy in both the prompt contract and the action
handler. Be honest about what the policy does and does not protect.

---

## 9. Large Files As Explicit Artifacts

Observation: large files exceed context windows.

Therefore: create explicit split, index, summary, and patch artifacts.

Inline reads are capped at 64 KB by `READ_SPLIT_THRESHOLD_BYTES`. If a model asks
for `<nagent-read>` on a larger file, `execute_read()` returns an error telling
it to use `<nagent-file-read>`.

`<nagent-file-read>` either returns small files inline or calls
`nagent-file-split` and returns an index path plus segment paths. Split output
lives under the nagent root, in `splits/{slug}-{uuid}/`, when invoked by the
main loop.

The split/edit/patch workflow is:

```text
source file
  -> segment files + index.json
  -> edit selected segments
  -> unified diff patch
  -> refreshed source file + refreshed index.json
```

`nagent-file-split` uses `bin/helpers/nagent_file_split_lib.py` plus per-type
helper executables. It stores durable metadata in `index.json`: source path,
source hash, source size, line count, split type, target bytes, natural-mode
flag, creation time, segment count, and segment paths/line ranges.

Supported split types are `txt`, `md`, `cpp`, `py`, `xml`, `js`, `ts`, `json`,
`yaml`, `go`, `rs`, and `java`, with extension aliases such as `.tsx`, `.jsonc`,
`.yml`, `.html`, `.pyi`, and `.mdx`. Natural split mode prefers type-specific
boundaries such as paragraphs, headings, top-level Python definitions, braces,
JSON/YAML depth, XML tags, and language declarations.

`nagent-file-patch` validates the source hash before applying edits unless
`--force` is used. It merges segments, writes a unified diff patch artifact,
optionally applies the merged text, and refreshes index line numbers and the
source hash. `--dry-run` writes the patch without changing the source or index;
`--no-apply` refreshes the index without modifying the source file.

`nagent-file-summarize` summarizes small files inline. For files over 64 KB it
delegates to `nagent-file-split --summarize`, stores per-segment summaries in
`index.json`, and returns a combined summary.

**Build your own:** when context is too large, do not hide chunking inside an
opaque retriever. Write the split index down, edit bounded artifacts, and verify
the source before merging.

---

## 10. Tool Discovery

Observation: tool registries can become hidden state.

Therefore: let executables describe themselves.

Each top-level helper supports `--description`. `exit_on_description()` prints
the executable path and description, then exits. `collect_bin_tool_descriptions()`
iterates over executable files in `bin/`, runs each with `--description`, and
inserts the collected text into the generated initial context.

There is no central registry. The startup prompt is assembled from explicit
data produced by the tools themselves.

Top-level tools:

| Tool | Role |
| --- | --- |
| `nagent` | Main conversation loop and orchestration entrypoint. |
| `nagent-llm-text` | Send a text file to the configured LLM. |
| `nagent-llm-upload` | Upload a supported artifact with a prompt. |
| `nagent-file-edit` | Run a per-file conversation for one source file. |
| `nagent-file-split` | Split large files into segment files plus `index.json`. |
| `nagent-file-patch` | Merge edited segments, write a patch, validate hashes, refresh metadata. |
| `nagent-file-summarize` | Summarize small files inline or large files through split summaries. |

Shared CLI helpers in `bin/helpers/nagent_cli.py` provide JSON output,
`--description` handling, and the optional wait spinner.

**Build your own:** make tool discovery executable and inspectable. A registry
can be a derived artifact, not a place where behavior hides.

---

## 11. How This Differs From Frameworks

nagent is not an argument against frameworks. It is a different architectural
style.

| Framework-oriented style | nagent data-oriented style |
| --- | --- |
| Hidden state in object graphs, services, threads, or managed stores. | Explicit files: conversations, indexes, summaries, patches. |
| Behavior described as agents with capabilities. | Behavior described as transformations over artifacts. |
| Tool registry owned by framework code. | Executables describe themselves with `--description`. |
| Session memory is primary. | Artifact memory is primary. |
| Orchestration hidden behind framework abstractions. | `run_agent_loop()` shows append, call, parse, act, append, repeat. |
| Tool failures may be exceptions or logs. | Failures are appended to conversation state. |
| Large-context handling may be implicit. | Split indexes and summaries are durable data structures. |

The tradeoff is visible in the code. nagent is less polished, less abstract, and
less protected than a production framework. It is also small enough to read in
one sitting.

**Build your own:** use a framework when it buys you something real. Otherwise,
start with explicit artifacts and visible transformations.

---

## 12. Build Your Own

The whole system can be reduced to a recipe:

1. Implement `generate_text(file) -> text`.
2. Keep a durable conversation document.
3. Generate initial context from explicit environment and tool data.
4. Teach the model a small structured protocol.
5. Parse the protocol strictly.
6. Run action handlers.
7. Append every result to the conversation.
8. Retry malformed output by appending the failure and correction.
9. Add child loops for noisy or scoped work.
10. Add artifact-local memory for repeated work on the same file.
11. Add split/index/summary/patch artifacts for large files.
12. Let users save, load, summarize, edit, branch, and rewrite memory.

Code reading order:

```text
bin/nagent
  main()
  run_agent_loop()
  call_llm()
  parse_response()
  process_tags()
  execute_read()
  execute_file_read()
  execute_write()
  execute_shell()
  execute_agent()

bin/helpers/nagent_llm.py
bin/helpers/nagent_cli.py
bin/helpers/nagent_file_edit_lib.py
bin/helpers/nagent_file_split_lib.py
bin/helpers/nagent_file_patch_lib.py
bin/helpers/nagent_file_summarize_lib.py
```

Then read the thin command wrappers in `bin/` and the tests in `tests/`.

The tests are useful architecture notes. They cover parser behavior,
conversation lifecycle, root context loading, retry behavior, token accounting,
sub-agent wrapping, write validation, per-file edit indexing, split metadata,
natural splitting, patch merging, hash validation, summaries, upload
classification, provider configuration, tool descriptions, and CLI JSON output.

**Build your own:** keep the first version plain. A text file, an LLM,
structured tags, and a loop are enough to learn what kind of system you actually
need.

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

Example config:

```json
{
  "provider": "openai",
  "model": "gpt-5.5"
}
```

Provider defaults:

| Provider | Default model | Credential environment variable |
| --- | --- | --- |
| `openai` | `gpt-5.5` | `OPENAI_API_KEY` |
| `anthropic` | `claude-sonnet-4-6` | `ANTHROPIC_API_KEY` |
| `google` | `gemini-2.5-flash` | `GOOGLE_API_KEY` or `GEMINI_API_KEY` |
| `cursor` | `composer-2.5` | `CURSOR_API_KEY` |

Useful environment variables:

| Variable | Meaning |
| --- | --- |
| `NAGENT_CONFIG` | Path to config JSON. |
| `NAGENT_NO_SPINNER=1` | Disable the optional spinner/status line. |

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
nagent --edit-conversation "summarize the useful parts and remove noise"
nagent --file-edit src/foo.py "make this change"
nagent --list-file-edits

nagent-llm-text --file question.txt --json
nagent-llm-upload --file diagram.png --prompt "Explain the diagram." --json
nagent-file-split --file src/big_file.py --output /tmp/big-file-split --json
nagent-file-patch --index /tmp/big-file-split/index.json --json
nagent-file-summarize --file src/big_file.py --json
nagent-file-edit --file src/foo.py "add validation"
```

Use `--help` on any command for its current argument list. Use `--description`
on top-level helper tools to see the text nagent can include in its startup
context.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

Some tests mock provider calls. Live integration tests call configured LLM
providers and require matching credentials.
