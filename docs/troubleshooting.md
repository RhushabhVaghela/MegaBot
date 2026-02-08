# MegaBot Troubleshooting Guide

Common issues and solutions for MegaBot.

## Table of Contents
- [Installation Issues](#installation-issues)
- [Configuration Issues](#configuration-issues)
- [Connection Issues](#connection-issues)
- [Adapter Issues](#adapter-issues)
- [Performance Issues](#performance-issues)
- [Security Issues](#security-issues)

## Installation Issues

### Import Errors (Module Not Found)

**Problem:**
```
ImportError: No module named 'fastapi'
```

**Solution:**
```bash
pip install -r requirements.txt
```

Or using conda:
```bash
conda env create -f environment.yml
conda activate megabot
```

### Docker Issues

**Problem:** Container fails to start

**Solution:**
```bash
# Rebuild the container
docker-compose down
docker-compose up -d --build

# Check logs
docker-compose logs -f megabot
```

## Configuration Issues

### Config File Not Found

**Problem:**
```
FileNotFoundError: mega-config.yaml
```

**Solution:**
```bash
# Copy the template
cp mega-config.yaml.template mega-config.yaml

# Edit with your settings
nano mega-config.yaml
```

### Invalid YAML Syntax

**Problem:** Parser errors when loading config

**Solution:**
Use a YAML validator:
```bash
python -c "import yaml; yaml.safe_load(open('mega-config.yaml'))"
```

Common YAML issues:
- Tabs instead of spaces (use 2 spaces for indentation)
- Missing quotes around special characters
- Trailing spaces

## Connection Issues

### Cannot Connect to OpenClaw

**Problem:**
```
Failed to connect to OpenClaw: [Errno 111] Connection refused
```

**Solutions:**

1. **Check if OpenClaw is running:**
```bash
# Check OpenClaw process
ps aux | grep openclaw

# Or check the port
lsof -i :18789
```

2. **Verify configuration:**
```yaml
adapters:
  openclaw:
    host: "127.0.0.1"  # Must match OpenClaw bind address
    port: 18789        # Must match OpenClaw port
```

3. **Check OpenClaw logs:**
```bash
# OpenClaw typically logs to ~/.openclaw/logs/
tail -f ~/.openclaw/logs/gateway.log
```

### WebSocket Connection Refused

**Problem:** UI cannot connect to MegaBot

**Solution:**
```bash
# Check if MegaBot is running
curl http://localhost:8000/health

# Check port availability
lsof -i :8000

# Verify bind address in config
# bind_address: "0.0.0.0"  # For external access
# bind_address: "127.0.0.1"  # For localhost only
```

### Native Messaging Server Issues

**Problem:** Cannot connect on port 18790

**Solution:**
```bash
# Check if port is in use
lsof -i :18790

# Kill existing process or change port in config
# adapters:
#   messaging:
#     port: 18791
```

## Adapter Issues

### MCP Server Not Found

**Problem:**
```
Failed to start MCP Servers: [Errno 2] No such file or directory: 'npx'
```

**Solution:**
```bash
# Install Node.js and npm
# On Ubuntu/Debian:
sudo apt-get install nodejs npm

# On macOS:
brew install node

# Verify installation
npx --version
```

### MemU Adapter Fallback

**Problem:**
```
WARNING: memU not found at /tmp/mock_repos. Using functional fallback mock.
```

**Solution:**
This is expected behavior. MegaBot will use a functional mock if memU is not installed.

To use real memU:
1. Clone memU repository to `external_repos` path
2. Install memU dependencies
3. Update `mega-config.yaml` with correct path

### WhatsApp/Telegram Not Working

**Problem:** Messages not being sent/received

**Solution:**
The messaging adapters (SMS, iMessage, WhatsApp) are fully implemented. To use them:

1. **Via OpenClaw:** Ensure OpenClaw is configured with WhatsApp/Telegram skills
2. **Via MCP:** Install MCP servers for messaging platforms
3. **Custom Adapter:** Implement your own adapter following `docs/adapters.md`

## Performance Issues

### High Memory Usage

**Problem:** MegaBot consuming too much RAM

**Solutions:**

1. **Limit MCP servers:**
```yaml
adapters:
  mcp:
    servers: []  # Only enable needed servers
```

2. **Adjust sync frequency:**
In `core/orchestrator.py`, increase sync interval:
```python
await asyncio.sleep(7200)  # Sync every 2 hours instead of 1
```

3. **Use SQLite instead of PostgreSQL:**
```yaml
adapters:
  memu:
    database_url: "sqlite:///:memory:"
    vector_db: sqlite
```

### Slow Response Times

**Problem:** Commands taking too long

**Solutions:**

1. **Check Ollama availability:**
```bash
curl http://localhost:11434/api/tags
```

2. **Use faster models:**
```yaml
llm_profiles:
  default:
    chat_model: "llama3.2"  # Smaller, faster model
```

3. **Reduce memory search depth:**
In `adapters/memu_adapter.py`:
```python
# Limit results
results = await self.service.retrieve(query=key, limit=10)
```

## Security Issues

### Approval Interlock Not Working

**Problem:** Dangerous commands executing without approval

**Solution:**
1. Check policies in `mega-config.yaml`:
```yaml
policies:
  allow: []  # Empty = ask for everything
  deny: ["rm", "format", "del"]
```

2. Verify you're not using wildcard allow:
```yaml
# DANGEROUS - Allows everything
policies:
  allow: ["*"]
```

3. Check admin commands work:
```
!policies  # Should show current rules
```

### Authentication Failures

**Problem:** Cannot authenticate with adapters

**Solution:**
```bash
# Set environment variables
export MEGABOT_AUTH_TOKEN="your-secure-token"
export MEGABOT_WS_PASSWORD="your-secure-password"
export OPENCLAW_AUTH_TOKEN="your-openclaw-token"
```

### Encryption Not Working

**Problem:** Messages not encrypted

**Solution:**
Check encryption settings:
```yaml
# In code or config
enable_encryption: true
```

Verify password is set:
```bash
export MEGABOT_WS_PASSWORD="min-16-char-password"
```

## Debugging

### Enable Verbose Logging

Add to your startup:
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Check All Logs

```bash
# MegaBot logs (if running in Docker)
docker-compose logs megabot

# System logs
journalctl -u megabot -f

# OpenClaw logs
tail -f ~/.openclaw/logs/*.log
```

### Test Individual Components

```bash
# Test orchestrator
python -m core.orchestrator

# Test specific adapter
python -m adapters.memu_adapter

# Run tests
pytest tests/ -v
```

## Common Error Messages

### "Orchestrator not initialized"

**Cause:** WebSocket endpoint called before orchestrator started

**Solution:** Restart MegaBot and wait for "Starting MegaBot..." message

### "Policy: Auto-denying"

**Cause:** Command matches deny policy

**Solution:** Check `mega-config.yaml` policies or use `!allow <command>`

### "Connection closed"

**Cause:** Network issue or service not running

**Solution:** Check network connectivity and service status

### "Rate limit exceeded"

**Cause:** Too many requests from client

**Solution:** Wait and retry, or adjust rate limits in code

## Getting Help

If issues persist:

1. Check the logs for detailed error messages
2. Run tests: `pytest tests/ -v`
3. Review configuration: `python -c "from core.config import load_config; print(load_config())"`
4. Open an issue with:
   - Error message
   - Configuration (redact sensitive info)
   - Steps to reproduce
   - Environment details (OS, Python version, etc.)

## Quick Health Check

Run this diagnostic:
```bash
#!/bin/bash
echo "=== MegaBot Health Check ==="

# Check Python
echo "Python: $(python --version)"

# Check config
echo "Config valid: $(python -c "import yaml; yaml.safe_load(open('mega-config.yaml'))" && echo "YES" || echo "NO")"

# Check ports
echo "Port 8000 (API): $(lsof -i :8000 > /dev/null && echo "IN USE" || echo "FREE")"
echo "Port 18790 (Messaging): $(lsof -i :18790 > /dev/null && echo "IN USE" || echo "FREE")"

# Check Docker
if command -v docker &> /dev/null; then
    echo "Docker: $(docker ps --filter "name=megabot" --format "{{.Status}}")"
fi

echo "=== End Health Check ==="
```

---

Last updated: February 2026
