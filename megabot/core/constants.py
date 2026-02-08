"""Shared constants for the MegaBot core package.

Extracted to avoid circular imports between ``core.orchestrator`` and
other modules that need these values.
"""

GREETING_TEXT = """🤖 *MegaBot Connected!*
I am your unified AI assistant, powered by OpenClaw, memU, and MCP.

🚀 *Abilities:*
- 📂 **File System**: Read/write files (requires approval).
- 🧠 **Proactive Memory**: I remember context and anticipate needs.
- 🛠️ **MCP Tools**: 1000+ standardized tools at my disposal.
- 📞 **Communications**: Voice/Video calls, SMS, and IM.

🔐 *Security:*
- **Approval Interlock**: I will ask for permission before running system commands.
- **E2E Encryption**: Our messages are secure.

⌨️ *Commands:*
- `!approve` / `!yes`: Authorize a pending action (Vision, CLI, System).
- `!deny` / `!no`: Reject a pending action.
- `!link <name>`: Link this device to your unified identity.
- `!whoami`: View your identity and platform info.
- `!backup`: Create an encrypted memory snapshot.
- `!briefing`: Get a voice summary of recent bot activity.
- `!health`: Check system component status.
- `!mode <mode>`: Switch between `plan`, `build`, `ask`, `loki`.

How can I help you today?
"""
