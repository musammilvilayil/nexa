# NEXA

NEXA is a local-first autonomous personal AI operating platform with a trading-first execution architecture.

The project is built around a standalone kernel rather than a monolithic chatbot. Language models can help interpret, teach, critique, and generate candidate skills, but executable actions must pass deterministic skill validation, risk policy, and auditing.

## Current architecture

```text
Typed / Voice Transcript / Local API
   |
   v
RuntimeControlPlane + KernelInputRouter
   |
   v
NEXA Kernel
   |-- ContextBus
   |-- SkillRegistry
   |-- SecurityGate
   |-- Dispatcher
   |-- AuditLedger
   |
   +-- WorkspaceSkill
   +-- FileSkill
   +-- GitPlugin
   +-- GitHubSkill
   +-- TradingSkill
   +-- TradingControlSkill

Model/resource bridges
   |-- OllamaBridge
   |-- GeminiBridge
   +-- SubprocessBridge

Trading platform
   |-- Market data validation
   |-- Regime detection
   |-- Adaptive momentum + mean reversion router
   |-- RiskEngine
   |-- Backtester
   |-- Walk-forward evaluation
   |-- Strategy promotion ledger
   |-- Persistent autonomous paper trader
   |-- Paper evidence ledger
   |-- Bounded paper runtime service
   |-- LiveArmController
   |-- TradingKillSwitch
   |-- BrokerAdapter contract
   +-- Explicit trusted broker-factory registry

Autonomous learning
   |-- Trading curriculum
   |-- Gemini teacher
   |-- Ollama student
   |-- Persistent mastery state
   |-- Capability-gap backlog
   |-- SkillForge
   |-- Static validator
   |-- Sandbox runner
   +-- Candidate staging
```

## Core invariants

- No arbitrary shell command API is exposed to model text.
- Subprocess execution uses argument arrays with `shell=False`.
- File operations are contained inside the active configured workspace.
- Workspace discovery uses explicit roots and does not scan the whole drive by default.
- Remote/destructive kernel actions require short-lived explicit confirmation.
- Pending confirmations execute the exact previously validated request; they are not reparsed by an LLM.
- Pending actions expire and can be cancelled.
- Git remote mutations recheck branch/conflict/working-tree preconditions immediately before execution.
- API keys are read from environment secrets and are not stored in candidate code or audit parameters.
- Generated skills are treated as untrusted until static validation and isolated tests pass.
- Generated skills are staged outside the live source tree; autonomous training cannot rewrite the security kernel.
- Typed input, voice transcripts, and local API commands route through the same kernel permission boundary.

## Trading safety model

NEXA is designed to support autonomous trading only inside an explicit owner mandate. It does not assume that a strategy is profitable because it worked on historical data.

The promotion path is:

```text
RESEARCH
   -> out-of-sample / walk-forward evaluation
PAPER
   -> autonomous paper evidence
LIVE_ELIGIBLE
   -> owner-approved eligibility
LIVE_AUTONOMOUS mandate
   -> explicit session arm
LIVE EXECUTION
```

Normal live orders are intended to run without per-trade confirmation after the exact owner mandate has been armed. The independent `RiskEngine`, strategy promotion state, broker health checks, and kill switch remain authoritative on every entry.

Risk-reducing exits are intentionally treated differently from new exposure so safety controls do not trap an existing position.

**Important:** no broker-specific live adapter is enabled by default. `build_runtime()` ignores broker-provider environment selectors and creates no live broker. Reviewed owner-controlled code must either pass a concrete `BrokerAdapter` directly or supply an explicit `BrokerFactoryRegistry` to `build_runtime_from_trusted_brokers()`. Environment text can select only a factory that trusted code already registered. Live execution is still disarmed after construction.

Trading performance is uncertain. Backtests and paper results are evidence, not guarantees of future profit.

## Persistent autonomous paper runtime

Paper execution state survives restarts through the local `NEXA_PAPER_DB` SQLite database. Persisted state includes simulated orders, positions and realized PnL, duplicate-bar guards, protective stop/target context, and trading-date state.

The same database also stores session-scoped paper evidence. Evidence reports include trading-day count, closed trades, reconstructed realized net PnL/drawdown, safety violations, and an integrity flag. Starting a new evidence session preserves prior history.

Run a bounded paper cycle:

```powershell
python src\paper_runner.py --cycles 1
```

Run as a long-lived local service:

```powershell
python src\paper_runner.py --cycles 0
```

The runner fails closed unless the mandate is `paper_autonomous` and the strategy stage permits paper execution. It does not promote a research-only strategy merely because the runner was started.

## Local control/status API

`src/local_api.py` exposes the real local runtime, not the hosted demo kernel. Its action endpoints call `NexaKernel` through `RuntimeControlPlane`, so normal validation, confirmation, and audit rules still apply.

```powershell
python src\local_api.py
```

Default bind: `127.0.0.1:8765`.

Endpoints:

```text
GET  /health
GET  /status
POST /command   {"command":"..."}
POST /confirm   {"action_id":"..."}
POST /cancel    {"action_id":"..."}
```

A non-loopback bind is refused unless `NEXA_LOCAL_API_TOKEN` is configured. The API intentionally exposes no direct live-order endpoint.

## Voice/input boundary

`input_adapters.py` defines provider-neutral typed/voice input contracts. `VoiceTranscriptAdapter` accepts already-transcribed speech from a reviewed STT integration, and `KernelInputRouter` always offers the transcript to `NexaKernel` first. Only a true `no_match` can reach an optional text-only language fallback, which receives no runtime or execution capability.

This is the integration boundary for future microphone/STT work; it is deliberately not a permission bypass.

## Autonomous teacher-student learning

The local student can be trained through a bounded curriculum using Gemini as a teacher/reviewer. This is knowledge and skill training, not copying Gemini weights.

The autonomous supervisor can:

1. detect the next unmastered curriculum module,
2. request a structured lesson and quiz from Gemini,
3. evaluate the local Ollama student's answer,
4. persist progress,
5. retry within fixed budgets,
6. process queued capability gaps through SkillForge,
7. statically validate and sandbox generated candidates,
8. stage successful candidates for later promotion.

It cannot arm live trading, bypass RiskEngine, disable audit, or automatically import generated code into the live kernel.

## Requirements

- Windows is the primary development environment.
- Python 3.14
- Ollama with a local model such as `qwen3:1.7b`
- `httpx`
- Optional: GitHub CLI (`gh`) for GitHubSkill
- Optional: `GEMINI_API_KEY` for teacher/forge workflows

Install runtime dependencies:

```powershell
python -m pip install -r requirements.txt
```

Install development/test dependencies:

```powershell
python -m pip install -r requirements-dev.txt
```

## Run NEXA

```powershell
python src\nexa.py
```

Useful commands include:

```text
/skills
/pending
/confirm <action-id>
/cancel <action-id>
/teacher-stats
/training-status
/live status
/live kill <reason>
/live disarm
/live arm
/live clear-kill
```

`/live arm` and `/live clear-kill` are confirmation-gated. `/live kill` and `/live disarm` are immediate risk-reduction operations.

## Autonomous training

Status only:

```powershell
python src\autonomous_train.py --status
```

Run bounded autonomous training:

```powershell
python src\autonomous_train.py
```

Queue a candidate capability for the forge without running training:

```powershell
python src\autonomous_train.py --queue-skill "describe the narrow capability" --gap-risk read --queue-only
```

Generated candidates are staged under `data/generated_skills/` by default and are ignored by Git.

## Tests

Primary regression command:

```powershell
python -m unittest discover -s tests -v
```

Pytest is also scoped to the real test suite:

```powershell
python -m pytest -q
```

GitHub Actions runs both commands on pushes and pull requests. Build-completion tests are present, but this branch is intentionally code-first: the full local validation phase is performed after code freeze.

## Configuration

See `config.example.env` for runtime variables. Real API keys, broker credentials, API tokens, personal memory databases, local market CSVs, and generated private artifacts must not be committed.

The default trading mode is `research`.

## Project status

`build-completion-v0.1` is the code-completion branch layered on top of `trading-core-v0.1`. It contains persistent paper recovery/evidence, the paper service runner, the explicit trusted broker boundary, local control/health API, provider-neutral voice/input routing, lifecycle hooks, documentation, and targeted regression tests.

After code freeze, pull this branch to the owner machine and run the full regression, recovery/failure-injection, paper-trading, and strategy validation phases before considering any live-broker implementation or live eligibility.
