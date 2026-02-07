# WebSocket API Specification

MegaBot provides real-time communication capabilities through WebSocket connections, enabling bidirectional, event-driven interactions for applications requiring live updates and interactive features.

## Overview

The WebSocket API enables real-time communication between clients and MegaBot, supporting features like live chat, real-time notifications, collaborative editing, and streaming responses.

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Client        │◄──►│   WebSocket     │◄──►│   MegaBot       │
│   Application   │    │   Gateway       │    │   Core          │
├─────────────────┤    ├─────────────────┤    ├─────────────────┤
│ • Browser       │    │ • Connection    │    │ • Orchestrator  │
│ • Mobile App    │    │ • Message       │    │ • Memory        │
│ • Desktop App   │    │ • Authentication│    │ • Adapters      │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

## Connection Establishment

### WebSocket URL

```
ws://localhost:8000/ws
wss://api.megabot.ai/ws  # Production with SSL
```

### Connection Parameters

WebSocket connections support URL query parameters for authentication and configuration:

```javascript
// Basic connection
const ws = new WebSocket('ws://localhost:8000/ws');

// With authentication
const ws = new WebSocket('ws://localhost:8000/ws?token=your_jwt_token');

// With user context
const ws = new WebSocket('ws://localhost:8000/ws?user_id=user123&platform=web');
```

**Query Parameters:**
- `token`: JWT authentication token
- `user_id`: User identifier for session tracking
- `platform`: Platform identifier (web, mobile, desktop)
- `session_id`: Existing session to resume
- `compression`: Enable message compression (gzip)

### Authentication

#### JWT Token Authentication

```javascript
// Obtain JWT token via REST API
const response = await fetch('/api/auth/login', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ username: 'user', password: 'pass' })
});

const { token } = await response.json();

// Use token in WebSocket connection
const ws = new WebSocket(`ws://localhost:8000/ws?token=${token}`);
```

#### API Key Authentication

```javascript
// Direct API key authentication
const ws = new WebSocket('ws://localhost:8000/ws', {
  headers: {
    'Authorization': 'Bearer your_api_key',
    'X-API-Key': 'your_api_key'
  }
});
```

## Message Protocol

### Message Format

All WebSocket messages follow a standardized JSON format:

```typescript
interface WebSocketMessage {
  id: string;           // Unique message identifier
  type: string;         // Message type (see Message Types)
  payload: any;         // Message-specific data
  timestamp: number;    // Unix timestamp
  metadata?: {          // Optional metadata
    user_id?: string;
    session_id?: string;
    platform?: string;
    [key: string]: any;
  };
}
```

### Message Types

#### Connection Messages

**Connection Established (`connection_established`)**
```json
{
  "id": "msg_123",
  "type": "connection_established",
  "payload": {
    "session_id": "sess_456",
    "user_id": "user_789",
    "capabilities": ["chat", "realtime", "streaming"]
  },
  "timestamp": 1640995200
}
```

**Connection Error (`connection_error`)**
```json
{
  "id": "msg_124",
  "type": "connection_error",
  "payload": {
    "error": "authentication_failed",
    "message": "Invalid token provided",
    "code": 401
  },
  "timestamp": 1640995201
}
```

#### Chat Messages

**Send Message (`chat_send`)**
```json
{
  "id": "msg_125",
  "type": "chat_send",
  "payload": {
    "content": "Hello MegaBot!",
    "platform": "web",
    "attachments": []
  },
  "metadata": {
    "user_id": "user_789",
    "session_id": "sess_456"
  }
}
```

**Receive Message (`chat_receive`)**
```json
{
  "id": "msg_126",
  "type": "chat_receive",
  "payload": {
    "content": "Hello! How can I help you today?",
    "sender": "assistant",
    "platform": "megabot",
    "timestamp": 1640995202
  }
}
```

**Streaming Response (`chat_stream`)**
```json
{
  "id": "msg_127",
  "type": "chat_stream",
  "payload": {
    "chunk": "Hello",
    "is_complete": false,
    "sequence": 1
  }
}
```

#### Real-time Updates

**Status Update (`status_update`)**
```json
{
  "id": "msg_128",
  "type": "status_update",
  "payload": {
    "status": "processing",
    "progress": 0.75,
    "message": "Analyzing codebase...",
    "task_id": "task_123"
  }
}
```

**Notification (`notification`)**
```json
{
  "id": "msg_129",
  "type": "notification",
  "payload": {
    "type": "info",
    "title": "Task Completed",
    "message": "Your code review is ready",
    "action_url": "/reviews/123",
    "dismissible": true
  }
}
```

#### Tool Execution

**Tool Call (`tool_call`)**
```json
{
  "id": "msg_130",
  "type": "tool_call",
  "payload": {
    "tool_name": "run_tests",
    "parameters": {
      "test_suite": "unit",
      "verbose": true
    },
    "execution_id": "exec_456"
  }
}
```

**Tool Result (`tool_result`)**
```json
{
  "id": "msg_131",
  "type": "tool_result",
  "payload": {
    "execution_id": "exec_456",
    "status": "completed",
    "result": {
      "passed": 15,
      "failed": 0,
      "duration": 2.3
    },
    "output": "All tests passed successfully"
  }
}
```

## Real-time Features

### Live Chat

Full-duplex chat with real-time message delivery:

```javascript
class ChatClient {
  constructor(wsUrl) {
    this.ws = new WebSocket(wsUrl);
    this.setupEventHandlers();
  }

  setupEventHandlers() {
    this.ws.onmessage = (event) => {
      const message = JSON.parse(event.data);

      switch (message.type) {
        case 'chat_receive':
          this.displayMessage(message.payload);
          break;
        case 'chat_stream':
          this.updateStreamingMessage(message.payload);
          break;
        case 'status_update':
          this.updateStatus(message.payload);
          break;
      }
    };
  }

  sendMessage(content) {
    const message = {
      id: generateId(),
      type: 'chat_send',
      payload: { content },
      timestamp: Date.now()
    };

    this.ws.send(JSON.stringify(message));
  }
}
```

### Streaming Responses

Real-time streaming of AI responses for improved user experience:

```javascript
class StreamingChat {
  constructor(ws) {
    this.ws = ws;
    this.currentStream = null;
  }

  handleStreamChunk(chunk) {
    if (!this.currentStream) {
      this.currentStream = {
        id: chunk.id,
        content: '',
        element: this.createMessageElement()
      };
    }

    this.currentStream.content += chunk.chunk;
    this.currentStream.element.textContent = this.currentStream.content;

    if (chunk.is_complete) {
      this.finalizeStream();
    }
  }

  finalizeStream() {
    // Mark as complete, enable actions
    this.currentStream.element.classList.add('complete');
    this.currentStream = null;
  }
}
```

### Collaborative Features

Support for multi-user collaboration and shared workspaces:

```javascript
class CollaborativeSession {
  constructor(ws, sessionId) {
    this.ws = ws;
    this.sessionId = sessionId;
    this.participants = new Set();
  }

  joinSession() {
    this.ws.send(JSON.stringify({
      id: generateId(),
      type: 'session_join',
      payload: { session_id: this.sessionId }
    }));
  }

  broadcastAction(action, data) {
    this.ws.send(JSON.stringify({
      id: generateId(),
      type: 'collaborative_action',
      payload: {
        session_id: this.sessionId,
        action: action,
        data: data
      }
    }));
  }

  handleCollaborativeAction(message) {
    const { action, data, user_id } = message.payload;

    switch (action) {
      case 'cursor_move':
        this.updateCursor(user_id, data.position);
        break;
      case 'text_edit':
        this.applyTextEdit(data);
        break;
      case 'file_open':
        this.openSharedFile(data.file_path);
        break;
    }
  }
}
```

## Error Handling

### Connection Errors

Handle WebSocket connection failures gracefully:

```javascript
class ResilientWebSocket {
  constructor(url, options = {}) {
    this.url = url;
    this.options = {
      maxRetries: 5,
      retryDelay: 1000,
      ...options
    };
    this.connect();
  }

  connect() {
    try {
      this.ws = new WebSocket(this.url);
      this.setupEventHandlers();
    } catch (error) {
      this.handleConnectionError(error);
    }
  }

  setupEventHandlers() {
    this.ws.onopen = () => {
      console.log('WebSocket connected');
      this.retryCount = 0;
    };

    this.ws.onclose = (event) => {
      if (!event.wasClean) {
        this.handleReconnection();
      }
    };

    this.ws.onerror = (error) => {
      console.error('WebSocket error:', error);
    };
  }

  handleReconnection() {
    if (this.retryCount < this.options.maxRetries) {
      setTimeout(() => {
        this.retryCount++;
        console.log(`Reconnecting... (${this.retryCount}/${this.options.maxRetries})`);
        this.connect();
      }, this.options.retryDelay * this.retryCount);
    } else {
      this.onConnectionFailed();
    }
  }
}
```

### Message Validation

Validate incoming and outgoing messages:

```javascript
class MessageValidator {
  static validateMessage(message) {
    // Required fields
    if (!message.id || !message.type || !message.payload) {
      throw new Error('Missing required message fields');
    }

    // Type-specific validation
    switch (message.type) {
      case 'chat_send':
        this.validateChatMessage(message.payload);
        break;
      case 'tool_call':
        this.validateToolCall(message.payload);
        break;
    }

    return true;
  }

  static validateChatMessage(payload) {
    if (!payload.content || typeof payload.content !== 'string') {
      throw new Error('Invalid chat message content');
    }

    if (payload.content.length > 10000) {
      throw new Error('Message content too long');
    }
  }
}
```

## Security Considerations

### Transport Security

Always use WSS in production:

```javascript
// Production connection
const ws = new WebSocket('wss://api.megabot.ai/ws?token=' + token);

// Certificate validation
ws.addEventListener('open', () => {
  // Verify certificate fingerprint if required
  console.log('Secure connection established');
});
```

### Authentication Security

Implement proper token management:

```javascript
class SecureWebSocket {
  constructor(baseUrl) {
    this.baseUrl = baseUrl;
    this.tokenManager = new TokenManager();
  }

  async connect() {
    const token = await this.tokenManager.getValidToken();
    const ws = new WebSocket(`${this.baseUrl}?token=${token}`);

    ws.onmessage = (event) => {
      const message = JSON.parse(event.data);

      // Verify message integrity
      if (this.verifyMessageIntegrity(message)) {
        this.handleMessage(message);
      }
    };

    return ws;
  }

  verifyMessageIntegrity(message) {
    // Implement message signing/verification if required
    return true;
  }
}
```

### Rate Limiting

Respect API rate limits:

```javascript
class RateLimitedWebSocket {
  constructor(ws, limits = {}) {
    this.ws = ws;
    this.limits = {
      messagesPerSecond: 10,
      maxMessageSize: 1024 * 1024, // 1MB
      ...limits
    };
    this.messageQueue = [];
    this.isProcessing = false;
  }

  send(message) {
    if (this.messageQueue.length >= 100) {
      throw new Error('Message queue full');
    }

    this.messageQueue.push(message);
    this.processQueue();
  }

  async processQueue() {
    if (this.isProcessing || this.messageQueue.length === 0) {
      return;
    }

    this.isProcessing = true;

    while (this.messageQueue.length > 0) {
      const message = this.messageQueue.shift();

      // Rate limiting check
      if (this.checkRateLimit()) {
        this.ws.send(JSON.stringify(message));
        await this.delay(100); // 10 messages per second
      } else {
        // Re-queue message
        this.messageQueue.unshift(message);
        break;
      }
    }

    this.isProcessing = false;
  }

  checkRateLimit() {
    // Implement rate limiting logic
    return true;
  }
}
```

## Performance Optimization

### Message Batching

Batch multiple small messages to reduce overhead:

```javascript
class MessageBatcher {
  constructor(ws, batchSize = 10, batchDelay = 100) {
    this.ws = ws;
    this.batchSize = batchSize;
    this.batchDelay = batchDelay;
    this.batch = [];
    this.batchTimer = null;
  }

  send(message) {
    this.batch.push(message);

    if (this.batch.length >= this.batchSize) {
      this.flush();
    } else if (!this.batchTimer) {
      this.batchTimer = setTimeout(() => this.flush(), this.batchDelay);
    }
  }

  flush() {
    if (this.batch.length === 0) return;

    if (this.batch.length === 1) {
      // Single message, send directly
      this.ws.send(JSON.stringify(this.batch[0]));
    } else {
      // Batch messages
      const batchMessage = {
        id: generateId(),
        type: 'batch',
        payload: { messages: this.batch },
        timestamp: Date.now()
      };
      this.ws.send(JSON.stringify(batchMessage));
    }

    this.batch = [];
    if (this.batchTimer) {
      clearTimeout(this.batchTimer);
      this.batchTimer = null;
    }
  }
}
```

### Compression

Enable compression for large messages:

```javascript
// Server-side compression
const WebSocket = require('ws');
const wss = new WebSocket.Server({
  port: 3000,
  perMessageDeflate: {
    zlibDeflateOptions: {
      chunkSize: 1024,
      memLevel: 7,
      level: 3
    },
    zlibInflateOptions: {
      chunkSize: 10 * 1024
    },
    clientNoContextTakeover: true,
    serverNoContextTakeover: true,
    serverMaxWindowBits: 10,
    concurrencyLimit: 10,
    threshold: 1024
  }
});

// Client-side compression
const ws = new WebSocket('ws://localhost:8000/ws', {
  perMessageDeflate: true
});
```

## Client Libraries

### JavaScript/TypeScript

```javascript
// megabot-websocket.js
class MegaBotWebSocket {
  constructor(options = {}) {
    this.options = {
      url: 'ws://localhost:8000/ws',
      reconnect: true,
      maxRetries: 5,
      ...options
    };

    this.connect();
  }

  connect() {
    this.ws = new WebSocket(this.options.url);
    this.setupEventHandlers();
  }

  // ... implementation
}

export default MegaBotWebSocket;
```

### Python

```python
# megabot_websocket.py
import asyncio
import websockets
import json

class MegaBotWebSocketClient:
    def __init__(self, url, token=None):
        self.url = url
        self.token = token

    async def connect(self):
        headers = {}
        if self.token:
            headers['Authorization'] = f'Bearer {self.token}'

        async with websockets.connect(self.url, extra_headers=headers) as ws:
            await self.handle_connection(ws)

    async def handle_connection(self, ws):
        # Connection handling logic
        pass

# Usage
client = MegaBotWebSocketClient('ws://localhost:8000/ws', token='your_token')
asyncio.run(client.connect())
```

## Monitoring and Debugging

### Connection Monitoring

Track connection health and performance:

```javascript
class WebSocketMonitor {
  constructor(ws) {
    this.ws = ws;
    this.metrics = {
      messagesSent: 0,
      messagesReceived: 0,
      bytesSent: 0,
      bytesReceived: 0,
      connectionTime: Date.now(),
      reconnectCount: 0
    };

    this.setupMonitoring();
  }

  setupMonitoring() {
    const originalSend = this.ws.send;
    this.ws.send = (data) => {
      this.metrics.messagesSent++;
      this.metrics.bytesSent += data.length;
      return originalSend.call(this.ws, data);
    };

    this.ws.addEventListener('message', (event) => {
      this.metrics.messagesReceived++;
      this.metrics.bytesReceived += event.data.length;
    });
  }

  getMetrics() {
    const uptime = Date.now() - this.metrics.connectionTime;
    return {
      ...this.metrics,
      uptime,
      messagesPerSecond: this.metrics.messagesReceived / (uptime / 1000)
    };
  }
}
```

### Debug Logging

Enable detailed logging for troubleshooting:

```javascript
class DebugWebSocket extends WebSocket {
  constructor(url, protocols) {
    super(url, protocols);
    this.debug = true;
    this.messageLog = [];
  }

  send(data) {
    if (this.debug) {
      console.log('WS SEND:', data);
      this.messageLog.push({ type: 'send', data, timestamp: Date.now() });
    }
    super.send(data);
  }

  addEventListener(type, listener) {
    if (type === 'message') {
      const debugListener = (event) => {
        if (this.debug) {
          console.log('WS RECEIVE:', event.data);
          this.messageLog.push({ type: 'receive', data: event.data, timestamp: Date.now() });
        }
        listener(event);
      };
      super.addEventListener(type, debugListener);
    } else {
      super.addEventListener(type, listener);
    }
  }

  getMessageLog() {
    return this.messageLog;
  }
}
```

This WebSocket API provides a robust foundation for real-time, bidirectional communication with MegaBot, supporting everything from simple chat to complex collaborative workflows.