# Harvest durable knowledge from a nagent conversation

You are given one nagent conversation (or a summary of one). Extract only
knowledge that stays useful after this conversation is deleted. Return only
JSON in exactly this form (no prose, no markdown fence):

{"facts": [{"statement": "...", "detail": "..."}],
 "decisions": [{"statement": "...", "detail": "..."}],
 "tasks_done": [{"statement": "...", "detail": "..."}],
 "tasks_open": [{"statement": "...", "detail": "..."}],
 "questions": [{"statement": "...", "detail": "..."}],
 "playbooks": [{"name": "...", "steps": "..."}],
 "files": [{"path": "...", "note": "..."}]}

Category rules:

- facts: durable statements about systems, repositories, tools, environments,
  or constraints that were learned, not assumed.
- decisions: choices that were made, with the why in `detail`.
- tasks_done: concrete work completed in this conversation.
- tasks_open: work that was started, planned, or requested but not finished.
- questions: questions raised and never answered.
- playbooks: command sequences or processes that worked and are reusable;
  `steps` is the runnable sequence.
- files: a note tied to one specific file path (use the absolute path seen in
  the conversation).

General rules:

- Empty arrays are valid and expected: most conversations contain nothing
  durable. Do not invent items to fill categories.
- One item per distinct piece of knowledge; keep `statement` to one sentence.
- `detail` is optional context; omit it or use "" when the statement stands
  alone.
- Do not include conversation mechanics, tool output noise, retries, or
  one-off trivia (timestamps, token counts, transient errors).
