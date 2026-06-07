# Prep

Read bin/nagent
Run --description on all files in bin/
Read other source files when need more detail.

# Create the nagent README

Write `README.md` for the `nagent` project.

Before writing, inspect the current source code. Do not rely only on this prompt
or on an existing README. Read the main scripts under `bin/`, the helper modules
under `bin/helpers/`, and the tests when needed. Ground the walkthrough in the
implementation that actually exists.

Do not treat the README as marketing material. Treat it as a teaching document
for programmers who want to understand the architecture and build their own
version.

Do not turn the README into API documentation. Teach the system.

---

# Core Thesis

The README should communicate one central idea:

**The persistent object is not the agent. The persistent object is the work.**

nagent is a data-oriented architecture for AI workflows.

LLMs are temporary.

Processes are temporary.

Sub-agents are temporary.

Context windows are temporary.

The durable part of the system is explicit data.

nagent keeps durable state in editable artifacts:

- conversations
- per-file conversations
- root context files
- repository history summaries
- historical coupling data
- artifact neighborhoods
- file summaries
- split indexes
- patch artifacts

The agent loop exists to transform those artifacts.

A text file, an LLM, structured tags, and a loop are the implementation of this
idea, not the idea itself.

---

# Data-Oriented Design

Frame nagent using data-oriented principles.

Do not describe the system primarily as interacting objects, personalities, or
autonomous agents.

Describe it as a series of explicit data transformations:

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

Emphasize these ideas:

- state should be explicit
- state should be inspectable
- state should be editable
- state should not hide inside process memory
- transformations should be visible
- artifacts should outlive the processes that create them
- workers are disposable
- artifacts are durable

Connect the implementation to familiar data-oriented principles:

- the data is more important than the code operating on it
- behavior is a transformation over explicit state
- avoid hidden mutable state
- separate durable artifacts from temporary execution
- optimize the shape, availability, and maintenance of the data

Show that:

- conversations are data
- per-file memory is data
- repository history is data
- historical coupling is data
- split indexes are data
- patch artifacts are data
- sub-agents are temporary workers operating on data

---

# Intent

The README should make these ideas clear:

- **nagent** means **not-an-agent**
- the project intentionally uses plain files, Python, subprocesses, and
  structured text
- "agent behavior" is mostly:
  - append to conversation
  - call LLM
  - parse reply
  - run actions
  - append results
  - repeat
- the implementation is intentionally small
- the architecture should be understandable in one sitting
- the reader should understand the design well enough to copy, modify, or reject
  pieces of it
- the novel part is artifact management and explicit data flow, not tool calling

The README should be grounded in the actual code.

Avoid hype.

Avoid framework jargon except when making comparisons.

Prefer concrete examples.

---

# Audience

Write for programmers who:

- know basic Python
- know command-line tools
- are curious how agent loops work
- appreciate explicit state
- like inspectable systems
- may want to build a small tool without a framework
- understand why durable artifacts can matter more than runtime behavior

Do not assume the reader already knows nagent's internals.

---

# Teaching Strategy

Do not organize the README only around implementation order.

Teach through a sequence of reductions:

```text
Problem
    ->
Observation
    ->
Design decision
    ->
Implementation
    ->
Transferable pattern
```

Use these reductions throughout the README:

LLMs forget.

Therefore:

Put memory in files.

---

One conversation grows too large.

Therefore:

Attach memory to artifacts.

---

Repeated work accumulates around individual files.

Therefore:

Give each file persistent local memory.

---

Repositories contain historical knowledge.

Therefore:

Transform git history into editing context.

---

Exploration creates noise.

Therefore:

Use disposable sub-agents.

---

Large files exceed context windows.

Therefore:

Create explicit split/index/patch artifacts.

---

Memory becomes stale.

Therefore:

Allow conversations to be edited, summarized, branched, and rewritten.

---

# Required Concept Checklist

Before finishing the README, verify that it explicitly explains all of these:

- [ ] durable explicit state
- [ ] editable conversations
- [ ] direct conversation-file editing
- [ ] artifact-local memory
- [ ] per-file conversations
- [ ] stable file ids
- [ ] root context
- [ ] repository history as data
- [ ] commit summaries
- [ ] file summaries
- [ ] people who edited a file
- [ ] historical coupling
- [ ] co-edited files
- [ ] artifact neighborhoods
- [ ] large-file split/index/patch
- [ ] disposable workers
- [ ] sub-agent isolation
- [ ] controlled writes
- [ ] visible protocols
- [ ] explicit transformation pipelines
- [ ] parser retries as visible state
- [ ] tool discovery through executable descriptions

---

# Structure

Organize the main body as numbered sections.

Each major numbered section must include:

1. **Idea** — the design idea.
2. **Implementation** — where and how nagent implements it.
3. **Example** — a command, tag, table, or pseudocode block.
4. **Build your own:** — the reusable pattern.

## 1. Durable work, disposable workers

Introduce the philosophy.

Explain that the system preserves work, not processes.

Include this diagram or an equivalent:

```text
temporary worker
        |
        v
durable artifacts
        |
        v
next temporary worker
```

Make clear that the durable artifacts, not the running process, are the system.

## 2. Text in, text out

Show the smallest possible LLM primitive.

Include a minimal `nagent-llm-text` example:

```bash
echo "What is 2+2?" > question.txt
nagent-llm-text --file question.txt
```

Explain that everything else is orchestration around this primitive.

Mention `bin/nagent-llm-text` and `bin/helpers/nagent_llm.py`.

## 3. Conversations are editable state

Explain that the conversation file is not chat history.

It is:

- working state
- tool transcript
- correction channel
- continuation point
- editable artifact

Explain both forms of editing.

Explicit editing:

- `--save-conversation`
- `--load-conversation`
- `--summarize`
- `--edit-conversation`

Implicit editing:

Because conversations are ordinary files they can be:

- opened
- edited
- trimmed
- rewritten
- diffed
- copied
- versioned
- scripted

Use this idea:

**The agent does not own its memory. The user does.**

Explain that conversation files are mutable data structures, not immutable logs.

## 4. Teach the model an output format

Explain structured tags.

Show examples of action tags and result tags.

Explain that runtime-generated initial context is part of the protocol.

Mention the parser contract and `parse_response()`.

Include a table of available tags:

- `<nagent-response>`
- `<nagent-read path="..."/>`
- `<nagent-file-read path="..."/>`
- `<nagent-file-patch index="..."/>`
- `<nagent-write path="...">...</nagent-write>`
- `<nagent-shell>...</nagent-shell>`
- `<nagent-next>...</nagent-next>`
- `<nagent-agent>...</nagent-agent>`

Explain result wrappers appended by handlers.

## 5. The loop

Show the append/call/parse/act/append/repeat algorithm:

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

Mention the code path:

```text
main()
  run_agent_loop()
    call_llm()
    parse_response()
    process_tags()
```

Explain malformed output retries.

Explain that failures become visible state instead of hidden control-flow state.

Explain token/status accounting at a high level.

## 6. Persistent per-file memory

Treat this as a memory model, not merely a helper tool.

Explain that most coding agents remember sessions.

nagent remembers artifacts.

Per-file conversations preserve:

- previous investigations
- failed attempts
- local assumptions
- file-specific context
- editing history
- historical context

Explain stable file ids.

Explain why artifact-local memory keeps the main conversation small.

Include example commands:

```bash
nagent-file-edit --file src/foo.py "add error handling"
nagent-file-edit --file src/foo.py --clear
nagent --list-file-edits
```

Show a small JSON-like example with:

- `by_file_id`
- `file_id`
- `path`
- `conversation`

## 7. Repository history as data

Explain that nagent does not treat the repository as only a set of current files.

It also treats repository history as a durable artifact that can be transformed
into editing context.

For file-edit sessions, explain the current implementation should include
available details such as:

- file history
- commit summaries
- file summaries
- people who edited the file
- files edited in the same commits
- historical coupling / co-edit rates

Explain that this is not generic retrieval.

It is transformation of historical artifacts into working context.

Use this diagram or an equivalent:

```text
git history
    ->
commit/file summaries
    ->
file-edit initial context
    ->
better artifact-local edit decisions
```

Make clear that historical context is a hint, not a command.

## 8. Historical coupling and artifact neighborhoods

Introduce the idea that a file exists within a neighborhood of related artifacts.

Historical coupling can identify:

- likely companion files
- related tests
- related headers
- related configuration
- frequently co-edited implementation files

Explain that co-edited files are candidates for inspection, not automatic edit
targets.

Use this phrase or equivalent:

**High co-edit files are candidates for inspection, not automatic edit targets.**

Include an example table:

| file | commits together | historical co-edit rate |
| --- | ---: | --- |
| src/foo_test.py | 7 | high (70%) |
| src/foo.h | 5 | medium (50%) |

Prefer "historical co-edit rate" or "changed with this file" over ambiguous
phrases such as "likelihood of same-commit edit."

## 9. Disposable sub-agents

Frame sub-agents as temporary workers.

Their lifetime is not important.

The artifacts they produce are important.

Explain that:

- the parent keeps coordination
- the child keeps noisy exploration
- the parent receives only the useful result
- delegation is primarily context management, not just parallelism

Show a `<nagent-agent>` example.

## 10. Controlled writes

Explain write boundaries.

Explain temp writes.

Explain per-file edit mode.

Be explicit that this is a convention-based reference implementation rather than
a hardened sandbox.

Explain that shell commands are powerful and not fully sandboxed.

## 11. Large files as explicit artifacts

Explain the split/edit/patch workflow.

Present split indexes as durable data structures.

Explain:

- summaries
- natural splitters
- source hash validation
- patch artifacts
- refresh behavior when relevant

Use this diagram or an equivalent:

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

## 12. Tool discovery

Explain `--description`.

Explain that helper tools describe themselves.

Show that there is no central registry.

The startup prompt is assembled from explicit data.

Connect this back to data-oriented design: even tool capabilities are surfaced as
data.

## 13. How this differs from frameworks

Do not market against frameworks.

Compare architectural styles.

Include a table covering:

| Framework-style system | nagent |
| --- | --- |
| hidden or managed state | explicit files |
| session memory | artifact memory |
| object/service graph | data artifacts |
| central tool registry | executable descriptions |
| long-lived agent abstraction | disposable workers |
| opaque orchestration | visible transformations |

Also include a small table comparing:

| Common term | nagent framing |
| --- | --- |
| memory | editable artifact |
| retrieval | preserved work / historical context |
| agent | temporary transformation function |
| context | explicit input data |

## 14. Build your own

End with a compact recipe:

- implement `generate_text(file) -> str`
- keep a growing conversation document
- generate initial context that states the contract
- define an output format and parser
- write action handlers that append results back into state
- loop after actions
- retry malformed output with visible corrections
- add child loops for delegated work
- add per-artifact memory
- transform repository history into artifact context
- add split/index/patch for large files
- add save/load/edit/summarize tools for memory maintenance

Include code reading order:

```text
main()
  run_agent_loop()
    call_llm()
    parse_response()
    process_tags()
```

---

# Required Technical Coverage

Cover the existing implementation accurately.

Include:

- `nagent-llm-text`
- conversation files
- root context loading
- structured tags
- parser
- result wrappers
- loop
- retry behavior
- token accounting
- sub-agents
- write controls
- large-file support
- per-file editing
- stable file ids
- file-edit initial context
- repository history
- commit summaries
- file summaries
- historical coupling / co-edited files
- provider abstraction
- upload support
- tool discovery
- setup
- common commands
- tests

Ground these sections in the implementation.

Do not invent features.

---

# Required Diagrams

Include at least these diagrams, adapted to the final wording:

## Transformation model

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

## Context model

```text
main conversation
        |
        +-- file A memory
        |
        +-- file B memory
        |
        +-- file C memory
```

## Artifact neighborhood

```text
target file
        |
        +-- historical summary
        +-- co-edited files
        +-- local conversation
        +-- split indexes
```

---

# Required Tables

Include tables for:

- hidden state vs explicit artifacts
- session memory vs artifact memory
- retrieval vs preserved work
- long-lived agents vs disposable workers
- object graphs vs data artifacts
- framework-style systems vs nagent

---

# Style Rules

Target 2500-5000 words.

Keep the README readable in one sitting.

Use short sections.

Use concrete examples.

Use diagrams where helpful.

Use Markdown tables where they make reference material easier to scan.

Use horizontal rules between major step sections if it improves readability.

Prefer **Build your own:** notes over implementation trivia.

Mention source files and functions only when they help the reader find the
implementation.

Do not overstate safety.

Do not describe nagent as a product.

Do not describe nagent as an autonomous intelligence.

Do not turn the README into full API documentation.

Teach the architecture.

Teach the data flow.

Teach why the state is explicit.

Teach why artifacts matter more than workers.

---

# Final Self-Review Checklist

Before finishing the README, verify:

- [ ] Every major feature is justified by a reduction.
- [ ] Every major numbered section ends with **Build your own:**.
- [ ] Every architectural claim is grounded in implementation.
- [ ] Novelty is attributed to data flow and artifact management, not tool calling.
- [ ] The README explains editable conversations as mutable data structures.
- [ ] The README explains per-file conversations as artifact-local memory.
- [ ] The README explains repository history as first-class data.
- [ ] The README explains historical coupling as inspection guidance, not an edit mandate.
- [ ] The README explains sub-agents as disposable workers.
- [ ] The README explains split/index/patch as explicit artifacts.
- [ ] The reader could build a minimal version after reading.
