# NEXA Agent Platform v2

This branch starts NEXA's transition from a command-oriented kernel into a chat-first personal agent workspace.

## Design influences

- Agent Substrate: explicit agent/session lifecycle and replaceable isolation backend.
- treg: searchable capability registry and runtime tool resolution.
- CLI-Anything: structured argv-based CLI harness execution with machine-readable results.
- Univer: planned office/artifact workspace integration for sheets, docs, slides and PDFs.

These are architectural references; NEXA does not copy or vendor their implementations.

## Included foundation

- `platform.runtime`: persistent create/run/suspend/resume/stop sessions.
- `platform.tools`: discoverable tool catalog with structured results.
- `platform.agent`: chat-first execution facade and deterministic starter planner.
- Workspace read/write tools restricted to a workspace root.
- Structured CLI execution (`shell=False`, argv input, bounded timeout).
- Unit tests for discovery, workspace isolation and session persistence.

## Next integration milestones

1. Connect NEXA's existing Gemini/Ollama bridges as planner/model providers.
2. Add approval gates for high-risk tools before CLI/browser execution.
3. Adapt existing BrowserControl capability into the registry.
4. Add CLI-Anything-compatible harness discovery and SKILL metadata ingestion.
5. Add Univer web workspace for spreadsheet/document/presentation artifacts.
6. Add streaming chat API and a polished web chat shell.
7. Add optional Docker/gVisor runtime backend while keeping local development lightweight.

## Safety model

Tool metadata includes risk levels. The current CLI tool is deliberately structured around argv rather than shell strings. Before exposing it through the hosted chat API, high-risk calls must be routed through NEXA's existing confirmation/approval mechanisms.
