#!/usr/bin/python3

import json
import mimetypes
import os
import sys
import time
from pathlib import Path

PROVIDERS = ("openai", "anthropic", "google", "cursor")

DEFAULT_MODELS = {
    "openai": "gpt-5.5",
    "anthropic": "claude-sonnet-4-6",
    "google": "gemini-2.5-flash",
    "cursor": "composer-2.5",
}

CREDENTIAL_ENV = {
    "openai": ("OPENAI_API_KEY",),
    "anthropic": ("ANTHROPIC_API_KEY",),
    "google": ("GOOGLE_API_KEY", "GEMINI_API_KEY"),
    "cursor": ("CURSOR_API_KEY",),
}

PACKAGE_HINTS = {
    "openai": "openai",
    "anthropic": "anthropic",
    "google": "google-genai",
    "cursor": "cursor-sdk",
}


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


def resolve_settings(
    provider: str | None = None,
    model: str | None = None,
    config_path: Path | None = None,
) -> tuple[str, str]:
    config = load_config(config_path)
    resolved_provider = resolve_provider(provider, config_path, config)
    resolved_model = model or config.get("model") or default_model(resolved_provider)
    return resolved_provider, resolved_model


def resolve_provider(
    provider: str | None = None,
    config_path: Path | None = None,
    config: dict | None = None,
) -> str:
    config = config if config is not None else load_config(config_path)
    resolved_provider = (provider or config.get("provider") or "openai").lower()
    if resolved_provider not in PROVIDERS:
        raise ValueError(
            f"Unsupported provider {resolved_provider!r}. "
            f"Supported providers: {', '.join(PROVIDERS)}."
        )
    return resolved_provider


def credential_env_var(provider: str) -> str | None:
    for env_var in CREDENTIAL_ENV[provider]:
        if os.environ.get(env_var):
            return env_var
    return None


def require_credentials(provider: str) -> None:
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

    raise ValueError(f"Unsupported provider: {provider}")


def generate_text(message: str, provider: str, model: str) -> str:
    if provider == "openai":
        OpenAI = require_package(provider)
        client = OpenAI()
        response = client.responses.create(model=model, input=message)
        return response.output_text

    if provider == "anthropic":
        anthropic = require_package(provider)
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=model,
            max_tokens=8192,
            messages=[{"role": "user", "content": message}],
        )
        return _anthropic_text(response)

    if provider == "google":
        genai = require_package(provider)
        api_key = os.environ.get("GOOGLE_API_KEY") or os.environ["GEMINI_API_KEY"]
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(model=model, contents=message)
        return response.text or ""

    Agent, AgentOptions, LocalAgentOptions = require_package(provider)
    result = Agent.prompt(
        message,
        AgentOptions(
            api_key=os.environ["CURSOR_API_KEY"],
            model=model,
            local=LocalAgentOptions(cwd=os.getcwd()),
        ),
    )
    if getattr(result, "status", None) not in (None, "completed", "success"):
        raise RuntimeError(f"Cursor agent failed with status {result.status!r}")
    return getattr(result, "result", None) or ""


def generate_with_upload(path: Path, prompt: str, provider: str, model: str) -> str:
    if provider == "openai":
        return _openai_upload(path, prompt, model)
    if provider == "anthropic":
        return _anthropic_upload(path, prompt, model)
    if provider == "google":
        return _google_upload(path, prompt, model)
    if provider == "cursor":
        return _cursor_upload(path, prompt, model)
    raise ValueError(f"Unsupported provider: {provider}")


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


def _openai_upload(path: Path, prompt: str, model: str) -> str:
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
    return response.output_text


def _anthropic_upload(path: Path, prompt: str, model: str) -> str:
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
    return _anthropic_text(response)


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


def _google_upload(path: Path, prompt: str, model: str) -> str:
    genai = require_package("google")
    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ["GEMINI_API_KEY"]
    client = genai.Client(api_key=api_key)
    uploaded = client.files.upload(file=str(path))
    uploaded = _google_wait_for_file(client, uploaded)
    response = client.models.generate_content(
        model=model,
        contents=[prompt, uploaded],
    )
    return response.text or ""


def _cursor_upload(path: Path, prompt: str, model: str) -> str:
    message = (
        f"{prompt}\n\n"
        f"Analyze the file at this absolute path:\n{path.resolve()}\n"
        "Read the file and respond to the prompt."
    )
    return generate_text(message, "cursor", model)
