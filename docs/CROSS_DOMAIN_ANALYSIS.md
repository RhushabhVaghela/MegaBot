# MegaBot Cross-Domain Analysis Report

**Date:** 2026-02-06
**Scope:** Full cross-cutting concern analysis across Security, Backend, Frontend, Testing, DevOps, and Performance domains
**Methodology:** Multi-agent orchestrated analysis with manual verification of all findings

---

## Executive Summary

MegaBot demonstrates strong foundational security design — parameterized SQL queries, permission gating at the orchestrator layer, TOCTOU-hardened file operations, and robust input sanitization via Tirith Guard. Recent commits have addressed several risks (symlink attacks, audit logging, CI linting).

However, **critical gaps exist at domain boundaries** — the seams where security meets networking, where documentation meets code, and where adapters meet the permission system. These cross-cutting issues are invisible to single-domain audits and represent the highest-risk attack surface.

### Risk Posture: MODERATE-HIGH

| Severity | Count | Status |
|----------|-------|--------|
| **CRITICAL** | 2 | Open |
| **HIGH** | 4 | Open |
| **MEDIUM** | 5 | Open (1 partially mitigated) |
| **LOW** | 3 | Open |

---

## Finding 1: Unauthenticated WebSocket — No Auth on Primary Control Channel

**Severity: 🔴 CRITICAL**
**Domains: Frontend × Backend × Security**

### Description

The WebSocket endpoint at `/ws` (`core/orchestrator.py:1884`) accepts connections with **zero authentication**. The React UI (`ui/src/App.tsx`) connects to `ws://127.0.0.1:8000/ws` without sending any token, cookie, or credential. Once connected, a client can:

- Execute arbitrary commands: `{type: 'command', command: '...'}`
- Change system operating mode: `{type: 'set_mode', mode: '...'}`
- Access all message history and memory systems

### Evidence

```
# orchestrator.py:1884
@app.websocket("/ws")  # pragma: no cover
```

```javascript
// ui/src/App.tsx — connection with no auth
const ws = new WebSocket('ws://127.0.0.1:8000/ws');
ws.send(JSON.stringify({ type: 'command', command: terminalInput }));
ws.send(JSON.stringify({ type: 'set_mode', mode: newMode }));
```

### Impact

Any process on the local machine (or any machine on the network if bound to `0.0.0.0`) can connect and control MegaBot with full privileges. Combined with Finding 2 (no CORS), a malicious webpage could establish a WebSocket connection from a user's browser.

### Remediation

1. **Immediate:** Add token-based auth to WebSocket handshake — validate a Bearer token in the first message or via query parameter (`ws://host/ws?token=...`)
2. **Short-term:** Bind to `127.0.0.1` only (verify this is enforced)
3. **Medium-term:** Implement session-based auth with expiring tokens

---

## Finding 2: No CORS Middleware on FastAPI Application

**Severity: 🔴 CRITICAL**
**Domains: Frontend × Backend × Security**

### Description

The FastAPI application in `core/orchestrator.py` has **no CORS middleware configured**. A search for `CORSMiddleware` and `add_middleware` across the entire Python codebase returns zero matches.

### Evidence

```bash
$ grep -rn "CORSMiddleware\|add_middleware" core/ adapters/
# (no output)
```

### Impact

Without CORS restrictions:
- Any website can make cross-origin requests to MegaBot's HTTP endpoints (`/`, `/health`, `/ivr`)
- Combined with the unauthenticated WebSocket (Finding 1), a malicious page visited in any browser on the same machine could exfiltrate data or execute commands
- The `/ivr` POST endpoint (`orchestrator.py:1835`) processes voice/IVR payloads with no origin validation

### Remediation

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # UI origin only
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization"],
    allow_credentials=True,
)
```

---

## Finding 3: Adapter-Layer Permission Bypass

**Severity: 🟠 HIGH**
**Domains: Security × Backend**

### Description

The `PermissionManager` (`core/permissions.py`) enforces action authorization at the orchestrator and agent coordinator layers. However, **no adapter performs its own `is_authorized()` check**. If an adapter is accessed directly (bypassing the orchestrator), all permission gating is skipped.

### Evidence

Permission checks exist in:
| File | Line | Check |
|------|------|-------|
| `core/orchestrator.py` | 1305, 1312, 1316 | `permissions.is_authorized()` in `_check_policy` |
| `core/agent_coordinator.py` | 243 | Tool execution gating |
| `core/message_router.py` | 113 | `vision.outbound` check |
| `features/dash_data/agent.py` | 122 | `data.execute` check |

Permission checks are **absent** in all adapters:
- `adapters/messaging/server.py` — WebSocket/HTTP messaging server
- `adapters/messaging/whatsapp.py` — only a comment at line 622
- All platform adapters (Discord, Telegram, Slack, Signal, Voice, MCP, Nanobot, OpenClaw)

### Impact

If any adapter exposes a direct interface (e.g., the messaging server's WebSocket), commands bypass permission checks entirely. The security model assumes all paths route through the orchestrator — a single misconfiguration breaks the entire permission system.

### Remediation

1. **Defense in depth:** Add `is_authorized()` checks at the adapter layer as a secondary enforcement point
2. **Architecture:** Consider a middleware/decorator pattern that wraps all inbound message handlers with permission verification
3. **Document:** If adapters are intentionally permission-free (relying on orchestrator), document this as an architectural decision with the associated risk acceptance

---

## Finding 4: Phantom API Documentation — 15 Documented Endpoints, Only 4 Exist

**Severity: 🟠 HIGH**
**Domains: Documentation × Backend**

### Description

`docs/api/index.md` documents approximately 15 RESTful API endpoints with detailed request/response schemas, authentication headers (`Authorization: Bearer <token>`), and rate limiting headers (`X-RateLimit-*`). **Only 4 endpoints exist in code.**

### Evidence

**Documented but non-existent endpoints:**
- `POST /api/v1/messages/send`
- `GET /api/v1/messages/history/{chat_id}`
- `POST /api/v1/messages/broadcast`
- `GET /api/v1/memory/stats`
- `POST /api/v1/memory/search`
- `POST /api/v1/memory/backup`
- `GET /api/v1/config`
- `PUT /api/v1/config`
- `GET /api/v1/security/approvals`
- `POST /api/v1/security/approve/{id}`
- `POST /api/v1/security/deny/{id}`
- `GET /api/v1/security/policies`
- `POST /api/v1/security/policies`
- `GET /status`

**Actually implemented endpoints:**
```
orchestrator.py:1835  @app.post("/ivr")
orchestrator.py:1864  @app.get("/")
orchestrator.py:1877  @app.get("/health")
orchestrator.py:1884  @app.websocket("/ws")
```

### Impact

- Developers and integrators will build against APIs that don't exist
- The documented `Authorization: Bearer <token>` creates a false sense of security — auth is not implemented
- Documented rate limiting headers don't exist, masking the absence of HTTP rate limiting

### Remediation

1. **Option A:** Remove phantom documentation and document only the 4 real endpoints
2. **Option B:** Implement the documented endpoints (significant effort, but valuable for external integrations)
3. **Either way:** Add a "Documentation Status" badge indicating which endpoints are implemented vs. planned

---

## Finding 5: Security-Critical Code Excluded from Test Coverage

**Severity: 🟠 HIGH**
**Domains: Testing × Security**

### Description

The `_check_policy` method (`orchestrator.py:1293`) — the core security enforcement function that decides whether to allow, deny, or queue actions — is entirely marked with `# pragma: no cover`. This means the most security-critical code path is **explicitly excluded from coverage metrics**.

### Evidence

```
orchestrator.py:1293  def _check_policy(self, data: Dict):  # pragma: no cover
orchestrator.py:1305      auth = self.permissions.is_authorized(s)  # pragma: no cover
orchestrator.py:1312      auth = self.permissions.is_authorized(s)  # pragma: no cover
orchestrator.py:1316  auth = self.permissions.is_authorized(scope)  # pragma: no cover
orchestrator.py:1348      policy = self._check_policy(data)  # pragma: no cover
orchestrator.py:1350      if policy == "allow":  # pragma: no cover
orchestrator.py:1355      if policy == "deny":  # pragma: no cover
```

### Impact

- Coverage reports show artificially high numbers while the most critical security path is untested
- Regressions in permission enforcement will go undetected
- The `_check_policy → is_authorized` chain is the **single point of enforcement** for the entire system (per Finding 3)

### Remediation

1. Remove `# pragma: no cover` from all security-critical methods
2. Write integration tests that exercise the full `_check_policy` → `is_authorized` → action chain
3. Add a CI rule: `# pragma: no cover` must not appear in files matching `**/security/**` or methods containing `policy`, `permission`, `auth`

---

## Finding 6: Unsanitized Filename in Media Storage — Path Traversal Risk

**Severity: 🟠 HIGH**
**Domains: Security × Backend**

### Description

The `_save_media` method in `adapters/messaging/server.py` constructs file paths using a user-controlled `attachment.filename` without sanitization.

### Evidence

```python
# adapters/messaging/server.py:418-421
async def _save_media(self, attachment: MediaAttachment) -> str:
    file_hash = hashlib.sha256(attachment.data).hexdigest()[:16]
    filepath = os.path.join(
        self.media_storage_path, f"{file_hash}_{attachment.filename}"
    )
```

A malicious filename like `../../etc/cron.d/backdoor` would produce:
```
os.path.join("/media", "abc123_../../etc/cron.d/backdoor")
→ "/media/abc123_../../etc/cron.d/backdoor"
→ resolves to "/etc/cron.d/backdoor"
```

### Impact

An attacker who can send media attachments (via any messaging platform) can write files to arbitrary locations on disk, limited only by process permissions.

### Remediation

```python
import os
from pathlib import Path

safe_name = os.path.basename(attachment.filename)  # Strip directory components
safe_name = "".join(c for c in safe_name if c.isalnum() or c in ".-_")  # Whitelist chars
filepath = Path(self.media_storage_path) / f"{file_hash}_{safe_name}"

# Verify resolved path is within media directory
if not filepath.resolve().is_relative_to(Path(self.media_storage_path).resolve()):
    raise ValueError("Path traversal detected in filename")
```

---

## Finding 7: No Adversarial Security Tests

**Severity: 🟡 MEDIUM**
**Domains: Testing × Security**

### Description

While unit tests exist for `PermissionManager` (`tests/test_permissions.py`, 78 lines) and Tirith Guard sanitization, there are **no adversarial tests** that submit actual attack payloads.

### Missing Test Categories

| Attack Vector | Defensive Code Exists | Adversarial Test Exists |
|--------------|----------------------|------------------------|
| SQL Injection | ✅ Parameterized queries + ORDER BY whitelist (`knowledge_memory.py:157`) | ❌ No |
| Path Traversal | ✅ `_validate_path` + TOCTOU hardening (`agent_coordinator.py:254`) | ✅ Partial (TOCTOU/symlink tests added recently) |
| XSS via WebSocket | ❌ No output encoding | ❌ No |
| Unicode/Homoglyph | ✅ Tirith Guard | ✅ Yes (`test_tirith_guard.py`) |
| Command Injection | ✅ Shell prefix matching in permissions | ❌ No payload tests |

### Remediation

1. Add a `tests/test_security_adversarial.py` with payloads for each vector
2. Consider property-based testing with Hypothesis for fuzzing input boundaries
3. Add CI step: `pytest tests/test_security_adversarial.py -v`

---

## Finding 8: Docker Compose Default Credentials

**Severity: 🟡 MEDIUM**
**Domains: DevOps × Security**

### Description

`docker-compose.yaml` uses environment variable fallbacks with default passwords:

```yaml
# docker-compose.yaml:23
DATABASE_URL: postgresql://megabot:${POSTGRES_PASSWORD:-megabot_secure_password}@postgres:5432/megabot

# docker-compose.yaml:28
POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-megabot_secure_password}
```

### Impact

If deployed without setting `POSTGRES_PASSWORD`, the database uses a predictable password. While the default has been improved from `megabot_dev_password` to `megabot_secure_password`, any static default is insecure for production.

### Remediation

1. Remove default values: `POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?POSTGRES_PASSWORD must be set}`
2. Add a `.env.example` file with placeholder values
3. Add a startup check script that validates all required secrets are set

---

## Finding 9: Benchmarks Not Integrated into CI

**Severity: 🟡 MEDIUM**
**Domains: Performance × Testing × DevOps**

### Description

Three benchmark files exist (`tests/benchmarking.py`, `tests/benchmarks.py`, `tests/benchmark_tirith.py`) but **none are referenced in CI workflows**. A `grep -rn "benchmark\|perf" .github/workflows/` returns zero matches.

### Impact

- Performance regressions go undetected until production
- No baseline metrics exist for comparison
- Tirith Guard sanitization performance (critical for message throughput) is not tracked

### Remediation

1. Add a CI job that runs benchmarks and stores results as artifacts
2. Set threshold alerts: if latency increases >20% from baseline, fail the build
3. Use `pytest-benchmark` with `--benchmark-compare` for regression detection

---

## Finding 10: Security Validation Skipped During Testing

**Severity: 🟡 MEDIUM**
**Domains: Testing × Security**

### Description

`core/config.py:64-68` explicitly skips security validation when `PYTEST_CURRENT_TEST` is set:

```python
if os.environ.get("PYTEST_CURRENT_TEST"):
    if not self.megabot_encryption_salt:
        self.megabot_encryption_salt = "test-salt-minimum-16-chars"
    return  # Skip all subsequent validation
```

### Impact

Security configurations that would fail in production (missing encryption salt, weak settings) are never tested. Tests pass with insecure defaults, creating a false confidence in the configuration layer.

### Remediation

1. Create separate test fixtures that explicitly set valid security configs rather than bypassing validation
2. Add at least one test that verifies `validate_environment()` **rejects** missing/weak configurations
3. Use `monkeypatch` to test both valid and invalid config scenarios

---

## Finding 11: Credentials Loaded from Python File

**Severity: 🟡 MEDIUM**
**Domains: Security × DevOps**

### Description

`core/orchestrator.py:57` loads credentials from a Python file on disk:

```python
cred_path = os.path.join(os.getcwd(), "api-credentials.py")  # pragma: no cover
```

### Impact

- Python files can contain executable code — loading credentials from `.py` files risks code injection if the file is tampered with
- Credentials in a `.py` file may be accidentally committed to version control
- This bypasses the `SecretManager` and environment variable patterns used elsewhere

### Remediation

1. Migrate to environment variables or the existing `SecretManager` (`core/secrets.py`)
2. If a file is required, use `.env` or `.json` format (not executable Python)
3. Add `api-credentials.py` to `.gitignore` (verify it's already there)

---

## Finding 12: HTTP Rate Limiting Gap

**Severity: 🟢 LOW**
**Domains: Backend × Security**

### Description

Rate limiting exists in `core/network/gateway.py` for WebSocket connections, but the 4 HTTP endpoints (`/`, `/health`, `/ivr`, `/ws` upgrade) have **no rate limiting**. The documented `X-RateLimit-*` headers (Finding 4) don't exist.

### Remediation

Add `slowapi` or custom middleware for HTTP rate limiting, especially on `/ivr` which processes external input.

---

## Finding 13: `git push || true` in CI

**Severity: 🟢 LOW**
**Domains: DevOps**

### Description

`.github/workflows/ci.yml:126` uses `git push || true`, silently swallowing push failures.

### Remediation

Remove `|| true` and handle push failures explicitly, or add a comment explaining why silent failure is acceptable.

---

## Finding 14: SearXNG Container Runs as Root

**Severity: 🟢 LOW (if network-isolated)**
**Domains: DevOps × Security**

### Description

The SearXNG service in docker-compose runs without a non-root user specification. Container escape from a root-running container has higher blast radius.

### Remediation

Add `user: "1000:1000"` or equivalent non-root user to the SearXNG service definition.

---

## Prioritized Action Plan

### Phase 1: Critical (This Week)

| # | Action | Finding | Effort |
|---|--------|---------|--------|
| 1 | Add WebSocket authentication | F1 | 2-4 hours |
| 2 | Add CORS middleware to FastAPI | F2 | 30 minutes |
| 3 | Sanitize `attachment.filename` in `_save_media` | F6 | 1 hour |

### Phase 2: High Priority (This Sprint)

| # | Action | Finding | Effort |
|---|--------|---------|--------|
| 4 | Remove `# pragma: no cover` from security methods; write tests | F5 | 4-6 hours |
| 5 | Reconcile API documentation with actual endpoints | F4 | 2-3 hours |
| 6 | Add permission checks to adapter layer | F3 | 4-8 hours |

### Phase 3: Medium Priority (Next Sprint)

| # | Action | Finding | Effort |
|---|--------|---------|--------|
| 7 | Write adversarial security tests | F7 | 4-6 hours |
| 8 | Remove docker-compose default passwords | F8 | 1 hour |
| 9 | Integrate benchmarks into CI | F9 | 2-3 hours |
| 10 | Fix security validation bypass in tests | F10 | 2 hours |
| 11 | Migrate `api-credentials.py` to env vars | F11 | 1-2 hours |

### Phase 4: Low Priority (Backlog)

| # | Action | Finding | Effort |
|---|--------|---------|--------|
| 12 | Add HTTP rate limiting | F12 | 2 hours |
| 13 | Fix `git push || true` in CI | F13 | 15 minutes |
| 14 | Run SearXNG as non-root | F14 | 15 minutes |

---

## Appendix: What's Working Well

It's important to note the strong foundations that were confirmed:

1. **Parameterized SQL everywhere** — `knowledge_memory.py` and all memory modules use `?` placeholders consistently. The `ORDER BY` whitelist at line 157-159 is a great defense-in-depth measure.

2. **TOCTOU-hardened file operations** — Recent commits added `lstat` pre-checks and `O_NOFOLLOW` flags to `agent_coordinator.py`, with dedicated tests for symlink and race condition attacks.

3. **Tirith Guard sanitization** — Comprehensive ANSI escape, Unicode homoglyph, and Cyrillic detection with good test coverage.

4. **Permission system design** — The `AUTO/ASK_EACH/NEVER` model with shell prefix matching and global wildcards is well-designed. The issue is enforcement coverage, not design.

5. **CI improvements** — `mypy` now fails the build on errors (previously `|| true`), and Python version is consistent at 3.13.

6. **Audit logging** — Recent commits added audit logging for permission denials and file-tool operations.

7. **No secrets in CI** — GitHub Actions workflows contain zero hardcoded secrets or tokens.

---

*Report generated by cross-domain orchestrated analysis. All file:line references verified against commit `5923b89`.*
