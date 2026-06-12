#!/usr/bin/python3

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

# The nagent install folder: the parent of bin/ (this file lives in bin/helpers/).
INSTALL_DIR = Path(__file__).resolve().parent.parent.parent


def user_root() -> Path:
    return Path("~/.nagent").expanduser()


def git_toplevel(path: Path | None = None) -> Path | None:
    # Discovery probe: any failure (no git, not a repo, odd environment)
    # means "not in a project" — never an error.
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=path or Path.cwd(),
            capture_output=True,
            text=True,
        )
    except Exception:
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return Path(result.stdout.strip())


def resolve_default_root(root_arg: str | None) -> Path:
    """Root resolution: --root wins; inside a git repo the project's .nagent
    is the default; otherwise the user root (~/.nagent)."""
    if root_arg:
        return Path(root_arg).expanduser()
    toplevel = git_toplevel()
    if toplevel is not None:
        return toplevel / ".nagent"
    return user_root()


def ensure_root_scaffold(root: Path) -> None:
    """Create the root on first use. A newly created root ships a .gitignore
    covering regenerable artifacts only; everything else is the user's call
    to commit. An existing root is left exactly as it is."""
    created = not root.exists()
    root.mkdir(parents=True, exist_ok=True)
    if created:
        (root / ".gitignore").write_text("splits/\n", encoding="utf-8")


def resolve_prompt_path(root: Path, name: str) -> Path:
    """Prompt resolution: project root prompts, then user prompts, then the
    prompts shipped with the install. First hit wins; the install copy is
    the fallback even when absent (callers report the missing file)."""
    candidates = [
        root / "prompts" / name,
        user_root() / "prompts" / name,
        INSTALL_DIR / "prompts" / name,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[-1]


def tool_search_dirs(install_bin: Path, root: Path) -> list[Path]:
    """Tool discovery layers, least specific first: install bin, user bin,
    project-root bin. Later layers shadow earlier ones by basename."""
    dirs: list[Path] = []
    seen: set[str] = set()
    for candidate in (install_bin, user_root() / "bin", root / "bin"):
        try:
            key = str(candidate.resolve())
        except OSError:
            continue
        if key not in seen:
            seen.add(key)
            dirs.append(candidate)
    return dirs


def default_pid() -> str:
    # In screen, STY and WINDOW identify the current virtual terminal more
    # stably than the shell process. BASHPID is not exported by bash by default;
    # fall back to the parent shell process id so repeated terminal invocations
    # share one conversation.
    if os.environ.get("STY"):
        return f"{os.environ['STY']}-{os.environ.get('WINDOW', '')}"
    return os.environ.get("BASHPID") or str(os.getppid())


def emit_json(payload: dict) -> None:
    print(json.dumps(payload, indent=2))


def exit_on_description(description: str) -> None:
    if "--description" in sys.argv:
        tool_path = Path(sys.argv[0]).resolve()
        print(f"path: {tool_path}\n{description.strip()}")
        raise SystemExit(0)


def collect_bin_tool_descriptions(bin_dirs: Path | list[Path]) -> str:
    """Self-described tools from one or more bin directories. With a list,
    later directories shadow earlier ones by basename (most specific layer
    wins)."""
    if isinstance(bin_dirs, Path):
        bin_dirs = [bin_dirs]

    by_name: dict[str, str] = {}
    for bin_dir in bin_dirs:
        if not bin_dir.is_dir():
            continue
        for path in sorted(entry for entry in bin_dir.iterdir() if entry.is_file()):
            try:
                result = subprocess.run(
                    [str(path.resolve()), "--description"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
            except (OSError, subprocess.TimeoutExpired):
                continue
            if result.returncode != 0:
                continue
            description = result.stdout.strip()
            if description:
                by_name[path.name] = description

    if not by_name:
        return ""

    entries = [by_name[name] for name in sorted(by_name)]
    return "Available tools:\n\n" + "\n\n".join(entries)


class WaitSpinner:
    def __init__(self, message: str, *, enabled: bool = True) -> None:
        self.message = message
        self.enabled = enabled and sys.stderr.isatty()
        self._active = False
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "WaitSpinner":
        if not self.enabled:
            return self
        self._active = True
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if not self.enabled:
            return
        self._active = False
        if self._thread is not None:
            self._thread.join(timeout=1)
        sys.stderr.write("\r\033[K")
        sys.stderr.flush()

    def _spin(self) -> None:
        frames = "|/-\\"
        index = 0
        while self._active:
            sys.stderr.write(f"\r\033[K{self.message} {frames[index % len(frames)]}")
            sys.stderr.flush()
            index += 1
            time.sleep(0.1)
