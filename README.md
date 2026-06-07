# nagent

**nagent** means **not-an-agent**.

nagent is a small, readable example of agent-like behavior: a text file, an LLM, structured tags, and a loop. It is intentionally plain: files on disk, Python, subprocesses, and structured text.

This is not an agent framework or a product pitch. It is a reference implementation you can read, copy, modify, or discard. The point is to show that much of "agent behavior" is just this: append to a conversation file, call the LLM, parse the reply, run requested actions, append results, and repeat.

This README walks through that design step by step and maps each part back to the code.

## What It Looks Like

Ask nagent to inspect a project, delegate a scoped file edit, and run tests:

```bash
nagent "Inspect this repo, explain the main entry points, then use nagent-file-edit to make the smallest safe fix for the failing test and rerun the relevant tests."
```

The parent conversation can stay focused on coordination while a per-file edit conversation handles the source edit:

```bash
nagent-file-edit --file src/foo.py "add error handling for a missing config file"
python3 -m unittest discover -s tests -v
```

You can also use it for slower diagnostic work where ordinary terminal state matters:

```bash
nagent "Investigate why this Linux service config is not being picked up. Read the relevant files, run diagnostic commands, explain the planned change, and do not modify anything until the plan is clear."
```

nagent does not bypass normal OS permissions and it is not a sandbox. It can only do what the process, shell, and filesystem permissions allow.

---

## 1. Text in, text out

Start with one primitive: send text to an LLM and get text back.

```bash
echo "What is 2+2?" > question.txt
nagent-llm-text --file question.txt
```

That command reads a text file, sends its contents to the configured provider, and prints the model response. The rest of nagent is orchestration around this primitive.

In the source, the command is `bin/nagent-llm-text`. Provider setup, config loading, default models, credential checks, package checks, text generation, upload generation, usage reporting, and model listing live in `bin/helpers/nagent_llm.py`.

`nagent-llm-text --json` returns the response plus provider, model, and token usage when the provider exposes it:

```bash
nagent-llm-text --file question.txt --json
```

**Build your own:** write one boring function first: `generate_text(file) -> str`. Keep provider-specific code outside the agent loop so the loop stays easy to reason about.

---

## 2. Put state in a file

Memory is a plain conversation file. A user-level nagent conversation uses this path shape:

```text
~/.nagent/conversations/latest-{hostname}-{pid}
```

Repeated invocations in the same shell append to that file:

```bash
nagent "What files are in this directory?"
nagent "Which one is the main entry point?"
```

The second command is not a separate chat. It sends the same growing conversation file back to the model, including the first prompt, the model's tags, and any tool results.

There is no separate memory service. No database is required. You can open the file and inspect the exact prompt history being sent to the model.

By default, `bin/nagent` chooses the pid this way:

| Case | pid source |
|---|---|
| Inside GNU screen | `{STY}-{WINDOW}` |
| `BASHPID` is available | `BASHPID` |
| Fallback | parent process id from `os.getppid()` |

Conversation lifecycle commands operate on the loaded conversation:

```bash
nagent --status
nagent --clear
nagent --save-conversation before-refactor
nagent --load-conversation before-refactor
nagent --summarize
nagent --edit-conversation "remove obsolete tool output and keep the useful decisions"
```

`--clear` archives the current conversation and starts fresh at the same path. `--status` prints the conversation path, size, provider, and model. `--save-conversation` copies the loaded conversation to another name. `--load-conversation` archives the loaded conversation, then replaces it with the named copy. `--summarize` sends the conversation to the LLM and prints a summary without appending it to the conversation. `--edit-conversation` archives the conversation, edits that backup through a scoped file-edit session, then loads the edited backup.

Root context is loaded from `~/.nagent/context.yaml` or `~/.nagent/context.md` during initial context creation. A markdown file is inserted directly. A YAML file can be a list or `{ "paths": [...] }`; paths are absolute or relative to the nagent root, and nested `context.yaml` files are expanded recursively.

Prompts can come from arguments, piped stdin, or a trailing `-`:

```bash
echo "prompt from stdin" | nagent
nagent "Summarize this log:" -
```

**Build your own:** start with a single durable document. Append user prompts, model replies, tool results, and follow-up instructions to it. Make the state visible before making it clever.

---

## 3. Teach the model an output format

Free-form prose is hard for a program to act on. nagent asks the model to reply only with structured tags.

For example, the model can request a shell command:

```xml
<nagent-shell>ls -la</nagent-shell>
```

nagent parses that tag, runs the command, appends the result to the conversation, and calls the LLM again:

```xml
<nagent-shell-result>
exit_code: 0
stdout:
total 24
...
</nagent-shell-result>
```

Available model output tags:

| Tag | What nagent does |
|---|---|
| `<nagent-response>...</nagent-response>` | Print a human-facing response. If there are no action tags left, stop. |
| `<nagent-read path="..."/>` | Read a small file inline. Files over `64KB` are rejected with guidance to use file-read. |
| `<nagent-file-read path="..."/>` | Read a file inline if small, or split it first if large. |
| `<nagent-file-patch index="..."/>` | Merge edited split segments back into the source file. |
| `<nagent-write path="...">...</nagent-write>` | Write file content through nagent's write handler. |
| `<nagent-shell>...</nagent-shell>` | Run shell commands and append stdout, stderr, and exit code. |
| `<nagent-next>...</nagent-next>` | Append a follow-up prompt and continue the loop. |
| `<nagent-agent>...</nagent-agent>` | Spawn a child nagent process for a scoped task. |

The parser is `parse_response()` in `bin/nagent`. It accepts only these tags and whitespace between them. Unexpected prose is treated as an invalid response, not as something to print.

Action handlers append result wrappers back into the conversation:

| Result wrapper | Produced by |
|---|---|
| `<nagent-read-result>` | `<nagent-read .../>` |
| `<nagent-file-read-result>` | `<nagent-file-read .../>` |
| `<nagent-file-patch-result>` | `<nagent-file-patch .../>` |
| `<nagent-write-result>` | `<nagent-write ...>` |
| `<nagent-shell-result>` | `<nagent-shell>` |
| `<nagent-agent-result>` | `<nagent-agent>` |

`clean_user_output()` handles final display. It strips accidental whole-response wrappers such as a nested `<nagent-response>...</nagent-response>` or one surrounding markdown fence, but it does not treat inline examples as protocol tags.

**Build your own:** choose an output format the model can follow consistently: XML-like tags, JSON, or another small grammar. Write the parser before adding more tools.

---

## 4. The loop

The loop is deliberately small:

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

In `bin/nagent`, the code-reading path is:

```text
main()
  run_agent_loop()
    call_llm()
    parse_response()
    process_tags()
```

`main()` resolves CLI options, conversation names, provider settings, prompt input, root context, and command modes. `run_agent_loop()` appends the user prompt and keeps calling the LLM until it reaches a final response. `call_llm()` shells out to `nagent-llm-text --json`. `process_tags()` dispatches reads, writes, shell commands, file patches, sub-agent calls, `next` prompts, and final responses.

If the model returns malformed output, nagent appends the bad output back to the conversation inside `<agent-response>`, adds a `<system>` correction, and retries. It stops after `MAX_FORMAT_RETRIES`.

Token/status accounting is intentionally simple. `TokenStats` tracks turns, the most recent conversation input size, recursive input tokens, and recursive output tokens. `nagent-llm-text --json` supplies usage counts when possible. Child agents return JSON, and the parent adds their recursive totals. In an interactive user invocation, nagent can show a spinner and prints a final status line:

```text
[Turns:2 Conversation-Tokens:1234 Tokens-In:1800 Tokens-Out:420]
```

Set `NAGENT_NO_SPINNER=1` to disable the spinner.

**Build your own:** implement the loop with one action first. For example: parse `<shell>...</shell>`, run it, append the result, and repeat. Add capabilities only after the basic read/call/parse/act/append cycle is working.

---

## 5. Delegate with sub-agents

A sub-agent is another nagent process with its own conversation file. The parent gives it a scoped prompt:

```xml
<nagent-agent>
Find all TODO comments in src/ and return a markdown list with file paths.
</nagent-agent>
```

`execute_agent()` starts `bin/nagent` with `--invocation delegated`, `--parent-conversation`, the shared `--pid`, the same root, provider, model, optional config, and `--json`. The child conversation name is unique and includes the pid.

The child receives its own initial context and runs the same loop. The parent does not import the child's whole history. It appends only the child final response, stdout/stderr, exit code, child conversation name, and recursive token counts inside `<nagent-agent-result>`.

This keeps exploratory work, long logs, and isolated tasks out of the parent conversation.

**Build your own:** when work is independent, start a fresh loop with a narrow prompt and a separate state file. Return only the summary or artifact the parent needs.

---

## 6. Control writes

nagent separates coordination from source-file editing.

| Context | Write rule |
|---|---|
| Main conversation | `<nagent-write>` is allowed only under `/tmp`, `/var/tmp`, or `$TMPDIR`. |
| Project files | Use `nagent-file-edit`, which starts a per-file edit session. |
| Per-file edit session | `<nagent-write>` may write the target file or split segments associated with that target. |

`validate_write_path()` enforces those rules for `<nagent-write>`. In a per-file session, it recognizes the original file, the stable file id, and segment files under the nagent split metadata for that source file.

Shell writes are discouraged and are not fully sandboxed. This repository is a demo/reference implementation, not a sandboxed security product. The write boundaries are safety by convention and by nagent's handlers, not a complete OS-level security model.

**Build your own:** define write authority explicitly. Decide which paths the main loop can touch, which paths require a scoped edit session, and where human approval should sit.

---

## 7. Handle large files

`<nagent-read path="..."/>` has a `64KB` inline read limit. Larger files use this workflow:

```text
split -> edit segment files -> patch source file
```

`<nagent-file-read path="..."/>` inlines small files. For larger files, it runs `nagent-file-split`, records the split under `~/.nagent/splits/...`, and returns the `index.json` path plus segment paths and line ranges.

The large-file tools are:

| Tool | Role |
|---|---|
| `nagent-file-split` | Split a file into segment files and `index.json`. |
| `nagent-file-patch` | Validate and merge edited segments back into the source file. |
| `nagent-file-summarize` | Summarize a file; for large files, split first and summarize each segment. |

`nagent-file-split` writes metadata including source path, source hash, source size, line count, split type, target bytes, natural mode, creation time, segment count, segment paths, and line ranges. It autodetects common text/source formats and can use type-specific natural splitters for `txt`, `md`, `cpp`, `py`, `xml`, `js`, `ts`, `json`, `yaml`, `go`, `rs`, and `java`. `--natural` splits at every recognized boundary while still respecting `--target-bytes`. `--refresh` rebuilds an existing split after the source changes. `--summarize` stores per-segment summaries and a combined summary in the split metadata.

After segment edits, `nagent-file-patch --index ...` validates the source hash, merges segment text, writes a unified diff patch artifact, applies the merged content unless told not to, and refreshes line numbers in `index.json`. `--dry-run`, `--no-apply`, and `--force` expose the lower-level controls.

**Build your own:** when input is too large for context, make the chunks visible on disk and give the model stable filenames. Use a separate merge step that validates the source file before writing back.

---

## 8. Per-file editing

`nagent-file-edit` keeps the main conversation small by giving each edited file its own conversation.

```bash
nagent-file-edit --file src/foo.py "add error handling"
nagent-file-edit --file src/foo.py --clear
nagent --list-file-edits
```

The file index is stored under:

```text
~/.nagent/conversations/file-index-{pid}.json
```

Each entry is keyed by a stable file id, usually `{device}:{inode}`, so a renamed file can keep the same edit conversation:

```json
{
  "by_file_id": {
    "2050:123456": {
      "file_id": "2050:123456",
      "path": "/abs/path/to/src/foo.py",
      "conversation": "foo-a1b2c3d4-7e89-..."
    }
  }
}
```

`bin/nagent-file-edit` resolves the target file through `bin/helpers/nagent_file_edit_lib.py`, looks up or creates the per-file conversation, then invokes:

```bash
nagent --file-edit src/foo.py ...
```

`nagent --file-edit` is the lower-level mode that adds file-edit rules to the initial context. `nagent --list-file-edits` reports the per-shell file edit index.

**Build your own:** keep coordinator state separate from file-worker state. A coordinator should know that a file was edited; it does not need every model turn used to make the edit.

---

## 9. How this differs from agent frameworks

nagent is meant to expose the pattern, not hide it behind abstractions.

| Typical framework | nagent |
|---|---|
| State in objects, services, stores, or threads. | State in a plain text file. |
| Tools registered in code and invoked through a runtime schema. | Tools requested as tags in model output. |
| Shared memory or one managed thread. | One file per instance, including child agents and per-file edits. |
| Many layers, dependencies, plugins, and callbacks. | One loop and a few scripts. |

Frameworks can be useful when you need their structure. nagent is useful when you want to see the mechanics clearly enough to build your own version.

**Build your own:** add abstractions only after the file-and-loop version becomes painful in a specific way.

---

## 10. Build your own

A compact recipe:

1. `generate_text(file) -> str`
2. A growing document that holds prompts, model replies, and action results.
3. An output format and parser.
4. A loop that reads, calls, parses, acts, appends, and repeats.
5. Incremental capabilities: shell, file read, constrained write, sub-agents, large-file splitting, per-file editing.

Code-reading order:

```text
main()
  run_agent_loop()
    call_llm()
    parse_response()
    process_tags()
```

After that, read `bin/helpers/nagent_llm.py` for provider handling, `bin/helpers/nagent_cli.py` for shared CLI behavior, and the smaller `bin/nagent-file-*` tools for split, patch, summarize, and per-file edit flows.

**Build your own:** copy the smallest useful version first. Replace the provider, rename the tags, change the write policy, or remove sub-agents entirely. The pattern survives those changes.

---

## Tool Reference

Run any command with `--description` for the short description that nagent collects into its initial context, or `--help` for full options. `bin/helpers/nagent_cli.py` implements shared JSON emission, `--description` handling, tool description collection, and the wait spinner.

| Command | Purpose | JSON output |
|---|---|---|
| `nagent` | Main conversation loop, conversation lifecycle commands, sub-agent orchestration, write validation, and file-edit mode. | `--json` for status, list, clear, save/load, final responses, summaries, and recursive token totals. |
| `nagent-llm-text` | Send a text file to the configured LLM. | `--json`, including response and usage counts. |
| `nagent-llm-upload` | Upload a file with a prompt for vision or document-style inputs. | `--json`, including response and usage counts. |
| `nagent-file-split` | Split a large file into segment files and `index.json`. | `--json` |
| `nagent-file-patch` | Merge edited segment files back into the source file and write a patch artifact. | `--json` |
| `nagent-file-edit` | Run nagent against one project file using a dedicated conversation. | `--json` |
| `nagent-file-summarize` | Summarize a file, splitting first if it is larger than `64KB`. | `--json` |

Shared provider and config code lives under `bin/helpers/`.

---

## Setup

```bash
pip install -r requirements.txt
export PATH="$PWD/bin:$PATH"
mkdir -p ~/.nagent
cp config.example.json ~/.nagent/config.json   # optional
```

Config loads from `NAGENT_CONFIG` or `~/.nagent/config.json`. CLI flags override config values.

Example config:

```json
{
  "provider": "openai",
  "model": "gpt-5.5"
}
```

Provider defaults and credential variables:

| Provider | Default model | API key |
|---|---|---|
| `openai` | `gpt-5.5` | `OPENAI_API_KEY` |
| `anthropic` | `claude-sonnet-4-6` | `ANTHROPIC_API_KEY` |
| `google` | `gemini-2.5-flash` | `GOOGLE_API_KEY` or `GEMINI_API_KEY` |
| `cursor` | `composer-2.5` | `CURSOR_API_KEY` |

`bin/helpers/nagent_llm.py` checks that credentials and provider packages are available before making calls. Package hints are `openai`, `anthropic`, `google-genai`, and `cursor-sdk`.

Useful environment variables:

| Variable | Meaning |
|---|---|
| `NAGENT_CONFIG` | Path to a config JSON file. |
| `NAGENT_NO_SPINNER=1` | Disable the wait spinner. |

---

## LLM Providers and Uploads

Provider selection is shared by `nagent`, `nagent-llm-text`, `nagent-llm-upload`, `nagent-file-split --summarize`, and `nagent-file-summarize`. Each command accepts provider/model/config flags where applicable:

```bash
nagent --provider anthropic --model claude-sonnet-4-6 "summarize this repo"
nagent-llm-text --file prompt.txt --json
nagent --list-models --json
```

`nagent-llm-upload` supports images, PDFs, office documents, CSV/TSV, JSON/YAML/XML, text, logs, config files, and common source files. It rejects unsupported extensions such as `.zip`; extract archives first. The current upload size limit is `50MB`.

```bash
nagent-llm-upload --file diagram.png --prompt "Describe the architecture" --json
nagent-llm-upload --file report.pdf --prompt "Summarize the risks"
```

Upload generation is provider-specific in `bin/helpers/nagent_llm.py`: OpenAI and Anthropic use file upload APIs, Google waits for uploaded file processing when needed, and Cursor receives an absolute-path prompt.

---

## Common Commands

```bash
nagent "your prompt here"
echo "prompt from stdin" | nagent
nagent --status --json
nagent --list-models --json
nagent --list-file-edits --pid "$BASHPID"
nagent --clear
nagent --save-conversation before-refactor
nagent --load-conversation before-refactor
nagent --summarize
nagent --edit-conversation "condense this conversation"

nagent-llm-text --file prompt.txt --json
nagent-llm-upload --file chart.png --prompt "Describe this" --json
nagent-file-split --file src/big.py --json
nagent-file-split --file src/big.py --natural --summarize --json
nagent-file-patch --index /tmp/big-split/index.json --json
nagent-file-summarize --file src/big.py --json
nagent-file-edit --file src/foo.py "add error handling"
```

Run `--help` on any command for full options.

---

## Tests

```bash
python3 -m unittest discover -s tests -v
```

The tests cover tag parsing, action dispatch, conversation lifecycle commands, root context loading, prompt resolution, tool discovery, JSON modes, token accounting, file-edit indexes, split metadata, natural split behavior, hash validation, patch generation, line-number refresh, summarization metadata, upload type checks, and spinner behavior.

---

## Source Coverage Checklist

For readers auditing the implementation, these are the main source areas and where the README maps them:

| Source area | Covered in |
|---|---|
| `bin/nagent`: initial context, root context, conversation naming, prompt resolution, parsing, retries, dispatch, lifecycle commands, sub-agents, token accounting, JSON mode, write validation | Steps 2-6, Tool Reference, Common Commands |
| `bin/nagent-llm-text` and `bin/helpers/nagent_llm.py`: config, defaults, credentials, packages, generation, uploads, usage, model listing | Steps 1 and 4, Setup, LLM Providers and Uploads |
| `bin/nagent-llm-upload`: supported file categories, size/type checks, prompts, JSON output | LLM Providers and Uploads, Common Commands |
| `bin/nagent-file-edit` and `bin/helpers/nagent_file_edit_lib.py`: stable file ids, per-pid indexes, per-file conversations, source path resolution | Step 8 |
| `bin/nagent-file-split` and `bin/helpers/nagent_file_split_lib.py`: metadata, line ranges, natural boundaries, refresh, summarization | Step 7 |
| `bin/nagent-file-patch` and `bin/helpers/nagent_file_patch_lib.py`: source hash validation, patch generation, merge behavior, refreshed line numbers | Step 7 |
| `bin/nagent-file-summarize` and `bin/helpers/nagent_file_summarize_lib.py`: small-file summaries, large-file split summaries, metadata updates | Step 7, Tool Reference |
| `bin/helpers/nagent_cli.py`: `--description`, JSON emission, spinner behavior | Steps 4 and Tool Reference |

---

## License

MIT - see [LICENSE](LICENSE).
