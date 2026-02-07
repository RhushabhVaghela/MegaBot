# Webhook Integration Guide

MegaBot supports webhook integrations for event-driven communication, enabling external services to receive real-time notifications about MegaBot activities and respond to events programmatically.

## Overview

Webhooks allow external services to be notified when specific events occur within MegaBot, enabling integration with CI/CD pipelines, monitoring systems, chat platforms, and other automation tools.

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   MegaBot       │    │   Webhook       │    │   External      │
│   Events        │───►│   Dispatcher    │───►│   Service       │
├─────────────────┤    ├─────────────────┤    ├─────────────────┤
│ • Chat Messages │    │ • Event         │    │ • CI/CD         │
│ • Tool Results  │    │ • Filtering     │    │ • Monitoring    │
│ • Status Updates│    │ • Retry Logic   │    │ • Chat Apps     │
│ • Errors        │    │ • Signing       │    │ • Automation    │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

## Webhook Configuration

### Setting Up Webhooks

Webhooks are configured through the MegaBot configuration file or API:

```yaml
# mega-config.yaml - Webhook configuration
webhooks:
  enabled: true
  secret_key: "${WEBHOOK_SECRET_KEY}"  # For signature verification

  endpoints:
    - url: "https://api.github.com/repos/owner/repo/dispatches"
      events: ["deployment_completed", "error_occurred"]
      headers:
        Authorization: "token ${GITHUB_TOKEN}"
        Accept: "application/vnd.github.v3+json"

     - url: "https://hooks.slack.com/services/YOUR_SLACK_WEBHOOK_URL"
       events: ["chat_message", "tool_executed"]
       filters:
         platforms: ["slack"]
         users: ["admin_user"]

    - url: "https://your-monitoring-service.com/webhook"
      events: ["*"]  # All events
      retry_policy:
        max_attempts: 5
        backoff_multiplier: 2.0
        initial_delay: 1.0
```

### Dynamic Webhook Registration

Register webhooks programmatically via API:

```bash
# Register a webhook
curl -X POST http://localhost:8000/api/webhooks \
  -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://your-service.com/webhook",
    "events": ["chat_message", "tool_result"],
    "secret": "your_webhook_secret",
    "filters": {
      "platforms": ["telegram", "discord"],
      "min_severity": "info"
    }
  }'
```

## Event Types

### Core Events

#### Chat Events

**`chat_message_received`**
Triggered when MegaBot receives a message from any platform.

```json
{
  "event": "chat_message_received",
  "id": "evt_123456",
  "timestamp": 1640995200,
  "data": {
    "message_id": "msg_789",
    "platform": "telegram",
    "user_id": "user_123",
    "username": "john_doe",
    "content": "Hello MegaBot!",
    "attachments": [],
    "metadata": {
      "chat_id": "chat_456",
      "platform_specific": {
        "message_thread_id": "thread_789"
      }
    }
  }
}
```

**`chat_message_sent`**
Triggered when MegaBot sends a message.

```json
{
  "event": "chat_message_sent",
  "id": "evt_123457",
  "timestamp": 1640995201,
  "data": {
    "message_id": "msg_790",
    "platform": "telegram",
    "recipient_id": "user_123",
    "content": "Hello! How can I help you today?",
    "message_type": "text",
    "metadata": {
      "in_response_to": "msg_789",
      "model_used": "claude-3-5-sonnet"
    }
  }
}
```

#### Tool Execution Events

**`tool_execution_started`**
Triggered when a tool execution begins.

```json
{
  "event": "tool_execution_started",
  "id": "evt_123458",
  "timestamp": 1640995202,
  "data": {
    "execution_id": "exec_123",
    "tool_name": "run_tests",
    "parameters": {
      "test_suite": "unit",
      "verbose": true
    },
    "user_id": "user_123",
    "platform": "web",
    "estimated_duration": 30
  }
}
```

**`tool_execution_completed`**
Triggered when a tool execution completes successfully.

```json
{
  "event": "tool_execution_completed",
  "id": "evt_123459",
  "timestamp": 1640995232,
  "data": {
    "execution_id": "exec_123",
    "tool_name": "run_tests",
    "status": "success",
    "result": {
      "passed": 15,
      "failed": 0,
      "skipped": 2,
      "duration": 28.5
    },
    "output": "All tests passed successfully\nCoverage: 95%",
    "metadata": {
      "exit_code": 0,
      "resource_usage": {
        "cpu_percent": 45.2,
        "memory_mb": 256
      }
    }
  }
}
```

**`tool_execution_failed`**
Triggered when a tool execution fails.

```json
{
  "event": "tool_execution_failed",
  "id": "evt_123460",
  "timestamp": 1640995210,
  "data": {
    "execution_id": "exec_124",
    "tool_name": "deploy_app",
    "status": "failed",
    "error": {
      "type": "DeploymentError",
      "message": "Failed to connect to database",
      "details": "Connection timeout after 30 seconds"
    },
    "partial_output": "Starting deployment...\nConnecting to database...",
    "metadata": {
      "exit_code": 1,
      "retry_count": 0
    }
  }
}
```

#### System Events

**`system_status_changed`**
Triggered when MegaBot's operational status changes.

```json
{
  "event": "system_status_changed",
  "id": "evt_123461",
  "timestamp": 1640995200,
  "data": {
    "old_status": "healthy",
    "new_status": "degraded",
    "reason": "High memory usage detected",
    "details": {
      "memory_usage_percent": 85,
      "cpu_usage_percent": 72,
      "active_connections": 150
    },
    "severity": "warning"
  }
}
```

**`error_occurred`**
Triggered when errors occur within MegaBot.

```json
{
  "event": "error_occurred",
  "id": "evt_123462",
  "timestamp": 1640995205,
  "data": {
    "error_id": "err_789",
    "type": "LLMProviderError",
    "message": "Anthropic API rate limit exceeded",
    "severity": "error",
    "context": {
      "user_id": "user_123",
      "operation": "chat_response",
      "provider": "anthropic"
    },
    "stack_trace": "...",
    "metadata": {
      "retry_eligible": true,
      "fallback_available": true
    }
  }
}
```

#### Memory Events

**`memory_lesson_learned`**
Triggered when MegaBot learns a new lesson.

```json
{
  "event": "memory_lesson_learned",
  "id": "evt_123463",
  "timestamp": 1640995200,
  "data": {
    "lesson_id": "lesson_456",
    "type": "security_pattern",
    "title": "Input validation prevents SQL injection",
    "content": "Always validate and sanitize user inputs before database operations",
    "confidence": 0.95,
    "source": "tool_execution_failed",
    "tags": ["security", "database", "validation"]
  }
}
```

#### Loki Mode Events

**`loki_execution_started`**
Triggered when Loki Mode begins autonomous development.

```json
{
  "event": "loki_execution_started",
  "id": "evt_123464",
  "timestamp": 1640995200,
  "data": {
    "execution_id": "loki_789",
    "prd_summary": "Build a task management web application",
    "estimated_tasks": 8,
    "user_id": "user_123",
    "platform": "web"
  }
}
```

**`loki_execution_completed`**
Triggered when Loki Mode completes.

```json
{
  "event": "loki_execution_completed",
  "id": "evt_123465",
  "timestamp": 1640995500,
  "data": {
    "execution_id": "loki_789",
    "status": "success",
    "duration_seconds": 300,
    "tasks_completed": 8,
    "deployment_url": "https://my-app.vercel.app",
    "summary": {
      "code_lines": 1250,
      "tests_passed": 45,
      "security_issues": 0
    }
  }
}
```

## Event Filtering

### Filter Configuration

Filter events based on various criteria:

```yaml
webhooks:
  endpoints:
    - url: "https://slack-webhook.com/notify"
      events: ["error_occurred", "tool_execution_failed"]
      filters:
        # Platform filtering
        platforms: ["telegram", "discord"]

        # User filtering
        users: ["admin_user", "moderator_user"]

        # Severity filtering
        min_severity: "warning"  # debug, info, warning, error, critical

        # Content filtering
        content_filters:
          - type: "contains"
            field: "error.message"
            value: "database"

          - type: "regex"
            field: "data.tool_name"
            pattern: "^deploy_"

        # Time-based filtering
        time_window:
          start_hour: 9   # 9 AM
          end_hour: 17    # 5 PM
          timezone: "UTC"
```

### Advanced Filtering

Programmatic event filtering:

```python
class WebhookFilter:
    def __init__(self, config):
        self.config = config

    def should_send_event(self, event):
        """Determine if event should be sent to webhook."""

        # Platform filter
        if self.config.get('platforms'):
            if event['data'].get('platform') not in self.config['platforms']:
                return False

        # Severity filter
        min_severity = self.config.get('min_severity', 'debug')
        event_severity = event['data'].get('severity', 'info')
        if self.get_severity_level(event_severity) < self.get_severity_level(min_severity):
            return False

        # Content filters
        for filter_config in self.config.get('content_filters', []):
            if not self.matches_content_filter(event, filter_config):
                return False

        return True

    def matches_content_filter(self, event, filter_config):
        """Check if event matches content filter."""
        field_path = filter_config['field'].split('.')
        value = self.get_nested_value(event, field_path)

        if filter_config['type'] == 'contains':
            return filter_config['value'] in str(value)
        elif filter_config['type'] == 'regex':
            import re
            return re.search(filter_config['pattern'], str(value))

        return True
```

## Security

### Webhook Signing

All webhooks are signed using HMAC-SHA256 for verification:

```python
import hmac
import hashlib
import json

class WebhookSigner:
    def __init__(self, secret_key):
        self.secret_key = secret_key.encode()

    def sign_payload(self, payload):
        """Sign webhook payload."""
        payload_str = json.dumps(payload, separators=(',', ':'))
        signature = hmac.new(
            self.secret_key,
            payload_str.encode(),
            hashlib.sha256
        ).hexdigest()

        return {
            'signature': f'sha256={signature}',
            'payload': payload_str
        }

    def verify_signature(self, payload, signature):
        """Verify webhook signature."""
        expected = self.sign_payload(payload)['signature']
        return hmac.compare_digest(expected, signature)
```

### Signature Verification

Verify webhook signatures in your endpoint:

```python
# webhook_receiver.py
from webhook_signer import WebhookSigner

def verify_webhook_signature(request):
    """Verify incoming webhook signature."""
    signature = request.headers.get('X-MegaBot-Signature')
    payload = request.get_json()

    signer = WebhookSigner('your_webhook_secret')
    return signer.verify_signature(payload, signature)

@app.route('/webhook', methods=['POST'])
def handle_webhook():
    if not verify_webhook_signature(request):
        return 'Invalid signature', 401

    # Process webhook
    event = request.get_json()
    process_event(event)

    return 'OK', 200
```

### Security Headers

MegaBot sends security headers with all webhooks:

```
X-MegaBot-Signature: sha256=abc123...
X-MegaBot-Event: chat_message_received
X-MegaBot-Delivery: evt_123456
X-MegaBot-Timestamp: 1640995200
User-Agent: MegaBot-Webhook/1.0
```

## Retry Logic

### Automatic Retries

Failed webhook deliveries are automatically retried:

```python
class WebhookRetryHandler:
    def __init__(self, max_attempts=5, backoff_multiplier=2.0, initial_delay=1.0):
        self.max_attempts = max_attempts
        self.backoff_multiplier = backoff_multiplier
        self.initial_delay = initial_delay

    async def send_with_retry(self, url, payload, headers):
        """Send webhook with retry logic."""
        delay = self.initial_delay

        for attempt in range(self.max_attempts):
            try:
                response = await self.send_webhook(url, payload, headers)
                if response.status_code < 500:
                    return response
            except Exception as e:
                print(f"Webhook attempt {attempt + 1} failed: {e}")

            if attempt < self.max_attempts - 1:
                await asyncio.sleep(delay)
                delay *= self.backoff_multiplier

        raise Exception(f"Webhook failed after {self.max_attempts} attempts")
```

### Retry Configuration

Configure retry behavior per webhook:

```yaml
webhooks:
  endpoints:
    - url: "https://critical-service.com/webhook"
      retry_policy:
        max_attempts: 10
        backoff_multiplier: 1.5
        initial_delay: 0.5
        max_delay: 300  # 5 minutes

    - url: "https://best-effort-service.com/webhook"
      retry_policy:
        max_attempts: 2
        backoff_multiplier: 1.0
        initial_delay: 1.0
```

## Integration Examples

### GitHub Integration

Trigger GitHub Actions on MegaBot events:

```yaml
# .github/workflows/megabot-events.yml
name: MegaBot Events

on:
  repository_dispatch:
    types: [deployment_completed, error_occurred]

jobs:
  handle_event:
    runs-on: ubuntu-latest
    steps:
      - name: Handle Deployment Success
        if: github.event.action == 'deployment_completed'
        run: |
          echo "MegaBot deployment completed!"
          echo "URL: ${{ github.event.client_payload.url }}"

      - name: Handle Error
        if: github.event.action == 'error_occurred'
        run: |
          echo "MegaBot error occurred!"
          echo "Error: ${{ github.event.client_payload.error.message }}"
```

### Slack Notifications

Send notifications to Slack channels:

```python
# slack_webhook_handler.py
import requests
import json

def send_slack_notification(webhook_url, event):
    """Send formatted Slack notification."""

    event_type = event['event']
    data = event['data']

    if event_type == 'tool_execution_failed':
        color = 'danger'
        title = '🚨 Tool Execution Failed'
        message = f"*{data['tool_name']}* failed: {data['error']['message']}"

    elif event_type == 'deployment_completed':
        color = 'good'
        title = '✅ Deployment Completed'
        message = f"Successfully deployed to {data.get('url', 'production')}"

    else:
        color = 'good'
        title = f'📢 {event_type.replace("_", " ").title()}'
        message = f"Event received from MegaBot"

    payload = {
        "attachments": [{
            "color": color,
            "title": title,
            "text": message,
            "fields": [
                {
                    "title": "Timestamp",
                    "value": f"<@{event['timestamp']}|{event['timestamp']}>",
                    "short": True
                },
                {
                    "title": "Event ID",
                    "value": event['id'],
                    "short": True
                }
            ]
        }]
    }

    requests.post(webhook_url, json=payload)
```

### Monitoring Integration

Integrate with monitoring systems like Datadog or Prometheus:

```python
# datadog_webhook_handler.py
from datadog import api, initialize

def handle_megabot_event(event):
    """Send metrics and events to Datadog."""

    initialize(api_key='your_api_key', app_key='your_app_key')

    event_type = event['event']
    data = event['data']

    # Send event
    api.Event.create(
        title=f"MegaBot {event_type}",
        text=json.dumps(data, indent=2),
        tags=['source:megabot', f'event:{event_type}'],
        alert_type='info'
    )

    # Send metrics
    if event_type == 'tool_execution_completed':
        api.Metric.send(
            metric='megabot.tool_execution.duration',
            points=data['result']['duration'],
            tags=['tool:' + data['tool_name'], 'status:success']
        )

    elif event_type == 'error_occurred':
        api.Metric.send(
            metric='megabot.errors.count',
            points=1,
            tags=['error_type:' + data['type'], 'severity:' + data.get('severity', 'unknown')]
        )
```

### CI/CD Integration

Trigger Jenkins/GitLab CI pipelines:

```yaml
# .gitlab-ci.yml
stages:
  - deploy

megabot_deployment:
  stage: deploy
  script:
    - echo "MegaBot signaled deployment completion"
    - echo "Version: $MEGABOT_VERSION"
    - echo "URL: $MEGABOT_DEPLOY_URL"
  only:
    variables:
      - $MEGABOT_DEPLOY_TRIGGER == "true"
```

## Testing Webhooks

### Local Testing

Test webhooks locally using tools like ngrok or webhook.site:

```bash
# Using ngrok to expose local endpoint
ngrok http 3000

# Configure webhook to use ngrok URL
curl -X POST http://localhost:8000/api/webhooks \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://abc123.ngrok.io/webhook",
    "events": ["chat_message"]
  }'
```

### Webhook Testing Tools

Use webhook testing services:

```python
# webhook_tester.py
import requests
import time

def test_webhook_delivery(webhook_url, test_event):
    """Test webhook delivery with retry logic."""

    start_time = time.time()

    try:
        response = requests.post(
            webhook_url,
            json=test_event,
            headers={
                'Content-Type': 'application/json',
                'X-MegaBot-Signature': 'sha256=test_signature'
            },
            timeout=10
        )

        delivery_time = time.time() - start_time

        return {
            'status_code': response.status_code,
            'delivery_time': delivery_time,
            'response_body': response.text,
            'success': response.status_code in [200, 201, 202]
        }

    except requests.exceptions.RequestException as e:
        return {
            'error': str(e),
            'delivery_time': time.time() - start_time,
            'success': False
        }
```

## Monitoring and Analytics

### Webhook Metrics

Track webhook delivery performance:

```python
class WebhookMetrics:
    def __init__(self):
        self.metrics = {
            'deliveries_total': 0,
            'deliveries_success': 0,
            'deliveries_failed': 0,
            'delivery_times': [],
            'retries_total': 0
        }

    def record_delivery(self, success, delivery_time, retry_count):
        """Record webhook delivery metrics."""
        self.metrics['deliveries_total'] += 1

        if success:
            self.metrics['deliveries_success'] += 1
        else:
            self.metrics['deliveries_failed'] += 1

        self.metrics['delivery_times'].append(delivery_time)
        self.metrics['retries_total'] += retry_count

    def get_stats(self):
        """Get webhook delivery statistics."""
        total = self.metrics['deliveries_total']
        success_rate = self.metrics['deliveries_success'] / total if total > 0 else 0
        avg_delivery_time = sum(self.metrics['delivery_times']) / len(self.metrics['delivery_times']) if self.metrics['delivery_times'] else 0

        return {
            'total_deliveries': total,
            'success_rate': success_rate,
            'average_delivery_time': avg_delivery_time,
            'total_retries': self.metrics['retries_total']
        }
```

### Alerting

Set up alerts for webhook failures:

```yaml
# Alert configuration
webhook_alerts:
  enabled: true
  failure_threshold: 0.95  # Alert if success rate drops below 95%
  delivery_timeout_threshold: 30  # Alert if delivery takes longer than 30s

  channels:
    - type: "slack"
      webhook_url: "${SLACK_ALERT_WEBHOOK}"
      message: "Webhook delivery failure detected"

    - type: "email"
      recipients: ["admin@megabot.ai"]
      subject: "MegaBot Webhook Alert"
```

## Best Practices

### Webhook Design

1. **Idempotency**: Make webhook handlers idempotent to handle retries
2. **Asynchronous Processing**: Process webhooks asynchronously to avoid timeouts
3. **Validation**: Always validate webhook signatures and payload structure
4. **Error Handling**: Implement proper error handling and logging
5. **Rate Limiting**: Implement rate limiting to prevent abuse

### Security Considerations

1. **Signature Verification**: Always verify webhook signatures
2. **HTTPS Only**: Only accept webhooks over HTTPS
3. **Secret Management**: Store webhook secrets securely
4. **Access Control**: Implement proper access controls on webhook endpoints
5. **Logging**: Log all webhook attempts for audit purposes

### Performance Optimization

1. **Batch Processing**: Batch related events when possible
2. **Queueing**: Use queues for reliable webhook delivery
3. **Monitoring**: Monitor webhook delivery success rates and latency
4. **Load Balancing**: Distribute webhook load across multiple instances

This webhook system enables seamless integration between MegaBot and external services, providing real-time event-driven automation capabilities.