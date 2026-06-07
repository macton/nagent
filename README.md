# nagent

**nagent** means **not-an-agent**.

It is a very small, but usable, example of how to build “agent-like” systems. The goal is not to ship a product-grade agent platform. The goal is to show that the idea is simpler than it sounds — so you can read the code, understand it, and build your own.

Many “agent” products wrap the same few steps in heavy abstractions. That makes it hard to see what is actually happening. nagent keeps the steps visible.

## The whole idea

At the bottom, everything is this:

1. You have a **text file** (the conversation).
2. You **send that text** to an LLM.
3. You **get text back**.
4. You **append** the response (and any results from actions it requested) to the file.
5. You **repeat** until the model gives a final answer to the user.

That is the entire loop. “Agent behavior” is just rules for what to do with the response before you call the LLM again.

There is no hidden runtime, no magic memory, no special agent object. There is a file on disk and a loop that edits it.

In the same shell, you can run nagent more than once. Each prompt continues the same conversation:

```
$ nagent "What files are in this directory?"
There are 12 files, including README.md, bin/, and tests/.

$ nagent "Which one is the main entry point?"
The main script is bin/nagent.
```

The second answer works because the conversation file still contains the first exchange. You are not starting over each time.

## Step 1: Send text, get text

The smallest piece is `nagent-llm-text`:

```bash
echo "What is 2+2?" > question.txt
nagent-llm-text --file question.txt
```

This reads a file, sends its contents to the configured LLM, and prints the reply. One file in, one string out.

Everything else in nagent is built on top of this.

## Step 2: Keep the conversation in a file

`nagent` does not send just your one-line prompt. It keeps a **conversation file** — a growing text document — and sends the whole thing to the LLM each turn.

On first run, nagent creates something like:

```
~/.nagent/latest-{hostname}-{pid}
```

That file starts with instructions (what tags the model may use, what tools exist, where it is running) and your prompt:

```
<initial_context>
...environment info...
</initial_context>

<nagent-response>...</nagent-response>
<nagent-read path="..." />
...

<user-prompt>
What files are in this directory?
</user-prompt>
```

Each time the LLM replies, nagent **appends** that reply to the conversation file. If the model asked to run a command or read a file, nagent runs that, **appends the output**, and calls the LLM again with the updated file.

So “memory” is just: *what is currently in the text file*.

## Step 3: Teach the LLM a simple output format

The LLM is asked to reply using plain XML-like **tags**, not free-form chat. For example:

```xml
<nagent-shell>ls -la</nagent-shell>
```

nagent parses the response, runs `ls -la`, and appends something like:

```xml
<nagent-shell-result>
exit_code: 0
stdout:
total 24
...
</nagent-shell-result>
```

Then it sends the whole conversation file to the LLM again.

Available tags:

| Tag | What nagent does |
|---|---|
| `<nagent-response>` | Print this to the user (final answer) |
| `<nagent-read path="..."/>` | Read a file, append contents to conversation |
| `<nagent-write path="...">...</nagent-write>` | Write a file |
| `<nagent-shell>...</nagent-shell>` | Run shell commands, append output |
| `<nagent-next>...</nagent-next>` | Append a follow-up prompt and continue |
| `<nagent-agent>...</nagent-agent>` | Start a sub-agent (see below) |

The model chooses tags. nagent executes them and updates the text file. No separate message bus or tool registry — just text in, text out, append, repeat.

## Step 4: The loop

In code, the loop is roughly:

```
append user prompt to conversation file
loop:
    response = send conversation file to LLM   # via nagent-llm-text
    append response to conversation file
    if response contains action tags:
        run those actions
        append results to conversation file
        continue loop
    if response contains <nagent-response>:
        print it and stop
```

That is `bin/nagent`. You can read it start to finish; it is a few hundred lines of Python.

## Step 5: Sub-agents are the same pattern again

When the model emits `<nagent-agent>`, nagent starts **another** `nagent` process with its **own** conversation file and a scoped prompt.

The parent does not share its full history with the child. The child runs the same text-file loop, returns a result, and the parent appends that result to its own conversation.

Sub-agents are not a different system. They are the same “manage a text file, call the LLM” loop, nested.

## Large files: split, edit, patch

For files too big to fit in context, nagent includes two partner tools:

1. **`nagent-file-split`** — break a file into smaller segments plus an `index.json`.
2. Edit the segment files (via `<nagent-read>` / `<nagent-write>` or by hand).
3. **`nagent-file-patch`** — merge segment edits back into the original file.

Same idea: files on disk, plain text, no special agent machinery.

## Tools

Run any tool with `--description` to see what it does and its path:

```bash
nagent --description
```

| Command | Purpose |
|---|---|
| `bin/nagent` | Main loop: manage conversation file, parse tags, call LLM |
| `bin/nagent-llm-text` | Send a text file to the LLM, print response |
| `bin/nagent-llm-upload` | Send a file (image, PDF, etc.) with a prompt |
| `bin/nagent-file-split` | Split a large file into segments |
| `bin/nagent-file-patch` | Merge segment edits back to the source file |

Shared provider/config code lives in `bin/helpers/` (not meant to be run directly).

## Installation

```bash
pip install -r requirements.txt
```

Add `bin/` to your `PATH`, or run commands from the repo:

```bash
./bin/nagent "hello"
```

## Configuration

nagent loads settings from:

1. `NAGENT_CONFIG` — path to a config JSON file, if set
2. otherwise `~/.nagent/config.json`

If no config exists, the default provider is `openai` with that provider's default model.

```bash
mkdir -p ~/.nagent
cp config.example.json ~/.nagent/config.json
```

Example `~/.nagent/config.json`:

```json
{
  "provider": "openai",
  "model": "gpt-5.5"
}
```

`model` is optional. CLI flags override the config file.

### Providers

| Provider | Default model | Python package |
|---|---|---|
| `openai` | `gpt-5.5` | `openai` |
| `anthropic` | `claude-sonnet-4-6` | `anthropic` |
| `google` | `gemini-2.5-flash` | `google-genai` |
| `cursor` | `composer-2.5` | `cursor-sdk` |

### API keys

Set the key for your configured provider:

| Provider | Environment variable(s) |
|---|---|
| `openai` | `OPENAI_API_KEY` |
| `anthropic` | `ANTHROPIC_API_KEY` |
| `google` | `GOOGLE_API_KEY` or `GEMINI_API_KEY` |
| `cursor` | `CURSOR_API_KEY` |

## Usage

```bash
# Run the loop with a prompt
nagent "What files are in this directory?"

# Conversation path and size
nagent --status

# List models for the configured provider
nagent --list-models

# One-shot: send a text file to the LLM
nagent-llm-text --file prompt.txt

# One-shot: upload a file with a prompt
nagent-llm-upload --file chart.png --prompt "Describe this chart"

# Split a large file for editing
nagent-file-split --file src/big.py --output /tmp/big-split

# Merge segment edits back
nagent-file-patch --index /tmp/big-split/index.json
```

Run `--help` on any command for full options.

## Build your own

If you want to make something “agent-like”:

1. Start with **text file → LLM → text response** (`nagent-llm-text` is the minimal version).
2. Decide what **format** you want the model to reply in (tags, JSON, etc.).
3. Write a **loop** that parses the response, runs side effects, appends results to the file, and calls the LLM again.
4. Add only what you need: file I/O, shell, sub-processes, chunking large files.

You do not need a framework. You need a file, a loop, and clear rules for the model's output.

Read `bin/nagent` and follow the flow from `main()` → `run_agent_loop()` → `call_llm()` → `process_tags()`. That is the whole design.

## Tests

```bash
python3 -m unittest discover -s tests -v
```
