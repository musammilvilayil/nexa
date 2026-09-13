# NEXA SYSTEM AUDIT & ARCHITECTURAL GAP ANALYSIS
**Repository Root**: `C:\NEXA`  
**Date**: September 2026  
**Auditor**: Lead Architect & Autonomous Agent Engineering Group  
**Target**: Transform NEXA from a fragile command/skill assistant into a verified Level-5 General-Purpose Autonomous Personal AI Computer Agent.

---

## Executive Summary

A comprehensive full-system audit of the entire `C:\NEXA` codebase, test suite, runtime subsystems, UI layer, browser engines, computer controls, security gates, and self-improvement pipelines was performed.

The system currently possesses strong foundations:
- **520 unit and integration tests** pass cleanly with 0 failures and 0 errors.
- An immutable SQLite audit ledger (`SQLiteAuditLedger`), structured risk tiers (`SecurityGate`), an active failsafe monitor (`FailsafeMonitor`), and an asynchronous event bus (`UIEventBus`) are operational.
- Low-level computer controls (`Win32` window handles, `mss` screen capture, mouse and keyboard injection via `pynput`, `ctypes` clipboard with secret masking) are functional.

However, NEXA cannot currently function as a truly autonomous, general-purpose personal computer agent because it suffers from **five systemic architectural bottlenecks**:
1. **Hardcoded Regex Brittle Dispatch**: Skills match commands through rigid regex patterns (e.g. `\S+` path capture, strict phrasing templates). Natural variations, compound goals, or descriptive prompts fail with `no_match` or default to conversational chat.
2. **Disconnected App Automation**: "Open Notepad and create test.txt" launches Notepad as a detached process, while silently creating an empty file on disk via Python file I/O. NEXA never interacts with the open Notepad window, never types text into it, never invokes its Save dialog, and never verifies Notepad's GUI state.
3. **Dual Competing Browser Subsystems & Port 8765 Collision**: `BrowserSkill` (headless Playwright) and `BrowserControlSkill` (CDP/Extension bridge) conflict. Playwright runs hidden from the user by default, while the CDP bridge attempts to bind to `127.0.0.1:8765`, colliding directly with the NEXA UI server on the exact same port.
4. **Arbitrary Workspace Path Confinement**: `FileSkill._resolve` throws `ValueError("path escaped active workspace")` on any path outside `C:\NEXA` or home directory, preventing genuine drive-wide computer tasks such as managing files on `D:\` or creating folders in user-specified drives.
5. **Absence of a Formal Observe-Act-Verify-Recover Closed Loop**: Once a command is triggered, NEXA assumes success. There is no active `ObservationEngine` or `VerificationEngine` ensuring that a window actually appeared, a process is alive, a URL completed navigation, or a file contains the expected payload.

---

## PHASE 0 DETAILED AUDIT: THE 11 KEY SYSTEM QUESTIONS

### 1. What Currently Works

| Subsystem | Location | Details |
|---|---|---|
| **Kernel Core** | `src/core/kernel.py` | Core orchestration pipeline, pending action tokens, dispatching registered skills, parameter contract validation. |
| **Audit Ledger** | `src/core/audit.py` | Forensic append-only SQLite action ledger (`SQLiteAuditLedger`). Records action hashes, inputs, and results. |
| **Security Gate** | `src/core/security.py` | Five-tier risk classification (`READ`, `LOW_RISK`, `MUTATE`, `HIGH_RISK`, `CRITICAL`, `REMOTE`). Denylist for destructive commands (`rm -rf`, `format`, `del /s`). |
| **Failsafe System** | `src/core/failsafe.py` | Non-bypassable emergency stop, screen corner trigger (`(0,0)` to `(5,5)` px), rate limiting (up to 60 actions/sec), blocked process detection. |
| **Computer Control Primitives** | `src/computer/` | `screen.py` (`mss` screen capture), `mouse.py` (movement, clicks, scroll), `keyboard.py` (typing, hotkeys, secret masking), `clipboard.py` (Win32 clipboard with retry & secret mask), `window.py` (Win32 window enumeration, focus, restore). |
| **Application Launcher** | `src/computer/app_control.py` | Windows executable resolution via `shutil.which`, `C:\Program Files`, `System32`, with alias mapping for 15+ standard Windows applications. |
| **Task Store** | `src/planner/task_store.py` | SQLite persistence schema for task definitions, plan steps, and recovery history. |
| **Event Bus** | `src/ui/event_bus.py` | In-memory pub-sub with async queue registration and historical event replay buffer. |
| **Terminal Skill** | `src/skills/terminal_skill.py` | Safe terminal execution via PowerShell cmdlet routing (`powershell.exe -NoProfile -Command`) and cmd built-ins (`cmd.exe /c`). |
| **Test Suite** | `tests/` | 520 automated tests passing with 0 failures and 0 errors. |

---

### 2. What is Partially Implemented

| Subsystem | Location | Partial Status & Limitations |
|---|---|---|
| **Task Planner** | `src/planner/task_planner.py` | Decomposes compound commands on hardcoded conjunctions (`and then`, `pinne`, `ennitt`) and rigid regex templates. Fails when phrases do not match regexes. |
| **Plan Executor** | `src/planner/executor.py` | Sequentially executes steps with basic rollback. Lacks real-time observation, visual verification, and dynamic in-flight replanning. |
| **Browser Engine** | `src/browser/engine.py` | Playwright engine runs in headless mode by default. On timeout, it falls back to `about:blank` and claims success. Does not connect to user Chrome profile by default. |
| **UI REST & WebSocket Server** | `src/ui/server.py` | Serves web client and streams events. Port 8765 overlaps with external extension bridge; JSON serialization can fail on complex objects. |
| **Web Frontend** | `src/ui/web/app.js` | Full-featured UI (Chat, Tasks, Monitoring, Training tabs). `window.resumeTask` and other control bindings were previously scoped inside `DOMContentLoaded` only. |
| **Voice Subsystem** | `src/voice/` | Modules exist for listener, STT (Vosk/Gemini), TTS (pyttsx3/Edge-TTS), and wake word. Not continuously integrated into the main agent control loop. |
| **Long-Running Task Manager** | `src/planner/long_running.py` | Runs threads in memory, but state updates (pause/resume) are not cleanly synchronized back to SQLite `TaskStore`. |
| **Self-Extension System** | `src/capabilities/` | Dynamically registers newly coded Python skills into `capabilities.db`. Lacks automated sandbox execution, regression testing, and verification. |

---

### 3. What is Mocked

1. **Trading Execution**: `src/skills/trading/` is entirely simulated paper trading (`paper_trading.db`) with simulated broker adapters and promotion criteria. This is mocked by design for financial safety.
2. **Storage Analysis Reports**: In `src/skills/file_skill.py:568-575`, storage summaries previously output hardcoded static drive strings (`"Drive C: Total 476 GB, Free 185 GB..."`) instead of querying live Windows disk geometry via `GetDiskFreeSpaceExW` or `shutil.disk_usage`.
3. **Vision Backend in ScreenAnalyzer**: In `src/computer/vision.py`, when Gemini API key is missing or offline, the analyzer returns stub states or assumptions of success (`return True`).
4. **Browser Integration Tests**: Certain tests in `tests/test_browser_skill.py` and `tests/test_agent_evaluation_40.py` mock network responses or test against local HTML buffers.

---

### 4. What is Broken

1. **Natural Language Routing**: Commands like `"Open Chrome and search GitHub"` or `"Create a folder called Projects on D drive"` fail to match because skill regexes expect rigid formats (`_SEARCH_RE`, `mkdir_match`). Unmatched commands fall back to conversational chat or return `no_match`.
2. **Notepad & App Workflow Disconnect**: `"Open Notepad and create test.txt"` launches `notepad.exe` as an unattached subprocess, while creating `test.txt` via Python `Path.write_text()`. It never interacts with Notepad's GUI, never enters text into the window, and never uses Notepad's Save dialog.
3. **Port 8765 Socket Conflict**: The `external/browserControl` CDP bridge attempts to bind to port 8765, colliding directly with `src/ui/server.py` running on `8765`, causing `EADDRINUSE` errors and WebSocket disconnections.
4. **Drive Confinement in FileSkill**: `FileSkill._resolve` enforces `is_relative_to(root)` where root is `C:\NEXA` or user home. Any operation targeting `D:\` or external paths throws `ValueError("path escaped active workspace")`.

---

### 5. What Capabilities Are Missing

1. **Dynamic Intent Understanding Engine**: An intent parser that translates free-form natural language into structured capability requests and parameter schemas without relying on brittle regexes.
2. **Formal ObservationEngine**: A dedicated system that captures pre- and post-action system state (active window HWND, process PID tree, screenshot difference, DOM snapshot, filesystem delta).
3. **Formal VerificationEngine**: A multi-modal verification system that validates that an action actually had its intended effect (e.g. window exists and has target title, file exists with correct byte size and contents, URL navigated and page DOM loaded).
4. **Structured Failure Analyzer**: An automated post-failure diagnostic engine that logs failure context, takes screen/DOM snapshots, categorizes root causes, and saves records to `data/learning/failures/`.
5. **Closed-Loop Self-Improving Skill Builder**: A pipeline that automatically identifies missing capabilities upon failure, generates a candidate skill in a sandbox, validates AST and security, executes regression tests, hot-registers the skill, and retries the task.
6. **Task Memory System**: Persistent SQLite/vector storage for task plans and solutions, enabling the agent to retrieve proven plans for similar tasks.
7. **Configurable Autonomy Policies**: Policy profiles (`SUPERVISED`, `SEMI_AUTONOMOUS`, `AUTONOMOUS_SAFE`) in `SecurityGate` so safe read and low-risk mutate actions execute smoothly without halting for interactive confirmation.

---

### 6. Why Natural-Language Commands Currently Fail

NEXA routes user inputs through a deterministic regex-first pipeline:
1. `NexaKernel.process(text)` iterates through all registered skills in `SkillRegistry`.
2. Each skill runs its custom `match(text, context)` method containing dozens of hand-written regexes (e.g., `_SEARCH_RE`, `_NL_WRITE_FILE_RE`, `_LAUNCH_RE`).
3. If the user phrasing deviates even slightly from the exact pattern (e.g. `"Create a folder called Projects on D drive"` or `"Open YouTube and search for Python tutorials"`):
   - In `file_skill.py`: `mkdir_match` uses `(\S+)` which expects a single word without spaces. The phrase `"Projects on D drive"` fails.
   - In `browser_skill.py`: `_SEARCH_RE` expects `"search google for <query>"`, failing on `"open youtube and search for python tutorials"`.
4. When `SkillRegistry.resolve()` fails to find a match, NEXA falls through to `ConversationalEngine` (which responds as a chatbot) or returns `no_match`. Natural language is never transformed into an actionable intent tree.

---

### 7. Why Chrome / Browser Commands Fail

1. **Headless Execution Concealment**: `BrowserEngine` initializes with `headless=True` by default. When a user says `"Open browser"` or `"Open Chrome"`, Playwright opens a hidden background chromium process. The user sees nothing on screen and believes the command failed.
2. **Port 8765 Collision**: The `external/browserControl` local extension server binds to `127.0.0.1:8765`. NEXA UI server in `src/ui/server.py` ALSO defaults to `port = 8765`. When both run simultaneously, the socket fails to bind or corrupts WebSocket communication.
3. **Hardcoded Fallbacks Masking Errors**: In `BrowserEngine._navigate_impl`, if a navigation timeout occurs, the code catches the exception and redirects to `about:blank`, returning `success=True` with `message="Navigated to ... (fallback)"`. This false success prevents error recovery.
4. **SecurityGate Confirmation Trap**: In `BrowserSkill`, browser operations (`open`, `search`, `download`) are assigned `RiskTier.REMOTE`. In `SecurityGate`, `REMOTE` mandates explicit interactive confirmation (`confirmation_required`). As a result, autonomous browser pipelines halt before executing.

---

### 8. Why Notepad / File Workflows Fail

1. **Disconnected Execution Plan**: For `"Open Notepad and create test.txt"`, `TaskPlanner` generates two uncoordinated steps:
   - Step 1: `app_control.launch(app_name="Notepad")`
   - Step 2: `files.write(path="test.txt", content="")`
   Step 1 spawns `notepad.exe`. Step 2 uses Python's `Path.write_text()` to create an empty file directly in the workspace directory. Step 2 never sends keystrokes to Notepad, never interacts with its window, never uses File -> Save, and never confirms Notepad holds the content.
2. **Path Sandbox Confinement**: In `FileSkill._resolve`:
   ```python
   is_inside = target.is_relative_to(root)
   if not is_inside:
       raise ValueError("path escaped active workspace")
   ```
   If a user asks to create, copy, or move files to `D:\` or any directory outside `C:\NEXA` (or user home), `FileSkill` aborts with a validation exception.
3. **Missing Verification**: Once Notepad is launched, the system checks nothing. If Notepad crashed or hung, NEXA reports success simply because `subprocess.Popen` succeeded.

---

### 9. Why WebSocket / UI Errors Occur

1. **Port Address Collisions**: The dual usage of port 8765 by the UI server and the browserControl bridge leads to `EADDRINUSE` socket conflicts, causing frequent disconnects.
2. **WebSocket Message Serialization Faults**: `ui/server.py` attempts to transmit raw event objects over WebSocket. When an event payload contains non-serializable objects (such as `Path`, `bytes`, dataclasses with cyclic references, or custom exceptions), JSON serialization fails.
3. **Aggressive Polling Fallback Race Conditions**: In `app.js`, when a WebSocket closes, `startRestPolling()` runs a `setInterval(pollRest, 3000)`. When WebSocket reconnects, if polling is not cleanly cleared or if multiple reconnections overlap, concurrent state updates overwrite active UI components.

---

### 10. Why `resumeTask` and UI Functions Were Missing / Failing

1. **Deferred Window Export**: In `src/ui/web/app.js:1373-1381`, `window.resumeTask`, `window.pauseTask`, etc., were defined inside `window.addEventListener('DOMContentLoaded', ...)`. If any inline event handler (`onclick="resumeTask('...')"` in dynamic templates) or external script executed before `DOMContentLoaded`, `window.resumeTask` was `undefined`, throwing a fatal JavaScript `ReferenceError`.
2. **Store vs In-Memory Desynchronization**: In `LongRunningTaskManager`, pausing or resuming a task manipulated internal thread control flags without synchronizing the state in `TaskStore` (`tasks.db`). When the UI reloaded task history from `/api/tasks`, the state appeared unchanged or in conflict.

---

### 11. Which Existing Code Can Be Reused

The audit confirms that substantial parts of NEXA are well-engineered and must be preserved:
1. **`NexaKernel` (`src/core/kernel.py`)**: Robust orchestration pipeline, pending action tokens, and clean interface contracts.
2. **`SQLiteAuditLedger` (`src/core/audit.py`)**: Immutable forensic action logging.
3. **`FailsafeMonitor` (`src/core/failsafe.py`)**: Comprehensive screen corner detection, emergency stop semantics, and action throttling.
4. **`ApplicationRegistry` & `ApplicationLauncher` (`src/computer/app_control.py`)**: Accurate executable path resolution for Windows apps (`C:\Program Files`, `System32`, `which`).
5. **Computer Control Modules (`src/computer/`)**:
   - `window.py`: Win32 window enumeration, title search, and foreground window activation.
   - `screen.py`: Fast multi-monitor capture via `mss`.
   - `mouse.py` & `keyboard.py`: Windows input injection with coordinate scaling.
   - `clipboard.py`: Win32 clipboard read/write with retry backoff and secret masking.
6. **Task Persistence (`src/planner/task_store.py`)**: Robust SQLite schema for task definitions, steps, and recovery attempts.
7. **UI Event Bus (`src/ui/event_bus.py`)**: Asynchronous, thread-safe event publishing architecture.
8. **Security Framework (`src/core/security.py`)**: Five-tier risk classification system ready for autonomy policy extensions.
9. **Terminal Skill (`src/skills/terminal_skill.py`)**: Safe command execution with PowerShell and cmd routing.

---

## HIGHEST-PRIORITY BLOCKERS & DEPENDENCY ORDER

To transform NEXA systematically without breaking existing functionality, the implementation must proceed in exact dependency order:

1. **Blocker 1 (Phase 1 — Core Agent Architecture)**: Eliminate brittle regex dependency by introducing dynamic Intent Understanding that decomposes user goals into structured plans.
2. **Blocker 2 (Phase 2 — Unified Browser Control Skill)**: Consolidate Playwright and CDP into a first-class visible browser capability, resolving port 8765 collision (moving CDP bridge to 8766) and providing DOM inspection and structured results.
3. **Blocker 3 (Phase 3 & 4 — Windows Computer Control & Safe Filesystem Agent)**: Connect app launching with window focus/GUI typing for Notepad and Office apps; allow drive-wide operations on C: and D: with strict safety classification (`SAFE`, `CAUTION`, `SYSTEM`, `UNKNOWN`).
4. **Blocker 4 (Phase 5 — Observe / Verify Engine)**: Implement `ObservationEngine` and `VerificationEngine` so every action is verified via real OS/DOM state.
5. **Blocker 5 (Phase 6 & 7 — Failure Analyzer & Self-Improving Skill Builder)**: Log structured failure records in `data/learning/failures/` and enable automated sandboxed skill synthesis with regression verification.
6. **Blocker 6 (Phase 8–13 — Memory, UI, Voice, Events, Security)**: Wire Task Memory, polish ChatGPT-style control center, guarantee WebSocket stability, and provide autonomy profiles.
7. **Blocker 7 (Phase 14–18 — 5000-Task Benchmark, Improvement Loop, Windows Startup)**: Scale benchmark evaluation and automated training loop.
