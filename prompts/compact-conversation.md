# Compact This Conversation

You are not summarizing a chat log.

You are maintaining a durable working artifact.

The conversation is a mutable data structure that exists to support future work.
Its purpose is not to preserve chronology. Its purpose is to preserve capability.

## Core Principle

The agent is not the thing.

The data is the thing.

Optimize the conversation for future transformations.

Preserve information that would be expensive to rediscover.

Remove information that no longer contributes to future work.

## Data-Oriented Rules

Keep:
- accepted decisions
- user requirements
- constraints
- discovered invariants
- successful experiments
- important failed experiments
- artifact summaries
- repository knowledge
- file-local knowledge
- historical coupling information
- open questions
- TODO items
- durable context

Remove:
- repeated reasoning
- repeated shell output
- repeated file reads
- duplicated summaries
- obsolete hypotheses
- intermediate exploration
- dead conversations
- verbose deliberation
- chronology that no longer matters

Keep conclusions.
Remove exploration.

Keep decisions.
Remove deliberation.

Keep state.
Remove history.

## Transformation Rules

Replace many shell commands with verified outcomes.

Replace long investigations with:
- conclusion
- evidence

Replace long discussions with:
- decision
- reason
- rejected alternatives

Merge duplicate investigations.
Collapse repeated facts.
Delete obsolete information.
Rewrite aggressively.

The conversation is not sacred.

## Preserve Artifact Knowledge

Preserve references to:
- root context
- per-file conversations
- file summaries
- repository history summaries
- historical coupling
- split indexes
- patch artifacts

Prefer references over duplication.

## Preserve Failure Knowledge

Keep:
- failed experiments
- rejected designs
- dangerous edge cases
- corrected assumptions

Future workers should not repeat expensive mistakes.

## Required Output Structure

# User Intent

# Current Objective

# Accepted Decisions

# Constraints

# Durable Knowledge

## Global

## Artifact Local

## Repository History

## Historical Coupling

# Verified Facts

# Important Failed Attempts

# Open Questions

# TODO

# Minimal Context Needed To Continue

## Explicit Instructions

Do not preserve chronology.

Preserve state.

Do not preserve conversation flow.

Preserve useful information.

Do not preserve intermediate worker behavior.

Preserve durable artifacts.

If ten pages can become one paragraph without reducing future capability,
do so.

If an investigation can be represented as a fact, store the fact.

If a discussion can be represented as a decision, store the decision.

If repeated information exists, keep the best version.

## Self Review

Before finishing, verify:

- Can another worker continue immediately?
- Would expensive investigation need to be repeated?
- Are accepted decisions preserved?
- Are constraints preserved?
- Are important failures preserved?
- Are artifact references preserved?
- Has duplicated information been removed?
- Has chronology been replaced with state?
- Is the conversation substantially smaller?
- Is future capability unchanged or improved?

If not, continue compacting.
