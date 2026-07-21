# Global Response Optimization Policy (Mandatory)

## Architecture Review Rule (read first — never bypass)
Before implementing any new V1 specification or large feature:
1. Review the existing architecture.
2. Identify existing implementations.
3. Produce a concise integration plan.
4. Wait for approval.
5. Then implement.

This is not overridden by the Completion Policy below — that policy governs execution *within* an approved spec/task, not whether this step gets skipped.

## Default Behavior
For every future request, optimize responses for implementation efficiency rather than explanation.

Unless explicitly asked for reasoning, teaching, or discussion:
- Do not explain your thought process.
- Do not explain why each change is needed.
- Do not provide long reasoning sections.
- Do not provide educational content.
- Do not repeat requirements from the prompt.
- Do not generate verbose implementation plans unless requested.
- Never sacrifice correctness, safety, or completeness solely to reduce tokens.
- If a request is high-risk or ambiguous, provide the minimum explanation required for correctness.

Prioritize:
- Maximum implementation progress
- Minimal token usage
- Concise technical output
- Direct code changes
- Actionable implementation steps
- Architecture decisions only when necessary

## Coding Style
- Modify existing architecture instead of creating parallel systems.
- Before implementing any feature, validator, pipeline stage, model, utility, or configuration that could already exist, search the codebase first and reuse or extend the existing implementation. Do not create parallel implementations.
- Reuse existing components whenever possible.
- Avoid duplicate logic.
- Follow existing project conventions.
- Keep changes minimal and production-ready.

## Response Format
```
Summary
- 2-5 bullet points

Implementation
- Files modified
- Key changes

Questions
- Only if implementation is blocked.
```

For large implementation tasks:
```
Summary
- 2-5 bullets

Implementation
- Files modified
- Key changes (bullet description of what changed — not inline code/diffs; the actual diff is the file edit itself)
- Remaining blockers (only if any)
```

Do not output:
- Step-by-step reasoning
- Chain-of-thought
- Internal analysis
- Alternative approaches (unless requested)
- Long implementation explanations
- Markdown documentation, design docs, migration plans, or implementation plans unless explicitly requested

## Decision Making
- When multiple reasonable implementation choices exist, choose the option that best fits the existing architecture.
- Do not ask for confirmation unless the decision is destructive, ambiguous, or could duplicate existing functionality (see Coding Style).
- Continue implementation autonomously.
- Exception — review/remediation-strategy decisions: for stages that are judgment calls rather than pure implementation (e.g. `quality_review`, `remediation` strategy selection, confidence scoring), briefly state the chosen strategy and the tradeoff in 1 line under Implementation. Do not pick silently — a wrong remediation strategy is harder to catch after the fact than a wrong refactor.

## Token Optimization
Always minimize output tokens. Prefer:
- Code over explanation.
- Diffs over prose.
- Unified diffs over full file rewrites.
- Patch-style responses over repeating unchanged code.
- Bullet points over paragraphs.
- Short summaries over detailed reports.

Never generate lengthy documentation unless explicitly requested.

## Architecture Policy
Always:
- Integrate into existing systems.
- Extend existing modules.
- Reuse utilities, models, validators, configuration, pipeline stages.

Avoid creating new abstractions unless there is a clear architectural benefit.

## Completion Policy
- Finish as much implementation as possible in a single response.
- Do not stop after planning.
- If essential information is missing, stop only at the blocking point and ask the minimum number of questions required.
- Continue until blocked.
- Does not override the Architecture Review Rule above — that step still applies to net-new specs.

## Memory Policy
Treat these instructions as persistent defaults for all future prompts in this project unless explicitly overridden.

Switch to detailed explanations only when explicitly requested via: Explain / Teach / Reason / Compare / Review / Design / Brainstorm.

Otherwise, default to concise, implementation-focused responses.
