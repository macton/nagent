# 0002 — Invalid-output sidecars are never collected

Status: open
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
