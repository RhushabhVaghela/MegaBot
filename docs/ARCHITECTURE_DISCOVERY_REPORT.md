# MegaBot Architecture Discovery Report

**Date:** 2026-02-07
**Codebase Version:** `447302a` (Phase 8 — lint cleanup)
**Auditor:** Explorer Agent (claude-opus-4.6)
**Scope:** Full architectural audit of 54 production files, 84 test files (~44,629 LOC total)

---

## Executive Summary

MegaBot is a multi-platform AI bot orchestrator that routes conversations across Discord, Slack, WhatsApp, Telegram, Signal, iMessage, SMS, and custom WebSocket channels. It integrates LLM providers, memory systems, MCP tool servers, RAG indexing, push notifications, voice calls, and an autonomous "Loki Mode" build system.

**Overall Health Grade: C+** (see §6 for breakdown)

The codebase has undergone 8 refactoring phases since its initial audit, addressing some critical issues (dead imports, security hardening, lint cleanup). However, the **core architectural issues remain**: a 1,842-line God class, universal service locator coupling, and a DI container that exists but is largely bypassed. The adapter layer has two competing interface hierarchies with no unification path.

---

## §1. Import Dependency Graph

### 1.1 Top-Level Import Map

```
                           ┌─────────────────────────────────────────┐
                           │       core/orchestrator.py (1842L)      │
                           │           MegaBotOrchestrator            │
                           └───┬───┬───┬───┬───┬───┬───┬───┬───┬────┘
                               │   │   │   │   │   │   │   │   │
          ┌────────────────────┘   │   │   │   │   │   │   │   └──────────────────────┐
          │          ┌─────────────┘   │   │   │   │   │   └────────────────────┐      │
          │          │        ┌────────┘   │   │   │   └──────────────┐        │      │
          ▼          ▼        ▼            │   │   │                  ▼        ▼      ▼
   core/config   core/loki  core/         │   │   │          core/agents   core/   core/
      (281L)     (360L)   interfaces      │   │   │            (170L)    drivers  projects
                             (51L)        │   │   │                      (138L)   (...)
                               │          │   │   │
                               ▼          ▼   ▼   ▼
                     core/llm_providers  core/ core/ core/
                         (679L)        perms  secrets rag/pageindex
                           │                            (205L)
                           │
                           ▼
                    core/instrumentation

          ┌────────────────────────────────────────────────────────┐
          │              Extracted Components (all take `self`)     │
          │                                                        │
          │  orchestrator_components.py (413L)                      │
          │    ├─ MessageHandler    → self.orchestrator (10 refs)   │
          │    ├─ HealthMonitor     → self.orchestrator (8 refs)    │
          │    └─ BackgroundTasks   → self.orchestrator (12 refs)   │
          │  admin_handler.py (486L) → self.orchestrator (44 refs)  │
          │  message_router.py (223L)→ self.orchestrator (3 refs)   │
          │  agent_coordinator.py (589L)→self.orchestrator(16 refs) │
          │  loki.py (360L)          → self.orchestrator (13 refs)  │
          └────────────────────────────────────────────────────────┘
                               │
                               ▼
          ┌────────────────────────────────────────────────────────┐
          │                    Adapter Layer                        │
          │                                                        │
          │  Protocol-based (core/interfaces.py):                  │
          │    openclaw_adapter.py ──── MessagingInterface          │
          │    nanobot_adapter.py ───── MessagingInterface          │
          │    memu_adapter.py ──────── MemoryInterface             │
          │    mcp_adapter.py ────────── ToolInterface              │
          │    voice_adapter.py ──────── VoiceInterface             │
          │                                                        │
          │  Class-based (adapters/messaging/server.py):           │
          │    discord_adapter.py ───── PlatformAdapter             │
          │    slack_adapter.py ──────── PlatformAdapter            │
          │    whatsapp.py ──────────── PlatformAdapter             │
          │    telegram.py ──────────── PlatformAdapter             │
          │    imessage.py ──────────── PlatformAdapter             │
          │    sms.py ────────────────── PlatformAdapter            │
          │                                                        │
          │  Standalone (neither):                                 │
          │    signal_adapter.py ────── (own class hierarchy)       │
          │    push_notification_adapter.py ─ (own class hierarchy) │
          └────────────────────────────────────────────────────────┘
                               │
                               ▼
          ┌────────────────────────────────────────────────────────┐
          │                Infrastructure Layer                     │
          │                                                        │
          │  core/network/gateway.py (738L) ── UnifiedGateway      │
          │  adapters/messaging/server.py (472L) ── MessagingServer │
          │  adapters/security/tirith_guard.py ── TirithGuard      │
          │  core/memory/*.py ── Chat/Knowledge/Identity/Backup    │
          │  core/dependencies.py (180L) ── DI Container           │
          └────────────────────────────────────────────────────────┘
```

### 1.2 Runtime / Deferred Imports (Potential Circular Chains)

| Source File | Runtime Import | Location |
|---|---|---|
| `orchestrator.py` | `features.dash_data.agent.DashDataAgent` | line 268, 1401 |
| `loki.py` | `core.interfaces.Message` | line 100 |
| `loki.py` | `core.agents.SubAgent` | line 304 |
| `loki.py` | `adapters.security.tirith_guard.guard` | line 322 |
| `message_router.py` | `adapters.messaging.MediaAttachment, PlatformMessage, MessageType` | line 24 |
| `agent_coordinator.py` | `core.orchestrator._orch_mod` | line 80 |
| `gateway.py` | `adapters.unified_gateway` | line 303 |
| `gateway.py` | `aiohttp.web` | lines 410, 445 |

**Critical chain:** `orchestrator → agent_coordinator → core.orchestrator` (line 80) is a confirmed circular import resolved at runtime.

---

## §2. Coupling Analysis

### 2.1 Coupling Score by Module

Coupling Score = (direct imports from module) + (runtime `self.orchestrator.*` references) + (deferred imports targeting module)

| Module | Imported By | Imports Others | `self.orchestrator` Refs | Coupling Score | Rank |
|---|---|---|---|---|---|
| `core/orchestrator.py` | 20 test files + `core/__init__` + `agent_coordinator` (runtime) | 25 internal modules | N/A (is the orchestrator) | **48** | 🔴 #1 |
| `core/interfaces.py` | 8 modules (orchestrator, admin, message_router, orch_components, openclaw, nanobot, memu, voice) | 0 | 0 | **8** | #2 |
| `core/task_utils.py` | 5 modules (orchestrator, loki, admin, orch_components, message_router) | 0 | 0 | **5** | #3 |
| `adapters/messaging/server.py` | 6 modules (discord, slack, whatsapp, telegram, imessage, sms) + `__init__` | 0 internal | 0 | **7** | #4 |
| `core/admin_handler.py` | 1 (orchestrator) | 2 (interfaces, task_utils) | 44 | **47** | 🔴 #1t |
| `core/orchestrator_components.py` | 1 (orchestrator) | 4 (dependencies, interfaces, drivers, task_utils) | 30 | **35** | 🟠 #3 |
| `core/agent_coordinator.py` | 1 (orchestrator) | 1 (agents) | 16 | **18** | #4 |
| `core/loki.py` | 1 (orchestrator) | 2 (agents, task_utils) | 13 | **16** | #5 |
| `core/message_router.py` | 1 (orchestrator) | 2 (interfaces, task_utils) | 3 | **6** | #6 |

### 2.2 Coupling Patterns

**Hub-and-Spoke:** Every extracted component is coupled exclusively to the orchestrator. No component-to-component communication exists except through the orchestrator mediator.

```
admin_handler ─────┐
orch_components ───►│ orchestrator │◄─── loki
message_router ────►│  (hub)       │◄─── agent_coordinator
                    └──────────────┘
```

**Afferent Coupling (Ca)** — who depends on me:
- `core/interfaces.py`: Ca = 8 (most stable, correctly)
- `core/task_utils.py`: Ca = 5
- `core/orchestrator.py`: Ca = 22 (tests + core/__init__ + runtime)

**Efferent Coupling (Ce)** — who I depend on:
- `core/orchestrator.py`: Ce = 25 (imports everything)
- `core/admin_handler.py`: Ce = 2 + 44 runtime = 46

**Instability (I = Ce / (Ca + Ce)):**
- `core/interfaces.py`: I = 0.00 → Maximally stable ✅
- `core/orchestrator.py`: I = 25/47 = 0.53 → Should be lower for a hub
- `core/admin_handler.py`: I = 46/47 = 0.98 → Maximally unstable (expected for leaf)

---

## §3. Blast Radius Analysis

### 3.1 What Breaks If This File Changes

| File Changed | Direct Importers | Runtime Dependents | Test Files | Total Blast Radius | Risk |
|---|---|---|---|---|---|
| `core/orchestrator.py` | 1 (`core/__init__`) + 1 runtime (`agent_coordinator`) | ALL components via `self.orchestrator` (6 files) | 20+ test files | **28+** | 🔴 CRITICAL |
| `core/interfaces.py` | 8 modules | 0 | 5+ test files | **13** | 🟠 HIGH |
| `adapters/messaging/server.py` | 7 modules (`__init__` + 6 adapters) | `message_router.py` (runtime) | 10+ test files | **18** | 🟠 HIGH |
| `core/task_utils.py` | 5 modules | 0 | 3+ test files | **8** | 🟡 MEDIUM |
| `core/config.py` | 2 (`orchestrator`, `dependencies`) | All (via `self.orchestrator.config`) | 5+ test files | **14** | 🟠 HIGH |
| `core/dependencies.py` | 2 (`orchestrator`, `orch_components`) | 0 | 3+ test files | **5** | 🟡 MEDIUM |
| `core/llm_providers.py` | 1 (`orchestrator`) | All (via `self.orchestrator.llm`) | 5+ test files | **12** | 🟠 HIGH |
| `core/memory/mcp_server.py` | 1 (`orchestrator`) | All (via `self.orchestrator.memory`) | 8+ test files | **15** | 🟠 HIGH |
| `adapters/discord_adapter.py` | 0 (dynamically loaded) | `orchestrator` (via discovery) | 3 test files | **4** | 🟢 LOW |
| `core/agents.py` | 2 (`loki`, `agent_coordinator`) | 0 | 3+ test files | **5** | 🟡 MEDIUM |

### 3.2 Cascade Failure Scenarios

1. **`orchestrator.py` signature change** → All 6 extracted components break (they all access `self.orchestrator.*` attributes directly, not through interfaces). All 20+ test files likely need updating.

2. **`interfaces.py` Protocol change** → 8 adapter files need updating. However, since Python Protocols are structural, runtime won't break unless methods are called — this is a silent failure risk.

3. **`messaging/server.py` `PlatformAdapter` change** → 6 messaging adapters break. `message_router.py` breaks at runtime (deferred import). 10+ test files affected.

---

## §4. Adapter Consistency Matrix

| Adapter | Protocol | PlatformAdapter | `connect()` | `start()` | `shutdown()` | Mock Fallback | Lines | Lifecycle Consistent? |
|---|---|---|---|---|---|---|---|---|
| `OpenClawAdapter` | ✅ `MessagingInterface` | ❌ | ✅ | ❌ | ❌ | ❌ | 137 | ⚠️ No shutdown |
| `NanobotAdapter` | ✅ `MessagingInterface` | ❌ | ❌ | ❌ | ❌ | ❌ | 143 | ⚠️ No lifecycle |
| `MemUAdapter` | ✅ `MemoryInterface` | ❌ | ❌ | ❌ | ❌ | ❌ | 195 | ⚠️ No lifecycle |
| `MCPAdapter` | ✅ `ToolInterface` | ❌ | ❌ | ✅ | ❌ | ❌ | — | ⚠️ No shutdown |
| `MCPManager` | ❌ (wrapper) | ❌ | ❌ | ✅ (`start_all`) | ❌ | ❌ | — | ⚠️ No shutdown |
| `VoiceAdapter` | ✅ `VoiceInterface` | ❌ | ❌ | ❌ | ✅ | ❌ | 200 | ⚠️ No start |
| `DiscordAdapter` | ❌ | ✅ | ❌ | ❌ | ✅ | 🔴 `Mock, MagicMock` | 801 | ⚠️ |
| `SlackAdapter` | ❌ | ✅ | ❌ | ❌ | ✅ | 🔴 `MagicMock` | 560 | ⚠️ |
| `WhatsAppAdapter` | ❌ | ✅ | ❌ | ❌ | ✅ | ❌ | 964 | ✅ |
| `TelegramAdapter` | ❌ | ✅ | ❌ | ❌ | ✅ | ❌ | 271 | ✅ |
| `IMessageAdapter` | ❌ | ✅ | ❌ | ❌ | ✅ | ❌ | — | ✅ |
| `SMSAdapter` | ❌ | ✅ | ❌ | ❌ | ✅ | ❌ | — | ✅ |
| `SignalAdapter` | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ | 1059 | ⚠️ Standalone |
| `PushNotificationAdapter` | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | 1226 | 🔴 No lifecycle |
| `UnifiedGateway` | ❌ | ❌ | ❌ | ✅ | ✅ | ❌ | 738 | ✅ |
| `MegaBotMessagingServer` | ❌ | ❌ | ❌ | ✅ | ✅ | ❌ | 472 | ✅ |

### Key Inconsistencies

1. **Two interface hierarchies** — Protocol-based (`interfaces.py`) vs. class-based (`PlatformAdapter`). No adapter implements both. No unification path exists.
2. **No standard lifecycle** — Some have `start()`, some `connect()`, some neither. `shutdown()` exists in 11/16 but is absent in 5.
3. **Mock pollution** — Discord and Slack adapters import `unittest.mock` at module level for production fallback when SDK packages are missing.
4. **SignalAdapter is orphaned** — Implements neither Protocol nor PlatformAdapter. Has its own 8-class type hierarchy (212 lines of dataclasses).
5. **PushNotificationAdapter has no lifecycle** — 1,226 lines with no `start()`, `connect()`, or `shutdown()` method.

---

## §5. Technical Debt Inventory

### P0 — Critical (Address Before Next Feature)

| # | Issue | Location | Impact | Fix | Effort |
|---|---|---|---|---|---|
| P0-1 | **God Class** — `MegaBotOrchestrator` is 1,842 lines with 30+ methods, FastAPI routes, CORS, lifespan, and `uvicorn.run` all in one file | `core/orchestrator.py` | Untestable in isolation, every change is high-risk, merge conflicts | Extract FastAPI app to `core/app.py`, extract routes to `core/routes.py`, move background tasks out | 3-5 days |
| P0-2 | **Service Locator** — 106 `self.orchestrator.*` references across 6 files provide implicit coupling with zero compile-time safety | `admin_handler`, `orch_components`, `loki`, `agent_coordinator`, `message_router` | Can't test components without full orchestrator mock, can't refactor orchestrator without breaking all | Inject specific dependencies (`memory`, `llm`, `adapters`) instead of whole orchestrator | 3-5 days |
| P0-3 | **Mock Detection in Production** — 4 locations check for `"Mock" in cls_name` at runtime, adding ~80 lines of defensive code | `orchestrator.py:443,1665`, `gateway.py:146,228` | Production code aware of test infrastructure, fragile to mock library changes, performance overhead | Use proper DI/interface contracts; tests should inject real or fake implementations, not `Mock()` | 2-3 days |

### P1 — High (Address Within Next Sprint)

| # | Issue | Location | Impact | Fix | Effort |
|---|---|---|---|---|---|
| P1-1 | **Mock Imports in Production** — `unittest.mock.MagicMock` imported at module level as fallback when SDK missing | `discord_adapter.py:22,29`, `slack_adapter.py:21` | `unittest.mock` loaded in production, objects won't behave like real APIs, silent failures | Create proper stub/null-object classes for missing SDKs | 1 day |
| P1-2 | **DI Container Bypassed** — `core/dependencies.py` has full DI (inject decorator, scopes, factories) but only `resolve_service()` is used in 7 places; `inject()` decorator unused | `orchestrator.py:223-256`, `orch_components.py:99` | Two systems: DI for some services, service locator for components. Inconsistent, confusing | Migrate all component construction to use DI container | 2-3 days |
| P1-3 | **Dual Interface Hierarchy** — Protocol-based interfaces and class-based `PlatformAdapter` coexist with no bridge | `core/interfaces.py`, `adapters/messaging/server.py` | Can't polymorphically treat all adapters the same; `SignalAdapter` and `PushNotificationAdapter` implement neither | Unify under Protocol-based interfaces; make `PlatformAdapter` implement `MessagingInterface` | 2-3 days |
| P1-4 | **Circular Import Chain** — `orchestrator → agent_coordinator → core.orchestrator` (runtime import at line 80) | `agent_coordinator.py:80` | Fragile import ordering, potential `ImportError` on refactor | Break cycle by injecting `SubAgent` class via DI rather than importing orchestrator module | 1 day |

### P2 — Medium (Address Within Next Quarter)

| # | Issue | Location | Impact | Fix | Effort |
|---|---|---|---|---|---|
| P2-1 | **Magic Numbers** — 14+ hardcoded numeric literals control critical system behavior | Throughout `orchestrator.py`, `agent_coordinator.py` | Behavior undiscoverable, can't configure per-environment, easy to introduce inconsistency | Move to `Config` model or module-level named constants | 1 day |
| P2-2 | **NotImplementedError Stubs** — 6 methods raise `NotImplementedError` in production code | `voice_adapter.py:156-193`, `nanobot_adapter.py:130-132`, `loki.py:355-357`, `drivers.py:96-98` | Runtime crashes if called, no compile-time warning, false sense of completeness | Either implement or remove from interface; add `@abstractmethod` if intentionally deferred | 1-2 days |
| P2-3 | **SignalAdapter Orphaned** — 1,059 lines with own 8-class type hierarchy, doesn't extend any base | `adapters/signal_adapter.py` | Can't route messages through unified pipeline, needs special-case handling | Align with `PlatformAdapter` or `MessagingInterface` Protocol | 2 days |
| P2-4 | **PushNotificationAdapter No Lifecycle** — 1,226 lines, no `start()`/`shutdown()` | `adapters/push_notification_adapter.py` | Can't gracefully start/stop, no health monitoring integration | Add standard lifecycle methods | 0.5 days |
| P2-5 | **`sys.path` Manipulation** — Adapters modify `sys.path` to find external packages | `memu_adapter.py`, `nanobot_adapter.py` | Fragile path resolution, breaks if directory structure changes | Use proper package installation or `importlib` | 0.5 days |

### P3 — Low (Nice to Have)

| # | Issue | Location | Impact | Fix | Effort |
|---|---|---|---|---|---|
| P3-1 | **No TODO/FIXME/HACK Comments** — Zero instances across 44K+ lines | Entire codebase | Known limitations are undocumented, team loses institutional knowledge of incomplete work | Add `# TODO:` comments for known stubs, deferred features, workarounds | Ongoing |
| P3-2 | **Re-export Shims** — `adapters/unified_gateway.py` (11L) and `adapters/__init__.py` exist only to re-export from other modules | `adapters/unified_gateway.py`, `adapters/__init__.py` | Import path confusion, two valid paths to same class | Consolidate to single canonical import path | 0.5 days |
| P3-3 | **Deferred `uuid` Imports** — `import uuid` appears inside methods in 4 locations rather than at module level | `orchestrator.py:797,1123,1216,1542` | Micro-performance hit on each call, inconsistent with stdlib import conventions | Move to module-level imports | 15 min |
| P3-4 | **84 Test Files for 54 Production Files** — 1.56:1 test-to-production file ratio may indicate test fragmentation | `tests/` | Hard to find the right test file, risk of duplicate test coverage | Consolidate tests to mirror production file structure | 1-2 days |

---

## §6. Architecture Health Score

### Scoring Rubric

Each dimension scored 0-100, then letter-graded:
- **A** (90-100): Industry best practice
- **B** (75-89): Good, minor issues
- **C** (60-74): Acceptable, notable issues
- **D** (40-59): Below standard, significant issues
- **F** (<40): Critical, needs immediate attention

### Dimension Scores

| Dimension | Score | Grade | Weight | Rationale |
|---|---|---|---|---|
| **Modularity** | 40 | D | 20% | God class (1,842L), FastAPI app/routes/server all in one file, monolithic entry point. Extracted components exist but are tightly coupled back. |
| **Coupling** | 35 | F | 20% | 106 `self.orchestrator.*` references create implicit coupling. All roads go through one object. Hub-and-spoke with no interface contracts between components. |
| **Interface Consistency** | 45 | D | 15% | Two competing hierarchies (Protocol vs. PlatformAdapter), two standalone adapters fitting neither, inconsistent lifecycle methods across adapters. |
| **Testability** | 55 | D+ | 15% | 84 test files exist (good coverage intent), but mock pollution and service locator pattern mean tests must mock the entire orchestrator. No component can be tested with real dependencies in isolation. |
| **Security** | 75 | B | 15% | TirithGuard provides ANSI/homoglyph/injection protection. Phases 1-8 addressed exec sandbox, shell injection, crypto hardening, CORS, TOCTOU. Fernet encryption for WebSocket. Some mock-detection code is a defense-in-depth concern. |
| **Code Organization** | 60 | C | 15% | Clear directory structure (`core/`, `adapters/`, `features/`, `tests/`). DI container exists but is underused. Config is Pydantic-based (good). Dead imports cleaned in Phase 8. But 14+ magic numbers, re-export shims, `sys.path` hacks. |

### Weighted Overall Score

```
Overall = (40 × 0.20) + (35 × 0.20) + (45 × 0.15) + (55 × 0.15) + (75 × 0.15) + (60 × 0.15)
        = 8.0 + 7.0 + 6.75 + 8.25 + 11.25 + 9.0
        = 50.25 → D+
```

### Adjusted Score (Post-Refactoring Credit)

The 8 refactoring phases demonstrate active improvement momentum. Adjusting for:
- Phase 1: Security hardening (+3)
- Phase 3: Dead code removal (+2)
- Phase 8: 111 unused imports removed (+2)
- Active test suite of 84 files (+3)

**Adjusted Score: 60.25 → C+** (reflecting trajectory, not just current state)

---

## §7. Recommended Refactoring Sequence

Based on blast radius and dependency analysis, the optimal refactoring order is:

```
Phase A: Extract FastAPI app/routes from orchestrator.py
    └── Reduces orchestrator from 1842→~1200 lines
    └── Zero blast radius (routes are module-level, not imported)
    └── Effort: 1-2 days

Phase B: Define component interfaces (what each component needs from orchestrator)
    └── Create typed Protocol for OrchestratorServices
    └── Each component declares its dependency surface
    └── Effort: 1 day

Phase C: Wire components through DI instead of service locator
    └── Use existing DependencyContainer
    └── Replace `self.orchestrator` with specific injected services
    └── Effort: 2-3 days

Phase D: Unify adapter interfaces
    └── Make PlatformAdapter implement MessagingInterface
    └── Add standard lifecycle Protocol (start/shutdown)
    └── Migrate SignalAdapter and PushNotificationAdapter
    └── Effort: 2-3 days

Phase E: Eliminate mock pollution
    └── Create proper null-object stubs for missing SDKs
    └── Remove all `unittest.mock` imports from production
    └── Remove mock-detection code from orchestrator/gateway
    └── Effort: 1-2 days
```

**Total estimated effort: 7-11 days for a single developer.**

---

## Appendix A: File Size Distribution

```
Lines   Files  Description
──────  ─────  ─────────────
>1000     3    orchestrator.py, push_notification_adapter.py, signal_adapter.py
500-999   5    whatsapp.py, discord_adapter.py, gateway.py, llm_providers.py, agent_coordinator.py
200-499   8    slack_adapter, admin_handler, messaging/server, orch_components, loki, dash_data/agent, config, knowledge_memory
100-199   8    telegram, message_router, chat_memory, rag/pageindex, voice_adapter, memu_adapter, dependencies, agents
<100     10    Various small modules, __init__.py files, shims
──────  ─────
Total    54    production files = 14,663 lines
               84 test files    = ~29,966 lines
               Grand total      = ~44,629 lines
```

## Appendix B: Key Constants & Magic Numbers Registry

| Value | Meaning | Location(s) | Should Be |
|---|---|---|---|
| `18790` | Messaging server port | `orchestrator.py:287,290` | `Config.messaging_port` |
| `8000` | Uvicorn HTTP port | `orchestrator.py:1842` | `Config.system.http_port` |
| `60` | Heartbeat interval (sec) | `orchestrator.py:545` | `Config.intervals.heartbeat` |
| `300` | Approval escalation timeout | `orchestrator.py:717` | `Config.timeouts.approval` |
| `3600` | Proactive/sync loop interval | `orchestrator.py:640,1482` | `Config.intervals.proactive` |
| `43200` | Backup interval (12h) | `orchestrator.py:595` | `Config.intervals.backup` |
| `86400` | Pruning interval (24h) | `orchestrator.py:608` | `Config.intervals.pruning` |
| `500` | Max chat history | `orchestrator.py:604-605` | `Config.limits.max_chat_history` |
| `1048576` | READ_LIMIT 1MB | `agent_coordinator.py:48` | `Config.limits.read_file_max` |
| `10` | Max autonomous build steps | `orchestrator.py:959` | `Config.limits.max_build_steps` |
| `22`, `7` | DND hours start/end | `orchestrator.py:727` | `Config.system.dnd_start/end` |
| `30` | Subprocess timeout | `orchestrator.py:1348` | `Config.timeouts.subprocess` |
| `10` | Auth timeout (gateway) | `gateway.py:49` | `Config.timeouts.auth` |
| `1024×768` | Display resolution | `orchestrator.py:918-919` | `Config.display.*` |

---

*End of Architecture Discovery Report*
