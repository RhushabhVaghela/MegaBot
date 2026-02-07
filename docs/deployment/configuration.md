# Configuration Reference

This document provides a comprehensive reference for all MegaBot configuration options available in `mega-config.yaml`.

> **Legend**: Sections marked **Implemented** reflect fields that exist in `core/config.py` today. Sections marked **Planned** document aspirational features that are not yet wired into the config classes — they are included here as design documentation for future development.

## Configuration File Structure

MegaBot uses YAML format for configuration. The configuration file is loaded at startup and can be reloaded without restarting (where supported).

```yaml
# mega-config.yaml
system:           # Core system settings
adapters:         # Platform and service adapters
policies:         # Security and permission policies
paths:           # File system paths
security:        # Security-related settings
llm:            # Language model configuration
admins:          # Administrator user IDs
```

## System Configuration — Implemented

### Core Settings

```yaml
system:
  name: "MegaBot"                    # Bot display name
  local_only: true                   # Restrict to localhost (recommended for security)
  default_mode: "plan"               # Default AI mode: plan, build, ask, loki
  bind_address: "127.0.0.1"         # Network bind address
  port: 8000                        # Main API port (env: MEGABOT_PORT)
  messaging_host: "127.0.0.1"       # Messaging server bind address
  messaging_port: 18790              # Messaging server port
  admin_phone: null                  # Phone number for voice escalation (env: ADMIN_PHONE_NUMBER)
  dnd_start: 22                      # Do Not Disturb start hour (24h, env: DND_START_HOUR)
  dnd_end: 7                        # Do Not Disturb end hour (24h, env: DND_END_HOUR)
  telemetry: false                   # Enable anonymous usage telemetry (boolean)
```

> **Note**: `telemetry` is a simple boolean toggle. The detailed telemetry sub-object shown below is **planned** but not yet implemented.

### Telemetry Settings — Planned

```yaml
# NOT YET IMPLEMENTED — design documentation only
system:
  telemetry:
    enabled: false                   # Enable telemetry collection
    endpoint: "https://telemetry.megabot.ai"  # Telemetry server
    interval_minutes: 60             # Telemetry send interval
    include_system_info: false       # Include system information
    include_usage_stats: true        # Include usage statistics
```

## Adapter Configuration — Implemented

All adapters share the `AdapterConfig` base fields: `host`, `port`, `bridge_type`, `database_url`, `vector_db`, `servers`, `web_search`, `auth_token`, `encryption_key`. Additional fields shown below (e.g. `reconnect_attempts`, `heartbeat_interval`) are **planned** extensions.

### OpenClaw Adapter

```yaml
adapters:
  openclaw:
    host: "127.0.0.1"               # OpenClaw server host
    port: 18789                     # OpenClaw server port
    database_url: "sqlite:///megabot.db"  # Database connection string
    auth_token: ""                  # Authentication token (if required)
    bridge_type: "websocket"        # Connection type: websocket, http
    encryption_key: ""              # Encryption key for secure communication
    # --- Planned (not yet in AdapterConfig) ---
    # reconnect_attempts: 5
    # reconnect_delay: 1.0
    # heartbeat_interval: 30
    # request_timeout: 30
```

### MemU Adapter (Memory) — Implemented

```yaml
adapters:
  memu:
    host: "127.0.0.1"               # MemU server host
    port: 3000                      # MemU server port (AdapterConfig default)
    database_url: "sqlite:///:memory:"  # In-memory SQLite (development)
    # database_url: "postgresql://user:pass@localhost/memu"  # Production
    auth_token: ""                  # Authentication token
    bridge_type: "websocket"        # Connection type
    encryption_key: ""              # Encryption key
    vector_db: "sqlite"             # Vector database: sqlite, pgvector, pinecone
    web_search:                     # Web search configuration
      enabled: true
      provider: "duckduckgo"        # Search provider: duckduckgo, google, bing
      api_key: ""                   # API key for premium search
      max_results: 10               # Maximum search results
      cache_ttl: 3600               # Cache time-to-live (seconds)
```

> **Note**: `web_search` is stored as `Dict[str, Any]` — the sub-keys above are conventions, not schema-validated.

### MCP (Model Context Protocol) Adapter — Implemented

```yaml
adapters:
  mcp:
    host: "127.0.0.1"               # MCP server host
    port: 3000                      # MCP server port (AdapterConfig default)
    database_url: "sqlite:///mcp.db"  # MCP database
    auth_token: ""                  # Authentication token
    bridge_type: "websocket"        # Connection type
    encryption_key: ""              # Encryption key
    servers: []                     # List of MCP servers to connect
      # Example server configuration:
      # - name: "filesystem"
      #   command: "npx"
      #   args: ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
      #   env:
      #     API_KEY: "${MCP_FILESYSTEM_KEY}"
    vector_db: "pgvector"            # Vector database type
    web_search: {}                   # Web search configuration (same as memu)
```

### Messaging Adapter — Planned

> The messaging system uses `system.messaging_host` / `system.messaging_port` for its server bind. The detailed per-platform adapter config below is **planned** — individual messaging adapters currently read tokens from environment variables directly.

```yaml
# NOT YET IMPLEMENTED — design documentation only
adapters:
  messaging:
    host: "127.0.0.1"               # Messaging server host
    port: 18790                     # Messaging server port
    enable_encryption: true         # Enable end-to-end encryption
    encryption_algorithm: "AES256"  # Encryption algorithm
    max_message_size: 1048576       # Maximum message size (bytes)
    rate_limit:                     # Rate limiting configuration
      enabled: true
      messages_per_minute: 60       # Messages per minute per user
      burst_limit: 10               # Burst message limit
    platforms:                      # Platform-specific configurations
      telegram:
        enabled: true
        bot_token: "${TELEGRAM_BOT_TOKEN}"
        webhook_url: null           # Webhook URL for production
        max_file_size: 20971520     # 20MB max file size
      discord:
        enabled: false
        bot_token: "${DISCORD_BOT_TOKEN}"
        intents: ["guilds", "messages"]  # Discord intents
      signal:
        enabled: false
        phone_number: "+1234567890"
        device_name: "MegaBot"
      slack:
        enabled: false
        bot_token: "${SLACK_BOT_TOKEN}"
        signing_secret: "${SLACK_SIGNING_SECRET}"
```

### Unified Gateway — Planned

```yaml
# NOT YET IMPLEMENTED — design documentation only
adapters:
  gateway:
    host: "127.0.0.1"               # Gateway server host
    port: 18791                     # Gateway server port
    enable_cloudflare: false        # Enable Cloudflare tunnel
    cloudflare_token: ""            # Cloudflare tunnel token
    enable_vpn: false               # Enable VPN support
    vpn_provider: "tailscale"       # VPN provider: tailscale, zerotier
    vpn_auth_key: ""                # VPN authentication key
    allowed_origins: ["*"]          # CORS allowed origins
    rate_limiting:
      enabled: true
      requests_per_minute: 100      # Requests per minute
      burst_limit: 20               # Burst request limit
    ssl:
      enabled: false                # Enable SSL/TLS
      cert_file: "/path/to/cert.pem"  # SSL certificate file
      key_file: "/path/to/key.pem"   # SSL private key file
```

## LLM Configuration

### Provider API Keys — Implemented

```yaml
llm:
  # All API keys are implemented — set via config or environment variables
  anthropic_api_key: null           # env: ANTHROPIC_API_KEY
  openai_api_key: null              # env: OPENAI_API_KEY
  groq_api_key: null                # env: GROQ_API_KEY
  deepseek_api_key: null            # env: DEEPSEEK_API_KEY
  deepinfra_api_key: null           # env: DEEPINFRA_API_KEY
  fireworks_api_key: null           # env: FIREWORKS_API_KEY
  gemini_api_key: null              # env: GEMINI_API_KEY
  sambanova_api_key: null           # env: SAMBANOVA_API_KEY
  xai_api_key: null                 # env: XAI_API_KEY
  perplexity_api_key: null          # env: PERPLEXITY_API_KEY
  openrouter_api_key: null          # env: OPENROUTER_API_KEY
  mistral_api_key: null             # env: MISTRAL_API_KEY
  cerebras_api_key: null            # env: CEREBRAS_API_KEY
  github_token: null                # env: GITHUB_TOKEN (GitHub models)

  # Local model endpoints
  lm_studio_url: null               # env: LM_STUDIO_URL
  llama_cpp_url: null               # env: LLAMA_CPP_URL
  vllm_url: null                    # env: VLLM_URL
  vllm_api_key: null                # env: VLLM_API_KEY
```

### Provider Selection & Advanced LLM Settings — Planned

```yaml
# NOT YET IMPLEMENTED — design documentation only
llm:
  provider: "anthropic"             # Default LLM provider

  # Provider-specific settings
  anthropic:
    model: "claude-3-5-sonnet-20241022"
    max_tokens: 4096
    temperature: 0.7
    timeout: 30

  openai:
    model: "gpt-4"
    max_tokens: 4096
    temperature: 0.7
    timeout: 30

  fallback_providers: ["openai", "groq"]
```

### Advanced LLM Settings — Planned

```yaml
# NOT YET IMPLEMENTED — design documentation only
llm:
  # Request optimization
  max_concurrent_requests: 5        # Maximum concurrent LLM requests
  request_timeout: 60               # Request timeout (seconds)
  retry_attempts: 3                 # Number of retry attempts
  retry_delay: 1.0                  # Delay between retries (seconds)

  # Response processing
  max_response_length: 8192         # Maximum response length
  truncate_long_responses: true     # Truncate long responses
  include_reasoning: true           # Include reasoning in responses

  # Caching
  enable_caching: true              # Enable LLM response caching
  cache_ttl: 3600                   # Cache time-to-live (seconds)
  cache_max_size: 1000              # Maximum cache entries

  # Cost management
  max_daily_cost: 10.0              # Maximum daily cost (USD)
  cost_alert_threshold: 5.0         # Cost alert threshold (USD)
```

## Security Configuration

### Core Security Settings — Partially Implemented

> Only `megabot_backup_key`, `megabot_encryption_salt`, and `megabot_media_path` exist in `SecurityConfig`. All other fields below are **planned**.

```yaml
security:
  # --- Implemented ---
  megabot_backup_key: null          # Backup encryption key (env: MEGABOT_BACKUP_KEY)
  megabot_encryption_salt: "megabot-static-salt"  # Encryption salt (env: MEGABOT_ENCRYPTION_SALT, min 16 chars)
  megabot_media_path: "./media"     # Media storage path (env: MEGABOT_MEDIA_PATH)

  # --- Planned (not yet in SecurityConfig) ---
  # enable_content_filtering: true
  # content_filter_level: "strict"
  # enable_image_redaction: true
  # redaction_sensitivity: "high"
  # allowed_ips: []
  # blocked_ips: []
  # enable_ip_filtering: false
  # session_timeout: 3600
  # max_sessions_per_user: 5
  # enable_session_locking: true
```

### Permission System — Partially Implemented

> `policies` is `Dict[str, Any]` with `allow`/`deny` lists implemented. `default_permission`, `time_restricted`, and `ip_restricted` are **planned**.

```yaml
policies:
  # --- Implemented ---
  allow:
    - "git status"
    - "git log --oneline"
    - "read *.md"
    - "read *.txt"
    - "ls -la"

  deny:
    - "rm -rf /"
    - "rm -rf /*"
    - "sudo *"
    - "chmod 777 *"
    - "* > /dev/null"               # Prevent output redirection attacks
    - "curl * | bash"               # Prevent pipe-to-shell attacks

  # --- Planned (not yet enforced) ---
  # default_permission: "ASK_EACH"  # AUTO, ASK_EACH, NEVER
  # time_restricted:
  #   - action: "shell.*"
  #     allowed_hours: "9-17"
  #     weekdays_only: true
  # ip_restricted:
  #   - action: "admin.*"
  #     allowed_ips: ["192.168.1.0/24"]
```

### Tirith Guard (Content Sanitization) — Planned

> Homoglyph detection is implemented in `core/tirith.py` but not configurable via `mega-config.yaml`.

```yaml
# NOT YET IMPLEMENTED — design documentation only
security:
  tirith_guard:
    enabled: true                   # Enable content sanitization
    ansi_escape_removal: true       # Remove ANSI escape sequences
    unicode_normalization: true     # Normalize Unicode text
    control_char_filtering: true    # Filter control characters
    homoglyph_detection: true       # Detect suspicious homoglyphs
    max_text_length: 10000          # Maximum text length
    suspicious_chars_threshold: 0.1 # Threshold for suspicious character ratio
```

## Path Configuration — Implemented

> `paths` is `Dict[str, str]` — any key/value pair is valid. The keys below are conventions used by the codebase.

### Directory Paths

```yaml
paths:
  # Core directories
  workspaces: "/home/user/megabot/workspaces"  # Project workspaces
  external_repos: "/tmp/mock_repos"           # External repository cache
  logs: "/var/log/megabot"                    # Log directory
  temp: "/tmp/megabot"                        # Temporary files
  backups: "/var/backups/megabot"             # Backup directory

  # Data directories
  databases: "/var/lib/megabot/db"            # Database files
  cache: "/var/cache/megabot"                 # Cache directory
  media: "/var/lib/megabot/media"             # Media storage

  # Configuration directories
  config_dir: "/etc/megabot"                  # Configuration directory
  secrets_dir: "/etc/megabot/secrets"         # Secrets directory
  ssl_certs: "/etc/megabot/ssl"               # SSL certificates
```

### File Permissions — Planned

> `paths` is a flat `Dict[str, str]`. Nested `permissions` sub-object is not supported.

```yaml
# NOT YET IMPLEMENTED — design documentation only
paths:
  permissions:
    workspaces: "755"               # Directory permissions
    logs: "750"                     # Log directory permissions
    secrets: "700"                  # Secrets directory permissions
    databases: "600"                # Database file permissions
    backups: "600"                  # Backup file permissions
```

## Advanced Configuration — Planned

> The `performance`, `monitoring`, and `database` top-level sections below are **not yet implemented** in `core/config.py`. They are included as design documentation for future development.

### Performance Tuning — Planned

```yaml
# NOT YET IMPLEMENTED — design documentation only
performance:
  # Memory management
  max_memory_usage: "2GB"           # Maximum memory usage
  memory_cleanup_interval: 300      # Memory cleanup interval (seconds)
  cache_max_size: 1000              # Maximum cache entries

  # CPU management
  max_worker_threads: 4             # Maximum worker threads
  thread_pool_size: 10              # Thread pool size
  cpu_affinity: null                # CPU affinity mask

  # I/O optimization
  io_buffer_size: 65536             # I/O buffer size (bytes)
  max_file_handles: 1024            # Maximum open file handles
  disk_cache_size: "1GB"            # Disk cache size

  # Network optimization
  connection_pool_size: 20          # Connection pool size
  request_timeout: 30               # Request timeout (seconds)
  keep_alive_timeout: 60            # Keep-alive timeout (seconds)
```

### Monitoring and Observability — Planned

```yaml
# NOT YET IMPLEMENTED — design documentation only
monitoring:
  # Health checks
  health_check_interval: 30         # Health check interval (seconds)
  health_check_timeout: 5           # Health check timeout (seconds)
  unhealthy_threshold: 3            # Unhealthy threshold

  # Metrics collection
  enable_metrics: true              # Enable metrics collection
  metrics_port: 9090                # Metrics server port
  metrics_path: "/metrics"          # Metrics endpoint path

  # Logging
  log_format: "json"                # Log format: json, text
  log_rotation: "daily"             # Log rotation: daily, weekly, size
  log_max_size: "100MB"             # Maximum log file size
  log_retention_days: 30            # Log retention period

  # Alerting
  alerts:
    enabled: true
    slack_webhook: ""               # Slack webhook for alerts
    email_recipients: []            # Email recipients for alerts
    alert_levels: ["ERROR", "CRITICAL"]  # Alert levels
```

### Database Configuration — Planned

```yaml
# NOT YET IMPLEMENTED — design documentation only
database:
  # Connection settings
  connection_pool_size: 10          # Connection pool size
  connection_timeout: 30            # Connection timeout (seconds)
  max_connections: 20               # Maximum connections
  connection_retry_attempts: 3      # Connection retry attempts
  connection_retry_delay: 1.0       # Connection retry delay (seconds)

  # Performance settings
  enable_query_logging: false       # Enable query logging
  slow_query_threshold: 1.0         # Slow query threshold (seconds)
  enable_query_caching: true        # Enable query result caching
  cache_ttl: 300                    # Query cache TTL (seconds)

  # Backup settings
  backup_enabled: true              # Enable automatic backups
  backup_interval_hours: 12         # Backup interval (hours)
  backup_retention_days: 30         # Backup retention (days)
  backup_compression: "gzip"        # Backup compression: none, gzip, bz2
  backup_encryption: true           # Encrypt backups
```

## Environment Variables — Implemented

MegaBot supports environment variable substitution in configuration files using the `${VAR_NAME}` syntax. The following environment variables are auto-populated by `_populate_from_environment()` in `core/config.py`.

### Common Environment Variables

```bash
# API Keys (all implemented — see LLM section above)
export ANTHROPIC_API_KEY="sk-ant-..."
export OPENAI_API_KEY="sk-..."
export TELEGRAM_BOT_TOKEN="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"

# System
export MEGABOT_PORT="8000"
export ADMIN_PHONE_NUMBER="+1234567890"
export DND_START_HOUR="22"
export DND_END_HOUR="7"
export AUTHORIZED_ADMINS="admin1,admin2"

# Security
export MEGABOT_ENCRYPTION_SALT="your-salt-min-16-chars"
export MEGABOT_BACKUP_KEY="backup-encryption-key"
export MEGABOT_MEDIA_PATH="./media"

# Platform-specific (read directly by adapters)
export DISCORD_BOT_TOKEN="your-discord-token"
export SLACK_BOT_TOKEN="xoxb-your-slack-token"
```

### Secret Management

```bash
# Load secrets from files
export MEGABOT_BACKUP_KEY="$(cat /etc/megabot/secrets/backup_key)"
export MEGABOT_ENCRYPTION_SALT="$(cat /etc/megabot/secrets/encryption_salt)"

# Use in configuration
llm:
  anthropic_api_key: "${ANTHROPIC_API_KEY}"
```

## Configuration Validation

### Schema Validation

MegaBot validates configuration files against a JSON schema. Invalid configurations will prevent startup.

```bash
# Validate configuration
python3 -c "
from core.config import load_config
config = load_config('mega-config.yaml')
print('Configuration loaded successfully')
"
```

### Common Validation Errors

- **Missing required fields**: `admins` list cannot be empty in production
- **Invalid API keys**: Keys must match expected format for each provider
- **Invalid permissions**: Permission scopes must follow `category.action` format
- **Invalid paths**: Directory paths must exist and be writable
- **Port conflicts**: Ports must not be in use by other services

### Configuration Hot Reload

Some configuration changes can be applied without restarting MegaBot:

```bash
# Reload configuration via API
curl -X POST http://localhost:8000/admin/reload-config \
  -H "Authorization: Bearer ${ADMIN_TOKEN}"

# Check reload status
curl http://localhost:8000/admin/config-status
```

**Note**: Security-related changes (permissions, admins) require a full restart for security reasons.

## Configuration Examples

### Development Configuration

```yaml
system:
  name: "MegaBot Dev"
  local_only: true

admins: ["dev_user_id"]

llm:
  anthropic_api_key: "${ANTHROPIC_API_KEY}"

adapters:
  openclaw:
    database_url: "sqlite:///dev.db"
  memu:
    database_url: "sqlite:///:memory:"

policies:
  allow: ["*"]  # Permissive for development
  deny: []
```

### Production Configuration

```yaml
system:
  name: "MegaBot Production"
  local_only: false
  port: 8000
  telemetry: false

admins: ["admin_user_1", "admin_user_2"]

llm:
  anthropic_api_key: "${ANTHROPIC_API_KEY}"

adapters:
  openclaw:
    database_url: "${DATABASE_URL}"
  memu:
    database_url: "${DATABASE_URL}"

policies:
  allow: ["git status", "read *.md"]
  deny: ["rm -rf /", "sudo *"]

security:
  megabot_encryption_salt: "${MEGABOT_ENCRYPTION_SALT}"
  megabot_backup_key: "${MEGABOT_BACKUP_KEY}"
```

### High-Security Configuration

```yaml
system:
  local_only: true
  dnd_start: 18  # 6 PM
  dnd_end: 8     # 8 AM

admins: ["security_admin"]

policies:
  allow: ["git status", "read *.md"]
  deny: ["*"]

security:
  megabot_encryption_salt: "${MEGABOT_ENCRYPTION_SALT}"
  megabot_backup_key: "${MEGABOT_BACKUP_KEY}"
```

This configuration reference covers all available and planned options. For specific use cases or advanced scenarios, refer to the deployment and security documentation.</content>
<parameter name="filePath">docs/deployment/configuration.md