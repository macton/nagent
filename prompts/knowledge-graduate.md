# Knowledge graduation

You are given the playbooks file from a nagent knowledge store. Identify
entries that deserve to graduate from prose into reusable artifacts.

Return only JSON in this form (no prose, no markdown fence):

{"drafts": [{"kind": "tool",
             "name": "short-kebab-name",
             "description": "one or two sentences: what it does and when to use it",
             "content": "the full file content"},
            {"kind": "prompt", "name": "...", "description": "...", "content": "..."}]}

Rules:

- Graduate only concrete, proven, reusable entries: a command sequence that
  has worked repeatedly becomes a "tool"; durable guidance that shapes how
  work should be done becomes a "prompt". Skip one-offs, vague notes, and
  anything environment-specific that would not survive a second machine.
- A "tool" draft is a complete executable script (shebang line first). It
  must print its path and description and exit 0 when invoked with
  --description, like every other nagent tool, and otherwise do the work.
  Prefer #!/bin/sh or #!/usr/bin/env python3.
- A "prompt" draft is a complete markdown instruction file.
- Empty {"drafts": []} is valid and expected when nothing has earned
  graduation. Do not pad.
