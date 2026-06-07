# Create the nagent README

Write `README.md` for the `nagent` project.

Before writing, inspect the current source code. Do not rely only on this prompt
or on an existing README. Read the main scripts under `bin/`, the helper modules
under `bin/helpers/`, and the tests when needed, then ground the walkthrough in
the implementation details that matter for understanding how nagent works.

The README should explain nagent as a small, readable reference implementation
of agent-like behavior: a text file, an LLM, structured tags, and a loop. Its
job is not to market nagent as a framework or product. Its job is to teach the
reader how the pattern works and give them enough concrete detail to build or
adapt their own version.

## Intent

The README should make these ideas clear:

- **nagent** means **not-an-agent**.
- The project is intentionally plain: files on disk, Python, subprocesses, and
  structured text.
- "Agent behavior" is mostly: append to a conversation file, call the LLM, parse
  the reply, run requested actions, append results, and repeat.
- nagent is a reference implementation, not a competitor to agent frameworks.
- The reader should come away understanding the design well enough to copy,
  modify, or discard pieces of it.
- The README should be grounded in the actual code as it exists now, not in an
  idealized architecture.

Use a direct, explanatory tone. Prefer concrete examples over abstract claims.
Avoid hype, vague promises, and framework jargon unless contrasting nagent with
framework-style systems.

## Audience

Write for programmers who:

- Understand command-line tools and basic Python.
- Are curious how agent loops work under the hood.
- May want to build a small agent-like tool without adopting a large framework.
- Value seeing the state, prompts, and model outputs as ordinary files.

Do not assume the reader already knows nagent's internals.

## Structure

Construct the README as a guided build-up from the smallest primitive to the
complete tool. The main body should be organized as numbered steps:

1. **Text in, text out** - start with the LLM call as the only primitive.
2. **Put state in a file** - introduce the growing conversation file under
   `~/.nagent/conversations/`.
3. **Teach the model an output format** - explain structured tags and show input
   and result examples.
4. **The loop** - show the simple read/call/parse/act/append/repeat algorithm.
5. **Delegate with sub-agents** - explain child nagent processes with separate
   conversation files.
6. **Control writes** - explain write boundaries, temp writes, and
   `nagent-file-edit` for project files.
7. **Handle large files** - explain split, edit segment, patch, and summarize.
8. **Per-file editing** - explain one conversation per edited file and stable
   file ids.
9. **How this differs from agent frameworks** - compare the plain-file loop with
   heavier framework abstractions.
10. **Build your own** - finish with a compact recipe and code-reading order.

Each step should include:

- A short explanation of the design idea.
- A concrete command, tag, pseudocode block, or table when useful.
- A **Build your own:** note that translates the nagent implementation into a
  general pattern the reader can reuse.

After the numbered steps, include reference sections for tools, setup, common
commands, and tests.

## Required Content

Include the following details.

### Opening

- Start with `# nagent`.
- State that **nagent** means **not-an-agent**.
- Describe nagent as a small, readable example of agent-like behavior.
- Include the core phrase or idea: a text file, an LLM, structured tags, and a
  loop.
- Say the README walks through the design step by step and maps it to code.
- Include a short "What it looks like" or similar introduction subsection with a
  couple of quick examples showing `nagent` doing complex, multi-step work. The
  introduction examples should use only the `nagent` command, not helper
  commands. For example:

  ```bash
  nagent "Inspect this project, explain the plan, update the README, and run the relevant tests."
  nagent "Investigate this Linux configuration issue, read the relevant files, run diagnostics, and propose the change before editing anything."
  ```

  Later reference sections may introduce helper commands such as
  `nagent-file-edit`, `nagent-file-split`, and `nagent-llm-text`.
- The examples should be concrete command snippets, but should not promise
  sandboxed safety or pretend nagent can modify protected system files without
  the normal OS permissions.

### LLM Primitive

- Show a minimal `nagent-llm-text` example using a text file:

  ```bash
  echo "What is 2+2?" > question.txt
  nagent-llm-text --file question.txt
  ```

- Explain that the rest of nagent is orchestration around this primitive.
- Mention `bin/nagent-llm-text` and `bin/helpers/nagent_llm.py`.

### Conversation State

- Explain that memory is a plain conversation file.
- Explain that the conversation file is not just chat history: it is the working
  state, tool transcript, correction channel, and continuation point for the
  loop.
- Show the path shape:

  ```text
  ~/.nagent/conversations/latest-{hostname}-{pid}
  ```

- Explain that repeated invocations in the same shell append to that file.
- Emphasize that there is no separate memory service.
- Explain default pid selection, including GNU screen `STY`/`WINDOW`, `BASHPID`,
  and parent-process fallback.
- Explain conversation lifecycle commands: `--clear`, `--status`,
  `--save-conversation`, `--load-conversation`, `--summarize`, and
  `--edit-conversation`.
- Explain how `--save-conversation`, `--load-conversation`, and
  `--edit-conversation` let readers inspect, branch, trim, or rewrite
  conversation history directly because the state is a normal file.
- Explain root context loading from `~/.nagent/context.md` or
  `~/.nagent/context.yaml`, including recursive YAML path expansion.

### Structured Tags

- Explain that nagent asks the model to reply only with structured tags.
- Explain that the initial context is generated at runtime and is itself part of
  the protocol: it includes environment information, discovered tool
  descriptions, context-management rules, write rules, and the exact tag grammar
  the model must follow.
- Show examples of `<nagent-shell>` and `<nagent-shell-result>`.
- Include a table of available tags:
  - `<nagent-response>`
  - `<nagent-read path="..."/>`
  - `<nagent-file-read path="..."/>`
  - `<nagent-file-patch index="..."/>`
  - `<nagent-write path="...">...</nagent-write>`
  - `<nagent-shell>...</nagent-shell>`
  - `<nagent-next>...</nagent-next>`
  - `<nagent-agent>...</nagent-agent>`
- Mention `parse_response()` in `bin/nagent`.
- Mention result wrappers appended by action handlers, including
  `<nagent-read-result>`, `<nagent-file-read-result>`,
  `<nagent-file-patch-result>`, `<nagent-write-result>`,
  `<nagent-shell-result>`, and `<nagent-agent-result>`.
- Explain `clean_user_output()` briefly: final user output strips accidental
  whole-response wrappers or a single surrounding markdown fence without
  treating inline examples as protocol tags.

### Agent Loop

- Include compact pseudocode for the loop:

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

- Mention the code path `main()` -> `run_agent_loop()` -> `call_llm()` ->
  `process_tags()`.
- Explain invalid-format retry behavior: malformed model output is appended back
  to the conversation with a system correction, up to `MAX_FORMAT_RETRIES`.
- Explain why the correction is appended to the same conversation file: failures
  become part of the visible state instead of disappearing inside control flow.
- Explain token/status accounting at a high level: `TokenStats`, JSON output
  from `nagent-llm-text`, recursive sub-agent token totals, and the optional
  spinner/status line.

### Sub-Agents

- Explain that sub-agents are child nagent processes with their own conversation
  files.
- Show a `<nagent-agent>` example.
- Explain that the parent receives only the child final response, wrapped as a
  result, rather than the whole child history.
- Emphasize that delegation is context management as much as parallelism: the
  parent keeps coordination and decisions, while children keep exploratory logs
  and noisy command output in their own files.
- Mention delegated invocation context, unique child conversation names, shared
  pid/root/provider/model/config, and recursive token accounting from child JSON
  output.

### Write Safety

- Explain the two write modes:
  - Main conversation: coordination, temp writes only via `<nagent-write>`.
  - Per-file edit session: project file writes through `nagent-file-edit`.
- State that shell writes are discouraged and not fully sandboxed.
- Frame this as safety by convention for a demo/reference implementation.
- Explain that write validation allows temp paths in `/tmp`, `/var/tmp`, or
  `$TMPDIR`; a per-file edit session may write only the target file or split
  segments associated with that target.

### Large Files

- Explain the `64KB` inline read limit.
- Describe the split -> edit segment -> patch workflow.
- Mention `nagent-file-split`, `nagent-file-patch`, and
  `nagent-file-summarize`.
- Explain that large-file summaries are stored in split metadata.
- Explain that `nagent-file-split` can use type-specific natural splitters for
  common source/config/document formats, and supports refresh/summarize
  workflows.
- Explain that `nagent-file-patch` validates the source hash before merging
  segment edits and writes a patch artifact.

### Per-File Editing

- Explain `nagent-file-edit` as a way to keep the main conversation small.
- Explain that per-file conversations are a deliberate design choice: editing
  state, prior attempts, and file-specific decisions live with a stable file id
  instead of bloating the main orchestration conversation.
- Include example commands:

  ```bash
  nagent-file-edit --file src/foo.py "add error handling"
  nagent-file-edit --file src/foo.py --clear
  nagent --list-file-edits
  ```

- Explain the stable file id concept and show a small JSON example with
  `by_file_id`, `file_id`, `path`, and `conversation`.
- Explain that `nagent --file-edit` is the lower-level mode used by
  `nagent-file-edit`, and that `nagent --list-file-edits` reports the per-shell
  file edit index.

### LLM Providers and Uploads

- Explain shared provider/config behavior from `bin/helpers/nagent_llm.py`:
  provider selection, default models, config lookup, CLI overrides, credential
  environment variables, and package checks.
- Mention text generation with usage accounting through `nagent-llm-text
  --json`.
- Mention file upload support through `nagent-llm-upload` for supported images,
  PDFs, office documents, CSV/JSON/text/code files, and the size/type checks.

### CLI and Tool Discovery

- Explain `--description` as the mechanism that lets nagent collect tool
  descriptions for the initial context.
- Explain that this makes helper tools discoverable without a central registry:
  each executable can describe itself, and `nagent` folds those descriptions
  into the model-visible startup prompt.
- Mention shared CLI helpers in `bin/helpers/nagent_cli.py`, including JSON
  output and the wait spinner.
- Mention stdin prompt handling, including trailing `-` and piped stdin.

### Framework Comparison

- Include a table comparing typical frameworks with nagent:
  - State in objects/services vs plain text file.
  - Tools registered in code vs tags in model output.
  - Shared memory/thread vs one file per instance.
  - Many layers/dependencies vs one loop and few files.

### Minimal Recipe

- End the educational walkthrough with a short recipe:
  - `generate_text(file) -> str`
  - a growing conversation document
  - a generated initial context that states the contract
  - an output format and parser
  - action handlers that append results back into state
  - a loop that retries malformed output and continues after actions
  - child loops for delegated work
  - explicit context boundaries for large files and per-file edits
  - conversation save/load/edit tools for inspecting and branching history

- Include the code-reading order:

  ```text
  main()
    run_agent_loop()
      call_llm()
      parse_response()
      process_tags()
  ```

### Tool Reference

- Include a reference table for:
  - `nagent`
  - `nagent-llm-text`
  - `nagent-llm-upload`
  - `nagent-file-split`
  - `nagent-file-patch`
  - `nagent-file-edit`
  - `nagent-file-summarize`
- Mention that tools accept `--json` where applicable.
- Mention shared provider/config code under `bin/helpers/`.

### Setup

- Include setup commands:

  ```bash
  pip install -r requirements.txt
  export PATH="$PWD/bin:$PATH"
  mkdir -p ~/.nagent
  cp config.example.json ~/.nagent/config.json   # optional
  ```

- Explain that config loads from `NAGENT_CONFIG` or `~/.nagent/config.json`, and
  CLI flags override config.
- Include a small config JSON example with provider and model.
- Include the provider/default-model/API-key table for OpenAI, Anthropic,
  Google, and Cursor.
- Mention `NAGENT_NO_SPINNER=1` and `NAGENT_CONFIG`.

### Common Commands

- Include examples for:
  - `nagent "your prompt here"`
  - `echo "prompt from stdin" | nagent`
  - `nagent --status --json`
  - `nagent --list-models --json`
  - `nagent --list-file-edits --pid "$BASHPID"`
  - `nagent --clear`
  - `nagent-llm-text`
  - `nagent-llm-upload`
  - `nagent-file-split`
  - `nagent-file-patch`
  - `nagent-file-summarize`
  - `nagent-file-edit`

### Tests

- Include:

  ```bash
  python3 -m unittest discover -s tests -v
  ```

## Style Rules

- Keep the README readable in one sitting.
- Use short sections and concrete examples.
- Use Markdown tables where they make reference material easier to scan.
- Use horizontal rules between major step sections if it improves readability.
- Prefer "Build your own:" notes over implementation trivia.
- Mention source files and functions only when they help the reader find the
  implementation.
- Do not overstate safety; be explicit that this is a demo/reference
  implementation, not a sandboxed security product.
- Do not turn the README into full API documentation. It should teach the core
  pattern, then point to `--help`, source files, and tests for details.
