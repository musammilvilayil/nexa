# NEXA

NEXA is a local-first autonomous personal AI operating platform with a trading-first execution architecture.

The project is built around a standalone kernel rather than a monolithic chatbot. Language models can help interpret, teach, critique, and generate candidate skills, but executable actions must pass deterministic skill validation, risk policy, and auditing.

## Current architecture

```text
User / CLI
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
   |-- Autonomous paper trader
   |-- LiveArmController
   |-- TradingKillSwitch
   +-- BrokerAdapter contract

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

**Important:** no broker-specific live adapter is enabled by default. `build_runtime()` creates no live broker from prompts or environment strings. Trusted application code must explicitly supply a reviewed `BrokerAdapter` implementation before a live controller exists.

Trading performance is uncertain. Backtests and paper results are evidence, not guarantees of future profit.

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

GitHub Actions runs both commands on pushes and pull requests.

## Configuration

See `config.example.env` for runtime variables. Real API keys, broker credentials, tokens, personal memory databases, and generated private artifacts must not be committed.

The default trading mode is `research`.

## Project status

The `trading-core-v0.1` branch contains the current integration work: standalone kernel, auditing, resource bridges, workspace/file/Git/GitHub plugins, trading research/paper platform, live-control boundary, autonomous teacher-student learning, SkillForge sandboxing, and production runtime wiring.

Before merging this milestone to `main`, run the full local regression suite and then run the Gemini/Ollama training workflow on the owner machine.
