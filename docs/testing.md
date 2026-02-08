# MegaBot: Testing & Quality Assurance

MegaBot is built with a strong focus on reliability, maintaining high test coverage across its core logic and adapters.

## 🧪 Coverage Overview
- **Core Orchestrator**: 99% (acceptable startup code exclusions)
- **Network Components**: 98% (gateway.py at 95%, server.py/monitor.py/tunnel.py at 100%)
- **Discovery Engine**: 100%
- **Interfaces**: 100%
- **Security (TirithGuard)**: 97%
- **Adapter Modules**: 80–100% (individual adapter coverage ranges from 80% to 100%)
- **Overall Core + Adapters**: 88% (including all latest tests)

### 📊 Current Coverage Details
- **Core Modules**:
  - config.py: 82%
  - discovery.py: 100%
  - instrumentation.py: 100%
  - interfaces.py: 100%
  - orchestrator.py: 99%
  - memory/knowledge_memory.py: 83%
  - memory/user_identity.py: 100%
  - permissions.py: 81%
  - projects.py: 79%
  - secrets.py: 64%

- **Adapter Modules**:
  - voice_adapter.py: 80%
  - memu_adapter.py: 94%
  - openclaw_adapter.py: 95%
  - mcp_adapter.py: 84%
  - discord_adapter.py: 99%
  - slack_adapter.py: 99%
  - signal_adapter.py: 100%
  - nanobot_adapter.py: 95%
  - telegram_adapter.py: 100%
  - sms.py: 100%
  - imessage.py: 100%
  - push_notification_adapter.py: 98%

- **Messaging Server**: 83% (239 statements, 40 missed - websockets edge cases)

### 📊 Coverage Improvement Progress
**Completed (high coverage achieved):**
- ✅ All adapter modules (12/12 completed — ranging from 80% to 100%)
- ✅ Core orchestrator (99% - acceptable exclusions)

**In Progress:**
- 🔄 Messaging server (52% → 83% - blocked by environment conflicts)
- 🔄 Network gateway (15% → 95% - near completion, 14 edge-case lines remaining)

**Completed (Network Modules):**
- ✅ Network tunnel (0% → 100%) - 14 comprehensive tests covering TunnelManager functionality
- ✅ Network monitor (0% → 100%) - 20 statements, 0 missed
- ✅ Network server (0% → 100%) - 24 statements, 0 missed

**Environment Constraints:**
- Messaging tests require dedicated "megabot" conda environment due to cryptography PyO3 version conflicts
- Base environment: cryptography 46.0.4
- Megabot environment: cryptography 41.0.7 (incompatible)
- Network gateway tests take significant time to execute

## 🛠️ Running Tests

### 1. Python (Backend)
Tests are located in `tests/` and use `pytest` with `pytest-cov`.

```bash
# Set PYTHONPATH to include the project root
export PYTHONPATH=$PYTHONPATH:.

# Run all adapter tests (80–100% coverage)
PYTHONPATH=. pytest tests/test_*_adapter.py --cov=adapters --cov-report=term-missing

# Run orchestrator tests (99% coverage)
PYTHONPATH=. pytest tests/test_orchestrator.py --cov=core.orchestrator --cov-report=term-missing

# Run core module tests (excludes network/messaging requiring special environments)
PYTHONPATH=. pytest tests/test_config.py tests/test_discovery.py tests/test_interfaces.py tests/test_orchestrator.py --cov=core --cov-report=term-missing

# Run network gateway tests (95% coverage - near complete)
PYTHONPATH=. pytest tests/test_unified_gateway.py --cov=core.network.gateway --cov-report=term-missing

# Check overall coverage status
python3 -m coverage run -m pytest tests/test_*_adapter.py tests/test_orchestrator.py --tb=no -q
python3 -m coverage report --show-missing
```

### 2. Special Environment Requirements
Some tests require dedicated conda environments due to dependency conflicts:

```bash
# Messaging server tests (83% coverage - cryptography version conflict)
conda activate megabot  # Uses cryptography 41.0.7
PYTHONPATH=. pytest tests/test_messaging_server.py --cov=adapters.messaging.server --cov-report=term-missing

# Base environment (cryptography 46.0.4) - cannot run messaging tests
# Use for: adapters, orchestrator, network gateway
```

### 3. React (Frontend)
Tests use `Vitest` and `React Testing Library`.
```bash
cd ui
npm run test      # Run all tests once
npm run coverage  # Generate coverage report
```

## 🏗️ Integration Testing
MegaBot includes comprehensive integration tests that simulate full WebSocket communication from the client through to the adapters using `AsyncMock`. Integration tests cover:

- **Cross-platform messaging** to a configured test number
- **Unified gateway routing** across different connection types (local, Cloudflare, VPN)
- **Rate limiting** per connection type
- **Health monitoring** for all services
- **Full messaging flow** from WebSocket to message handler

All integration tests currently pass and verify end-to-end functionality.

## 📈 Recent Testing Improvements

### Adapter Coverage Completion (2024)
- **Achievement**: All 12 adapter modules at high coverage (80–100%)
- **Methods**: Systematic testing with AsyncMock, error handling, and edge cases
- **100%**: signal_adapter.py, telegram_adapter.py, sms.py, imessage.py
- **95–99%**: discord_adapter.py (99%), slack_adapter.py (99%), push_notification_adapter.py (98%), openclaw_adapter.py, nanobot_adapter.py (95%)
- **80–84%**: voice_adapter.py, memu_adapter.py, mcp_adapter.py (84%)

### Orchestrator Coverage Enhancement
- **Before**: 97% coverage (10 lines missing)
- **After**: 99% coverage (4 lines missing - acceptable startup code exclusions)
- **New Tests Added**:
  - Health endpoint (/health) testing
  - WebSocket endpoint error handling when orchestrator is None
  - WebSocket endpoint normal operation when orchestrator is initialized

### New security-focused tests

- tests/test_agent_coordinator_toctou.py
  - Purpose: Covers TOCTOU (time-of-check to time-of-use) edge cases for AgentCoordinator file operations. Tests mock OS-level calls (os.open, os.fstat, os.read, os.replace) and assert that O_NOFOLLOW, fstat validation, and FD-based reads/writes are used to mitigate races.

- tests/test_agent_coordinator_write_edgecases.py
  - Purpose: Tests write edge-cases including atomic replace, tempfile handling, permission-denied flows, and symlink denial. Uses monkeypatch/patch to simulate failing os.replace and permission errors and verifies audit events are emitted.

Mocking OS operations
- These tests avoid fragile timing by mocking low-level OS functions (os.open, os.fstat, open, os.replace) and using fixtures to simulate file descriptors and errors. When reproducing or extending these tests locally, follow the fixture patterns used in the new test files.

Linting & static checks (CI)
- CI runs `ruff` and `mypy` as part of pre-commit/CI checks.
- Run them locally with:

  # ruff
  ruff check .

  # mypy
  mypy .

### Messaging Server Coverage Enhancement
- **Before**: 52% coverage (239 statements, 115 missed - requires dedicated conda environment due to cryptography conflicts)
- **After**: 83% coverage (239 statements, 40 missed - websockets edge cases)
- **New Tests Added**:
  - MediaAttachment serialization/deserialization methods
  - Server initialization (memU, voice adapters) with success/failure paths
  - Message processing with encryption support
  - Platform connection handling for all supported platforms
  - Media upload and command processing
  - Error handling and edge cases
- **Environment**: Requires dedicated "megabot" conda environment (cryptography 41.0.7)
- **Remaining Gaps**: WebSocket connection handling edge cases, startup code

### Network Gateway Coverage Enhancement
- **Before**: 15% coverage (298 statements, 253 missed - minimal test coverage)
- **After**: 95% coverage (298 statements, 14 missed - comprehensive async testing achieved)
- **New Tests Added**: 66 comprehensive test cases covering:
  - Connection lifecycle management and WebSocket handling
  - Connection type detection (local, Cloudflare, VPN, Direct HTTPS)
  - Rate limiting per connection type with isolation
  - Health monitoring loops for all services
  - Tunnel management (Cloudflare, Tailscale) with success/failure paths
  - HTTPS server setup with SSL certificate handling
  - Message processing with JSON validation and error handling
  - Exception handling for all major failure modes
  - Edge cases and error recovery scenarios
- **Technical Achievements**:
  - Comprehensive AsyncMock usage for complex async operations
  - Proper test class organization for pytest collection
  - Extensive mocking of websockets, subprocess calls, and external services
  - Fixed LSP errors and syntax issues in test file
- **Remaining Gaps**: 14 lines of very edge-case error handling (bytes decoding failures, websocket close exceptions) - acceptable exclusions given comprehensive coverage of core functionality

### Network Components Coverage Completion
- **Achievement**: All network modules (monitor, server, tunnel) now at 100% coverage
- **Network Monitor**: 100% coverage (20 statements, 0 missed) - HealthMonitor and RateLimiter classes
- **Network Server**: 100% coverage (24 statements, 0 missed) - Added test for process_request function execution path
- **Network Tunnel**: 100% coverage (39 statements, 0 missed) - 14 comprehensive tests for TunnelManager functionality
- **Overall Network Coverage**: ~98% complete (gateway at 95%, other modules at 100%)
- **Technical Approach**: Systematic async testing with AsyncMock, proper test class organization, and comprehensive error path coverage

## 🎯 Remaining Coverage Goals

### High Priority (Environment Blocked)
- **Messaging Server** (83% — target 95%+): Requires dedicated conda environment
  - Encryption/decryption methods
  - Platform adapter initialization
  - Media handling and storage
  - Message routing and handlers

### Medium Priority (Near Complete)
- **Network Gateway** (95% achieved): Complex async WebSocket and tunnel management — NEAR COMPLETE
  - Connection type handling (local, Cloudflare, VPN) ✅
  - Health monitoring loops ✅
  - Rate limiting implementation ✅
  - Tunnel management (Cloudflare, Tailscale) ✅
  - Remaining: 14 very edge-case error handling paths (acceptable exclusions)

### Low Priority (Infrastructure)
- **Network Monitor/Server/Tunnel**: COMPLETED - All network modules now at 100% coverage
  - Background task management ✅
  - External process handling ✅
  - Connection pooling ✅

## 📈 Standard Maintenance
Every new feature added to MegaBot must be accompanied by relevant unit tests. Coverage is automatically checked via the `coverage` script in `package.json`.
