# 0002 — Invalid-output sidecars are never collected

Status: closed 2026-09-28 — not a problem worth machinery
Filed: 2026-06-13
Area: `bin/nagent` — `write_invalid_sidecar`, rebuild/archive paths

## Context

Commit 065168c writes a `{conversation}.invalid.{guid}` file next to the
conversation whenever a turn contained non-protocol content that nagent
stripped. The file holds the raw model output (header + verbatim body) and is
linked from that turn's `<nagent-turn-status invalid="{guid}" />`.

Nothing ever deletes these files, and no other code path knows they exist.

## The problem (data)

- **Accumulation.** One sidecar per invalid turn, in
  `~/.nagent/conversations/` (or the project `.nagent/conversations/`). A
  leak-prone provider on a long run produces many. Each is small (one turn's
  output, capped by whatever the provider emitted), so this is a file-count and
  tidiness problem, not a disk-space emergency.
- **Orphaning on rebuild.** `rebuild_conversation` archives the conversation to
  `conv-{timestamp}` and starts a fresh window. The sidecars are named after
  the *live* conversation file, so after a rebuild they reference content that
  is now in the archive. The `invalid="{guid}"` link still resolves (same
  directory, same guid), but the sidecar is no longer associated with anything
  in the live conversation — it's only reachable via the archived copy.
- **No cleanup on conversation delete.** Removing a conversation leaves its
  sidecars behind as untracked orphans.

## Options (with cost)

1. **Sweep alongside archive/rebuild.** When `rebuild_conversation` archives a
   conversation, move (or rename) that conversation's sidecars next to the
   archive, keeping the link intact.
   - Cost: small; preserves reconstructability; sidecars travel with the
     history they document.
2. **TTL / cap.** Delete sidecars older than N days, or keep only the most
   recent K per conversation.
   - Cost: small; loses old debug data by policy — must be stated explicitly
     (out-of-range behavior: drop oldest), not silent.
3. **Fold into the archive instead of separate files.** On rebuild, concatenate
   the conversation's sidecars into the archive (or a single
   `conv-{timestamp}.invalid` log) and delete the per-turn files.
   - Cost: medium; fewer files, but the live-run per-turn link must still work
     before the rebuild.
4. **Do nothing.** Treat sidecars as user-managed debug artifacts.
   - Cost: zero; files accumulate and orphan over time.

## Recommendation

Option 1 (sweep with archive) as the baseline — it keeps sidecars attached to
the history they explain and is the smallest change. Add option 2's cap only if
file count becomes a real problem on long runs, and log what was dropped.

## Done criteria

- After a rebuild, a turn's `invalid="{guid}"` is still resolvable to its raw
  output (in the archive's neighborhood).
- Deleting a conversation does not leave orphan sidecars.
- Any automatic deletion logs what it removed (no silent truncation).

## 2026-09-28 — spilled output is a second family with the same gap

Compaction and rebuild now move oversized driver-result bodies into
`{conversation}.outputs/NNNN-tag.txt` (see 0004's addendum). Those files have the
same lifecycle hole this issue describes for sidecars: nothing collects them,
nothing moves them when `rebuild_conversation` archives the conversation under a
new name, and deleting a conversation orphans them.

They differ in one way that matters for the options above, and it rules some of
them out: **the live conversation points at them by absolute path.** A sidecar is
a debugging artifact nobody reads at runtime; a spilled output is the only copy of
an observation the model is told to read. So a TTL or an oldest-first cap
(option 2) cannot be applied to them as written — expiring one turns a pointer in
the conversation into a dangling path, which is exactly the "the output is missing,
fill the gap" situation the spill exists to prevent. Any sweep must either rewrite
the pointer at the same time or leave referenced files alone.

Option 1 (move them next to the archive on rebuild) has the same problem in
reverse: rebuild keeps a tail of the live conversation, and that tail can contain
pointers. Moving the files without rewriting those pointers breaks them.

The cheapest correct behaviour is probably: sweep only outputs no live
conversation references, and treat a referenced file as durable data rather than
debris. That is a different rule from the one this issue proposes for sidecars,
and both belong here rather than in two issues, because it is one question —
what owns conversation-adjacent files and when may they be removed.

## Resolution — 2026-09-28: closed

Sidecars and spilled outputs live next to the conversation they belong to. That is
the answer, not a workaround: the files are co-located with the thing that
explains them, the `invalid="{guid}"` link resolves in the same directory after an
archive, and a conversation's debris is found by looking where the conversation is.
Accumulation was the only real complaint and it is a file count, not a cost.

So no collector, no TTL, no sweep. Every option listed above adds a moving part
and a policy to explain in order to delete data that is cheap to keep and
occasionally the only record of what happened — the 1193 sidecars in one project's
conversations are what made issue 0004 measurable at all. Deleting them would have
hidden the problem.

The one constraint worth remembering if this is ever revisited: a spilled output is
referenced by absolute path from the live conversation, so it is data, not debris.
Anything that removes one must rewrite the pointer in the same breath.
