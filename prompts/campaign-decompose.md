# Campaign decomposition

Decompose the campaign goal below into a tree of concrete, independently
executable todo items.

Rules:

- Return only JSON in this form (no prose, no markdown fence):
  {"items": [{"description": "...",
              "blocked_by": ["sibling description ordinal refs not needed — omit unless essential"],
              "items": [{"description": "..."}]}]}
- Each description is one sentence of concrete work with a checkable
  outcome — "Implement X so that Y passes", not "Think about X".
- Prefer a shallow tree of 3–9 items; nest only when a child genuinely
  cannot be stated without its parent. The plan will be reviewed by a human
  before anything runs: clarity beats completeness.
- Order items so earlier ones unblock later ones; use "blocked_by"
  sparingly and only within siblings.
- Do not include items for work the goal does not ask for.
