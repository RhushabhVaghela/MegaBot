# Troubleshooting Guide

This guide helps diagnose and resolve common issues with MegaBot deployments.

## Quick Diagnosis

### Health Check Commands

```bash
# Check overall system health
curl http://localhost:8000/health

# Check component status
curl http://localhost:8000/health/components

# View recent logs
docker-compose logs --tail=50 megabot
tail -f logs/megabot.log
```

### Common Symptoms and Solutions

#### Symptom: MegaBot won't start

**Possible Causes:**
1. **Configuration errors**
2. **Port conflicts**
3. **Missing dependencies**
4. **Permission issues**

**Solutions:**
```bash
# Check configuration syntax
python -c "import yaml; yaml.safe_load(open('mega-config.yaml'))"

# Check for port conflicts
sudo lsof -i :3000
sudo lsof -i :18789

# Check Python dependencies
pip check

# Check file permissions
ls -la mega-config.yaml
```

#### Symptom: Components show "down" status

**Check individual components:**
```bash
# OpenClaw connection
curl http://localhost:18789/health

# Memory server
curl http://localhost:8000/memory/health

# MCP servers
curl http://localhost:8000/mcp/health
```

## Component-Specific Issues

### OpenClaw Adapter Issues

#### Connection Refused
```
Error: Failed to connect to OpenClaw: [Errno 111] Connection refused
```

**Solutions:**
1. **Check if OpenClaw is running:**
   ```bash
   ps aux | grep openclaw
   docker ps | grep openclaw
   ```

2. **Verify configuration:**
   ```yaml
   adapters:
     openclaw:
       host: "127.0.0.1"  # Correct host?
       port: 18789        # Correct port?
   ```

3. **Check firewall:**
   ```bash
   sudo ufw status
   sudo iptables -L
   ```

4. **Restart OpenClaw:**
   ```bash
   docker-compose restart openclaw
   ```

#### Authentication Failed
```
Error: OpenClaw authentication failed
```

**Solutions:**
1. **Verify auth token:**
   ```bash
   grep auth_token mega-config.yaml
   ```

2. **Check token format:**
   ```bash
   # Ensure token is properly set
   export OPENCLAW_TOKEN="your-token-here"
   ```

3. **Validate token on OpenClaw side**

### Memory (MemU) Issues

#### Database Connection Failed
```
Error: Can't connect to memory database
```

**SQLite Solutions:**
```bash
# Check database file permissions
ls -la megabot.db

# Check database integrity
sqlite3 megabot.db "PRAGMA integrity_check;"

# Recreate database if corrupted
rm megabot.db
python -c "from core.memory import init_db; init_db()"
```

**PostgreSQL Solutions:**
```bash
# Test connection
psql -h localhost -U megabot -d megabot -c "SELECT 1;"

# Check PostgreSQL status
sudo systemctl status postgresql

# Check connection string
grep database_url mega-config.yaml
```

#### Memory Loss on Restart
```
Error: Memory context lost after restart
```

**Solutions:**
1. **Check backup configuration:**
   ```yaml
   security:
     megabot_backup_key: "your-backup-key"
   ```

2. **Verify backup directory:**
   ```bash
   ls -la /path/to/backups/
   ```

3. **Enable automatic backups:**
   ```yaml
   database:
     backup_enabled: true
     backup_interval_hours: 12
   ```

### MCP Server Issues

#### Tool Not Available
```
Error: MCP tool 'filesystem' not found
```

**Solutions:**
1. **Check MCP server configuration:**
   ```yaml
   adapters:
     mcp:
       servers:
         - name: "filesystem"
           command: "npx"
           args: ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
   ```

2. **Verify MCP server installation:**
   ```bash
   npx @modelcontextprotocol/server-filesystem --help
   ```

3. **Check MCP logs:**
   ```bash
   docker-compose logs mcp-server
   ```

#### WebSocket Connection Failed
```
Error: MCP WebSocket connection failed
```

**Solutions:**
1. **Check WebSocket port:**
   ```bash
   netstat -tlnp | grep 3000
   ```

2. **Verify WebSocket configuration:**
   ```yaml
   adapters:
     mcp:
       bridge_type: "websocket"
       host: "127.0.0.1"
       port: 3000
   ```

3. **Check browser console for WebSocket errors**

### Messaging Platform Issues

#### Telegram Bot Not Responding

**Solutions:**
1. **Verify bot token:**
   ```bash
   curl "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getMe"
   ```

2. **Check webhook configuration:**
   ```bash
   curl "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getWebhookInfo"
   ```

3. **Restart messaging adapter:**
   ```bash
   docker-compose restart messaging
   ```

#### Discord Connection Failed
```
Error: Discord authentication failed
```

**Solutions:**
1. **Verify bot token format:**
   ```bash
   # Discord tokens start with 'Bot '
   echo "${DISCORD_BOT_TOKEN}" | head -c 10
   ```

2. **Check bot permissions:**
   - Visit Discord Developer Portal
   - Verify bot has necessary permissions
   - Check OAuth2 settings

3. **Validate intents:**
   ```yaml
   adapters:
     messaging:
       platforms:
         discord:
           intents: ["guilds", "guild_messages", "message_content"]
   ```

### LLM Provider Issues

#### API Key Invalid
```
Error: Invalid API key for provider
```

**Solutions:**
1. **Check environment variables:**
   ```bash
   echo $ANTHROPIC_API_KEY | head -c 10
   echo $OPENAI_API_KEY | head -c 10
   ```

2. **Verify key format:**
   - Anthropic: `sk-ant-...`
   - OpenAI: `sk-...`
   - Google: `AIza...`

3. **Test API key:**
   ```bash
   curl -H "Authorization: Bearer ${API_KEY}" \
        https://api.anthropic.com/v1/messages \
        -d '{"model": "claude-3-haiku-20240307", "max_tokens": 1, "messages": []}'
   ```

#### Rate Limit Exceeded
```
Error: API rate limit exceeded
```

**Solutions:**
1. **Check usage dashboard:**
   - Anthropic Console
   - OpenAI Dashboard
   - Provider-specific monitoring

2. **Implement rate limiting:**
   ```yaml
   llm:
     max_concurrent_requests: 3
     request_timeout: 60
   ```

3. **Add fallback providers:**
   ```yaml
   llm:
     fallback_providers: ["openai", "groq"]
   ```

### Permission and Security Issues

#### Action Blocked by Permissions
```
Error: Permission denied for action
```

**Solutions:**
1. **Check current permissions:**
   ```bash
   curl http://localhost:8000/admin/policies
   ```

2. **Update permission policies:**
   ```yaml
   policies:
     allow:
       - "git status"  # Add allowed actions
     deny:
       - "rm -rf /"    # Keep dangerous actions blocked
   ```

3. **Check permission levels:**
   ```yaml
   policies:
     default_permission: "ASK_EACH"  # Options: AUTO, ASK_EACH, NEVER
   ```

#### Approval Queue Issues

**Approvals not being processed:**
1. **Check admin configuration:**
   ```yaml
   admins:
     - "your_user_id"
   ```

2. **Verify admin commands:**
   ```bash
   # Try admin commands
   !health
   !policies
   ```

3. **Check approval queue:**
   ```bash
   curl http://localhost:8000/admin/approvals
   ```

### Database Issues

#### SQLite Database Locked
```
Error: database is locked
```

**Solutions:**
1. **Check for concurrent access:**
   ```bash
   lsof megabot.db
   ```

2. **Increase timeout:**
   ```yaml
   adapters:
     openclaw:
       database_url: "sqlite:///megabot.db?timeout=30"
   ```

3. **Use WAL mode:**
   ```sql
   PRAGMA journal_mode=WAL;
   PRAGMA synchronous=NORMAL;
   ```

#### PostgreSQL Connection Pool Exhausted
```
Error: connection pool exhausted
```

**Solutions:**
1. **Increase pool size:**
   ```yaml
   database:
     connection_pool_size: 20
     max_connections: 50
   ```

2. **Check for connection leaks:**
   ```sql
   SELECT count(*) FROM pg_stat_activity WHERE datname = 'megabot';
   ```

3. **Implement connection retry:**
   ```yaml
   database:
     connection_retry_attempts: 5
     connection_retry_delay: 1.0
   ```

### Performance Issues

#### High Memory Usage
```
Error: Memory usage exceeds limit
```

**Solutions:**
1. **Check memory configuration:**
   ```yaml
   performance:
     max_memory_usage: "4GB"
     memory_cleanup_interval: 300
   ```

2. **Monitor memory usage:**
   ```bash
   docker stats
   htop
   ```

3. **Enable memory profiling:**
   ```yaml
   monitoring:
     enable_memory_profiling: true
   ```

#### Slow Response Times
```
Error: Request timeout
```

**Solutions:**
1. **Check LLM provider latency:**
   ```bash
   time curl -X POST http://localhost:8000/chat \
     -d '{"message": "test"}'
   ```

2. **Optimize configuration:**
   ```yaml
   llm:
     max_concurrent_requests: 5
     request_timeout: 30
   ```

3. **Enable caching:**
   ```yaml
   llm:
     enable_caching: true
     cache_ttl: 3600
   ```

### Network Issues

#### WebSocket Connection Drops
```
Error: WebSocket connection lost
```

**Solutions:**
1. **Check network stability:**
   ```bash
   ping -c 5 8.8.8.8
   traceroute google.com
   ```

2. **Configure reconnection:**
   ```yaml
   adapters:
     openclaw:
       reconnect_attempts: 10
       reconnect_delay: 2.0
       heartbeat_interval: 30
   ```

3. **Check proxy/firewall settings**

#### SSL/TLS Certificate Issues
```
Error: SSL certificate verification failed
```

**Solutions:**
1. **Check certificate validity:**
   ```bash
   openssl s_client -connect api.anthropic.com:443 -servername api.anthropic.com
   ```

2. **Update CA certificates:**
   ```bash
   sudo apt update && sudo apt install ca-certificates
   ```

3. **Configure custom CA:**
   ```yaml
   system:
     ssl_ca_file: "/path/to/ca-certificates.crt"
   ```

### File System Issues

#### Permission Denied on File Operations
```
Error: Permission denied accessing file
```

**Solutions:**
1. **Check file permissions:**
   ```bash
   ls -la /path/to/file
   ```

2. **Fix permissions:**
   ```bash
   sudo chown -R megabot:megabot /path/to/workspace
   chmod 755 /path/to/workspace
   ```

3. **Check SELinux/AppArmor:**
   ```bash
   sudo getenforce  # SELinux
   sudo apparmor_status  # AppArmor
   ```

#### Disk Space Issues
```
Error: No space left on device
```

**Solutions:**
1. **Check disk usage:**
   ```bash
   df -h
   du -sh /path/to/megabot/data
   ```

2. **Clean up old logs:**
   ```bash
   find /var/log/megabot -name "*.log" -mtime +30 -delete
   ```

3. **Configure log rotation:**
   ```yaml
   monitoring:
     log_rotation: "daily"
     log_max_size: "100MB"
     log_retention_days: 30
   ```

## Advanced Troubleshooting

### Debug Mode

Enable verbose logging for detailed diagnostics:

```yaml
system:
  log_level: "DEBUG"

monitoring:
  enable_debug_logging: true
```

### Performance Profiling

```bash
# Enable Python profiling
export PYTHONPROFILE=1

# Run with profiling
python -m cProfile -s cumtime megabot/main.py

# Memory profiling
python -m memory_profiler megabot/main.py
```

### Network Debugging

```bash
# Monitor network connections
sudo netstat -tlnp
sudo ss -tlnp

# Packet capture (use with caution)
sudo tcpdump -i any port 3000 -w capture.pcap

# Check DNS resolution
nslookup api.anthropic.com
dig api.anthropic.com
```

### Database Debugging

```sql
-- Check table sizes
SELECT schemaname, tablename, n_tup_ins, n_tup_upd, n_tup_del
FROM pg_stat_user_tables;

-- Check long-running queries
SELECT pid, now() - pg_stat_activity.query_start AS duration, query
FROM pg_stat_activity
WHERE state = 'active' AND now() - pg_stat_activity.query_start > interval '1 minute';

-- Check locks
SELECT locktype, relation::regclass, mode, granted
FROM pg_locks
WHERE NOT granted;
```

## Recovery Procedures

### Emergency Shutdown
```bash
# Graceful shutdown
docker-compose down

# Force shutdown if needed
docker-compose down --remove-orphans --volumes
```

### Data Recovery
```bash
# From backup
tar -xzf backup.tar.gz -C /recovery/path

# Verify integrity
python -c "from core.memory import verify_backup; verify_backup('/path/to/backup')"

# Restore database
pg_restore -d megabot /path/to/backup.sql
```

### System Reset
```bash
# Reset to clean state
rm -rf data/ logs/ *.db
git checkout -- mega-config.yaml
docker-compose down --volumes --remove-orphans
docker-compose up -d
```

## Getting Help

### Log Collection
```bash
# Collect system information
uname -a > system_info.txt
python --version >> system_info.txt
pip list >> system_info.txt

# Collect recent logs
tail -n 1000 logs/megabot.log > recent_logs.txt
docker-compose logs --tail=1000 > container_logs.txt
```

### Support Information
When reporting issues, include:
- MegaBot version
- Operating system and version
- Python version
- Configuration file (with sensitive data redacted)
- Recent log entries
- Steps to reproduce the issue
- Expected vs actual behavior

### Community Resources
- GitHub Issues: Report bugs and request features
- Documentation Wiki: Extended troubleshooting guides
- Community Discord: Real-time help and discussions

## Prevention

### Regular Maintenance
```bash
# Weekly maintenance script
#!/bin/bash
# Update dependencies
pip install --upgrade -r requirements.txt

# Check disk space
df -h / | awk 'NR==2 {if ($5 > 80) print "WARNING: Disk usage above 80%"}'

# Verify backups
find /backups -name "*.sql" -mtime +7 -exec echo "Old backup: {}" \;

# Health check
curl -f http://localhost:8000/health || echo "Health check failed"
```

### Monitoring Setup
```yaml
monitoring:
  alerts:
    enabled: true
    email_recipients: ["admin@company.com"]
    slack_webhook: "YOUR_SLACK_WEBHOOK_URL"
    alert_conditions:
      - "component_down"
      - "high_memory_usage"
      - "disk_space_low"
      - "backup_failed"
```

This troubleshooting guide covers the most common issues. For complex problems or production deployments, consider engaging professional support or consulting the community forums.</content>
<parameter name="filePath">docs/deployment/troubleshooting.md