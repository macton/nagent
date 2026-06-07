#!/usr/bin/python3

import json
import subprocess
import sys
import threading
import time
from pathlib import Path


def emit_json(payload: dict) -> None:
    print(json.dumps(payload, indent=2))


def exit_on_description(description: str) -> None:
    if "--description" in sys.argv:
        tool_path = Path(sys.argv[0]).resolve()
        print(f"path: {tool_path}\n{description.strip()}")
        raise SystemExit(0)


def collect_bin_tool_descriptions(bin_dir: Path) -> str:
    entries: list[str] = []

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
            entries.append(description)

    if not entries:
        return ""

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
