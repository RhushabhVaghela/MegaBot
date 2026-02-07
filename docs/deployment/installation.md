# Installation Guide

This guide provides step-by-step instructions for installing and setting up MegaBot on various platforms.

## Prerequisites

### System Requirements

#### Minimum Requirements
- **Operating System**: Linux, macOS, or Windows (WSL2)
- **Python**: 3.11 or higher
- **Memory**: 4GB RAM
- **Storage**: 10GB free space
- **Network**: Internet connection for API access

#### Recommended Requirements
- **Operating System**: Linux (Ubuntu 22.04+)
- **Python**: 3.11.5+
- **Memory**: 8GB RAM
- **Storage**: 50GB SSD
- **Network**: Stable internet connection

### Required Dependencies

#### Python Packages
```bash
pip install fastapi uvicorn websockets aiohttp python-multipart
pip install pydantic-settings pyyaml cryptography
pip install sqlalchemy aiosqlite pgvector psycopg2-binary
```

#### External Services (Optional)
- **PostgreSQL**: For production database
- **Redis**: For session management
- **Docker**: For containerized deployment
- **Nginx**: For reverse proxy in production

## Installation Methods

### Method 1: Docker Deployment (Recommended)

#### Quick Start with Docker Compose
```bash
# Clone the repository
git clone https://github.com/RhushabhVaghela/MegaBot.git
cd megabot

# Create environment file
cp mega-config.yaml.template mega-config.yaml

# Edit configuration (see Configuration section below)
nano mega-config.yaml

# Start with Docker Compose
docker-compose up -d
```

#### Docker Compose Configuration
```yaml
version: '3.8'
services:
  megabot:
    build: .
    ports:
      - "3000:3000"
      - "18789:18789"
      - "18790:18790"
    volumes:
      - ./mega-config.yaml:/app/mega-config.yaml
      - ./data:/app/data
      - ./logs:/app/logs
    environment:
      - PYTHONPATH=/app
    restart: unless-stopped

  postgres:
    image: postgres:15
    environment:
      POSTGRES_DB: megabot
      POSTGRES_USER: megabot
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    restart: unless-stopped

volumes:
  postgres_data:
```

### Method 2: Native Python Installation

#### 1. Clone and Setup
```bash
# Clone repository
git clone https://github.com/RhushabhVaghela/MegaBot.git
cd megabot

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

#### 2. Database Setup

##### SQLite (Development)
```bash
# SQLite is used by default - no setup required
# Database file will be created automatically at ./megabot.db
```

##### PostgreSQL (Production)
```bash
# Install PostgreSQL
sudo apt update
sudo apt install postgresql postgresql-contrib

# Create database and user
sudo -u postgres psql
```

```sql
CREATE DATABASE megabot;
CREATE USER megabot WITH PASSWORD 'your_password';
GRANT ALL PRIVILEGES ON DATABASE megabot TO megabot;
```

#### 3. Configuration
```bash
# Copy example configuration
cp mega-config.yaml.template mega-config.yaml

# Edit with your settings
nano mega-config.yaml
```

#### 4. Start MegaBot
```bash
# Development mode
python -m megabot

# Production mode with uvicorn
uvicorn core.orchestrator:app --host 0.0.0.0 --port 3000
```

### Method 3: System Package Installation

#### Ubuntu/Debian
```bash
# Add repository (if available)
# sudo add-apt-repository ppa:RhushabhVaghela/MegaBot
# sudo apt update

# Install package
# sudo apt install megabot

# Configure service
# sudo systemctl enable megabot
# sudo systemctl start megabot
```

#### CentOS/RHEL
```bash
# Add repository
# sudo yum-config-manager --add-repo https://repo.your-org.com/megabot.repo

# Install package
# sudo yum install megabot

# Start service
# sudo systemctl enable megabot
# sudo systemctl start megabot
```

## Configuration

### Basic Configuration

Create `mega-config.yaml` with the following structure:

```yaml
# System settings
system:
  name: "MyMegaBot"
  local_only: true  # Set to false for remote access
  admin_phone: null  # For voice escalation

# Admin users
admins:
  - "your_telegram_user_id"

# LLM Provider configuration
llm:
  anthropic_api_key: "${ANTHROPIC_API_KEY}"
  # or other providers: openai_api_key, etc.

# Adapter configurations
adapters:
  openclaw:
    host: "127.0.0.1"
    port: 18789
    database_url: "sqlite:///megabot.db"

  memu:
    database_url: "sqlite:///:memory:"

  mcp:
    servers: []
    host: "127.0.0.1"
    port: 3000

# Security policies
policies:
  allow:
    - "git status"
    - "read *.md"
  deny:
    - "rm -rf /"

# Paths
paths:
  workspaces: "/path/to/workspaces"
  external_repos: "/path/to/external/repos"
```

### Environment Variables

Set required API keys and secrets:

```bash
# LLM API Keys (choose one or more)
export ANTHROPIC_API_KEY="sk-ant-..."
export OPENAI_API_KEY="sk-..."
export GROQ_API_KEY="gsk_..."

# Database (if using PostgreSQL)
export DATABASE_URL="postgresql://user:password@localhost/megabot"

# Security keys
export MEGABOT_SECRET_ENCRYPTION_KEY="your-256-bit-encryption-key"
export MEGABOT_SECRET_BACKUP_KEY="your-backup-encryption-key"
```

### Platform-Specific Setup

#### Telegram Bot
```yaml
adapters:
  messaging:
    telegram:
      bot_token: "${TELEGRAM_BOT_TOKEN}"
      enabled: true
```

#### Discord Bot
```yaml
adapters:
  messaging:
    discord:
      bot_token: "${DISCORD_BOT_TOKEN}"
      enabled: true
```

#### Signal Integration
```yaml
adapters:
  messaging:
    signal:
      phone_number: "+1234567890"
      enabled: true
```

## Verification

### Health Check
```bash
# Check if MegaBot is running
curl http://localhost:8000/health

# Should return:
{
  "status": "healthy",
  "components": {
    "memory": "up",
    "openclaw": "up",
    "messaging": "up"
  }
}
```

### Basic Functionality Test
```bash
# Test via HTTP API
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello MegaBot", "platform": "test"}'

# Test via WebSocket (requires wscat or similar)
# wscat -c ws://localhost:18790/ws
```

### Platform Connection Test
```bash
# Send test message via configured platform
# Check logs for successful connection messages
docker-compose logs megabot
```

## Troubleshooting Installation

### Common Issues

#### Python Version Issues
```bash
# Check Python version
python --version

# Upgrade pip
pip install --upgrade pip

# Install specific Python version
pyenv install 3.11.5
pyenv global 3.11.5
```

#### Permission Errors
```bash
# Fix directory permissions
sudo chown -R $USER:$USER /path/to/megabot

# Make scripts executable
chmod +x scripts/*.sh
```

#### Port Conflicts
```bash
# Check what's using ports
sudo lsof -i :3000
sudo lsof -i :18789

# Change ports in configuration
system:
  port: 3001  # Instead of 3000
```

#### Database Connection Issues
```bash
# Test database connection
python -c "
import sqlalchemy
engine = sqlalchemy.create_engine('postgresql://user:pass@localhost/megabot')
engine.execute('SELECT 1')
print('Database connection successful')
"
```

### Logs and Debugging

#### View Application Logs
```bash
# Docker deployment
docker-compose logs -f megabot

# Native installation
tail -f logs/megabot.log

# System logs
journalctl -u megabot -f
```

#### Enable Debug Logging
```yaml
system:
  log_level: "DEBUG"
```

#### Verbose Startup
```bash
# Run with verbose output
python -m megabot --verbose

# Or set environment variable
export MEGABOT_LOG_LEVEL=DEBUG
```

## Post-Installation Setup

### 1. Connect Platforms
Follow the platform-specific guides to connect MegaBot to your preferred messaging platforms.

### 2. Configure Permissions
Set up initial permission policies based on your security requirements.

### 3. Test Features
Run through the basic functionality tests to ensure all components work correctly.

### 4. Backup Setup
Configure automated backups for your MegaBot data.

### 5. Monitoring
Set up monitoring and alerting for production deployments.

## Upgrade Instructions

### Docker Deployment
```bash
# Pull latest image
docker-compose pull

# Stop, remove, and restart
docker-compose down
docker-compose up -d

# Check migration status
docker-compose logs megabot | grep -i migrat
```

### Native Installation
```bash
# Backup current installation
cp -r megabot megabot.backup

# Pull latest changes
git pull origin main

# Update dependencies
source venv/bin/activate
pip install -r requirements.txt --upgrade

# Run database migrations if needed
python -m megabot migrate

# Restart service
sudo systemctl restart megabot
```

### Rollback Procedures
```bash
# Docker rollback
docker-compose down
docker tag megabot:latest megabot:rollback
docker-compose up -d

# Native rollback
cp -r megabot.backup megabot
sudo systemctl restart megabot
```

## Security Checklist

Before going to production, verify:

- [ ] Admin users are properly configured
- [ ] Permission policies are restrictive enough
- [ ] API keys are stored securely (not in config files)
- [ ] Database is encrypted or secured
- [ ] Network access is limited (firewall rules)
- [ ] Logs are configured and monitored
- [ ] Backups are working and encrypted
- [ ] Voice escalation is configured (optional)

This installation guide covers the most common deployment scenarios. For advanced configurations or specific platform requirements, refer to the detailed configuration documentation.</content>
<parameter name="filePath">docs/deployment/installation.md