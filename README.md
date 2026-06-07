# nagent

**nagent** means **not-an-agent**.

nagent is a small, readable example of agent-like behavior: a text file, an LLM, structured tags, and a loop. It is intentionally plain: files on disk, Python, subprocesses, and structured text.

The project is not trying to be an agent framework or a product. It is a reference implementation you can read, copy, modify, or discard. The point is to show that much of "agent behavior" is just this: append to a conversation file, call the LLM, parse the reply, run requested actions, append results, and repeat.

This README walks through the design step by step and maps the pieces back to the code.

---

## 1. Text in, text out

Start with one primitive: send text to an LLM and get text back.

```bash
echo "What is 2+2?" > question.txt
nagent-llm-text --file question.txt
```

That command reads a file, sends its contents to the configured provider, and prints the model response. The rest of nagent is orchestration around this primitive.

In the source, the command lives in `bin/nagent-llm-text`. Provider setup, config loading, model defaults, credential checks, and `generate_text()` live in `bin/helpers/nagent_llm.py`.

**Build your own:** write one boring function first: `generate_text(file) -> str`. Keep provider-specific code outside the agent loop so the loop stays easy to reason about.

---

## 2. Put state in a file

Memory is a plain conversation file. A user-level nagent conversation uses this path shape:

```text
~/.nagent/conversations/latest-{hostname}-{pid}
```

By default, `pid` is `{STY}-{WINDOW}` inside GNU screen, otherwise `BASHPID` when available, otherwise the parent shell process id.

Repeated invocations in the same shell append to that file. That means this:

```bash
nagent "What files are in this directory?"
nagent "Which one is the main entry point?"
```

is not two unrelated chats. The second command sends the same growing conversation file, so the model can see the first turn and its result.

Use a trailing `-` when you want to type or paste a prompt on stdin, ending it with `Ctrl+D`:

```bash
nagent "Summarize this log:" -
```

You can copy and restore conversation files without switching the active conversation name:

```bash
nagent --save-conversation before-refactor
nagent --load-conversation before-refactor
nagent --summarize
nagent --edit-conversation "remove obsolete tool output and keep the useful decisions"
```

`--save-conversation` copies the loaded conversation to another conversation name. `--load-conversation` first archives the loaded conversation, then replaces it with the named copy. `--summarize` sends the loaded conversation to the LLM with summary instructions and prints the result without appending it to the conversation. `--edit-conversation` archives the current conversation, runs a scoped file-edit session on that backup using your prompt, and then loads the edited backup.

There is no separate memory service. No database is required. You can open the file and inspect the exact prompt history being sent to the model.

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

Available tags:

| Tag | What nagent does |
|---|---|
| `<nagent-response>...</nagent-response>` | Print the final human-facing response and stop. |
| `<nagent-read path="..."/>` | Read a small file inline. |
| `<nagent-file-read path="..."/>` | Read a file; split it first if it exceeds the inline limit. |
| `<nagent-file-patch index="..."/>` | Merge edited split segments back into the source file. |
| `<nagent-write path="...">...</nagent-write>` | Write file content through nagent's write handler. |
| `<nagent-shell>...</nagent-shell>` | Run shell commands and append stdout, stderr, and exit code. |
| `<nagent-next>...</nagent-next>` | Append a follow-up prompt and continue the loop. |
| `<nagent-agent>...</nagent-agent>` | Spawn a child nagent process for a scoped task. |

The parser is `parse_response()` in `bin/nagent`. It recognizes the tags, returns typed records, and lets the loop dispatch them.

**Build your own:** choose an output format the model can follow consistently: XML-like tags, JSON, or another small grammar. Write a parser before adding more tools.

---

## 4. The loop

The agent loop is deliberately small:

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

In `bin/nagent`, the path through the code is:

```text
main()
  run_agent_loop()
    call_llm()
    parse_response()
    process_tags()
```

`call_llm()` shells out to `nagent-llm-text`. `process_tags()` performs reads, writes, shell commands, file patches, sub-agent calls, and final responses.

While the loop waits, the spinner shows `Waiting...`. In user-direct mode (a human-run `nagent` invocation with no explicit `--pid`), nagent prints the final token status after the final response and before exiting:

```text
[Turns:2 Conversation-Tokens:1234 Tokens-In:1800 Tokens-Out:420]
```

`Turns` counts LLM calls in the current nagent process. `Conversation-Tokens` is the current loaded conversation input size for the next or most recent model call. `Tokens-In` and `Tokens-Out` include recursive sub-agent totals returned through child `nagent --json` runs.

**Build your own:** implement the loop with one action first. For example: parse `<shell>...</shell>`, run it, append the result, and repeat. Add capabilities only after the basic read/call/parse/act/append cycle is working.

---

## 5. Delegate with sub-agents

A sub-agent is just another nagent process with its own conversation file. The parent gives it a scoped prompt:

```xml
<nagent-agent>
Find all TODO comments in src/ and return a markdown list with file paths.
</nagent-agent>
```

The child receives its own initial context, runs the same loop, and eventually returns a `<nagent-response>`. The parent does not import the child's whole transcript. It appends only the child result, wrapped as a result block, then continues its own loop.

This keeps exploratory work, long logs, and isolated tasks out of the parent conversation.

**Build your own:** when work is independent, start a fresh loop with a narrow prompt and a separate state file. Return only the summary or artifact the parent needs.

---

## 6. Control writes

nagent separates coordination from source-file editing.

| Context | Write rule |
|---|---|
| Main conversation | `<nagent-write>` is allowed only under temp directories such as `/tmp`, `/var/tmp`, or `$TMPDIR`. |
| Project files | Use `nagent-file-edit`, which starts a per-file edit session. |
| Per-file edit session | `<nagent-write>` may write the target file and split segments for that same file. |

Shell writes are discouraged and are not fully sandboxed. This repository is a demo and reference implementation, not a sandboxed security product. The write boundaries are safety by convention and by nagent's handlers, not a complete OS-level security model.

**Build your own:** define write authority explicitly. Decide which paths the main loop can touch, which paths require a scoped edit session, and where human approval should sit.

---

## 7. Handle large files

`<nagent-read path="..."/>` has a `64KB` inline read limit. Larger files need a chunking workflow:

```text
split -> edit segment files -> patch source file
```

The CLI tools are:

| Tool | Role |
|---|---|
| `nagent-file-split` | Split a large file into structure-aware segment files and an `index.json`. |
| `nagent-file-patch` | Validate and merge edited segments back into the original source file. |
| `nagent-file-summarize` | Summarize a file; for large files, split first and summarize each segment. |

Inside the loop, `<nagent-file-read path="..."/>` inlines small files and splits large ones. After segment edits, `<nagent-file-patch index="..."/>` applies the merge.

Large-file summaries are stored in split metadata. When `nagent-file-split --summarize` or `nagent-file-summarize` handles a large file, per-segment summaries and a combined summary are recorded in `index.json`.

**Build your own:** when input is too large for context, make the chunks visible on disk and give the model stable filenames. Use a separate merge step that can validate the source file before writing back.

---

## 8. Per-file editing

`nagent-file-edit` keeps the main conversation small by giving each edited file its own conversation.

```bash
nagent-file-edit --file src/foo.py "add error handling"
nagent-file-edit --file src/foo.py --clear
nagent --list-file-edits
```

The file index is stored under `~/.nagent/conversations/file-index-{pid}.json`. Each entry is keyed by a stable file id, usually `{device}:{inode}`, so renames can keep the same edit conversation.

Small example:

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

`nagent-file-edit` resolves the target file, looks up or creates the per-file conversation, then invokes `nagent --file-edit ...` with that scoped context.

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

After that, read `bin/helpers/nagent_llm.py` for provider handling, then the smaller tools under `bin/nagent-file-*` for the split, patch, summarize, and per-file edit flows.

**Build your own:** copy the smallest useful version first. Replace the provider, rename the tags, change the write policy, or remove sub-agents entirely. The pattern survives those changes.

---

## Tool Reference

Run a command with `--description` for a short description, or `--help` for full options.

| Command | Purpose | JSON output |
|---|---|---|
| `nagent` | Main conversation loop. | `--json` for status, list, clear, final response output, and recursive token totals. |
| `nagent-llm-text` | Send a text file to the configured LLM. | `--json`, including input and output token counts. |
| `nagent-llm-upload` | Upload a file with a prompt for vision or document-style inputs. | `--json`, including input and output token counts. |
| `nagent-file-split` | Split a large file into segment files and `index.json`. | `--json` |
| `nagent-file-patch` | Merge edited segment files back into the source file. | `--json` |
| `nagent-file-edit` | Run nagent against one project file using a dedicated conversation. | `--json` |
| `nagent-file-summarize` | Summarize a file, splitting first if it is larger than `64KB`. | `--json` |

Shared provider and config helpers live under `bin/helpers/`. The tools accept `--json` where structured output is useful.

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

Provider defaults:

| Provider | Default model | API key |
|---|---|---|
| `openai` | `gpt-5.5` | `OPENAI_API_KEY` |
| `anthropic` | `claude-sonnet-4-6` | `ANTHROPIC_API_KEY` |
| `google` | `gemini-2.5-flash` | `GOOGLE_API_KEY` or `GEMINI_API_KEY` |
| `cursor` | `composer-2.5` | `CURSOR_API_KEY` |

Useful environment variables:

| Variable | Meaning |
|---|---|
| `NAGENT_CONFIG` | Path to a config JSON file. |
| `NAGENT_NO_SPINNER=1` | Disable the wait spinner. |

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
