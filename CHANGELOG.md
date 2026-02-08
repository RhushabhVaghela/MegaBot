## v1.2.0 (2026-02-08)

Full production readiness audit and fixes across 5 sessions.

### Logging & Observability (Phase 6B-1)

- Replaced ~252 `print()` calls with structured `logger` across 29 production files (16 core + 12 adapters + 1 coordinator).
- Logger naming convention: `logging.getLogger("megabot.<module>")` or `logging.getLogger(__name__)`.
- Only 6 `print()` remain in acceptable `if __name__ == "__main__"` blocks.

### Exception Handling (Phase 6B-2)

- Fixed 69 silent `except ...: pass` blocks across 19 files.
- Added appropriate logging: `logger.debug()` for expected failures (cleanup, shutdown, CancelledError), `logger.warning()` for unexpected non-critical, `logger.error()` for potential data loss.
- Split `except (CancelledError, Exception): pass` into separate clauses where appropriate.

### Security (Phase 6B-3)

- **Secrets directory permissions**: Added world-readable directory warning and secret name length limit (128 chars) in `core/secrets.py`.
- **MCP JSON-RPC IDs**: Replaced static `"id": 1` with incrementing counter in `adapters/mcp_adapter.py`.
- **Telegram file handle leak**: Refactored `_upload_media()` to guarantee `close()` in `finally` block.
- **Atomic file writes**: Admin handler `file_operation` write now uses `tempfile.mkstemp()` + `os.replace()` with cleanup on failure.

### Code Quality (Phase 6B-4)

- Removed misleading `# ... (rest of building logic) ...` comment in `core/rag/pageindex.py`.
- Consolidated duplicate `Dummy` classes in `adapters/memu_adapter.py` into `_make_dummy_service()` static method.

### Professional Cleanup (Phase 6B-5)

- Deleted 8 stale `features/` README files, empty `audits/` directory, build artifacts (`htmlcov/`, `megabot.egg-info/`, `.ruff_cache/`, `megabot_memory.db`).
- Deleted 2 duplicate architecture docs (canonical version: `docs/architecture/overview.md`).
- Deleted 7 stale audit/planning docs from `docs/`.
- Fixed PII leak: replaced real phone number in `docs/testing.md`.
- Fixed typos in `docs/troubleshooting.md` (conda env name, config filename).

### Documentation (Phase 6B-6)

- Fixed Python version `3.13` to `3.12+` in `docs/platforms.md`.
- Fixed 4 broken relative links in `docs/development/index.md`.
- Updated `docs/index.md`: removed broken link, updated last-updated date.

### Runtime Bug Fix

- Fixed `NameError` in `core/network/gateway.py`: bare `logger` replaced with `self.logger` on 3 lines.

### Testing (Phase 6B-7)

- 17 new tests covering all Phase 6 security and code quality changes.
- **1714 tests passing, 0 failures** (verified 2026-02-08).

---

## v1.1.0 (2026-02-07)

Comprehensive hardening, cleanup, and documentation overhaul across 17 sessions.

### Bug Fixes (Phase 1 — Sessions 1-5)

- **Serialization crash**: Added `sanitize_action()`/`sanitize_queue()` in `core/task_utils.py` to handle non-serializable objects.
- **Blocking I/O**: Wrapped synchronous file operations in `core/memory/backup_manager.py` with `asyncio.to_thread()`.
- **Deprecated asyncio**: Replaced 13 occurrences of `asyncio.get_event_loop()` with `asyncio.get_running_loop()` in `adapters/slack_adapter.py` and `adapters/voice_adapter.py`.
- **Test failures**: Fixed pre-existing bugs in `test_mcp_server.py`, `test_megabot_messaging.py`, `test_messaging_sms.py`, `test_messaging_telegram.py`, `test_orchestrator.py`, `test_user_identity.py`, and 5 escalation tests.

### Code Quality (Phase 1 — Sessions 1-5)

- **Orchestrator decomposition**: Extracted file operations to `core/agent_file_ops.py` (358 lines), reducing `agent_coordinator.py` from 589 to 254 lines.
- **Test consolidation**: Merged 5 large coverage test files into proper per-module test files, deleted originals.
- **Cleanup**: Removed stale artifacts (`.coverage`, `.megabot_index.json`, `megabot_memory.db`, audit reports, `.mypy_cache/`, `.ruff_cache/`, empty `adapters/channels/`).

### Resource Management (Phase 2 — Sessions 9-12)

- **ResourceGuard**: New `core/resource_guard.py` with `ResourceSnapshot`, `get_resource_status()`, `can_allocate()`, `LRUCache`, and `ResourceGuard` class. 59 tests.
- **LRU cache capping**: Replaced 10 unbounded dicts with `LRUCache` across 8 adapter files (Discord, Slack, Signal, OpenClaw, Push Notification, WhatsApp, memU, DashData).
- **ResourceGuard integration**: Wired into orchestrator init/start/stop/health_dict.
- **RuntimeWarning fixes**: Fixed coroutine leak in `core/lifecycle.py` health monitor startup.

### Graceful Degradation (Phase 3A — Session 13)

- Replaced 6 `NotImplementedError` stubs with graceful degradation in `core/drivers.py`, `core/loki.py`, `adapters/voice_adapter.py`, `adapters/nanobot_adapter.py`.

### Incomplete Implementations (Phase 3B — Session 14)

- Fixed Discord `download_media()` — now uses real aiohttp download.
- Fixed Slack `download_media()` — now uses Slack API with auth headers.
- Fixed Slack `_setup_event_handlers()` — registers message/reaction handlers.
- Fixed orchestrator audio transcription — uses OpenAI Whisper API.

### Security (Phase 3C — Session 14)

- **TwiML XML injection**: Escaped user input in `adapters/voice_adapter.py`.
- **Token leak**: Masked Twilio auth token in error logs.
- **WebSocket security**: Changed `ws://` to `wss://` in production URLs.
- **Twilio webhook verification**: Added `X-Twilio-Signature` validation.
- **Firebase import**: Made `firebase_admin` import conditional.
- **WebSocket error logging**: Sanitized error messages.
- **exec() sandbox**: Added timeout and output cap to `DashDataAgent`.
- **Homoglyph detection**: Rewrote to only flag mixed-script (Latin + Cyrillic/Greek), not all non-ASCII.

### Hardcoded Values (Phase 3D — Session 15)

- Added `port: int = 8000` to `SystemConfig` with `MEGABOT_PORT` env var.
- Made uvicorn use `config.system.port` instead of hardcoded 8000.
- Extracted WhatsApp Graph API version to class constants.
- Made memU Ollama URL configurable via `OLLAMA_URL` env var.
- Fixed stale OpenRouter referer URL.
- Replaced placeholder tokens in `__main__` blocks with `os.environ` reads.

### Documentation (Phase 4 — Sessions 16-17)

- Fixed `your-org/megabot` → `RhushabhVaghela/MegaBot` in docs.
- Fixed `localhost:3000` → `localhost:8000` across 10 documentation files.
- Fixed WebSocket URLs in `docs/api/websocket.md`.
- Updated `mega-config.yaml.template` with new fields (`port`, `messaging_host`, `messaging_port`, `dnd_start`, `dnd_end`).
- Fixed `from megabot.*` import paths → `from core.*` / `from adapters.*` (16 occurrences).
- Annotated `docs/deployment/configuration.md` — marked implemented vs planned config sections.
- Fixed CORS origin `localhost:3000` → `localhost:5173` in cross-domain analysis doc.
- Removed references to deleted test files.
- Updated CHANGELOG with all session work.

### Testing

- **1648 tests passing, 0 failures, 0 warnings** (verified Session 15).

---

## v1.0.0 (2026-02-06)

Production-ready release of MegaBot — the unified AI orchestrator.

### Highlights
- **1373 tests passing** with **~96% overall coverage** across core, adapters, and features.
- **Security hardening** (AGC-001/002/003): pre-flight sub-agent validation, strict boolean permission checks, workspace-confined filesystem tools with symlink denial, size limits, and atomic writes.
- **CI pipeline** (CI-001): automated lint (ruff), type checks (mypy), and full pytest suite.
- **Audit logging** (AUD-001): critical AgentCoordinator events emitted to `megabot.audit`.
- **UI layer**: Vite 7 + React 19 + Tailwind CSS 4 frontend with Vitest + React Testing Library.
- **Feature modules**: DashDataAgent for CSV/JSON analysis, integrated project documentation (Tirith, memU, OpenClaw, Nanobot, PageIndex, Agent Lightning, Agent Zero).
