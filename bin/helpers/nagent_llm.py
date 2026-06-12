#!/usr/bin/python3

import json
import mimetypes
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

PROVIDERS = ("openai", "anthropic", "google", "gemini", "cursor", "claude-code")
PROVIDER_ALIASES = {"gemini": "google"}

# For the claude-code provider, "default" means Claude Code's own configured
# model: the SDK is invoked with model=None and Claude Code decides.
CLAUDE_CODE_DEFAULT_MODEL = "default"

DEFAULT_MODELS = {
    "openai": "gpt-5.5",
    "anthropic": "claude-sonnet-4-6",
    "google": "gemini-2.5-flash",
    "cursor": "composer-2.5",
    "claude-code": CLAUDE_CODE_DEFAULT_MODEL,
}

# An empty tuple means the provider manages its own credentials; claude-code
# uses the local Claude Code login (subscription or API key), not an env var.
CREDENTIAL_ENV = {
    "openai": ("OPENAI_API_KEY",),
    "anthropic": ("ANTHROPIC_API_KEY",),
    "google": ("GOOGLE_API_KEY", "GEMINI_API_KEY"),
    "cursor": ("CURSOR_API_KEY",),
    "claude-code": (),
}

PACKAGE_HINTS = {
    "openai": "openai",
    "anthropic": "anthropic",
    "google": "google-genai",
    "cursor": "cursor-sdk",
    "claude-code": "claude-agent-sdk",
}


@dataclass
class LlmResult:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0


def default_config_path() -> Path:
    env_path = os.environ.get("NAGENT_CONFIG")
    if env_path:
        return Path(env_path).expanduser()
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
    )

    async def run_query():
        texts: list[str] = []
        result_message = None
        async for sdk_message in query(prompt=message, options=options):
            if isinstance(sdk_message, AssistantMessage):
                for block in sdk_message.content:
                    if isinstance(block, TextBlock):
                        texts.append(block.text)
            elif isinstance(sdk_message, ResultMessage):
                result_message = sdk_message
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
) -> LlmResult:
    if provider == "openai":
        OpenAI = require_package(provider)
        client = OpenAI()
        response = client.responses.create(model=model, input=message)
        return _result_with_usage(response.output_text, getattr(response, "usage", None), message)

    if provider == "anthropic":
        anthropic = require_package(provider)
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=model,
            max_tokens=8192,
            messages=[{"role": "user", "content": cache_prefix_blocks(message, cache_boundaries)}],
        )
        return _result_with_usage(_anthropic_text(response), getattr(response, "usage", None), message)

    if provider == "google":
        genai = require_package(provider)
        api_key = os.environ.get("GOOGLE_API_KEY") or os.environ["GEMINI_API_KEY"]
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(model=model, contents=message)
        return _result_with_usage(response.text or "", getattr(response, "usage_metadata", None), message)

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
