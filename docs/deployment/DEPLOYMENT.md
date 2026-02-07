# MegaBot Deployment Guide

Complete guide for deploying MegaBot in various environments.

## Table of Contents
- [Quick Start (Docker Compose)](#quick-start-docker-compose)
- [Production Deployment](#production-deployment)
- [Configuration](#configuration)
- [Monitoring \u0026 Maintenance](#monitoring--maintenance)
- [Troubleshooting](#troubleshooting)

---

## Quick Start (Docker Compose)

The fastest way to get MegaBot running locally.

### Prerequisites
- Docker \u0026 Docker Compose installed
- At least 8GB RAM (16GB recommended for Ollama with larger models)
- NVIDIA GPU (optional, for Ollama acceleration)

### Steps

1. **Clone the repository**
   ```bash
   git clone https://github.com/RhushabhVaghela/MegaBot.git
   cd MegaBot
   ```

2. **Create environment configuration**
   ```bash
   cp .env.example .env
   # Edit .env with your settings
   nano .env
   ```

3. **Start services**
   ```bash
   docker-compose up -d
   ```

4. **Pull Ollama model** (first time only)
   ```bash
   docker exec -it megabot-ollama ollama pull qwen2.5:14b
   ```

5. **Access MegaBot**
   - API: http://localhost:8000
   - Health: http://localhost:8000/health
   - WebSocket: ws://localhost:18790
   - Search (SearXNG): http://localhost:8080

---

## Production Deployment

### System Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| CPU       | 4 cores | 8+ cores    |
| RAM       | 8 GB    | 16+ GB      |
| Storage   | 50 GB   | 100+ GB SSD |
| GPU       | None    | NVIDIA GPU (for Ollama) |

### Environment Variables

Key environment variables to configure:

```bash
# Security (REQUIRED)
POSTGRES_PASSWORD=your_secure_password
OPENCLAW_AUTH_TOKEN=your_secret_token
MEGABOT_AUTH_TOKEN=your_megabot_token

# Database
DATABASE_URL=postgresql://megabot:password@postgres:5432/megabot

# Model Selection
OLLAMA_MODEL=qwen2.5:14b  # or llama2, mistral, etc.

# memU Configuration
MEMU_PROACTIVE_MODE=true

# Gateway (Optional)
ENABLE_CLOUDFLARE=false
ENABLE_TAILSCALE=false
```

### Deployment Options

#### Option 1: Docker Compose (Recommended)

Best for single-server deployments.

```bash
# Production compose file
docker-compose -f docker-compose.yml up -d

# View logs
docker-compose logs -f megabot

# Restart services
docker-compose restart
```

#### Option 2: Kubernetes

For multi-server, highly available deployments.

```bash
kubectl apply -f k8s/
```

#### Option 3: Bare Metal

For maximum control and performance.

```bash
# Install Python 3.12+
apt install python3.12 python3.12-venv

# Create virtual environment
python3.12 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -e .

# Start MegaBot
uvicorn core.orchestrator:app --host 0.0.0.0 --port 8000
```

---

## Configuration

### meta-config.yaml

Primary configuration file for MegaBot.

```yaml
orchestrator:
  host: "0.0.0.0"
  port: 8000
  log_level: "INFO"
  mode: "auto"  # auto, plan, execute
  max_context_tokens: 8192

openclaw:
  enabled: true
  repo_path: "/app/external_repos/openclaw"
  branch: "main"
  auto_sync: true
  auth_token: "${OPENCLAW_AUTH_TOKEN}"

memu:
  enabled: true
  repo_path: "/app/external_repos/memU"
  branch: "main"
  auto_sync: true
  ollama_model: "${OLLAMA_MODEL}"
  proactive_mode: true

mcp:
  enabled: true
  servers:
    - name: "filesystem"
      command: "npx"
      args: ["-y", "@modelcontextprotocol/server-filesystem", "/app/data"]
      env: {}
      timeout_seconds: 30
    
    - name: "github"
      command: "npx"
      args: ["-y", "@modelcontextprotocol/server-github"]
      env:
        GITHUB_TOKEN: "${GITHUB_TOKEN}"
      timeout_seconds: 30

gateway:
  enabled: true
  access_methods: ["local", "vpn"]
  ports:
    local: 18790
    cloudflare: 18791
    vpn: 18792
    direct: 18793
  auth_token: "${MEGABOT_AUTH_TOKEN}"
  rate_limits:
    local: {requests_per_minute: 100, burst: 20}
    cloudflare: {requests_per_minute: 60, burst: 10}
    vpn: {requests_per_minute: 100, burst: 20}
    direct: {requests_per_minute: 30, burst: 5}

security:
  default_policy: "prompt"  # allow, deny, prompt
  allowed_patterns: []
  denied_patterns:
    - "rm -rf /"
    - "mkfs.*"
    - "dd if=/dev/zero"
```

### External Repositories

MegaBot requires OpenClaw and memU repositories.

**Clone external dependencies:**
```bash
mkdir -p external
cd external

# Clone OpenClaw
git clone https://github.com/username/openclaw.git

# Clone memU
git clone https://github.com/username/memU.git

cd ..
```

---

## Monitoring \u0026 Maintenance

### Health Checks

```bash
# Check MegaBot health
curl http://localhost:8000/health

# Check database connection
docker exec megabot-postgres pg_isready -U megabot

# Check Ollama
curl http://localhost:11434/api/tags
```

### Logs

```bash
# View MegaBot logs
docker logs -f megabot-orchestrator

# View all services
docker-compose logs -f

# Filter by service
docker-compose logs -f megabot postgres
```

### Backups

```bash
# Backup PostgreSQL database
docker exec megabot-postgres pg_dump -U megabot megabot > backup_$(date +%Y%m%d).sql

# Backup volumes
docker run --rm -v megabot_data:/data -v $(pwd):/backup alpine tar czf /backup/data_backup.tar.gz /data
```

### Updates

```bash
# Pull latest changes
git pull origin main

# Rebuild and restart
docker-compose down
docker-compose build --no-cache
docker-compose up -d

# Verify
curl http://localhost:8000/health
```

---

## Troubleshooting

### Common Issues

#### 1. Database Connection Failed

**Symptom:** `FATAL:  database "megabot" does not exist`

**Solution:**
```bash
docker exec -it megabot-postgres createdb -U megabot megabot
docker-compose restart megabot
```

#### 2. Ollama Model Not Found

**Symptom:** `Error: model 'qwen2.5:14b' not found`

**Solution:**
```bash
docker exec -it megabot-ollama ollama pull qwen2.5:14b
```

#### 3. Permission Denied Errors

**Symptom:** `PermissionError: [Errno 13] Permission denied`

**Solution:**
```bash
# Fix volume permissions
docker-compose down
sudo chown -R 1000:1000 ./external ./data
docker-compose up -d
```

#### 4. Port Already in Use

**Symptom:** `Error: bind: address already in use`

**Solution:**
```bash
# Find process using port
sudo lsof -i :8000

# Kill process or change port in docker-compose.yml
```

#### 5. Out of Memory

**Symptom:** Container keeps restarting, OOM errors

**Solution:**
```bash
# Increase Docker memory limit
# Edit Docker Desktop settings or /etc/docker/daemon.json

# Use smaller Ollama model
OLLAMA_MODEL=phi3 docker-compose up -d
```

### Debug Mode

Enable detailed logging:

```yaml
# meta-config.yaml
orchestrator:
  log_level: "DEBUG"
```

```bash
# Restart with debug logs
docker-compose restart megabot
docker-compose logs -f megabot | grep DEBUG
```

### Performance Tuning

```yaml
# Increase workers for production
# In Dockerfile or docker-compose.yml
command: uvicorn core.orchestrator:app --host 0.0.0.0 --port 8000 --workers 4
```

---

## Security Best Practices

1. **Change default passwords** in `.env`
2. **Use strong auth tokens** (32+ characters)
3. **Enable HTTPS** in production
4. **Limit network exposure** (use VPN or Cloudflare Tunnel)
5. **Regular backups** of database and config
6. **Update dependencies** regularly
7. **Monitor logs** for suspicious activity
8. **Use `default_policy: prompt`** for sensitive operations

---

## Support

For issues and questions:
- GitHub Issues: [MegaBot Issues](https://github.com/RhushabhVaghela/MegaBot/issues)
- Documentation: [docs/](./docs/)
- Troubleshooting Guide: [docs/troubleshooting.md](./docs/troubleshooting.md)
