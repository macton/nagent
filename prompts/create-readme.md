# Create the nagent README

Write `README.md` for the `nagent` project.

Before writing, inspect the current source code. Do not rely only on this prompt
or on an existing README. Read the main scripts under `bin/`, the helper modules
under `bin/helpers/`, and the tests when needed. Ground the walkthrough in the
implementation that actually exists.

Do not treat the README as marketing material. Treat it as a teaching document
for programmers who want to understand the architecture and build their own
version.

---

# Core Thesis

The README should communicate one central idea:

**The persistent object is not the agent. The persistent object is the work.**

LLMs are temporary.

Processes are temporary.

Context windows are temporary.

The durable part of the system is explicit data.

nagent keeps durable state in editable artifacts:

* conversations
* per-file conversations
* root context files
* split indexes
* summaries
* patch artifacts

The agent loop exists to transform those artifacts.

A text file, an LLM, structured tags, and a loop are the implementation of this
idea, not the idea itself.

---

# Data-Oriented Design

Frame nagent using data-oriented principles.

Do not describe the system primarily as interacting objects, personalities, or
autonomous agents.

Describe it as a series of data transformations.

Emphasize these ideas:

* state should be explicit
* state should be inspectable
* state should be editable
* state should not hide inside process memory
* transformations should be visible
* artifacts should outlive the processes that create them

Connect the implementation to familiar data-oriented principles:

* the data is more important than the code operating on it
* behavior is a transformation over explicit state
* avoid hidden mutable state
* separate durable artifacts from temporary execution

Show that:

* conversations are data
* per-file memory is data
* split indexes are data
* patch artifacts are data
* sub-agents are temporary workers operating on data

---

# Intent

The README should make these ideas clear:

* **nagent** means **not-an-agent**
* the project intentionally uses plain files, Python, subprocesses, and
  structured text
* "agent behavior" is mostly:

  * append to conversation
  * call LLM
  * parse reply
  * run actions
  * append results
  * repeat
* the implementation is intentionally small
* the architecture should be understandable in one sitting
* the reader should understand the design well enough to copy, modify, or reject
  pieces of it

The README should be grounded in the actual code.

Avoid hype.

Avoid framework jargon except when making comparisons.

Prefer concrete examples.

---

# Audience

Write for programmers who:

* know basic Python
* know command-line tools
* are curious how agent loops work
* appreciate explicit state
* like inspectable systems
* may want to build a small tool without a framework

Do not assume knowledge of nagent internals.

---

# Teaching Strategy

Do not organize the README only around implementation order.

Teach through a sequence of reductions.

Observation:

LLMs forget.

Therefore:

Put memory in files.

Observation:

One conversation grows too large.

Therefore:

Attach memory to artifacts.

Observation:

Repeated work accumulates around individual files.

Therefore:

Give each file persistent local memory.

Observation:

Exploration creates noise.

Therefore:

Use disposable sub-agents.

Observation:

Large files exceed context windows.

Therefore:

Create explicit split/index/patch artifacts.

Observation:

Memory becomes stale.

Therefore:

Allow conversations to be edited, summarized, branched, and rewritten.

---

# Structure

Organize the main body as numbered sections.

## 1. Durable work, disposable workers

Introduce the philosophy.

Explain that the system preserves work, not processes.

Include a small diagram.

## 2. Text in, text out

Show the smallest possible LLM primitive.

Explain that everything else is orchestration.

Include a minimal `nagent-llm-text` example.

## 3. Conversations are editable state

Explain that the conversation file is not chat history.

It is:

* working state
* tool transcript
* correction channel
* continuation point
* editable artifact

Explain both forms of editing:

Explicit:

* `--save-conversation`
* `--load-conversation`
* `--summarize`
* `--edit-conversation`

Implicit:

Because conversations are ordinary files they can be:

* opened
* edited
* trimmed
* rewritten
* diffed
* copied
* versioned
* scripted

Use this idea:

"The agent does not own its memory. The user does."

## 4. Teach the model an output format

Explain structured tags.

Show examples.

Explain runtime-generated initial context.

Show the parser contract.

## 5. The loop

Show the append/call/parse/act/append/repeat algorithm.

Explain malformed output retries.

Explain that failures become visible state.

## 6. Persistent per-file memory

Treat this as a memory model, not merely a helper tool.

Explain that most coding agents remember sessions.

nagent remembers artifacts.

Per-file conversations preserve:

* previous attempts
* failed fixes
* local assumptions
* file-specific context
* editing history

Explain stable file ids.

Explain why artifact-local memory keeps the main conversation small.

Include example commands.

## 7. Disposable sub-agents

Frame sub-agents as temporary workers.

Their lifetime is not important.

The artifacts they produce are important.

Explain that:

* the parent keeps coordination
* the child keeps noisy exploration
* the parent receives only the useful result

Explain that delegation is primarily context management.

## 8. Controlled writes

Explain write boundaries.

Explain temp writes.

Explain per-file edit mode.

Be explicit that this is a convention-based reference implementation rather than
a hardened sandbox.

## 9. Large files as explicit artifacts

Explain the split/edit/patch workflow.

Present split indexes as durable data structures.

Explain:

* summaries
* natural splitters
* source hash validation
* patch artifacts

## 10. Tool discovery

Explain `--description`.

Explain that helper tools describe themselves.

Show that there is no central registry.

The startup prompt is assembled from explicit data.

## 11. How this differs from frameworks

Do not market against frameworks.

Compare architectural styles.

Include a table covering:

* hidden state vs explicit files
* object graphs vs data artifacts
* framework registries vs executable descriptions
* session memory vs artifact memory
* opaque orchestration vs visible transformations

## 12. Build your own

End with a minimal recipe:

* generate_text(file)
* durable conversation
* explicit protocol
* parser
* action handlers
* append results
* retry malformed output
* child loops
* artifact-local memory
* editable conversations

Include code reading order.

---

# Required Concepts

The README should explicitly explain:

## Editable Memory

Conversations are mutable data structures.

Users may rewrite history.

The history is part of the architecture.

## Artifact Memory

Per-file conversations are artifact-local memory.

The goal is not to preserve chat.

The goal is to preserve useful work.

## Data Flow

The architecture is fundamentally:

artifact
->
LLM transformation
->
artifact

not

object
->
method
->
hidden state

## Disposable Workers

LLMs and sub-agents are interchangeable transformation functions.

The durable object is the artifact they modify.

---

# Opening

Start with:

# nagent

State that nagent means not-an-agent.

Describe it as a small, readable reference implementation.

Include the core phrase:

"a text file, an LLM, structured tags, and a loop"

Then immediately explain that these are mechanisms for maintaining durable work
artifacts.

Include a short "What it looks like" section.

Use concrete examples.

Use only the `nagent` command in those examples.

---

# Required Technical Coverage

Cover the existing implementation accurately.

Include:

* `nagent-llm-text`
* conversation files
* root context loading
* structured tags
* parser
* result wrappers
* loop
* retry behavior
* token accounting
* sub-agents
* write controls
* large-file support
* per-file editing
* provider abstraction
* upload support
* tool discovery
* setup
* common commands
* tests

Ground these sections in the implementation.

Do not invent features.

---

# Build Your Own Notes

Each major section should end with:

**Build your own:**

Translate the implementation into a reusable design pattern.

Avoid implementation trivia.

Prefer architectural lessons.

---

# Style Rules

Keep the README readable in one sitting.

Use short sections.

Use concrete examples.

Use diagrams where helpful.

Use tables for reference material.

Do not overstate safety.

Do not describe nagent as a product.

Do not describe nagent as an autonomous intelligence.

Do not turn the README into API documentation.

Teach the architecture.

Teach the data flow.

Teach why the state is explicit.

Teach why the artifacts matter more than the workers.
