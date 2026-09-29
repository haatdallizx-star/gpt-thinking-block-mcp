# Hardened Succhia Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect 啵啵贝 Pro to the existing VPS/ChatGPT path through an authenticated Android Chrome BLE bridge with EMS locked and fail-safe zeroing.

**Architecture:** Add a focused `succhia_runtime.py` module beside the existing dependency-free MCP server, reuse the existing HTTPS reverse proxy, and serve a hardened control page derived from `29-Cu/succhia`. The existing thinking tool remains the default surface; Succhia tools appear only on requests carrying the dedicated MCP token.

**Tech Stack:** Python 3 standard library, dependency-free Streamable HTTP MCP, HTML/CSS/JavaScript, Web Bluetooth, `unittest`

**Spec:** `docs/superpowers/specs/2026-09-29-hardened-bridge.md`

## Global Constraints

- EMS is forced to zero at every boundary and is absent from user/model controls.
- Suction and vibration are capped at 30/100.
- Non-zero commands expire after 3-120 seconds; expiry clears channels and patterns.
- Disconnect/reconnect never restores a non-zero value.
- Page and MCP credentials are separate and never appear in status or diagnostics.
- Existing thinking-block MCP behavior must remain backward compatible.

## Review Focus

- Missing, malformed, or incorrect page tokens must produce 401 without state mutation.
- Missing or incorrect MCP tokens must not list or call Succhia tools.
- Values above 30, below zero, strings, and booleans must be rejected or clamped deterministically.
- Expired leases and bridge disconnect reports must atomically clear both channels and all patterns.
- Server restart with stale persisted state must boot at zero, not replay an old command.

---

### Task 1: Safe state runtime and authenticated bridge API

**Files:**
- Create: `succhia_runtime.py`
- Create: `tests/test_succhia_runtime.py`

**Interfaces:**
- Produces: `SucchiaRuntime(config_path, state_path)`, `runtime.handle_get(path, query, headers)`, `runtime.handle_post(path, query, headers, body)`, `runtime.mcp_tools(authorized)`, and `runtime.mcp_call(name, args, authorized)`.

- [ ] **Step 1: Write failing tests** for separate tokens, the 30 cap, EMS rejection, required leases, expiry zeroing, disconnect zeroing, and zero-on-restart.
- [ ] **Step 2: Run tests to verify they fail.**

Run: `python3 -m unittest tests.test_succhia_runtime -v`

- [ ] **Step 3: Implement the minimal runtime** with an in-process condition variable for long polling, atomic JSON writes, and redacted status output.
- [ ] **Step 4: Run tests to verify they pass.**
- [ ] **Step 5: Commit** runtime and tests.

### Task 2: Hardened Android Web Bluetooth control page

**Files:**
- Create: `web/succhia.html`
- Create: `tests/test_succhia_web.py`

**Interfaces:**
- Consumes: `/succhia-api/poll`, `/set`, `/status`, `/event`, and `/disconnect` from Task 1.
- Produces: an HTTPS page compatible with Android Chrome Web Bluetooth and device name `SOSEXY`.

- [ ] **Step 1: Write failing browser-contract tests** against a small fake Web Bluetooth stack, covering token headers, max 30 controls, no EMS writes, disconnect zeroing, and reconnect-at-zero behavior.
- [ ] **Step 2: Run tests to verify they fail.**

Run: `python3 -m unittest tests.test_succhia_web -v`

- [ ] **Step 3: Implement the hardened page** while preserving the upstream BLE frame format, serialized writes, long polling, watchdog reconnect, and manual Stop button.
- [ ] **Step 4: Run tests to verify they pass.**
- [ ] **Step 5: Commit** the page and tests.

### Task 3: Integrate authenticated Succhia tools into the existing MCP server

**Files:**
- Modify: `server.py`
- Modify: `tests/test_server.py`

**Interfaces:**
- Consumes: `SucchiaRuntime.mcp_tools()` and `SucchiaRuntime.mcp_call()` from Task 1.
- Produces: `succhia_set`, `succhia_pattern`, `succhia_stop`, and `succhia_status` for an authorized connector URL; serves `/succhia` and `/succhia-api/*`.

- [ ] **Step 1: Write failing integration tests** for legacy thinking-only callers, token-gated tool lists/calls, REST routing, and unchanged widget resources.
- [ ] **Step 2: Run tests to verify they fail.**

Run: `python3 -m unittest tests.test_server -v`

- [ ] **Step 3: Thread request authorization into MCP dispatch** and delegate Succhia routes without changing existing thinking responses.
- [ ] **Step 4: Run the complete suite.**

Run: `python3 -m unittest discover -s tests -v`

- [ ] **Step 5: Commit** integration and tests.

### Task 4: Deploy and perform the zero-risk connection check

**Files:**
- Create on VPS: `succhia-secrets.json` with restricted ACLs
- Modify on VPS: existing `gpt-thinking` deployment from the tested commit

**Interfaces:**
- Consumes: deployed HTTPS route, generated page token, generated MCP token.
- Produces: authenticated Android bridge and authenticated ChatGPT MCP tools.

- [ ] **Step 1: Generate separate random secrets** and install the tested files without printing secret values to logs.
- [ ] **Step 2: Restart the service and verify legacy health/MCP behavior.**
- [ ] **Step 3: Verify the page returns 401 without a page token and works with the token.**
- [ ] **Step 4: On the OPPO, connect `SOSEXY` and run only the manual 5/100 vibration, one-second test.**
- [ ] **Step 5: Verify Stop, disconnect, reconnect-at-zero, lease expiry, and authenticated MCP status.**
