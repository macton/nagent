#!/usr/bin/python3
"""Queued messages for nagent conversations.

Two pieces of data, both named after the conversation file and living beside
it under {root}/conversations/:

  {name}.inbox/   spool directory; one queued message per file
  {name}.run      runfile for a live user-invoked instance, JSON:
                  {"host": str, "pid": int, "started": iso8601, "cwd": str}

The producer (nagent-message) never touches the conversation file. The running
loop does read-modify-write on that path (refresh_initial_context,
rebuild_conversation, write_checkpoint, --clear/--load), so an outside append
landing inside one of those windows would be silently lost. The spool directory
is the whole handoff: write-temp + rename() is atomic within a directory, so a
drain never observes a partial message and neither side takes a lock.

Message file names are a UTC timestamp plus a uuid suffix, so lexicographic
order is arrival order. Two messages written in the same microsecond by
different processes are ordered arbitrarily relative to each other. Names
beginning with "." are in-progress temp files and are never drained.

Delivery is at-most-once: drain_messages removes a message before returning it,
so a crash between the drain and the conversation append loses it. The reverse
order would repeat a message forever whenever the unlink failed, which is the
worse failure.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

INBOX_SUFFIX = ".inbox"
RUNFILE_SUFFIX = ".run"
MESSAGE_SUFFIX = ".txt"
TEMP_PREFIX = "."
FILENAME_TIME_FORMAT = "%Y%m%dT%H%M%S%fZ"

# Liveness states reported for a conversation.
STATE_RUNNING = "running"
STATE_STALE = "stale"
STATE_UNKNOWN = "unknown"
STATE_NOT_RUNNING = "not-running"


def inbox_dir(conversation_file: Path) -> Path:
    return conversation_file.with_name(conversation_file.name + INBOX_SUFFIX)


def runfile_path(conversation_file: Path) -> Path:
    return conversation_file.with_name(conversation_file.name + RUNFILE_SUFFIX)


def message_filename(now: datetime) -> str:
    stamp = now.astimezone(timezone.utc).strftime(FILENAME_TIME_FORMAT)
    return f"{stamp}-{uuid.uuid4().hex[:8]}{MESSAGE_SUFFIX}"


def enqueue_messages(inbox: Path, texts: list[str], *, now: datetime | None = None) -> list[Path]:
    """Spool messages into an inbox, in list order, and return their paths.

    Creates the inbox on first use. Text is written exactly as given; callers
    reject empty text before getting here. One CLI invocation is a batch of
    one.
    """
    inbox.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for text in texts:
        name = message_filename(now or datetime.now(timezone.utc))
        temp = inbox / f"{TEMP_PREFIX}{name}"
        temp.write_text(text, encoding="utf-8")
        final = inbox / name
        temp.rename(final)
        written.append(final)
    return written


def pending_message_paths(inbox: Path) -> list[Path]:
    """Queued message files, oldest first.

    A missing inbox is empty, not an error: no inbox at all is the common case
    and is checked once per turn. An unreadable inbox is also reported empty --
    the loop must not die because a directory listing failed.
    """
    try:
        entries = list(os.scandir(inbox))
    except OSError:
        return []
    paths = [
        Path(entry.path)
        for entry in entries
        if not entry.name.startswith(TEMP_PREFIX) and entry.is_file()
    ]
    return sorted(paths, key=lambda path: path.name)


def drain_messages(inbox: Path) -> list[str]:
    """Read and remove every queued message, oldest first.

    Out-of-range behavior, explicit: a message that vanished between listing
    and read (an external rm) is skipped; undecodable bytes are replaced rather
    than raising; a message that cannot be read or removed is dropped with a
    warning on stderr, because delivering it would repeat it on every
    subsequent turn.
    """
    texts: list[str] = []
    for path in pending_message_paths(inbox):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            continue
        except OSError as exc:
            print(f"warning: cannot read queued message {path}: {exc}", file=sys.stderr)
            continue
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            print(
                f"warning: cannot remove queued message {path}: {exc}; dropping it",
                file=sys.stderr,
            )
            continue
        texts.append(text)
    return texts


def write_runfile(
    path: Path,
    *,
    pid: int | None = None,
    cwd: Path | None = None,
    hostname: str | None = None,
    now: datetime | None = None,
) -> Path:
    """Publish "this instance is alive" as data. Written at startup and removed
    on exit; a runfile left behind by a kill is detected as stale, not trusted."""
    payload = {
        "host": hostname or socket.gethostname(),
        "pid": os.getpid() if pid is None else pid,
        "started": (now or datetime.now(timezone.utc)).isoformat(),
        "cwd": str(cwd or Path.cwd()),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{TEMP_PREFIX}{path.name}.{os.getpid()}")
    temp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temp.rename(path)
    return path


def remove_runfile(path: Path) -> None:
    """Best effort: a runfile we cannot remove becomes a stale runfile, which
    the liveness check already handles."""
    try:
        path.unlink()
    except OSError:
        pass


def read_runfile(path: Path) -> dict | None:
    """The runfile payload, or None when absent, unreadable, or not an object."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OSError, TypeError, ValueError):
        return False
    return True


def runfile_state(payload: dict, *, hostname: str | None = None) -> str:
    """running | stale | unknown.

    A runfile written on another host cannot be checked here: os.kill would
    test an unrelated local pid, so the honest answer is unknown.
    """
    if payload.get("host") != (hostname or socket.gethostname()):
        return STATE_UNKNOWN
    pid = payload.get("pid")
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return STATE_STALE
    return STATE_RUNNING if process_alive(pid) else STATE_STALE


def conversation_instances(conversations: Path, *, hostname: str | None = None) -> list[dict]:
    """Every conversation in a conversations directory that has a runfile or an
    inbox, with its liveness state and queue depth, sorted by name.

    Scans that one directory. Campaign item conversations live under their
    campaign directory and are addressed explicitly by path instead.
    """
    try:
        entries = list(os.scandir(conversations))
    except OSError:
        return []

    names: set[str] = set()
    for entry in entries:
        if entry.name.endswith(RUNFILE_SUFFIX) and entry.is_file():
            names.add(entry.name[: -len(RUNFILE_SUFFIX)])
        elif entry.name.endswith(INBOX_SUFFIX) and entry.is_dir():
            names.add(entry.name[: -len(INBOX_SUFFIX)])

    rows: list[dict] = []
    for name in sorted(names):
        conversation_file = conversations / name
        payload = read_runfile(runfile_path(conversation_file))
        state = STATE_NOT_RUNNING if payload is None else runfile_state(payload, hostname=hostname)
        payload = payload or {}
        rows.append(
            {
                "conversation": name,
                "path": str(conversation_file),
                "state": state,
                "host": payload.get("host"),
                "pid": payload.get("pid"),
                "started": payload.get("started"),
                "cwd": payload.get("cwd"),
                "pending": len(pending_message_paths(inbox_dir(conversation_file))),
            }
        )
    return rows
