# BROWSERCONTROL AUDIT & EVALUATION REPORT
**Target Repository**: `https://github.com/Officially-aditya/browserControl`  
**Host System**: `C:\NEXA`  
**Date**: September 2026  
**Auditor**: NEXA Core Architecture & Agent Evaluation Group

---

## Executive Summary

`browserControl` is an open-source visual browser I/O layer designed for AI agents. Rather than running an isolated headless Puppeteer or Playwright browser with separate user profiles, cookies, and logins, `browserControl` connects directly to the user's existing Google Chrome session via a Manifest V3 Chrome Extension powered by Chrome DevTools Protocol (`chrome.debugger` API).

### Key Architectural Takeaways
1. **Model & Framework Agnostic**: browserControl does not bundle an LLM or planner; it strictly provides browser I/O via the Model Context Protocol (MCP) or raw WebSocket RPC.
2. **Vision-Driven Computer-Use Model**: It operates on normalized `0-1000` coordinate space and returns screenshots, eliminating brittle DOM selector dependencies.
3. **Strict Observation Freshness Contract**: Any visual mutation (click, type, drag, scroll) requires an `observationId`. Mutations against outdated frames fail with `STALE_OBSERVATION`.
4. **Port 8765 Conflict Identified**: Both NEXA UI and browserControl default to `127.0.0.1:8765`. This is an acute architectural collision that explains connection dropouts when both services run concurrently.

---

## 1. Architectural Components

```text
┌─────────────────────────────────────────────────────────────┐
│                       NEXA Kernel                           │
│     (Planner, SecurityGate, IntentRouter, EventBus)         │
└──────────────────────────────┬──────────────────────────────┘
                               │ MCP or JSON-RPC
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                 browserControl Local Runtime                 │
│                 (src/local/runtime.ts)                      │
│             Listens on 127.0.0.1:8765 (default)             │
│            - POST /handshake (challenge auth)               │
│            - WS /extension (challenge verification)         │
│            - Stdio MCP Server (@modelcontextprotocol/sdk)   │
└──────────────────────────────┬──────────────────────────────┘
                               │ Loopback WebSocket
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                 Chrome Extension (MV3)                      │
│                 (extension/service-worker.js)               │
│         - Uses chrome.debugger API (v1.3)                   │
│         - Arbitrates local vs remote leases                 │
│         - Renders logical pointer overlay                   │
│         - Tracks visualEpoch and stale observations         │
└──────────────────────────────┬──────────────────────────────┘
                               │ CDP (Page, DOM, Input, Runtime)
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                 Real User Google Chrome                     │
│    (Existing authenticated sessions, cookies, tabs)         │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. Deep Dive into browserControl Subsystems

### A. Local Runtime & Extension Server
- **File**: [`src/local/extension-server.ts`](file:///C:/NEXA/external/browserControl/src/local/extension-server.ts)
- **Binding**: Binds to `127.0.0.1` (loopback only).
- **Authentication**: Prevents arbitrary websites from spoofing the extension bridge.
  1. Extension issues `POST /handshake` with header `X-BrowserControl-Extension-Id: <extension-id>`.
  2. Server verifies `extensionId` against `/^[a-p]{32}$/` and matches the `Origin: chrome-extension://<id>`.
  3. Server generates a cryptographically secure 32-byte challenge token (`base64url`) with a 15-second TTL.
  4. Extension opens WebSocket to `/extension?extensionId=<id>&challenge=<token>`.
  5. If valid, the challenge is consumed and the socket is attached to `ExtensionBridge`.

### B. Chrome Extension Architecture
- **Manifest**: Manifest V3 (`manifest_version: 3`).
- **Permissions**: `debugger`, `tabs`, `storage`, `activeTab`, `alarms`.
- **Host Permissions**: `http://127.0.0.1/*` and Railway relay URL.
- **Debugger Attachment**: Does not stay attached to all tabs continuously. When an action is requested, `ensureAttached()` selects the active tab, attaches `chrome.debugger.attach({ tabId }, "1.3")`, and enables `Page`, `DOM`, and `Runtime` domains.
- **Auto-Targeting & Tab Exclusions**:
  - Automatically targets the active tab.
  - Skips internal pages (`chrome://*`, `edge://*`).
  - Skips AI chat control surfaces (`claude.ai`, `chatgpt.com`, `chat.openai.com`) to prevent the agent from accidentally clicking its own prompt interface.
  - Automatically detaches after 15 minutes of inactivity (`browsercontrol-control-session-idle` alarm).

### C. MCP Interface & Tool Catalog
`browserControl` registers 20 MCP tools via `createBrowserControlMcpServer`:

| Category | Tool Name | Mutating? | Description |
|---|---|:---:|---|
| **Status** | `browser_status` | No | Reports connection, active tab, pointer coords, lease status |
| **Observation** | `browser_observe` | No | Captures tab screenshot (JPEG/PNG/WebP), returns `observationId` |
| | `browser_inspect` | No | Captures a high-resolution sub-crop of an existing observation |
| **Mouse/Pointer** | `browser_move` | Yes | Moves the logical pointer overlay to normalized (0-1000) coords |
| | `browser_click` | Yes | Clicks at normalized coords (left, right, middle) |
| | `browser_double_click` | Yes | Double clicks at normalized coords |
| | `browser_drag` | Yes | Drags through a path of normalized waypoints |
| | `browser_scroll` | Yes | Scrolls with deltaX/deltaY CSS pixels at normalized coords |
| **Keyboard** | `browser_type` | Yes | Types text into currently focused element (max 5000 chars) |
| | `browser_keypress` | Yes | Sends keyboard shortcut combinations (e.g. `["Control", "t"]`) |
| **Navigation** | `browser_navigate` | Yes | Navigates to safe HTTP/HTTPS URL (deterministic recovery) |
| | `browser_back` | Yes | History backward navigation |
| | `browser_forward` | Yes | History forward navigation |
| | `browser_reload` | Yes | Reloads current page |
| **Tab Control** | `browser_tabs` | No | Lists all visible open tabs (ID, title, URL) |
| | `browser_switch_tab` | Yes | Switches control to specific `targetId` |
| | `browser_new_tab` | Yes | Creates new tab (`http`, `https`, or `about:blank`) |
| | `browser_close_tab` | Yes | Closes specific or active tab |
| **Dialogs/Control**| `browser_handle_dialog`| Yes | Accepts or dismisses JavaScript alert/confirm/prompt |
| | `browser_release_control` | Yes | Releases the interactive client lease |

### D. Observation System & Stale Observation Protection
- **Observation ID Format**: `${tabId}:${visualEpoch}:${crypto.randomUUID()}`.
- **Monotonic Counter**: `visualEpoch` starts at `0` and increments whenever the page undergoes:
  - Navigation or reload (`Page.frameNavigated`, `Page.navigatedWithinDocument`)
  - DOM mutation or layout changes
  - Prior mutating actions (`click`, `type`, `scroll`, `drag`, etc.)
  - Explicit user interaction
- **`assertFresh(observationId)`**:
  Before any mutating action executes, the service worker verifies:
  1. `record.tabId === attachedTabId`
  2. `record.visualEpoch === visualEpoch`
  If either condition fails, it aborts immediately with `STALE_OBSERVATION`:
  `Error: STALE_OBSERVATION: control context changed after the screenshot (<reason>)`
- **Result**: Zero "blind multi-clicking" or desynchronized clicks into ghost elements.

### E. Safety Boundaries
1. **URL Whitelisting**: `assertSafeNavigationUrl` strictly blocks `file://`, `javascript:`, `data:`, `chrome://`, `chrome-extension://`.
2. **Payload Size Guard**:
   - `type` text $\le$ 5,000 characters
   - `keys` $\le$ 10 keys
   - `drag` path $\le$ 50 waypoints
   - `scroll` deltas $\le \pm 4000$ pixels
3. **Emergency Pause**: The extension popup provides a physical "Pause" toggle that detaches the debugger and rejects all remote/local commands immediately.
4. **Client Leases**: `ControlLease` grants an exclusive 60-second lease to prevent multiple agents from fighting over the same browser window.

---

## 3. Comparison with Existing NEXA Architecture

| Feature / Domain | NEXA Existing Implementation | browserControl Implementation | Assessment |
|---|---|---|---|
| **Underlying Engine** | Playwright Chromium (`src/browser/engine.py`) | Chrome Extension via `chrome.debugger` CDP | **ADAPT / INTEGRATE**: browserControl controls the user's real Chrome session with existing logins. NEXA Playwright is best for isolated tests. |
| **Brain / Reasoning** | `IntentRouter`, `TaskPlanner`, `PlanExecutor` | None (pure I/O layer) | **KEEP NEXA**: NEXA remains the planner, executor, and security gatekeeper. |
| **Security Governance** | `SecurityGate` (5 Risk Tiers), `FailsafeMonitor` | Transport leases, safe URL assertions | **KEEP NEXA**: All browser actions must still route through NEXA `SecurityGate` and `Failsafe`. |
| **Interaction Paradigm**| CSS selectors, Playwright DOM locators | Screenshots, normalized `0-1000` coordinates | **WRAP / ADAPT**: Coordinate-based vision control is more robust for real web apps without selectors. |
| **Stale Action Protection** | Heuristic retries | Cryptographic `observationId` + `visualEpoch` | **ADAPT browserControl**: Incorporate strict `observationId` freshness checks. |
| **Tab Management** | Playwright BrowserContext pages | Chrome Extension `chrome.tabs` API | **WRAP**: Map to NEXA's high-level tab abstractions. |
| **UI Server Port** | `127.0.0.1:8765` (NexaUIServer) | `127.0.0.1:8765` (Default local bridge) | **CONFLICT**: Both claim port 8765. Requires deliberate architectural separation. |

---

## 4. Port 8765 Conflict Investigation

### The Conflict
- In **NEXA**:
  [`src/ui/server.py`](file:///C:/NEXA/src/ui/server.py) defaults to:
  ```python
  class NexaUIServer:
      def __init__(..., host="127.0.0.1", port=8765):
  ```
  And [`src/ui/web/app.js`](file:///C:/NEXA/src/ui/web/app.js) connects to `ws://127.0.0.1:8765/ws`.
- In **browserControl**:
  [`src/local/extension-server.ts`](file:///C:/NEXA/external/browserControl/src/local/extension-server.ts) defines:
  ```typescript
  export const DEFAULT_LOCAL_PORT = 8765;
  ```
  And [`extension/local-connection.js`](file:///C:/NEXA/external/browserControl/extension/local-connection.js) connects to:
  ```javascript
  export const LOCAL_BRIDGE_HTTP_ORIGIN = "http://127.0.0.1:8765";
  export const LOCAL_BRIDGE_WS_ORIGIN = "ws://127.0.0.1:8765";
  ```

### Impact
When both services run:
1. **Port Collisions**: If NEXA UI starts first, browserControl fails to bind with `EADDRINUSE`. The Chrome extension tries to connect to `ws://127.0.0.1:8765` and hits NEXA UI's WebSocket endpoint, which cannot understand the handshake.
2. **Reverse Collision**: If browserControl starts first on 8765, NEXA UI fails to bind or binds elsewhere, and the user's browser opens NEXA UI which sends `/api/command` to browserControl, producing `404 Not Found` or connection reset, surfacing as `Failed to fetch`.

### Architectural Resolution
- **Do not randomly change ports**:
  - `browserControl` supports an environment variable for its local port:
    `BROWSERCONTROL_LOCAL_PORT` in `src/local/runtime.ts`.
  - However, the unpacked Chrome extension in `extension/local-connection.js` hardcodes `8765` by default unless configured or proxied.
  - **Clean Architectural Solution**:
    Assign dedicated, collision-free ports:
    - **NEXA Core UI / REST / WebSocket**: Port `8765` (Authoritative NEXA Operating System Port).
    - **browserControl Local Bridge**: Port `8768` (or configured via `BROWSERCONTROL_LOCAL_PORT=8768`), OR embed a lightweight reverse-proxy / multiplexer in NEXA server that routes `/extension` and `/handshake` to browserControl and `/api/*`, `/ws`, and `/` to NEXA UI!
    - Alternatively: Keep NEXA UI on `8765` and configure the browserControl local bridge on `8766` with a synchronized extension configuration.

---

## 5. Decision & Recommendation

1. **Adopt browserControl as an Additional / Primary Real-Chrome Foundation**:
   - `browserControl` provides what Playwright cannot: access to the user's real Chrome browser with active logins, cookies, and extensions.
   - It should NOT replace NEXA's existing Playwright engine entirely; Playwright remains valuable for headless sandboxed background tasks, scrapers, and unit tests where the user does not want their active window touched.
2. **Create a Unified Adapter (`src/browser/browsercontrol_adapter.py`)**:
   - Encapsulates stdio MCP or WebSocket RPC to browserControl.
   - Enforces the `observe -> act -> observe -> act` freshness contract.
   - Bridges to NEXA `SecurityGate` and `FailsafeMonitor`.
3. **Preserve NEXA's Higher-Level Skills**:
   - `BrowserSkill` in NEXA can route actions either to `PlaywrightEngine` (sandbox mode) or `BrowserControlAdapter` (real Chrome mode).
