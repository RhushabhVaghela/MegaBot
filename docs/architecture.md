# MegaBot: Modular Adapter Architecture

MegaBot is designed with a **Modular Adapter Architecture** to ensure high decoupling and future-proofing. This design allows MegaBot to integrate various AI frameworks (OpenClaw, memU, Roo Code, OpenCode) as interchangeable components rather than a monolithic merge.

## Core Components

### 1. The Brain (FastAPI Orchestrator)
Located in `core/orchestrator.py`, the Brain is responsible for:
- Managing WebSocket connections with the UI.
- Routing messages between adapters.
- Managing system state and active "Modes" (Plan, Build, etc.).
- Coordinating background synchronization tasks (e.g., Memory Sync).
- **Policy Enforcement**: Intercepts sensitive commands and checks against local policies (`mega-config.yaml`). Supports runtime updates via chat commands (`!allow`, `!deny`).

### 2. The Hands & Feet (Adapters)
Adapters are thin wrappers located in `adapters/` that implement the standardized interfaces defined in `core/interfaces.py`.
- **OpenClawAdapter**: Handles multi-channel messaging and low-level system/browser tool execution.
- **MemUAdapter**: Manages proactive, hierarchical memory and local vector search. Uses "Layered Fetching" for context management.
- **MCPAdapter**: Provides a bridge to any Model Context Protocol server.
- **MessagingServer**: Native WebSocket platform with support for WhatsApp, Telegram, iMessage (macOS), and SMS (Twilio). Supports end-to-end encryption.
- **Unified Gateway**: Manages secure access via Cloudflare, Tailscale, and HTTPS.

### 3. The Sensory System (Module Discovery)
The `ModuleDiscovery` class in `core/discovery.py` dynamically scans the filesystem to find and register external capabilities (skills, prompts, tools). This allows the orchestrator to "learn" new abilities every time you add a new repository to your local agents folder.

## Communication Flow
1. **User Action**: The UI sends a JSON payload over a WebSocket to the Orchestrator.
2. **Parsing**: The Orchestrator parses the intent and checks the active Mode.
3. **Execution**:
   - If a message: The Orchestrator stores it in `memU` and relays it to `OpenClaw`.
   - If a tool call: The Orchestrator routes it to the `MCPManager` or the appropriate adapter.
4. **Memory Sync**: A background loop periodically ingests execution logs from `OpenClaw` into `memU` to ensure the long-term context remains updated.

## Future-Proofing
Because MegaBot relies on stable interfaces (`IMessaging`, `IMemory`, `ITool`), any internal changes or updates to the upstream repositories (OpenClaw, memU, etc.) only require a minor tweak to the corresponding adapter, leaving the core MegaBot logic untouched.
