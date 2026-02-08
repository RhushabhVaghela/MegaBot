# Development Guide

Complete guide for developing with and contributing to MegaBot.

## Table of Contents

- [Getting Started](#getting-started)
- [Development Environment](#development-environment)
- [Code Standards](#code-standards)
- [Testing](#testing)
- [Contributing](#contributing)
- [Architecture Guidelines](#architecture-guidelines)
- [Security Guidelines](#security-guidelines)

## Getting Started

### Prerequisites

- **Python 3.12+** - MegaBot requires modern Python features
- **Docker & Docker Compose** - For containerized development
- **Git** - Version control
- **VS Code** (recommended) - With Python and Pylance extensions

### Clone and Setup

```bash
# Clone the repository
git clone https://github.com/RhushabhVaghela/MegaBot.git
cd MegaBot

# Create virtual environment
python3.12 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy configuration template
cp mega-config.yaml.template mega-config.yaml
cp .env.example .env

# Edit configuration files with your settings
nano mega-config.yaml
nano .env
```

### First Run

```bash
# Start in development mode
python -m core.orchestrator

# Or with Docker
docker-compose -f docker-compose.dev.yml up --build
```

## Development Environment

### Project Structure

```
megabot/
├── core/                          # Core business logic
│   ├── orchestrator.py           # Main orchestrator
│   ├── config.py                 # Configuration management
│   ├── dependencies.py           # DI container
│   ├── interfaces.py             # Core interfaces
│   ├── llm_providers.py          # LLM integrations
│   ├── permissions.py            # Security permissions
│   └── memory/                   # Memory systems
├── adapters/                     # Platform integrations
│   ├── base.py                   # Adapter base classes
│   ├── messaging/                # Chat platforms
│   └── tools/                    # External tools
├── features/                     # Feature modules
├── tests/                        # Test suite
│   ├── unit/                     # Unit tests
│   ├── integration/              # Integration tests
│   └── fixtures/                 # Test fixtures
├── docs/                         # Documentation
├── scripts/                      # Utility scripts
└── docker/                       # Docker files
```

### Development Workflow

1. **Create Feature Branch**
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make Changes**
   - Follow code standards
   - Add/update tests
   - Update documentation

3. **Run Tests**
   ```bash
   pytest --cov=core --cov=adapters
   ```

4. **Commit Changes**
   ```bash
   git add .
   git commit -m "feat: add your feature description"
   ```

5. **Create Pull Request**
   - Push branch to GitHub
   - Create PR with description
   - Wait for CI and review

## Code Standards

### Python Standards

MegaBot follows PEP 8 with additional requirements:

#### Naming Conventions
```python
# Classes: PascalCase
class MegaBotOrchestrator:
    pass

# Functions: snake_case
async def send_platform_message(self, message: Message) -> bool:
    pass

# Constants: UPPER_CASE
MAX_CONTEXT_TOKENS = 8192

# Private members: _leading_underscore
self._running = False
```

#### Type Hints
All functions and methods must include type hints:

```python
from typing import Optional, Dict, List, Any
from datetime import datetime

async def process_message(
    self,
    message: Message,
    platform: str,
    sender_id: Optional[str] = None
) -> Dict[str, Any]:
    """Process incoming message and return response data."""
    pass
```

#### Docstrings
Use Google-style docstrings for all public methods:

```python
def approve_action(self, action_id: str, approved: bool) -> bool:
    """Approve or deny a pending security action.

    Args:
        action_id: Unique identifier for the action
        approved: True to approve, False to deny

    Returns:
        True if action was processed successfully

    Raises:
        ValueError: If action_id is not found
    """
    pass
```

### Async/Await Guidelines

All I/O operations must be async:

```python
# ✅ Good
async def send_message(self, message: Message) -> bool:
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=data) as response:
            return response.status == 200

# ❌ Bad
def send_message(self, message: Message) -> bool:
    response = requests.post(url, json=data)  # Blocking!
    return response.status_code == 200
```

### Error Handling

Use specific exception types and proper logging:

```python
import logging
from typing import Optional

logger = logging.getLogger(__name__)

async def process_adapter_message(self, data: dict) -> Optional[Message]:
    """Process message from adapter with proper error handling."""
    try:
        # Validate input
        if not isinstance(data, dict):
            raise ValueError("Message data must be a dictionary")

        # Process message
        message = Message.from_dict(data)
        await self.validate_message(message)

        return message

    except ValueError as e:
        logger.warning(f"Invalid message format: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error processing message: {e}", exc_info=True)
        return None
```

### Imports

Organize imports according to PEP 8:

```python
# Standard library imports
import asyncio
import json
from datetime import datetime
from typing import Optional, Dict, List

# Third-party imports
import aiohttp
import fastapi
from pydantic import BaseModel

# Local imports
from core.interfaces import Message
from core.config import Config
from adapters.base import AdapterHealth
```

## Testing

### Test Structure

```
tests/
├── unit/                     # Unit tests (no external dependencies)
│   ├── test_orchestrator.py
│   ├── test_config.py
│   └── test_adapters.py
├── integration/              # Integration tests (external services)
│   ├── test_messaging_integration.py
│   └── test_memory_integration.py
├── fixtures/                 # Test data and mocks
│   ├── sample_messages.py
│   └── mock_adapters.py
└── conftest.py              # Pytest configuration
```

### Unit Test Example

```python
import pytest
from unittest.mock import Mock, AsyncMock
from core.orchestrator import MegaBotOrchestrator

class TestMegaBotOrchestrator:
    @pytest.fixture
    def config(self):
        """Create test configuration."""
        return Mock(spec=Config)

    @pytest.fixture
    def orchestrator(self, config):
        """Create orchestrator instance for testing."""
        return MegaBotOrchestrator(config)

    @pytest.mark.asyncio
    async def test_start_success(self, orchestrator):
        """Test successful orchestrator startup."""
        # Arrange
        orchestrator.adapters = {}
        orchestrator._initialize_adapters = AsyncMock(return_value=True)

        # Act
        result = await orchestrator.start()

        # Assert
        assert result is True
        assert orchestrator._running is True

    @pytest.mark.asyncio
    async def test_send_platform_message_validation(self, orchestrator):
        """Test message validation in send_platform_message."""
        # Arrange
        invalid_message = Mock()
        invalid_message.content = None  # Invalid

        # Act & Assert
        with pytest.raises(ValueError, match="Message content cannot be empty"):
            await orchestrator.send_platform_message(invalid_message)
```

### Integration Test Example

```python
import pytest
import aiohttp
from tests.fixtures.mock_adapters import MockTelegramAdapter

@pytest.mark.integration
class TestMessagingIntegration:
    @pytest.fixture
    async def telegram_adapter(self):
        """Create real Telegram adapter for integration testing."""
        adapter = MockTelegramAdapter({
            'bot_token': 'test_token',
            'webhook_url': 'https://test.example.com'
        })
        await adapter.start()
        yield adapter
        await adapter.stop()

    @pytest.mark.asyncio
    async def test_full_message_flow(self, telegram_adapter):
        """Test complete message send/receive flow."""
        # Arrange
        test_message = PlatformMessage(
            id="test_123",
            platform="telegram",
            sender_id="user_456",
            chat_id="chat_789",
            content="Integration test",
            message_type="text",
            timestamp=datetime.now()
        )

        # Act
        send_result = await telegram_adapter.send_message(test_message)
        received_messages = []

        # Collect received messages
        async for msg in telegram_adapter.receive_messages():
            received_messages.append(msg)
            if len(received_messages) >= 1:
                break

        # Assert
        assert send_result is True
        assert len(received_messages) == 1
        assert received_messages[0].content == "Integration test"
```

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=core --cov=adapters --cov-report=html

# Run specific test file
pytest tests/unit/test_orchestrator.py

# Run tests matching pattern
pytest -k "test_message"

# Run integration tests only
pytest -m integration

# Debug failing test
pytest tests/unit/test_orchestrator.py::TestMegaBotOrchestrator::test_start_success -v -s
```

### Test Coverage Requirements

- **Unit Tests**: 90%+ coverage for core modules
- **Integration Tests**: All critical paths tested
- **Performance Tests**: Response times within limits
- **Security Tests**: All security boundaries validated

## Contributing

### Contribution Process

1. **Choose Issue**: Find or create a GitHub issue
2. **Discuss Design**: Comment on the issue with your approach
3. **Create Branch**: Use descriptive branch names
4. **Implement**: Follow code standards and add tests
5. **Test**: Ensure all tests pass and coverage maintained
6. **Document**: Update docs for any new features
7. **Submit PR**: Create pull request with detailed description

### Pull Request Guidelines

**Title Format:**
```
type(scope): description

Types: feat, fix, docs, style, refactor, test, chore
Examples:
- feat(auth): add OAuth2 support for Telegram
- fix(memory): resolve race condition in chat storage
- docs(api): update WebSocket API documentation
```

**Description Template:**
```markdown
## Description
Brief description of changes

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation update

## Testing
- [ ] Unit tests added/updated
- [ ] Integration tests added/updated
- [ ] Manual testing completed

## Checklist
- [ ] Code follows style guidelines
- [ ] Tests pass locally
- [ ] Documentation updated
- [ ] Breaking changes documented
```

### Commit Message Format

```
type(scope): description

[optional body]

[optional footer]
```

**Examples:**
```
feat(telegram): add support for animated stickers

The Telegram adapter now properly handles animated stickers
by converting them to MP4 format before processing.

Closes #123
```

```
fix(memory): prevent duplicate message storage

Fixed race condition where concurrent message saves could
create duplicate entries in SQLite database.

Test: tests/unit/test_memory.py::test_concurrent_saves
```

## Architecture Guidelines

### Component Design

#### Single Responsibility Principle
Each class should have one reason to change:

```python
# ✅ Good: Separate concerns
class MessageValidator:
    def validate_content(self, content: str) -> bool: pass

class MessageProcessor:
    def process_message(self, message: Message) -> Response: pass

# ❌ Bad: Mixed responsibilities
class MessageHandler:
    def validate_and_process(self, message: Message) -> Response: pass
```

#### Dependency Injection
Use the DI container for service dependencies:

```python
# ✅ Good: Injected dependencies
class Orchestrator:
    def __init__(self, memory: MemoryServer, llm: LLMProvider):
        self.memory = memory
        self.llm = llm

# ❌ Bad: Direct instantiation
class Orchestrator:
    def __init__(self):
        self.memory = MemoryServer()  # Tight coupling
```

#### Interface Segregation
Use specific interfaces rather than general ones:

```python
# ✅ Good: Specific interfaces
class MessagingAdapter(ABC):
    async def send_message(self, message: PlatformMessage) -> bool: pass

class ToolAdapter(ABC):
    async def execute_tool(self, name: str, params: dict) -> ToolResult: pass

# ❌ Bad: General interface
class Adapter(ABC):
    async def do_something(self, *args, **kwargs) -> Any: pass
```

### Error Handling Architecture

#### Custom Exceptions
Define specific exception types:

```python
class MegaBotError(Exception):
    """Base exception for MegaBot errors."""
    pass

class AdapterError(MegaBotError):
    """Adapter-related errors."""
    pass

class SecurityError(MegaBotError):
    """Security violation errors."""
    pass

class ValidationError(MegaBotError):
    """Data validation errors."""
    pass
```

#### Error Propagation
Use result types for complex operations:

```python
from typing import Union
from dataclasses import dataclass

@dataclass
class Success:
    value: Any

@dataclass
class Failure:
    error: str

Result = Union[Success, Failure]

async def process_command(self, command: str) -> Result:
    """Process a command and return success or failure."""
    try:
        result = await self.execute_command(command)
        return Success(result)
    except Exception as e:
        return Failure(str(e))
```

### Performance Guidelines

#### Async Best Practices
- Use `asyncio.gather()` for concurrent operations
- Avoid blocking calls in async functions
- Use `asyncio.Lock()` for shared state
- Implement proper cancellation handling

```python
# ✅ Good: Concurrent execution
async def send_to_multiple_platforms(self, message: Message):
    tasks = [
        self.telegram_adapter.send(message),
        self.signal_adapter.send(message),
        self.discord_adapter.send(message)
    ]
    await asyncio.gather(*tasks, return_exceptions=True)

# ❌ Bad: Sequential execution
async def send_to_multiple_platforms(self, message: Message):
    await self.telegram_adapter.send(message)  # Waits for each
    await self.signal_adapter.send(message)
    await self.discord_adapter.send(message)
```

#### Memory Management
- Use streaming for large data
- Implement proper cleanup in `__aexit__`
- Monitor memory usage in long-running tasks
- Use weak references for caches

## Security Guidelines

### Input Validation
Always validate external inputs:

```python
import re
from pydantic import BaseModel, validator

class MessageRequest(BaseModel):
    content: str
    platform: str

    @validator('content')
    def validate_content(cls, v):
        if not v or len(v.strip()) == 0:
            raise ValueError('Content cannot be empty')
        if len(v) > 10000:
            raise ValueError('Content too long')
        return v.strip()

    @validator('platform')
    def validate_platform(cls, v):
        allowed = {'telegram', 'signal', 'discord', 'websocket'}
        if v not in allowed:
            raise ValueError(f'Platform must be one of: {allowed}')
        return v
```

### Secure Defaults
- Deny by default for permissions
- Use minimum required privileges
- Implement timeouts for all operations
- Log security events

### Credential Management
- Never hardcode credentials
- Use environment variables or secure vaults
- Rotate credentials regularly
- Audit credential access

### Network Security
- Validate all URLs and endpoints
- Use HTTPS for external communications
- Implement rate limiting
- Sanitize user-generated content

### Code Security
- Avoid eval() and exec()
- Use parameterized queries
- Validate file paths
- Implement CSRF protection for web endpoints

---

## Additional Resources

- [API Documentation](../api/index.md)
- [Adapter Framework Guide](../adapters/framework.md)
- [Architecture Overview](../architecture/overview.md)
- [Security Deep-Dive](../security/model.md)
- [Testing Guide](testing.md)