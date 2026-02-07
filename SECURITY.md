# MegaBot Security Framework 🔒

MegaBot implements a **Defense-in-Depth** strategy to protect your host machine and data from malicious or accidental actions.

## 🛡️ The Security Stack

### 1. Tiered Permission Manager
MegaBot uses a granular permission system defined in `core/permissions.py`.
- **Permission Levels**:
  - `AUTO`: Pre-approved safe commands.
  - `ASK_EACH`: Default for all sensitive actions. Requires manual approval.
  - `NEVER`: Hard-blocked commands (e.g., `rm -rf /`).
- **Domain Boundaries**: Sub-agents are restricted to specific scopes (e.g., a "QA Engineer" cannot write to the filesystem outside of test directories).

### 2. Tirith Guard: Output & Command Sanitization
Inspired by the Tirith project, `adapters/security/tirith_guard.py` protects against:
- **ANSI Escape Injection**: Strips malicious terminal escape sequences that could hide commands or manipulate output.
- **Unicode Homoglyph Attacks**: Detects and blocks commands containing suspicious characters (e.g., Cyrillic 'а' replacing Latin 'a') used in phishing or obfuscation.
- **Output Scrubbing**: Automatically removes secrets and sensitive keys from terminal output before displaying them to the user.

### 3. Approval Interlock & Admin Queue
All `system.run` and `shell.execute` calls are intercepted by the Orchestrator.
- **Manual Gate**: Commands are queued in `orchestrator.approval_queue`.
- **Chat-Based Control**: Admins on Signal, Telegram, or the Web Dashboard receive a notification and can respond with:
  - `!approve <id>`: Authorize the action.
  - `!deny <id>`: Discard the action.
  - `!allow <pattern>`: Add to persistent auto-approve list.

### 4. Data Execution Interlocks (Phase 4)
The **DashDataAgent** allows for Python-based data analysis. To prevent malicious code execution:
- **python.execute scope**: Python code generation is isolated.
- **Pre-Execution Review**: The generated code is displayed to the Admin for approval before the local `exec()` call is triggered.
- **Environment Isolation**: Execution happens with limited local variables and no access to system `os` or `subprocess` modules by default.

## 🔐 Messaging Security
- **E2E Encryption**: The native WebSocket uses **Fernet (AES-128)** encryption with PBKDF2 key derivation.
- **Zero-Trust Platforms**: External messaging platforms (Telegram/Discord) are treated as untrusted zones. No command is executed without passing through the central Orchestrator's interlock.
- **Signal Protocol**: Signal integration provides the highest level of privacy for administrative commands.

## 🐳 Containerization
By default, MegaBot is designed to run in **Docker**.
- The `orchestrator` process is isolated from the host.
- Filesystem access is limited to the mounted `workspaces` directory.
- Network access is controlled via the `Unified Gateway`.

## 🧪 Security Benchmarking
We perform regular "Red Team" tests using `tests/benchmarking.py` to ensure:
1. No sensitive command bypasses the interlock.
2. Tirith Guard catches injection attempts.
3. Sub-agents stay within their assigned roles.
