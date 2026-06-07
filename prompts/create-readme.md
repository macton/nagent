# Create the nagent README

Write `README.md` for the `nagent` project.

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
- Show the path shape:

  ```text
  ~/.nagent/conversations/latest-{hostname}-{pid}
  ```

- Explain that repeated invocations in the same shell append to that file.
- Emphasize that there is no separate memory service.

### Structured Tags

- Explain that nagent asks the model to reply only with structured tags.
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

### Sub-Agents

- Explain that sub-agents are child nagent processes with their own conversation
  files.
- Show a `<nagent-agent>` example.
- Explain that the parent receives only the child final response, wrapped as a
  result, rather than the whole child history.

### Write Safety

- Explain the two write modes:
  - Main conversation: coordination, temp writes only via `<nagent-write>`.
  - Per-file edit session: project file writes through `nagent-file-edit`.
- State that shell writes are discouraged and not fully sandboxed.
- Frame this as safety by convention for a demo/reference implementation.

### Large Files

- Explain the `64KB` inline read limit.
- Describe the split -> edit segment -> patch workflow.
- Mention `nagent-file-split`, `nagent-file-patch`, and
  `nagent-file-summarize`.
- Explain that large-file summaries are stored in split metadata.

### Per-File Editing

- Explain `nagent-file-edit` as a way to keep the main conversation small.
- Include example commands:

  ```bash
  nagent-file-edit --file src/foo.py "add error handling"
  nagent-file-edit --file src/foo.py --clear
  nagent --list-file-edits
  ```

- Explain the stable file id concept and show a small JSON example with
  `by_file_id`, `file_id`, `path`, and `conversation`.

### Framework Comparison

- Include a table comparing typical frameworks with nagent:
  - State in objects/services vs plain text file.
  - Tools registered in code vs tags in model output.
  - Shared memory/thread vs one file per instance.
  - Many layers/dependencies vs one loop and few files.

### Minimal Recipe

- End the educational walkthrough with a short recipe:
  - `generate_text(file) -> str`
  - a growing document
  - an output format and parser
  - the loop
  - incremental capabilities

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
