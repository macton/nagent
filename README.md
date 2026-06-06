# nagent

nagent is a structured agent loop for the terminal. It maintains a conversation file, calls an LLM through pluggable providers, parses structured response tags, and can delegate work to sub-agents, shell commands, and file operations.

## Binaries

| Command | Purpose |
|---|---|
| `bin/nagent` | Main agent orchestrator |
| `bin/nagent-llm-text` | Send a text file to the configured LLM |
| `bin/nagent-llm-upload` | Upload a file with a prompt to the configured LLM |

Shared provider/config logic lives in `bin/helpers/nagent_llm.py` (not user-facing).

## Installation

```bash
pip install -r requirements.txt
```

Add `bin/` to your `PATH`, or invoke commands directly from the repo.

## Configuration

nagent and the LLM utilities auto-load configuration from:

1. `NAGENT_CONFIG` — if set, path to a config JSON file
2. otherwise `~/.nagent/config.json`

If no config file exists, the default provider is `openai` with that provider's default model.

Copy the example config:

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

`model` is optional. If omitted, nagent uses the default model for the selected provider (see table below).

List available models for the configured provider:

```bash
nagent --list-models
nagent --provider google --list-models
```

CLI flags override the config file:

```bash
nagent --provider anthropic --model claude-sonnet-4-6 "hello"
nagent-llm-text --file prompt.txt
nagent-llm-upload --file report.pdf --prompt "Summarize this"
```

### Providers

Supported `provider` values:

| Provider | Default model | Python package |
|---|---|---|
| `openai` | `gpt-5.5` | `openai` |
| `anthropic` | `claude-sonnet-4-6` | `anthropic` |
| `google` | `gemini-2.5-flash` | `google-genai` |
| `cursor` | `composer-2.5` | `cursor-sdk` |

### API keys and environment variables

Set the API key for the provider you configure. nagent checks credentials at runtime and exits with an error if the required variable is missing.

| Provider | Environment variable(s) |
|---|---|
| `openai` | `OPENAI_API_KEY` |
| `anthropic` | `ANTHROPIC_API_KEY` |
| `google` | `GOOGLE_API_KEY` or `GEMINI_API_KEY` |
| `cursor` | `CURSOR_API_KEY` |

Example:

```bash
export OPENAI_API_KEY="sk-..."
export ANTHROPIC_API_KEY="sk-ant-..."
export GOOGLE_API_KEY="..."
export CURSOR_API_KEY="..."
```

Only the key matching your configured `provider` is required for a given run.

Keys are typically obtained from:

- OpenAI: https://platform.openai.com
- Anthropic: https://console.anthropic.com
- Google Gemini: https://aistudio.google.com/apikey
- Cursor: Cursor account / API settings (Cursor SDK)

### Conversation storage

By default, nagent stores conversation files under `~/.nagent/`. Use `--root` and `--conversation` to change location or name. `--status` prints the conversation path and file size.

## Usage

```bash
# Run the agent with a prompt
nagent "What files are in this directory?"

# Check conversation status
nagent --status

# List models for the configured provider
nagent --list-models

# Send a text file directly to the LLM
nagent-llm-text --file prompt.txt

# Upload a file with a prompt
nagent-llm-upload --file chart.png --prompt "Describe this chart"
```

Run `--help` on any command for full options.

## Tests

```bash
python3 -m unittest tests.test_nagent -v
```
