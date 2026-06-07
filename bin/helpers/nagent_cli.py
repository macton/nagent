#!/usr/bin/python3

import subprocess
import sys
from pathlib import Path


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
