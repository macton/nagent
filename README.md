# nagent

**nagent** means **not-an-agent**.

nagent is a small, readable example of agent-like behavior: a text file, an LLM,
structured tags, and a loop. It is intentionally plain. Conversations are files
on disk, tools are Python scripts and subprocesses, and model actions are
structured text that the main script parses.

This README walks through the design step by step and maps each idea to the code
that implements it. The goal is not to sell nagent as a framework. The goal is
to make the pattern visible enough that you can copy it, modify it, or throw it
away and build your own version.

## What It Looks Like

The main entry point is just `nagent` plus a prompt:

```bash
nagent "Inspect this project, explain the plan, update the README, and run the relevant tests."
nagent "Investigate this Linux configuration issue, read the relevant files, run diagnostics, and propose the change before editing anything."
```

Those prompts can lead to multiple LLM calls, file reads, shell commands,
sub-agent invocations, and final responses. The interesting part is that all of
that work is driven by a conversation file and a handful of structured tags.

---

## 1. Text In, Text Out

The smallest primitive is: put text in a file, send that file to an LLM, print
the result.

```bash
echo "What is 2+2?" > question.txt
nagent-llm-text --file question.txt
```

`bin/nagent-llm-text` reads the file, resolves the configured provider and
model, calls `generate_text_with_usage()`, and prints the model response. The
provider details live in `bin/helpers/nagent_llm.py`.

Everything else in nagent is orchestration around this primitive. The agent loop
does not need a special runtime. It needs a way to turn a text file into model
output.

**Build your own:** start with `generate_text(file) -> str`. Do not build an
agent first. Build the one function that sends a document to a model and returns
text.

---

## 2. Put State In A File

nagent's memory is a plain conversation file under:

```text
~/.nagent/conversations/latest-{hostname}-{pid}
```

That file is not just chat history. It is the working state, tool transcript,
correction channel, and continuation point for the loop. User prompts, model
responses, tool results, parse errors, and follow-up instructions are appended
to the same document.

Repeated invocations in the same shell append to the same conversation by
default. The default pid is chosen in `default_pid()`:

| Environment | Default conversation id behavior |
| --- | --- |
| GNU screen | Uses `STY` plus `WINDOW` so the virtual terminal has a stable id. |
| Bash with exported `BASHPID` | Uses `BASHPID`. |
| Other shells | Falls back to the parent process id from `os.getppid()`. |

There is no separate memory service and no hidden thread store. If you can open
the file, you can inspect the state.

Conversation lifecycle commands:

```bash
nagent --status
nagent --clear
nagent --save-conversation saved-copy
nagent --load-conversation saved-copy
nagent --summarize
nagent --edit-conversation "remove stale tool output and keep the important decisions"
```

`--save-conversation`, `--load-conversation`, and `--edit-conversation` work
because the state is a normal file. You can inspect it, branch it, trim it, or
rewrite it directly.

At startup, nagent also loads optional root context from `~/.nagent/context.md`
or `~/.nagent/context.yaml`. A YAML context file can contain paths, or a
`paths:` list. Those paths are expanded recursively by `load_context_path()`, so
a small root file can assemble several context documents.

**Build your own:** store state as an append-only text document first. It is
simple, debuggable, and enough to make continuation work.

---

## 3. Teach The Model An Output Format

nagent asks the model to reply only with structured tags. The initial context is
generated at runtime by `create_initial_text()` and `build_initial_context()`.
It is itself part of the protocol: it includes environment information,
discovered tool descriptions, context-management rules, write rules, and the
exact tag grammar the model must follow.

Example action request from the model:

```xml
<nagent-shell>python3 -m unittest discover -s tests -v</nagent-shell>
```

Example result appended by nagent:

```xml
<nagent-shell-result>
exit_code: 0
stdout:
...
</nagent-shell-result>
```

The parser is `parse_response()` in `bin/nagent`. It accepts only these tags:

| Tag | Meaning |
| --- | --- |
| `<nagent-response>...</nagent-response>` | Human-facing final response, or child response to a parent. |
| `<nagent-read path="..."/>` | Read a small file inline. |
| `<nagent-file-read path="..."/>` | Read a file, splitting it first if it exceeds the inline limit. |
| `<nagent-file-patch index="..."/>` | Merge edited split segments back into the source file. |
| `<nagent-write path="...">...</nagent-write>` | Write allowed content to an allowed path. |
| `<nagent-shell>...</nagent-shell>` | Run shell commands and append stdout, stderr, and exit code. |
| `<nagent-next>...</nagent-next>` | Append a continuation prompt to the same conversation. |
| `<nagent-agent>...</nagent-agent>` | Start a child nagent process for a scoped task. |

Action handlers append result wrappers back into the conversation, including
`<nagent-read-result>`, `<nagent-file-read-result>`,
`<nagent-file-patch-result>`, `<nagent-write-result>`,
`<nagent-shell-result>`, and `<nagent-agent-result>`.

When final output is printed, `clean_user_output()` strips accidental
whole-response wrappers or one surrounding markdown fence. It does not treat
inline examples as protocol tags, so documentation can still show tag examples.

**Build your own:** give the model a small output language and write a strict
parser. Then turn parser failures into visible state so the model can correct
itself.

---

## 4. The Loop

The core loop is small:

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

In the code, the path is:

```text
main()
  run_agent_loop()
    call_llm()
    parse_response()
    process_tags()
```

`call_llm()` invokes `nagent-llm-text --json` so the loop can read both the
model text and usage counts. `process_tags()` dispatches to handlers such as
`execute_read()`, `execute_shell()`, `execute_write()`, and `execute_agent()`.

Malformed model output is not discarded. If `parse_response()` fails, nagent
appends the invalid output and a system correction to the same conversation:

```xml
<system>Invalid nagent response format: ... Respond only with valid nagent tags.</system>
```

It retries up to `MAX_FORMAT_RETRIES`. The failure stays in the file, which
makes the control flow visible instead of hiding it in an exception path.

Token and status accounting are intentionally lightweight. `TokenStats` tracks
turn count, current conversation input tokens, and recursive totals. JSON output
from `nagent-llm-text` supplies usage when the provider returns it. Child
sub-agent JSON contributes recursive token totals. User-facing runs may also
show a spinner/status line unless `NAGENT_NO_SPINNER=1` is set.

**Build your own:** after every model action, append the result to the same
state file and call the model again. That is the loop.

---

## 5. Delegate With Sub-Agents

A sub-agent is another nagent process with its own conversation file:

```xml
<nagent-agent>
Inspect tests related to file splitting. Return the relevant behavior and any
edge cases the README should mention.
</nagent-agent>
```

The parent receives only the child's final response, wrapped as a result:

```xml
<nagent-agent-result conversation="..." tokens_in="..." tokens_out="...">
exit_code: 0
output:
...
</nagent-agent-result>
```

Delegation is context management as much as parallelism. The parent keeps the
coordination and decisions. Child conversations keep exploratory logs, noisy
command output, and local dead ends in separate files.

`execute_agent()` starts the child with:

| Shared or generated value | What happens |
| --- | --- |
| Root, pid, provider, model, config | Passed through from the parent. |
| Invocation | Set to `delegated`. |
| Parent conversation | Passed as metadata. |
| Child conversation name | Generated uniquely with a UUID plus pid. |
| Token totals | Read from child JSON output and added recursively. |

**Build your own:** create child loops for scoped work. Return summaries, not
entire transcripts, to the parent.

---

## 6. Control Writes

nagent has two write modes:

| Mode | Write behavior |
| --- | --- |
| Main conversation | Coordination mode. `<nagent-write>` is allowed only under `/tmp`, `/var/tmp`, or `$TMPDIR`. |
| Per-file edit session | Project file writes go through `nagent-file-edit`; the session may write only the target file or split segments associated with that target. |

This is safety by convention for a demo/reference implementation, not a
sandboxed security product. Shell commands are powerful and are not fully
sandboxed. The startup prompt discourages shell writes, and `execute_write()`
validates structured writes, but normal OS permissions still matter.

Write validation in `validate_write_path()` allows temp paths in `/tmp`,
`/var/tmp`, or `$TMPDIR`. In a per-file edit session, it also allows the target
file, the same file after a rename as identified by file id, or segment files
from a split of that target.

**Build your own:** put write boundaries in the protocol and in the action
handler. Treat this as a visible contract, not as a substitute for real
sandboxing.

---

## 7. Handle Large Files

Inline reads are limited to `64KB` in `READ_SPLIT_THRESHOLD_BYTES`. A normal
`<nagent-read>` returns an error for larger files and tells the model to use
`<nagent-file-read>`.

The large-file workflow is:

```text
split source file into segment files
edit one or more segment files
patch the segments back into the source
refresh index metadata
```

The helper tools are:

```bash
nagent-file-split --file path/to/large.py --output /tmp/large-split --json
nagent-file-patch --index /tmp/large-split/index.json --json
nagent-file-summarize --file path/to/large.py --json
```

`nagent-file-split` writes segment files and an `index.json` containing the
source path, source hash, line numbers, split type, target size, and segment
metadata. It can use type-specific natural splitters for common source, config,
and document formats: text, Markdown, C/C++, Python, XML/HTML, JavaScript,
TypeScript, JSON, YAML, Go, Rust, and Java. `--refresh` re-splits from the
current source using an existing index. `--summarize` stores per-segment
summaries in the split metadata.

`nagent-file-patch` validates the source hash before merging segment edits. It
also writes a unified diff patch artifact, applies the merged content by
default, and refreshes `index.json` line numbers and source hash.

**Build your own:** when a file is too large for the model, make context
boundaries explicit. Split it, record metadata, edit bounded pieces, and verify
the source before merging.

---

## 8. Per-File Editing

`nagent-file-edit` runs nagent against one project file using a dedicated
conversation. This keeps the main conversation small while preserving
file-specific state.

```bash
nagent-file-edit --file src/foo.py "add error handling"
nagent-file-edit --file src/foo.py --clear
nagent --list-file-edits
```

Per-file conversations are deliberate. Editing state, prior attempts, and
file-specific decisions live with a stable file id instead of bloating the main
orchestration conversation.

The stable file id comes from device and inode in `file_id_for_path()`. The
index is stored per shell pid under `~/.nagent/conversations/`:

```json
{
  "by_file_id": {
    "2050:999": {
      "file_id": "2050:999",
      "path": "/home/me/project/src/foo.py",
      "conversation": "foo-2a5f..."
    }
  }
}
```

`nagent-file-edit` is a wrapper around the lower-level `nagent --file-edit`
mode. `nagent --list-file-edits` reports the per-shell file edit index.

**Build your own:** put repeated edit attempts for one file in one durable
place. A stable file id survives path lookups better than a path-only map.

---

## 9. How This Differs From Agent Frameworks

nagent is closer to a worked example than a framework. It keeps the moving parts
visible and small.

| Typical framework-style system | nagent |
| --- | --- |
| State in objects, databases, services, or managed threads. | State in a plain text conversation file. |
| Tools registered in code with schemas and framework dispatch. | Tags in model output parsed by `parse_response()`. |
| Shared memory or thread abstractions. | One file per instance; one file per child; one file per edit target. |
| Many layers and dependencies. | One loop, helper scripts, Python subprocesses, and provider SDKs. |
| Framework owns most control flow. | The loop is readable in `run_agent_loop()`. |

This is less polished and less protected than a production framework. That is
the point: it is small enough to read in one sitting.

**Build your own:** decide which parts of a framework you actually need. For
many experiments, a state file, strict tags, and handlers are enough.

---

## 10. Build Your Own

A compact recipe:

1. Implement `generate_text(file) -> str`.
2. Keep a growing conversation document on disk.
3. Generate an initial context that states the contract.
4. Define an output format and a strict parser.
5. Write action handlers that append results back into state.
6. Loop after actions and retry malformed output with visible corrections.
7. Add child loops for delegated work.
8. Add explicit context boundaries for large files and per-file edits.
9. Add save, load, edit, and summarize tools so conversation history can be
   inspected and branched.

Code-reading order:

```text
main()
  run_agent_loop()
    call_llm()
    parse_response()
    process_tags()
```

After that, read the helpers in this order: `nagent_llm.py`,
`nagent_cli.py`, `nagent_file_edit_lib.py`, `nagent_file_split_lib.py`,
`nagent_file_patch_lib.py`, and `nagent_file_summarize_lib.py`.

**Build your own:** keep the first version boring. The boring version is the
one you can debug.

---

## Tool Reference

| Tool | Purpose |
| --- | --- |
| `nagent` | Main conversation loop. Appends prompts, calls the LLM, parses tags, runs actions, and prints responses. |
| `nagent-llm-text` | Sends a text file to the configured LLM. Used directly and by `nagent`. |
| `nagent-llm-upload` | Uploads a supported file with a prompt for vision or document understanding. |
| `nagent-file-split` | Splits a source file into structure-aware segments and writes `index.json`. |
| `nagent-file-patch` | Merges edited split segments back into the source file and writes a patch artifact. |
| `nagent-file-edit` | Runs a per-file nagent conversation for editing one source file. |
| `nagent-file-summarize` | Summarizes a file inline or through split-and-summarize for large files. |

Tools accept `--json` where applicable. Provider and config behavior is shared
under `bin/helpers/`, especially `nagent_llm.py` and `nagent_cli.py`.

Helper discoverability is intentionally simple. Each executable can implement
`--description`; `collect_bin_tool_descriptions()` runs those commands and
folds their descriptions into the startup prompt. There is no central registry.

Shared CLI helpers in `bin/helpers/nagent_cli.py` provide JSON output,
`--description` handling, and the wait spinner. The main `nagent` command also
handles prompt text from argv, piped stdin, or a trailing `-`:

```bash
echo "summarize this prompt" | nagent
nagent "Use this leading instruction, then read stdin:" -
```

---

## Setup

```bash
pip install -r requirements.txt
export PATH="$PWD/bin:$PATH"
mkdir -p ~/.nagent
cp config.example.json ~/.nagent/config.json   # optional
```

Config loads from `NAGENT_CONFIG` or `~/.nagent/config.json`. CLI flags override
config values.

Example config:

```json
{
  "provider": "openai",
  "model": "gpt-5.5"
}
```

Provider defaults and credentials:

| Provider | Default model | Credential environment variable |
| --- | --- | --- |
| `openai` | `gpt-5.5` | `OPENAI_API_KEY` |
| `anthropic` | `claude-sonnet-4-6` | `ANTHROPIC_API_KEY` |
| `google` | `gemini-2.5-flash` | `GOOGLE_API_KEY` or `GEMINI_API_KEY` |
| `cursor` | `composer-2.5` | `CURSOR_API_KEY` |

Provider SDK package checks are in `require_package()`. Missing packages print
install hints based on `PACKAGE_HINTS`.

Useful environment variables:

| Variable | Meaning |
| --- | --- |
| `NAGENT_CONFIG` | Path to config JSON. |
| `NAGENT_NO_SPINNER=1` | Disable the optional spinner/status line. |

---

## LLM Providers And Uploads

`bin/helpers/nagent_llm.py` centralizes provider selection, default models,
config lookup, CLI overrides, credential environment variables, package checks,
model listing, text generation, upload generation, and usage extraction.

Text generation can include usage accounting:

```bash
nagent-llm-text --file question.txt --json
```

File uploads go through `nagent-llm-upload`. It supports common images, PDFs,
office documents, CSV/JSON/text/code files, and related document formats. It
checks file existence, a `50MB` size limit, and rejects unsupported archive
types such as `.zip`.

```bash
nagent-llm-upload --file diagram.png --prompt "Explain the diagram."
nagent-llm-upload --file report.pdf --prompt "Summarize the decision points." --json
```

---

## Common Commands

```bash
nagent "your prompt here"
echo "prompt from stdin" | nagent
nagent --status --json
nagent --list-models --json
nagent --list-file-edits --pid "$BASHPID"
nagent --clear

echo "What is 2+2?" > question.txt
nagent-llm-text --file question.txt
nagent-llm-text --file question.txt --json

nagent-llm-upload --file image.png --prompt "Describe this image."
nagent-llm-upload --file notes.pdf --prompt "Extract the key points." --json

nagent-file-split --file src/big_file.py --output /tmp/big-file-split --json
nagent-file-patch --index /tmp/big-file-split/index.json --json
nagent-file-summarize --file src/big_file.py --json

nagent-file-edit --file src/foo.py "add error handling"
nagent-file-edit --file src/foo.py --clear
```

Use `--help` on any command for the current argument list.

---

## Tests

```bash
python3 -m unittest discover -s tests -v
```

The tests cover the parser, conversation lifecycle behavior, write validation,
sub-agent wrapping, provider helpers, file edit indexing, split and natural
split behavior, patch merging, hash validation, summaries, upload file
classification, and CLI JSON output.
