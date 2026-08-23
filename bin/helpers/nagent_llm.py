#!/usr/bin/python3

import json
import mimetypes
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from nagent_cli import git_toplevel

PROVIDERS = ("openai", "anthropic", "google", "gemini", "cursor", "claude-code", "together", "openrouter")
PROVIDER_ALIASES = {"gemini": "google"}

# Together and OpenRouter expose OpenAI-wire-compatible APIs (chat completions
# + /v1/models), so those providers reuse the openai SDK pointed at their base URLs.
TOGETHER_BASE_URL = "https://api.together.ai/v1"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# For the claude-code provider, "default" means Claude Code's own configured
# model: the SDK is invoked with model=None and Claude Code decides.
CLAUDE_CODE_DEFAULT_MODEL = "default"

DEFAULT_MODELS = {
    "openai": "gpt-5.5",
    "anthropic": "claude-sonnet-4-6",
    "google": "gemini-2.5-flash",
    "cursor": "composer-2.5",
    "claude-code": CLAUDE_CODE_DEFAULT_MODEL,
    "together": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
    "openrouter": "stealth/ox-alpha",
}

# An empty tuple means the provider manages its own credentials; claude-code
# uses the local Claude Code login (subscription or API key), not an env var.
CREDENTIAL_ENV = {
    "openai": ("OPENAI_API_KEY",),
    "anthropic": ("ANTHROPIC_API_KEY",),
    "google": ("GOOGLE_API_KEY", "GEMINI_API_KEY"),
    "cursor": ("CURSOR_API_KEY",),
    "claude-code": (),
    "together": ("TOGETHER_API_KEY",),
    "openrouter": ("OPENROUTER_API_KEY",),
}

# Maximum input context window, in tokens, for models whose limit we have
# verified directly against the provider. nagent uses this to rebuild a
# conversation before a request would exceed the model's window. A model that
# is absent returns None from model_context_window() — "unknown", which falls
# back to the byte-size rebuild threshold. Override or extend per-model in
# config via "context_window_tokens" (no code change needed for a new model).
#
# Values are the maximum INPUT tokens the provider actually enforces (what the
# rebuild trigger compares estimated request tokens against), which is not
# always the advertised total context_length.
#
# Verified against the Together API on 2026-06-17:
# - DeepSeek entries read from /v1/models; V4-Pro confirmed by a
#   context_length_exceeded error ("maximum context length is 512000 tokens").
# - Qwen3.7-Plus/Max advertise context_length=1000000, but an oversized request
#   is rejected with "Range of input length should be [1, 983616]" — so the
#   enforced input cap is 983616, with ~16384 of the 1M reserved for output.
# Other providers' models are intentionally omitted rather than guessed; set
# them in config via "context_window_tokens".
MODEL_CONTEXT_WINDOWS = {
    "deepseek-ai/DeepSeek-V4-Pro": 512000,
    "deepseek-ai/DeepSeek-R1-0528": 163840,
    "deepseek-ai/DeepSeek-V3.1": 131072,
    "deepseek-ai/DeepSeek-R1-Distill-Llama-70B": 131072,
    "deepseek-ai/DeepSeek-R1-Distill-Qwen-14B": 131072,
    "deepseek-ai/DeepSeek-R1-Distill-Qwen-7B": 131072,
    "deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B": 131072,
    "deepseek-ai/deepseek-coder-33b-instruct": 16384,
    "deepseek-ai/DeepSeek-OCR-2": 8192,
    "Qwen/Qwen3.7-Plus": 983616,
    "Qwen/Qwen3.7-Max": 983616,
}

PACKAGE_HINTS = {
    "openai": "openai",
    "anthropic": "anthropic",
    "google": "google-genai",
    "cursor": "cursor-sdk",
    "claude-code": "claude-agent-sdk",
    "together": "openai",
    "openrouter": "openai",
}


@dataclass
class LlmResult:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0


def default_config_path() -> Path:
    """Config resolution: NAGENT_CONFIG, then the project's .nagent/config.json
    when inside a git repo, then the user config. CLI --config wins above all
    (callers pass it as config_path)."""
    env_path = os.environ.get("NAGENT_CONFIG")
    if env_path:
        return Path(env_path).expanduser()
    toplevel = git_toplevel()
    if toplevel is not None:
        project_config = toplevel / ".nagent" / "config.json"
        if project_config.is_file():
            return project_config
    return Path("~/.nagent/config.json").expanduser()


def load_config(config_path: Path | None = None) -> dict:
    path = config_path or default_config_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in config file {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Config file {path} must contain a JSON object.")
    return data


def default_model(provider: str) -> str:
    return DEFAULT_MODELS[provider]


def model_context_window(model: str) -> int | None:
    """Verified maximum input window (tokens) for a model, or None if unknown.
    None means the caller should fall back to its byte-size threshold rather
    than guess a window."""
    return MODEL_CONTEXT_WINDOWS.get(model)


# --- reasoning level -------------------------------------------------------
# Config carries an integer 1..REASONING_SCALE_MAX (a portable "N/5" dial) or a
# provider-specific string (passed through verbatim). The integer is mapped to
# each provider's native reasoning control by this table: the named effort
# scales (anthropic, openai) map directly; google maps to a thinking-budget
# token count (-1 = dynamic, 0 = off). None means "no portable knob at this
# level" — the level is ignored and no parameter is sent. Reasoning on
# Together's DeepSeek/Qwen models is intrinsic to the model, so the integer
# scale sends nothing there; pass a provider-specific string (e.g. "low") to
# force a reasoning_effort.
REASONING_SCALE_MAX = 5
REASONING_LEVELS = {
    "anthropic":   ["low", "medium", "high", "xhigh", "max"],
    "openai":      ["minimal", "low", "medium", "high", "high"],
    "google":      [0, 4096, 8192, 16384, -1],
    "together":    [None, None, None, None, None],
    "openrouter":  [None, None, None, None, None],
    "cursor":      [None, None, None, None, None],
    "claude-code": [None, None, None, None, None],
}


@dataclass
class ReasoningSetting:
    native: object | None = None   # provider-native value to apply, or None
    label: str = "default"         # human label for --status
    level: int | None = None       # the 1..5 level, when an integer was given
    supported: bool = True         # False when an integer level has no mapping


def _looks_like_int(value) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    if isinstance(value, str):
        return value.strip().lstrip("-").isdigit()
    return False


def _reasoning_label(provider, native, level, supported, passthrough) -> str:
    if passthrough:
        return f"{native} (provider-specific)"
    if not supported:
        return f"unsupported ({level}/{REASONING_SCALE_MAX})"
    if provider == "google":
        native_text = "dynamic" if native == -1 else ("off" if native == 0 else f"budget={native}")
    else:
        native_text = str(native)
    return f"{native_text} ({level}/{REASONING_SCALE_MAX})"


def resolve_reasoning(provider: str, value) -> ReasoningSetting:
    """Resolve a config reasoning value to a provider-native setting.

    - None / "" -> provider/model default (no parameter sent).
    - integer or digit string -> clamped to 1..REASONING_SCALE_MAX and mapped
      through REASONING_LEVELS; an unmapped level sends nothing (supported=False).
    - any other string -> passed through verbatim as the provider-native value.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return ReasoningSetting()
    if not _looks_like_int(value):
        text = str(value).strip()
        return ReasoningSetting(native=text, label=_reasoning_label(provider, text, None, True, True))
    level = max(1, min(REASONING_SCALE_MAX, int(value)))
    table = REASONING_LEVELS.get(provider) or []
    native = table[level - 1] if len(table) >= level else None
    supported = native is not None
    return ReasoningSetting(
        native=native if supported else None,
        label=_reasoning_label(provider, native, level, supported, False),
        level=level,
        supported=supported,
    )


def reasoning_value_from_args(args):
    """Raw reasoning value for a CLI front end: --reasoning overrides the
    config 'reasoning' key. Returns the raw value (int/str/None), not resolved."""
    cli = getattr(args, "reasoning", None)
    if cli is not None:
        return cli
    try:
        return load_config(getattr(args, "config", None)).get("reasoning")
    except ValueError:
        return None


def estimate_token_count(text: str) -> int:
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


def resolve_settings(
    provider: str | None = None,
    model: str | None = None,
    config_path: Path | None = None,
) -> tuple[str, str]:
    config = load_config(config_path)
    resolved_provider = resolve_provider(provider, config_path, config)
    if model is not None:
        resolved_model = model
    elif provider is not None:
        resolved_model = default_model(resolved_provider)
    else:
        resolved_model = config.get("model") or default_model(resolved_provider)
    return resolved_provider, resolved_model


def resolve_provider(
    provider: str | None = None,
    config_path: Path | None = None,
    config: dict | None = None,
) -> str:
    config = config if config is not None else load_config(config_path)
    requested_provider = (provider or config.get("provider") or "openai").lower()
    resolved_provider = PROVIDER_ALIASES.get(requested_provider, requested_provider)
    if requested_provider not in PROVIDERS and resolved_provider not in PROVIDERS:
        raise ValueError(
            f"Unsupported provider {requested_provider!r}. "
            f"Supported providers: {', '.join(PROVIDERS)}."
        )
    return resolved_provider


def credential_env_var(provider: str) -> str | None:
    for env_var in CREDENTIAL_ENV[provider]:
        if os.environ.get(env_var):
            return env_var
    return None


def require_credentials(provider: str) -> None:
    if not CREDENTIAL_ENV[provider]:
        # Provider manages its own credentials (e.g. claude-code uses the
        # local Claude Code login); nothing to check here.
        return
    env_var = credential_env_var(provider)
    if env_var is None:
        expected = " or ".join(CREDENTIAL_ENV[provider])
        print(
            f"Error: missing credentials for provider {provider!r}. "
            f"Set one of: {expected}.",
            file=sys.stderr,
        )
        sys.exit(1)


def require_package(provider: str):
    if provider == "openai":
        try:
            from openai import OpenAI
        except ImportError:
            _missing_package(provider)
        return OpenAI
    if provider in ("together", "openrouter"):
        # OpenAI-wire-compatible providers; reuse the openai SDK.
        try:
            from openai import OpenAI
        except ImportError:
            _missing_package(provider)
        return OpenAI
    if provider == "anthropic":
        try:
            import anthropic
        except ImportError:
            _missing_package(provider)
        return anthropic
    if provider == "google":
        try:
            from google import genai
        except ImportError:
            _missing_package(provider)
        return genai
    if provider == "cursor":
        try:
            from cursor_sdk import Agent, AgentOptions, LocalAgentOptions
        except ImportError:
            _missing_package(provider)
        return Agent, AgentOptions, LocalAgentOptions
    if provider == "claude-code":
        try:
            import anyio
            from claude_agent_sdk import (
                AssistantMessage,
                ClaudeAgentOptions,
                ResultMessage,
                TextBlock,
                query,
            )
        except ImportError:
            _missing_package(provider)
        return anyio, query, ClaudeAgentOptions, AssistantMessage, ResultMessage, TextBlock
    raise ValueError(f"Unsupported provider: {provider}")


def _missing_package(provider: str) -> None:
    print(
        f"Error: Python package {PACKAGE_HINTS[provider]!r} is required for provider {provider!r}. "
        f"Install it with: pip install {PACKAGE_HINTS[provider]}",
        file=sys.stderr,
    )
    sys.exit(1)


def _openai_compatible_client(provider: str, api_key_env: str, base_url: str):
    OpenAI = require_package(provider)
    return OpenAI(api_key=os.environ[api_key_env], base_url=base_url)


def _together_client():
    return _openai_compatible_client("together", "TOGETHER_API_KEY", TOGETHER_BASE_URL)


def _openrouter_client():
    return _openai_compatible_client("openrouter", "OPENROUTER_API_KEY", OPENROUTER_BASE_URL)


def _openai_compatible_chat(client, model, messages, reasoning=None):
    """One OpenAI-compatible chat completion, always streamed. Some providers'
    models (e.g. Together Qwen/Qwen3.7-Plus) ONLY support streaming and reject
    a non-streamed request; streaming is accepted by OpenRouter and the other
    compatible chat models used here. Accumulates delta text and returns
    (text, usage); usage arrives in the final chunk via include_usage when the
    provider supports it.

    reasoning, when set, is sent as the OpenAI-compatible reasoning_effort."""
    parts: list[str] = []
    usage = None
    extra = {"extra_body": {"reasoning_effort": reasoning}} if reasoning is not None else {}
    stream = client.chat.completions.create(
        model=model,
        messages=messages,
        stream=True,
        stream_options={"include_usage": True},
        **extra,
    )
    for chunk in stream:
        if getattr(chunk, "usage", None):
            usage = chunk.usage
        for choice in getattr(chunk, "choices", None) or []:
            delta = getattr(choice, "delta", None)
            content = getattr(delta, "content", None) if delta is not None else None
            if content:
                parts.append(content)
    return "".join(parts), usage


def _together_chat(client, model, messages, reasoning=None):
    return _openai_compatible_chat(client, model, messages, reasoning=reasoning)


def _openrouter_chat(client, model, messages, reasoning=None):
    return _openai_compatible_chat(client, model, messages, reasoning=reasoning)

def _openai_compatible_list_models(url: str, api_key: str) -> list[str]:
    # Together returns a top-level JSON array; OpenRouter returns
    # {"data": [...]}. Accept both shapes and ignore malformed entries.
    import urllib.request

    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {api_key}"},
    )
    with urllib.request.urlopen(request) as response:
        payload = json.loads(response.read().decode("utf-8"))
    items = payload.get("data", []) if isinstance(payload, dict) else payload
    return sorted(
        {item["id"] for item in items if isinstance(item, dict) and item.get("id")}
    )




def add_llm_arguments(parser) -> None:
    parser.add_argument(
        "--provider",
        choices=PROVIDERS,
        help=f"LLM provider (default: from {default_config_path()} or openai).",
    )
    parser.add_argument(
        "--model",
        help="Model name (default: from config or provider default).",
    )
    parser.add_argument(
        "--config",
        type=Path,
        help="Path to nagent config JSON (default: ~/.nagent/config.json).",
    )
    parser.add_argument(
        "--reasoning",
        help=(
            f"Reasoning level: integer 1-{REASONING_SCALE_MAX} (portable N/5 scale) "
            "or a provider-specific name (default: from config)."
        ),
    )


def resolve_from_args(args) -> tuple[str, str]:
    try:
        provider, model = resolve_settings(
            getattr(args, "provider", None),
            getattr(args, "model", None),
            getattr(args, "config", None),
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    require_credentials(provider)
    return provider, model


def list_models(provider: str) -> list[str]:
    if provider == "openai":
        OpenAI = require_package(provider)
        client = OpenAI()
        return sorted({model.id for model in client.models.list()})

    if provider == "together":
        return _openai_compatible_list_models(
            f"{TOGETHER_BASE_URL}/models",
            os.environ["TOGETHER_API_KEY"],
        )

    if provider == "openrouter":
        return _openai_compatible_list_models(
            f"{OPENROUTER_BASE_URL}/models",
            os.environ["OPENROUTER_API_KEY"],
        )

    if provider == "anthropic":
        anthropic = require_package(provider)
        client = anthropic.Anthropic()
        return sorted({model.id for model in client.models.list()})

    if provider == "google":
        genai = require_package(provider)
        api_key = os.environ.get("GOOGLE_API_KEY") or os.environ["GEMINI_API_KEY"]
        client = genai.Client(api_key=api_key)
        names: list[str] = []
        for model in client.models.list():
            name = getattr(model, "name", "") or ""
            if name.startswith("models/"):
                name = name[len("models/") :]
            if name:
                names.append(name)
        return sorted(set(names))

    if provider == "cursor":
        try:
            from cursor_sdk import Cursor
        except ImportError:
            _missing_package(provider)
        models = Cursor.models.list()
        names: list[str] = []
        for model in models:
            if isinstance(model, str):
                names.append(model)
                continue
            for attr in ("id", "name", "model"):
                value = getattr(model, attr, None)
                if value:
                    names.append(str(value))
                    break
        if not names:
            raise RuntimeError("Cursor.models.list() returned no models.")
        return sorted(set(names))

    if provider == "claude-code":
        raise RuntimeError(
            "claude-code does not expose a model list; pass --model with any "
            "Claude model id or alias (e.g. sonnet, opus, haiku), or "
            f"{CLAUDE_CODE_DEFAULT_MODEL!r} to use Claude Code's configured model."
        )

    raise ValueError(f"Unsupported provider: {provider}")


def list_providers() -> list[dict]:
    """Static catalog of supported providers: default model, credential env
    vars (empty when the provider manages its own login), and any aliases.
    No network or credentials needed. Iterates DEFAULT_MODELS so aliases
    (e.g. gemini) are reported as aliases of their target, not as providers."""
    aliases: dict[str, list[str]] = {}
    for alias, target in PROVIDER_ALIASES.items():
        aliases.setdefault(target, []).append(alias)
    return [
        {
            "provider": name,
            "default_model": DEFAULT_MODELS[name],
            "credentials": list(CREDENTIAL_ENV[name]),
            "aliases": sorted(aliases.get(name, [])),
        }
        for name in DEFAULT_MODELS
    ]


CURSOR_FAILURE_STATUSES = frozenset({"error", "cancelled", "expired"})


def _cursor_result_text(result) -> str:
    status = getattr(result, "status", None)
    if status in CURSOR_FAILURE_STATUSES:
        raise RuntimeError(f"Cursor agent failed with status {status!r}")
    return getattr(result, "result", None) or ""


def _usage_value(usage, *names: str) -> int:
    if usage is None:
        return 0
    for name in names:
        if isinstance(usage, dict):
            value = usage.get(name)
        else:
            value = getattr(usage, name, None)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                return 0
    return 0


def _result_with_usage(text: str, usage, input_text: str | None = None) -> LlmResult:
    input_tokens = _usage_value(usage, "input_tokens", "prompt_tokens", "prompt_token_count")
    # Anthropic reports cached prompt tokens separately; fold them back in so
    # input_tokens stays "tokens sent" across providers. Other providers lack
    # these fields and contribute zero.
    input_tokens += _usage_value(usage, "cache_read_input_tokens")
    input_tokens += _usage_value(usage, "cache_creation_input_tokens")
    output_tokens = _usage_value(
        usage,
        "output_tokens",
        "completion_tokens",
        "candidates_token_count",
        "output_token_count",
    )
    total_tokens = _usage_value(usage, "total_tokens", "total_token_count")
    if output_tokens == 0 and total_tokens and input_tokens:
        output_tokens = max(0, total_tokens - input_tokens)
    if input_tokens == 0 and input_text is not None:
        input_tokens = estimate_token_count(input_text)
    if output_tokens == 0:
        output_tokens = estimate_token_count(text)
    return LlmResult(
        text=text,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def _claude_code_generate(
    message: str,
    model: str,
    *,
    allowed_tools: list[str] | None = None,
    max_turns: int | None = 1,
) -> LlmResult:
    """Run one prompt through the local Claude Code via the Claude Agent SDK.

    Authentication is Claude Code's own login (subscription or API key) —
    no environment variable is read here. Tools are disabled by default so
    this behaves as plain text generation; pass allowed_tools to permit
    specific tools (e.g. Read for file analysis)."""
    anyio, query, ClaudeAgentOptions, AssistantMessage, ResultMessage, TextBlock = require_package(
        "claude-code"
    )

    # No model and "default" mean the same thing: Claude Code's configured model.
    options = ClaudeAgentOptions(
        model=None if not model or model == CLAUDE_CODE_DEFAULT_MODEL else model,
        max_turns=max_turns,
        tools=list(allowed_tools) if allowed_tools else [],
        allowed_tools=list(allowed_tools) if allowed_tools else [],
        cwd=os.getcwd(),
        # This provider bills through Claude Code's own login. An inherited
        # ANTHROPIC_API_KEY would silently redirect billing to that key
        # (Claude Code prefers it over its login); blank it in the subprocess.
        # Use the "anthropic" provider for API-key billing.
        env={"ANTHROPIC_API_KEY": ""},
    )

    async def run_query():
        texts: list[str] = []
        result_message = None
        try:
            async for sdk_message in query(prompt=message, options=options):
                if isinstance(sdk_message, AssistantMessage):
                    if getattr(sdk_message, "error", None):
                        # Synthetic error message (e.g. billing_error): its
                        # text is an error report, not generated output.
                        continue
                    for block in sdk_message.content:
                        if isinstance(block, TextBlock):
                            texts.append(block.text)
                elif isinstance(sdk_message, ResultMessage):
                    result_message = sdk_message
        except Exception:
            # After an error result the CLI exits non-zero on purpose, which
            # the SDK surfaces as an exception AFTER yielding the
            # ResultMessage — whose .result carries the real error text
            # ("Credit balance is too low"), unlike the generic exception.
            # Keep the result and let the is_error path below report it.
            if result_message is None or not result_message.is_error:
                raise
        return texts, result_message

    texts, result_message = anyio.run(run_query)

    if result_message is not None and result_message.is_error:
        errors = getattr(result_message, "errors", None) or []
        detail = errors[0] if errors else (result_message.result or "claude-code query failed")
        raise RuntimeError(f"claude-code provider failed: {detail}")

    text = ""
    usage = None
    if result_message is not None:
        text = result_message.result or ""
        usage = result_message.usage
    if not text:
        text = "\n".join(texts)
    return _result_with_usage(text, usage, message)


def cache_prefix_blocks(message: str, cache_boundaries: list[int] | None):
    """Split a message into content blocks at the given character offsets,
    marking each prefix block with cache_control so providers that cache on
    block boundaries can reuse stable prefixes. Returns the plain string when
    no valid boundary exists. At most 3 prefix blocks (provider limit is 4
    breakpoints per request)."""
    if not cache_boundaries:
        return message
    points = sorted({b for b in cache_boundaries if 0 < b < len(message)})[:3]
    if not points:
        return message
    blocks = []
    start = 0
    for point in points:
        blocks.append(
            {
                "type": "text",
                "text": message[start:point],
                "cache_control": {"type": "ephemeral"},
            }
        )
        start = point
    blocks.append({"type": "text", "text": message[start:]})
    return blocks


def generate_text_with_usage(
    message: str,
    provider: str,
    model: str,
    cache_boundaries: list[int] | None = None,
    reasoning=None,
) -> LlmResult:
    # Resolve the portable reasoning level (or provider-specific string) once;
    # each branch attaches it in that provider's own protocol. native is None
    # when no level was set or the level has no knob for this provider.
    native = resolve_reasoning(provider, reasoning).native

    if provider == "openai":
        OpenAI = require_package(provider)
        client = OpenAI()
        kwargs = {"reasoning": {"effort": native}} if native is not None else {}
        response = client.responses.create(model=model, input=message, **kwargs)
        return _result_with_usage(response.output_text, getattr(response, "usage", None), message)

    if provider == "anthropic":
        anthropic = require_package(provider)
        client = anthropic.Anthropic()
        kwargs = {"output_config": {"effort": native}} if native is not None else {}
        response = client.messages.create(
            model=model,
            max_tokens=8192,
            messages=[{"role": "user", "content": cache_prefix_blocks(message, cache_boundaries)}],
            **kwargs,
        )
        return _result_with_usage(_anthropic_text(response), getattr(response, "usage", None), message)

    if provider == "google":
        genai = require_package(provider)
        api_key = os.environ.get("GOOGLE_API_KEY") or os.environ["GEMINI_API_KEY"]
        client = genai.Client(api_key=api_key)
        kwargs = {}
        if native is not None:
            from google.genai import types

            thinking = (
                types.ThinkingConfig(thinking_budget=native)
                if isinstance(native, int)
                else types.ThinkingConfig(thinking_level=str(native))
            )
            kwargs["config"] = types.GenerateContentConfig(thinking_config=thinking)
        response = client.models.generate_content(model=model, contents=message, **kwargs)
        return _result_with_usage(response.text or "", getattr(response, "usage_metadata", None), message)

    if provider == "together":
        # Together implements the chat completions API, not the OpenAI
        # Responses API, so this path differs from the openai branch above.
        # cache_boundaries is ignored: Together has no block-cache API.
        client = _together_client()
        text, usage = _together_chat(client, model, [{"role": "user", "content": message}], reasoning=native)
        return _result_with_usage(text, usage, message)

    if provider == "openrouter":
        # OpenRouter implements the chat completions API, not the OpenAI
        # Responses API. cache_boundaries is ignored: OpenRouter has no
        # nagent-supported block-cache API.
        client = _openrouter_client()
        text, usage = _openrouter_chat(client, model, [{"role": "user", "content": message}], reasoning=native)
        return _result_with_usage(text, usage, message)

    if provider == "claude-code":
        return _claude_code_generate(message, model)

    Agent, AgentOptions, LocalAgentOptions = require_package(provider)
    result = Agent.prompt(
        message,
        AgentOptions(
            api_key=os.environ["CURSOR_API_KEY"],
            model=model,
            local=LocalAgentOptions(cwd=os.getcwd()),
        ),
    )
    text = _cursor_result_text(result)
    return LlmResult(
        text=text,
        input_tokens=estimate_token_count(message),
        output_tokens=estimate_token_count(text),
    )


def generate_text(message: str, provider: str, model: str) -> str:
    return generate_text_with_usage(message, provider, model).text


def generate_with_upload_usage(path: Path, prompt: str, provider: str, model: str) -> LlmResult:
    if provider == "openai":
        return _openai_upload(path, prompt, model)
    if provider == "anthropic":
        return _anthropic_upload(path, prompt, model)
    if provider == "google":
        return _google_upload(path, prompt, model)
    if provider == "together":
        return _together_upload(path, prompt, model)
    if provider == "openrouter":
        return _openrouter_upload(path, prompt, model)
    if provider == "cursor":
        return LlmResult(text=_cursor_upload(path, prompt, model))
    if provider == "claude-code":
        return _claude_code_upload(path, prompt, model)
    raise ValueError(f"Unsupported provider: {provider}")


def generate_with_upload(path: Path, prompt: str, provider: str, model: str) -> str:
    return generate_with_upload_usage(path, prompt, provider, model).text


def _anthropic_text(response) -> str:
    parts = []
    for block in response.content:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "\n".join(parts)


def _mime_type(path: Path) -> str:
    mime_type, _ = mimetypes.guess_type(path.name)
    return mime_type or "application/octet-stream"


def _is_image_mime(mime_type: str) -> bool:
    return mime_type.startswith("image/")


def _openai_upload(path: Path, prompt: str, model: str) -> LlmResult:
    OpenAI = require_package("openai")
    client = OpenAI()
    mime_type = _mime_type(path)
    purpose = "vision" if _is_image_mime(mime_type) else "user_data"
    with path.open("rb") as handle:
        uploaded = client.files.create(file=handle, purpose=purpose)

    content: list[dict] = [{"type": "input_text", "text": prompt}]
    if _is_image_mime(mime_type):
        content.append({"type": "input_image", "file_id": uploaded.id, "detail": "auto"})
    else:
        content.append({"type": "input_file", "file_id": uploaded.id})

    response = client.responses.create(
        model=model,
        input=[{"role": "user", "content": content}],
    )
    return _result_with_usage(response.output_text, getattr(response, "usage", None), prompt)


def _anthropic_upload(path: Path, prompt: str, model: str) -> LlmResult:
    anthropic = require_package("anthropic")
    client = anthropic.Anthropic()
    mime_type = _mime_type(path)
    with path.open("rb") as handle:
        uploaded = client.beta.files.upload(
            file=(path.name, handle, mime_type),
        )

    if _is_image_mime(mime_type):
        file_block = {
            "type": "image",
            "source": {"type": "file", "file_id": uploaded.id},
        }
    else:
        file_block = {
            "type": "document",
            "source": {"type": "file", "file_id": uploaded.id},
        }

    response = client.beta.messages.create(
        model=model,
        max_tokens=8192,
        betas=["files-api-2025-04-14"],
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    file_block,
                ],
            }
        ],
    )
    return _result_with_usage(_anthropic_text(response), getattr(response, "usage", None), prompt)


def _google_wait_for_file(client, uploaded):
    state = getattr(uploaded, "state", None)
    state_name = getattr(state, "name", None) if state is not None else None
    if state_name != "PROCESSING":
        return uploaded

    name = uploaded.name
    for _ in range(60):
        time.sleep(1)
        uploaded = client.files.get(name=name)
        state = getattr(uploaded, "state", None)
        state_name = getattr(state, "name", None) if state is not None else None
        if state_name != "PROCESSING":
            return uploaded
    raise RuntimeError(f"Timed out waiting for Google file processing: {name}")


def _google_upload(path: Path, prompt: str, model: str) -> LlmResult:
    genai = require_package("google")
    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ["GEMINI_API_KEY"]
    client = genai.Client(api_key=api_key)
    uploaded = client.files.upload(file=str(path))
    uploaded = _google_wait_for_file(client, uploaded)
    response = client.models.generate_content(
        model=model,
        contents=[prompt, uploaded],
    )
    return _result_with_usage(response.text or "", getattr(response, "usage_metadata", None), prompt)


def _openai_compatible_upload(
    path: Path,
    prompt: str,
    model: str,
    provider_label: str,
    client,
    chat,
) -> LlmResult:
    # Remote OpenAI-compatible APIs cannot read local files. Vision models
    # accept images as a base64 data URL via chat completions; non-image
    # documents have no equivalent, so reject them explicitly.
    mime_type = _mime_type(path)
    if not _is_image_mime(mime_type):
        raise ValueError(
            f"{provider_label} provider supports image upload only; cannot upload "
            f"{mime_type} file {path.name}."
        )
    import base64

    data = base64.b64encode(path.read_bytes()).decode("ascii")
    data_url = f"data:{mime_type};base64,{data}"
    text, usage = chat(
        client,
        model,
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
    )
    return _result_with_usage(text, usage, prompt)


def _together_upload(path: Path, prompt: str, model: str) -> LlmResult:
    return _openai_compatible_upload(
        path,
        prompt,
        model,
        "together",
        _together_client(),
        _together_chat,
    )


def _openrouter_upload(path: Path, prompt: str, model: str) -> LlmResult:
    return _openai_compatible_upload(
        path,
        prompt,
        model,
        "openrouter",
        _openrouter_client(),
        _openrouter_chat,
    )


def _cursor_upload(path: Path, prompt: str, model: str) -> str:
    message = (
        f"{prompt}\n\n"
        f"Analyze the file at this absolute path:\n{path.resolve()}\n"
        "Read the file and respond to the prompt."
    )
    return generate_text(message, "cursor", model)


def _claude_code_upload(path: Path, prompt: str, model: str) -> LlmResult:
    # Claude Code reads the file locally; permit only the Read tool and leave
    # the turn count open so read-then-answer can complete.
    message = (
        f"{prompt}\n\n"
        f"Analyze the file at this absolute path:\n{path.resolve()}\n"
        "Read the file and respond to the prompt."
    )
    return _claude_code_generate(message, model, allowed_tools=["Read"], max_turns=None)
