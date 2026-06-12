# Knowledge merge

You are given one knowledge category file from a nagent knowledge store.
Rewrite it: deduplicate, merge overlapping items, and compress wording —
without losing a single distinct fact.

Rules:

- Return only the rewritten file content. No commentary, no markdown fence.
- Keep the file's header line and overall shape. If the file has sections
  (e.g. "## Open" and "## Done" in tasks.md), keep every section and keep
  items under the section they came from.
- One bullet per distinct item. When merging duplicates, keep the clearest
  wording and carry over every provenance marker
  (`[from: conversation, date]`) from the merged bullets onto the surviving
  one.
- Never invent items, dates, or provenance. Never drop an item unless it is
  a true duplicate of another.
- Keep bullets terse and hand-editable; this file is maintained by a human.
