# Provider-side prompt caching for conversation prefixes

Status: implemented — second option below (`--cache-prefix-chars` on
`nagent-llm-text`, computed by `conversation_cache_boundaries()` in
`bin/nagent`, applied by `cache_prefix_blocks()` in `nagent_llm.py`).
Two boundaries are passed: end of the mode-shared stable context (before
`Instance:`) and end of the full initial-context block. The provider layer
stays generic: providers without block-boundary caching ignore the flag.
Cached prompt tokens are folded back into reported input tokens so token
accounting still means "tokens sent". Remaining open question: caching the
growing history tail would need cumulative per-turn block boundaries —
deferred until measured need.

The initial context now orders blocks stable-to-volatile (protocol, rules,
tools, install/root context, knowledge first; instance facts and environment
last), so conversations of the same mode share a byte-identical prefix.

That is a prerequisite, not the win. `nagent-llm-text` sends the whole
conversation file as a single message content block, and provider prompt
caches match on whole content blocks — a single growing block never matches
its own previous prefix. To get cache reads:

- the request would need the conversation split into at least two blocks
  (stable prefix with a cache breakpoint, growing tail), which couples
  `nagent_llm.py` (provider-generic today) to knowledge of the conversation
  layout, or
- `nagent-llm-text` grows an interface for callers to mark a prefix
  boundary (e.g. `--cache-prefix-bytes N`), keeping the provider layer
  generic.

Cost to decide against: every turn re-sends ~5K tokens of identical context
uncached, per conversation and per sub-conversation. Worth measuring against
a real workload before adding the interface. The claude-code provider is
unaffected (Claude Code manages its own caching).
