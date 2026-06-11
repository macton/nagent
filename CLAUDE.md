# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Operating rules

@context/data-oriented-design.md

The same file is injected into every nagent conversation via the repo's
`context.yaml` — one source of truth for both harnesses. Edit it there; do not
duplicate rules into this file.

## What this is

**nagent** ("not-an-agent") is a small reference implementation of a data-oriented
LLM workflow loop. The thesis drives every design decision and should drive yours:
**the data is the thing, not the agent.** State that matters lives in inspectable,
editable files on disk — never hidden in process memory. When output is wrong, fix
the generator or its inputs (the prompt), don't patch the artifact. `README.md` is
the canonical teaching document; read it before making non-trivial changes.

## Commands

```bash
# Setup
pip install -r requirements.txt
export PATH="$PWD/bin:$PATH"          # tools must be on PATH; nagent shells out to its siblings by name
mkdir -p ~/.nagent && cp config.example.json ~/.nagent/config.json

# Tests (no framework beyond stdlib unittest)
python3 -m unittest discover -s tests -v
python3 -m unittest tests.test_nagent_file_split -v          # one module
python3 -m unittest tests.test_nagent.SomeTest.test_case -v  # one test
```

There is no build step, linter, or package manifest — the `bin/` scripts are run
directly. Provider SDKs (`requirements.txt`) are only needed for live LLM calls;
most tests mock the provider.

## Architecture

The system is a set of standalone CLI executables in `bin/`, each of which prints
its own purpose when run with `--description`. There is **no central registry**:
`collect_bin_tool_descriptions()` discovers tools by running every `bin/` executable
with `--description` and injecting the results into the startup prompt. A new tool
becomes visible to the loop simply by being an executable in `bin/` that handles
`--description` (via `exit_on_description()` in `bin/helpers/nagent_cli.py`).

Thin wrappers live in `bin/`; real logic lives in `bin/helpers/*_lib.py`.

- `bin/nagent` (~2400 lines) — the main loop and the bulk of the system. Read this path first:
  `main()` → `run_agent_loop()` → `call_llm()` → `parse_response()` → `process_tags()`.
  The loop appends to a conversation file, sends the whole file to the LLM, parses
  structured tags, runs handlers, appends results, and repeats until a final
  `<nagent-response>` is emitted.
- `bin/helpers/nagent_llm.py` — provider abstraction. `generate_text_with_usage()`
  is the single primitive (file in → text out) for `openai`, `anthropic`, `google`,
  `cursor`. Provider churn should stay isolated here.
- `bin/nagent-llm-text` / `bin/nagent-llm-upload` — CLI front ends for text and
  file-upload generation.
- `bin/nagent-file-edit` + `nagent_file_edit_lib.py` — per-file conversations and
  git-history context.
- `bin/nagent-file-split` / `-patch` / `-summarize` + their `_lib.py` — large-file
  handling (split → bounded edit → patch).

### The structured-tag protocol

The model communicates only through a fixed set of XML-ish tags (`<nagent-read>`,
`<nagent-file-read>`, `<nagent-write>`, `<nagent-shell>`, `<nagent-next>`,
`<nagent-conversation>`, `<nagent-response>`, plus `<nagent-file-patch>`). The
protocol is *defined inside the prompt* — `build_initial_context()` /
`create_initial_text()` embed the tag list inside `<initial_context>` so refreshed
context always carries the current contract. `parse_response()` enforces it strictly
with regex; malformed output triggers up to `MAX_FORMAT_RETRIES` (3) visible
correction turns appended to the conversation. If you add or change a tag, update
**both** the prompt-building functions and the parser/handler dispatch in
`process_tags()`, and add a test.

### Durable state lives under `~/.nagent/`

- `conversations/` — conversation files (the working state). Named per host+shell
  via `default_conversation_name()` / `default_pid()`.
- `conversations/file-index-{pid}.json` — maps stable file ids (`device:inode` from
  `file_id_for_path()`, not paths) to per-file conversations, so renames survive.
- `config.json` — provider/model defaults (overridable by `NAGENT_CONFIG` env var
  and then by CLI flags, in that precedence order).
- `context.yaml` / `context.md` — root context injected into every conversation;
  nested `context.yaml` files expand recursively.

### Write boundaries (conventions, not a sandbox)

Shell runs with full user permissions — there is no security boundary, only
checked structured writes. `validate_write_path()` allows `<nagent-write>` to write
only to `/tmp`, `/var/tmp`, or `$TMPDIR` in main mode, or to the target file / its
split segments in per-file-edit mode. Project files are edited via
`nagent-file-edit`, not direct writes from the main loop.

### Large files

Inline reads cap at 64 KB. Beyond that, files are split into segment files plus an
`index.json` (carrying source hash, line ranges, split type) by language-aware
splitters in `bin/helpers/nagent-file-split-*`. Edits target segments; `nagent-file-patch`
validates the source hash, merges segments, and emits a unified-diff patch.

## Conventions for changes

- Prefer adding a self-describing `bin/` executable over wiring a new code path into
  the loop, unless it genuinely belongs in the loop.
- Keep provider-specific code inside `nagent_llm.py`.
- Tests in `tests/` double as executable specs (parser, conversation lifecycle,
  retries, token accounting, file ids, split/patch, providers, tool descriptions).
  Add or update the matching test for any behavioral change.
- `prompts/` holds reusable prompt documents (e.g. README-generation,
  conversation-compaction) used by the workflow, not application source.
