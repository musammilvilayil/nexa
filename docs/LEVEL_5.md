# NEXA — Level 5 Autonomous Personal AI Operating System

## Architecture Overview

NEXA Level 5 upgrades NEXA from a reliable computer-use agent (Level 4) into a true **Autonomous Personal AI Operating System**. Level 5 operates locally, securely, and deterministically across 10 core subsystems:

```
                                  USER INTENT (Voice / Text / CLI)
                                                ↓
                                      SECURITY GATE & FAILSAFE
                                                ↓
                                      NEXA KERNEL & RUNTIME
                                                ↓
       ┌──────────────────┬─────────────────────┼─────────────────────┬──────────────────┐
       ↓                  ↓                     ↓                     ↓                  ↓
  MULTI-AGENT        LONG-RUNNING          PERSISTENT            MODEL CONTEXT        10-LAYER
 ORCHESTRATION       TASK ENGINE            SCHEDULER              PROTOCOL            MEMORY
 (Supervisor &     (Priority Queue,      (SQLite-backed,         (Tool/Resource      (Episodic,
  7 Workers)        Checkpoints)          Interval/Cron)          Discovery)          Semantic,
                                                                                     Procedural)
       ↓                  ↓                     ↓                     ↓                  ↓
   RESEARCH             OAUTH &             OBSERVABILITY        COMPUTER-USE         FAILSAFE
  PIPELINE          AUTHENTICATION           & EXPLAIN            EXECUTION           MONITOR
 (5-Stage Deep       (PKCE Flow,             (Real-time           (Mouse, Kbd,        (Emergency
  Web Synthesis)     TokenStore)             Audit Feed)          Screen, Win)         Stop Guard)
```

---

## Key Level-5 Subsystems

### 1. Model Context Protocol (MCP)
- **Extension**: `src/extensions/mcp_extension.py` (`DefaultMCPExtension`)
- **Skill**: `src/skills/mcp_skill.py` (`MCPSkill`)
- **Capabilities**:
  - Full server, tool, resource, and prompt discovery.
  - JSON schema parameter validation before dispatch.
  - Deterministic `RiskTier` classification (`READ`, `MUTATE`, `REMOTE`, `CRITICAL`, `DESTRUCTIVE`).
  - Strict `SecurityGate` evaluation: unconfirmed `REMOTE`/`CRITICAL` tools require user confirmation; destructive commands on the deny list are unconditionally blocked.
  - Interactive CLI commands: `/mcp`, `/mcp-list`, `/mcp-status`, `/mcp-refresh`.

### 2. OAuth 2.0 & Authentication Handoff
- **Token Store**: `src/auth/token_store.py` (`TokenStore`)
  - Zero plaintext secrets in memory or logs.
  - Encrypt-then-MAC using PBKDF2-HMAC-SHA256 key derivation and keystream encryption with HMAC-SHA256 verification.
  - Complete redaction in `__repr__`, `__str__`, and default serialization.
- **OAuth Manager**: `src/auth/oauth_manager.py` (`OAuthManager`)
  - Standards-compliant OAuth 2.0 PKCE / Authorization Code flows for GitHub, Google, Microsoft, and custom services.
  - State machine: `AUTH_REQUIRED -> HUMAN_HANDOFF -> AUTHENTICATING -> AUTHENTICATED -> RESUME_TASK`.
  - Seamless detection of MFA, CAPTCHA, and biometric barriers with automatic human handoff and non-blocking resumption.

### 3. Long-Running Task Engine
- **Engine**: `src/planner/long_running.py` (`LongRunningTaskManager`)
- **Capabilities**:
  - Task priority queue: `CRITICAL` (100), `HIGH` (75), `NORMAL` (50), `LOW` (25).
  - State machine: `PENDING`, `RUNNING`, `PAUSED`, `BLOCKED`, `COMPLETED`, `FAILED`, `CANCELLED`.
  - Automatic checkpointing to `TaskStore` after every execution step.
  - Progress calculation: percentage, elapsed seconds, ETA, and current step index.
  - Reboot recovery (`recover_interrupted_tasks()`): automatically discovers active tasks on startup and safely sets them to `PAUSED` for operator resumption.
  - CLI controls: `/task-pause <id>`, `/task-resume <id>`, `/task-cancel <id>`.

### 4. Persistent Recurring Task Scheduler
- **Extension**: `src/extensions/scheduler_extension.py` (`SchedulerExtension`)
- **Capabilities**:
  - Implements `LifecycleExtension` protocol (`initialize`, `shutdown`, `health_check`, `is_available`).
  - Supports `ONCE`, `INTERVAL`, `DAILY` ("HH:MM"), `WEEKLY`, and `CRON` schedules.
  - Persistent SQLite storage surviving complete system restarts.
  - Integrated with `SecurityGate` so scheduled executions never bypass safety policies.

### 5. Multi-Agent Orchestration
- **Orchestrator**: `src/agents/orchestrator.py` (`SupervisorOrchestrator`)
- **Specialized Workers**: `src/agents/workers.py`
  - `PlannerWorker`: breaks complex goals into sequential subtasks.
  - `ResearchWorker`: gathers multi-source evidence and facts.
  - `BrowserWorker`: navigates and automates web applications.
  - `DesktopWorker`: manages native OS windows, mouse, and keyboard.
  - `CoderWorker`: synthesizes code and verifies workspace files.
  - `VerifierWorker`: checks conditions and tests deliverables.
  - `SecurityWorker`: inspects operations against organizational policies.
- **Safety Guarantees**:
  - Privilege escalation blocked: workers cannot delegate tasks requiring higher risk permissions than they possess.
  - Conflict resolution: supervisor detects failed or dissenting workers and arbitrates conservatively.

### 6. Advanced 10-Layer Memory System
- **Implementation**: `src/core/memory_layers.py` (`UnifiedMemory`)
- **Layers**:
  - Layer 1: `ConversationMemory` (multi-turn conversation history)
  - Layer 2: `UserPreferenceMemory` (key-value user preferences)
  - Layer 3: `TaskMemory` (active goals, subgoals, steps)
  - Layer 4: `CapabilityMemory` (registered, discovered, and learned skills)
  - Layer 5: `ApplicationContext` (active OS window, title, bounds)
  - Layer 6: `BrowserContext` (active tabs, search continuations)
  - Layer 7: `DeviceContext` (monitors, resolution, DPI scaling)
  - Layer 8: `EpisodicMemory` (chronological interaction logs and task outcomes)
  - Layer 9: `SemanticMemory` (knowledge graph triples: subject, predicate, object, confidence)
  - Layer 10: `ProceduralMemory` (learned workflow recipes and reusable playbooks)
- **Operations**:
  - `unified_search(query)` across all 10 layers simultaneously.
  - Snapshot persistence across restarts.

### 7. Structured Deep Web Research Pipeline
- **Orchestrator**: `src/research/orchestrator.py` (`ResearchOrchestrator`)
- **Workflow**:
  1. Query decomposition into targeted sub-queries.
  2. Multi-source search and URL deduplication.
  3. Content extraction and cross-source fact corroboration.
  4. Confidence assessment (`HIGH`, `MEDIUM`, `LOW`).
  5. Synthesis into structured markdown reports with executive summary, key findings, subtopics, and citations.

### 8. Observability & Explainability
- **Engine**: `src/core/observability.py` (`ObservabilityEngine`)
- **Capabilities**:
  - Activity stream with categorization and execution durations.
  - Complete security audit log of every decision (`ALLOW`, `REQUIRE_CONFIRMATION`, `DENY`).
  - Operation metrics (call counts, min/max/average latency, error rates).
  - Decision explainability: records goal, chosen path, alternatives considered, and policy rationale.
  - System health summary and success rate calculations.

---

## Verification & Test Results

- **Level 5 Comprehensive Evaluation**: `tests/test_level5_evaluation.py`
  - **31 / 31 Scenarios PASSED (100%)**
- **Level 4 Real-Agent Evaluation**: `tests/test_agent_evaluation_40.py`
  - **40 / 40 Scenarios PASSED (100%)**
- **Subsystem Tests**:
  - MCP: 5/5 PASS
  - OAuth & TokenStore: 6/6 PASS
  - Scheduler & Long-Running: 4/4 PASS
  - Multi-Agent: 7/7 PASS
  - Advanced Memory: 4/4 PASS (plus 8/8 regression)
  - Deep Research: 5/5 PASS
  - Observability: 4/4 PASS
