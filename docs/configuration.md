# MegaBot: Configuration Guide

MegaBot uses a central `mega-config.yaml` file for all settings. This guide explains each section and how to optimize for local performance.

## 1. System Settings
```yaml
system:
  name: MegaBot
  local_only: true       # Force loopback binding
  bind_address: "127.0.0.1"
  telemetry: false       # Disable all external pings
  default_mode: "plan"   # Startup mode
```

## 2. Adapter Configuration
Each adapter has specific requirements.

### OpenClaw
- **port**: Default is 18789. Ensure the OpenClaw Gateway process matches.
- **bridge_type**: Currently defaults to `websocket`.

### memU
- **database_url**: Default is `sqlite:///megabot.db` for local persistence.
- **vector_db**: Default is `sqlite`.

### MCP
Define your Model Context Protocol servers here.
```yaml
mcp:
  servers:
    - name: "filesystem"
      command: "npx"
      args: ["@modelcontextprotocol/server-filesystem", "/path/to/workdir"]
```

## 3. LLM Profiles
Configure your AI providers here.
```yaml
llm_profiles:
  default:
    provider: "ollama"
    model: "llama3"
    base_url: "http://127.0.0.1:11434/v1"
```
*Tip: You can add multiple profiles (e.g., `fast`, `heavy`, `backup`) and switch them via the UI.*

## 4. Paths
Point MegaBot to your repositories for Module Discovery.
```yaml
paths:
  external_repos: "/mnt/d/Agents and other repos/"
```
MegaBot will scan this folder for skills, themes, and prompt templates.
