# Testing Guide

This guide covers the comprehensive testing strategy for MegaBot, including unit tests, integration tests, security testing, and performance testing.

## Testing Overview

MegaBot employs a multi-layered testing approach to ensure reliability, security, and performance:

- **Unit Tests**: Test individual components in isolation
- **Integration Tests**: Test component interactions
- **Security Tests**: Validate security controls and permissions
- **Performance Tests**: Ensure scalability and responsiveness
- **End-to-End Tests**: Validate complete user workflows

## Testing Infrastructure

### Test Directory Structure

```
tests/
├── unit/                    # Unit tests
│   ├── test_orchestrator.py
│   ├── test_permissions.py
│   ├── test_security.py
│   └── test_adapters.py
├── integration/            # Integration tests
│   ├── test_messaging.py
│   ├── test_memory.py
│   └── test_llm_providers.py
├── security/               # Security tests
│   ├── test_permissions.py
│   ├── test_content_filtering.py
│   └── test_approvals.py
├── performance/            # Performance tests
│   ├── test_load.py
│   ├── test_memory_usage.py
│   └── test_concurrency.py
├── e2e/                    # End-to-end tests
│   ├── test_user_workflows.py
│   └── test_admin_operations.py
├── fixtures/               # Test data and mocks
│   ├── sample_configs.py
│   ├── mock_responses.py
│   └── test_databases.py
└── conftest.py            # Pytest configuration
```

### Test Configuration

#### pytest Configuration (`pytest.ini`)

```ini
[tool:pytest.ini_options]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts =
    --strict-markers
    --strict-config
    --disable-warnings
    --tb=short
    -v
markers =
    unit: Unit tests
    integration: Integration tests
    security: Security tests
    performance: Performance tests
    e2e: End-to-end tests
    slow: Slow running tests
    requires_api: Tests requiring external API access
```

#### Test Dependencies (`requirements-test.txt`)

```txt
pytest>=7.0.0
pytest-asyncio>=0.21.0
pytest-cov>=4.0.0
pytest-mock>=3.10.0
pytest-xdist>=3.0.0
pytest-html>=3.1.0
pytest-benchmark>=4.0.0
responses>=0.23.0
freezegun>=1.2.0
faker>=15.0.0
httpx>=0.24.0
```

## Unit Testing

### Core Component Tests

#### Orchestrator Tests (`tests/unit/test_orchestrator.py`)

```python
import pytest
from unittest.mock import Mock, AsyncMock
from core.orchestrator import MegaBotOrchestrator
from core.config import Config

class TestMegaBotOrchestrator:
    @pytest.fixture
    def config(self):
        return Config(
            system={"name": "TestBot", "local_only": True},
            admins=["test_admin"],
            adapters={
                "openclaw": {"host": "127.0.0.1", "port": 18789},
                "memu": {"database_url": "sqlite:///:memory:"}
            }
        )

    @pytest.fixture
    async def orchestrator(self, config):
        orch = MegaBotOrchestrator(config)
        # Mock adapters to avoid external dependencies
        orch.adapters = {
            "openclaw": Mock(),
            "memu": Mock(),
            "messaging": Mock()
        }
        yield orch

    @pytest.mark.asyncio
    async def test_initialization(self, orchestrator):
        """Test orchestrator initializes correctly."""
        assert orchestrator.config.system.name == "TestBot"
        assert orchestrator.mode == "plan"
        assert len(orchestrator.adapters) == 3

    @pytest.mark.asyncio
    async def test_message_processing(self, orchestrator):
        """Test message routing through orchestrator."""
        message = Message(content="Hello", sender="user")
        orchestrator.adapters["messaging"].send_message = AsyncMock()

        await orchestrator.send_platform_message(message)

        orchestrator.adapters["messaging"].send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_admin_command_processing(self, orchestrator):
        """Test admin command handling."""
        result = await orchestrator._handle_admin_command(
            "!health", "admin_id", platform="test"
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_permission_enforcement(self, orchestrator):
        """Test permission system integration."""
        # Test approved action
        orchestrator.permissions.set_policy("test.action", "AUTO")
        assert orchestrator.permissions.is_authorized("test.action") is True

        # Test denied action
        orchestrator.permissions.set_policy("dangerous.action", "NEVER")
        assert orchestrator.permissions.is_authorized("dangerous.action") is False
```

#### Permission System Tests (`tests/unit/test_permissions.py`)

```python
import pytest
from core.permissions import PermissionManager, PermissionLevel

class TestPermissionManager:
    @pytest.fixture
    def perm_manager(self):
        return PermissionManager()

    def test_default_permissions(self, perm_manager):
        """Test default permission behavior."""
        assert perm_manager.default_level == PermissionLevel.ASK_EACH

    def test_policy_setting(self, perm_manager):
        """Test setting permission policies."""
        perm_manager.set_policy("shell.execute", "AUTO")
        assert perm_manager.is_authorized("shell.execute") is True

    def test_scope_matching(self, perm_manager):
        """Test hierarchical scope matching."""
        perm_manager.set_policy("filesystem", "AUTO")

        assert perm_manager.is_authorized("filesystem.read") is True
        assert perm_manager.is_authorized("filesystem.write") is True
        assert perm_manager.is_authorized("shell.execute") is None  # Default

    def test_command_prefix_matching(self, perm_manager):
        """Test command prefix matching for shell commands."""
        perm_manager.set_policy("git", "AUTO")

        assert perm_manager.is_authorized("shell.git status") is True
        assert perm_manager.is_authorized("shell.git log") is True
        assert perm_manager.is_authorized("shell.ls") is None

    def test_config_loading(self, perm_manager):
        """Test loading policies from configuration."""
        config = {
            "policies": {
                "allow": ["git status", "read *.md"],
                "deny": ["rm -rf /"]
            }
        }

        perm_manager.load_from_config(config)

        assert perm_manager.is_authorized("shell.git status") is True
        assert perm_manager.is_authorized("shell.rm -rf /") is False
```

### Security Tests

#### Content Filtering Tests (`tests/security/test_content_filtering.py`)

```python
import pytest
from adapters.security.tirith_guard import TirithGuard

class TestTirithGuard:
    @pytest.fixture
    def guard(self):
        return TirithGuard()

    def test_ansi_escape_removal(self, guard):
        """Test ANSI escape sequence removal."""
        malicious_input = "\x1b[31mRed Text\x1b[0m"
        sanitized = guard.sanitize(malicious_input)
        assert sanitized == "Red Text"

    def test_unicode_normalization(self, guard):
        """Test Unicode normalization."""
        # Test NFC normalization
        input_text = "café"  # Precomposed
        normalized = guard.sanitize(input_text)
        assert normalized == "café"

    def test_homoglyph_detection(self, guard):
        """Test homoglyph attack detection."""
        # Cyrillic 'а' looks like Latin 'a'
        suspicious_text = "rnаsk"  # Contains Cyrillic 'а'
        assert guard.check_homoglyphs(suspicious_text) is True

        normal_text = "ransomware"
        assert guard.check_homoglyphs(normal_text) is False

    def test_bidi_attack_prevention(self, guard):
        """Test bidirectional control character blocking."""
        # Right-to-Left Override attack
        malicious = "txt.exe\x{202E}cod.bat"
        assert guard.validate(malicious) is False

        normal = "document.txt"
        assert guard.validate(normal) is True

    @pytest.mark.parametrize("input_text,expected_valid", [
        ("normal_text", True),
        ("text_with_сyrillic", False),  # Cyrillic 'с'
        ("file.txt", True),
        ("file.txt\x{202E}exe.bat", False),  # RLO attack
    ])
    def test_validation_comprehensive(self, guard, input_text, expected_valid):
        """Comprehensive validation testing."""
        assert guard.validate(input_text) == expected_valid
```

#### Approval System Tests (`tests/security/test_approvals.py`)

```python
import pytest
from unittest.mock import AsyncMock
from core.admin_handler import AdminHandler

class TestAdminHandler:
    @pytest.fixture
    def orchestrator(self):
        mock_orch = Mock()
        mock_orch.config = Mock()
        mock_orch.config.admins = ["admin_id"]
        mock_orch.permissions = Mock()
        return mock_orch

    @pytest.fixture
    def admin_handler(self, orchestrator):
        return AdminHandler(orchestrator)

    @pytest.mark.asyncio
    async def test_approval_creation(self, admin_handler):
        """Test approval action creation and queuing."""
        action = {
            "id": "test_123",
            "type": "shell_command",
            "description": "Test command",
            "payload": {"command": "ls"}
        }

        admin_handler.approval_queue.append(action)
        assert len(admin_handler.approval_queue) == 1
        assert admin_handler.approval_queue[0]["id"] == "test_123"

    @pytest.mark.asyncio
    async def test_admin_command_approval(self, admin_handler, orchestrator):
        """Test admin approval command processing."""
        # Setup approval queue
        action = {
            "id": "test_123",
            "type": "shell_command",
            "payload": {"command": "ls"}
        }
        admin_handler.approval_queue.append(action)

        # Mock approval processing
        admin_handler._process_approval = AsyncMock()

        # Test approval command
        result = await admin_handler.handle_command(
            "!approve test_123", "admin_id", platform="test"
        )

        assert result is True
        admin_handler._process_approval.assert_called_once_with("test_123", True)

    @pytest.mark.asyncio
    async def test_non_admin_rejection(self, admin_handler):
        """Test that non-admins cannot execute admin commands."""
        result = await admin_handler.handle_command(
            "!health", "non_admin_id", platform="test"
        )

        assert result is False
```

## Integration Testing

### Adapter Integration Tests (`tests/integration/test_adapters.py`)

```python
import pytest
from unittest.mock import Mock, patch
from adapters.openclaw_adapter import OpenClawAdapter
from adapters.memu_adapter import MemUAdapter

class TestAdapterIntegration:
    @pytest.mark.asyncio
    async def test_openclaw_connection(self):
        """Test OpenClaw adapter connection."""
        adapter = OpenClawAdapter("127.0.0.1", 18789)

        # Mock websocket connection
        with patch('websockets.connect', new_callable=AsyncMock) as mock_ws:
            mock_connection = AsyncMock()
            mock_ws.return_value.__aenter__.return_value = mock_connection

            await adapter.connect()

            mock_ws.assert_called_once_with(
                "ws://127.0.0.1:18789",
                extra_headers={"Authorization": "Bearer "}
            )

    @pytest.mark.asyncio
    async def test_memu_memory_operations(self):
        """Test MemU memory operations."""
        adapter = MemUAdapter("/tmp/test_memu", "sqlite:///:memory:")

        # Test memory storage
        await adapter.store_memory("test_key", {"data": "test_value"})
        retrieved = await adapter.retrieve_memory("test_key")

        assert retrieved["data"] == "test_value"

    @pytest.mark.asyncio
    async def test_messaging_platform_integration(self):
        """Test messaging platform integration."""
        from adapters.messaging import MegaBotMessagingServer

        server = MegaBotMessagingServer(host="127.0.0.1", port=18790)

        # Mock platform connections
        with patch('megabot.adapters.telegram_adapter.TelegramAdapter'):
            await server.start()

            # Verify server is listening
            assert server.server is not None
            assert server.server.sockets is not None

            await server.stop()
```

### LLM Provider Tests (`tests/integration/test_llm_providers.py`)

```python
import pytest
from unittest.mock import Mock, patch
from core.llm_providers import get_llm_provider

class TestLLMProviders:
    @pytest.fixture
    def anthropic_config(self):
        return {
            "anthropic_api_key": "test_key",
            "model": "claude-3-haiku-20240307"
        }

    def test_provider_initialization(self, anthropic_config):
        """Test LLM provider initialization."""
        provider = get_llm_provider(anthropic_config)

        assert provider is not None
        assert hasattr(provider, 'generate')

    @pytest.mark.asyncio
    async def test_anthropic_api_call(self, anthropic_config):
        """Test Anthropic API integration."""
        provider = get_llm_provider(anthropic_config)

        with patch('anthropic.AsyncAnthropic') as mock_anthropic:
            mock_client = Mock()
            mock_response = Mock()
            mock_response.content = [Mock(text="Test response")]
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_anthropic.return_value = mock_client

            response = await provider.generate(
                context="test",
                messages=[{"role": "user", "content": "Hello"}]
            )

            assert response == "Test response"

    @pytest.mark.asyncio
    async def test_fallback_provider(self):
        """Test fallback to secondary provider on failure."""
        config = {
            "anthropic_api_key": "invalid_key",
            "openai_api_key": "valid_key",
            "fallback_providers": ["openai"]
        }

        provider = get_llm_provider(config)

        # First call fails, second succeeds
        with patch.object(provider, 'generate', side_effect=[
            Exception("API Error"),  # Anthropic fails
            "Fallback response"      # OpenAI succeeds
        ]) as mock_generate:
            response = await provider.generate(
                context="test",
                messages=[{"role": "user", "content": "Hello"}]
            )

            assert response == "Fallback response"
            assert mock_generate.call_count == 2
```

## Performance Testing

### Load Testing (`tests/performance/test_load.py`)

```python
import pytest
import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from core.orchestrator import MegaBotOrchestrator

class TestLoadPerformance:
    @pytest.fixture
    async def orchestrator(self):
        config = Config(
            system={"name": "TestBot"},
            adapters={
                "openclaw": {"host": "127.0.0.1", "port": 18789},
                "memu": {"database_url": "sqlite:///:memory:"}
            }
        )
        orch = MegaBotOrchestrator(config)
        await orch.start()
        yield orch
        await orch.stop()

    @pytest.mark.performance
    @pytest.mark.asyncio
    async def test_concurrent_requests(self, orchestrator):
        """Test handling multiple concurrent requests."""
        async def make_request(i):
            message = Message(content=f"Request {i}", sender=f"user_{i}")
            start_time = time.time()
            await orchestrator.process_message(message)
            return time.time() - start_time

        # Test with 10 concurrent requests
        tasks = [make_request(i) for i in range(10)]
        start_time = time.time()

        results = await asyncio.gather(*tasks)

        total_time = time.time() - start_time
        avg_response_time = sum(results) / len(results)

        # Performance assertions
        assert total_time < 5.0  # Total time under 5 seconds
        assert avg_response_time < 0.5  # Average under 500ms
        assert max(results) < 1.0  # No request over 1 second

    @pytest.mark.performance
    def test_memory_usage_under_load(self):
        """Test memory usage during load."""
        import psutil
        import os

        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB

        # Simulate load
        self._generate_load()

        final_memory = process.memory_info().rss / 1024 / 1024  # MB
        memory_increase = final_memory - initial_memory

        assert memory_increase < 100  # Less than 100MB increase

    def _generate_load(self):
        """Generate test load."""
        # Simulate multiple message processing
        for i in range(100):
            message = Message(content=f"Load test message {i}", sender="test_user")
            # Process synchronously for memory measurement
            asyncio.run(self.orchestrator.process_message(message))
```

### Memory Usage Tests (`tests/performance/test_memory_usage.py`)

```python
import pytest
import gc
import psutil
import os
from memory_profiler import profile

class TestMemoryUsage:
    def test_memory_leak_prevention(self):
        """Test that operations don't cause memory leaks."""
        process = psutil.Process(os.getpid())

        # Force garbage collection
        gc.collect()
        initial_memory = process.memory_info().rss

        # Perform memory-intensive operations
        self._perform_memory_operations()

        # Force garbage collection again
        gc.collect()
        final_memory = process.memory_info().rss

        # Allow for some memory fluctuation (10MB)
        assert abs(final_memory - initial_memory) < 10 * 1024 * 1024

    @profile
    def _perform_memory_operations(self):
        """Perform operations that might cause memory leaks."""
        # Create many temporary objects
        messages = []
        for i in range(1000):
            message = Message(content=f"Message {i}", sender="test_user")
            messages.append(message)

        # Process messages
        for message in messages:
            # Simulate processing
            processed = message.content.upper()

        # Clear references
        del messages
```

## End-to-End Testing

### User Workflow Tests (`tests/e2e/test_user_workflows.py`)

```python
import pytest
from playwright.async_api import async_playwright
from core.orchestrator import MegaBotOrchestrator

class TestUserWorkflows:
    @pytest.fixture
    async def browser_context(self):
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            context = await browser.new_context()
            yield context
            await browser.close()

    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_complete_user_journey(self, browser_context):
        """Test complete user interaction workflow."""
        page = await browser_context.new_page()

        # Navigate to MegaBot interface
        await page.goto("http://localhost:8000")

        # Test authentication
        await page.fill("#username", "test_user")
        await page.fill("#password", "test_pass")
        await page.click("#login-button")

        # Verify login success
        await page.wait_for_selector(".chat-interface")

        # Send message
        await page.fill("#message-input", "Hello MegaBot")
        await page.click("#send-button")

        # Wait for response
        await page.wait_for_selector(".message-response")
        response_text = await page.text_content(".message-response")

        assert "Hello" in response_text

    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_admin_approval_workflow(self, browser_context):
        """Test admin approval workflow end-to-end."""
        admin_page = await browser_context.new_page()
        user_page = await browser_context.new_page()

        # Admin login
        await admin_page.goto("http://localhost:8000/admin")
        await admin_page.fill("#username", "admin")
        await admin_page.click("#login-button")

        # User attempts dangerous action
        await user_page.goto("http://localhost:8000")
        await user_page.fill("#message-input", "!run rm -rf /tmp/test")
        await user_page.click("#send-button")

        # Verify approval request appears for admin
        await admin_page.wait_for_selector(".approval-request")
        approval_text = await admin_page.text_content(".approval-request")

        assert "rm -rf /tmp/test" in approval_text

        # Admin approves
        await admin_page.click(".approve-button")

        # Verify action completes
        await user_page.wait_for_selector(".action-completed")
        result = await user_page.text_content(".action-completed")

        assert "completed successfully" in result
```

## Test Fixtures and Mocks

### Test Configuration Fixtures (`tests/fixtures/sample_configs.py`)

```python
import pytest
from core.config import Config

@pytest.fixture
def minimal_config():
    """Minimal configuration for basic testing."""
    return Config(
        system={"name": "TestBot", "local_only": True},
        admins=["test_admin"],
        adapters={
            "openclaw": {"host": "127.0.0.1", "port": 18789},
            "memu": {"database_url": "sqlite:///:memory:"}
        }
    )

@pytest.fixture
def full_config():
    """Complete configuration for comprehensive testing."""
    return Config(
        system={
            "name": "FullTestBot",
            "local_only": True,
            "log_level": "DEBUG"
        },
        admins=["admin1", "admin2"],
        llm={
            "anthropic_api_key": "test_key",
            "fallback_providers": ["openai"]
        },
        adapters={
            "openclaw": {
                "host": "127.0.0.1",
                "port": 18789,
                "database_url": "sqlite:///test.db"
            },
            "memu": {
                "database_url": "sqlite:///:memory:",
                "vector_db": "sqlite"
            },
            "messaging": {
                "enable_encryption": True,
                "platforms": {
                    "telegram": {"enabled": True, "bot_token": "test_token"}
                }
            }
        },
        policies={
            "allow": ["git status", "read *.md"],
            "deny": ["rm -rf /"]
        }
    )

@pytest.fixture
def security_config():
    """Configuration focused on security testing."""
    return Config(
        system={"name": "SecureBot"},
        security={
            "enable_content_filtering": True,
            "enable_image_redaction": True,
            "tirith_guard": {"enabled": True}
        },
        policies={
            "default_permission": "NEVER",
            "allow": ["git status"],
            "deny": ["*"]
        }
    )
```

### Mock Responses (`tests/fixtures/mock_responses.py`)

```python
import json

# LLM API Mock Responses
ANTHROPIC_SUCCESS_RESPONSE = {
    "content": [{"text": "This is a test response from Claude."}],
    "usage": {"input_tokens": 10, "output_tokens": 8}
}

OPENAI_SUCCESS_RESPONSE = {
    "choices": [{
        "message": {"content": "This is a test response from GPT."},
        "finish_reason": "stop"
    }],
    "usage": {"prompt_tokens": 10, "completion_tokens": 8}
}

# MCP Tool Responses
MCP_FILESYSTEM_RESPONSE = {
    "content": [{"text": "/home/user\n/tmp\n/etc"}],
    "is_error": False
}

MCP_WEB_SEARCH_RESPONSE = {
    "content": [{
        "text": json.dumps([
            {"title": "Test Result", "url": "https://example.com", "snippet": "Test content"}
        ])
    }],
    "is_error": False
}

# Platform API Responses
TELEGRAM_SEND_MESSAGE_RESPONSE = {
    "ok": True,
    "result": {
        "message_id": 123,
        "text": "Test message",
        "chat": {"id": 456}
    }
}

DISCORD_MESSAGE_RESPONSE = {
    "id": "123456789",
    "content": "Test message",
    "author": {"id": "987654321", "username": "test_user"}
}
```

## Test Execution

### Running Tests

```bash
# Run all tests
pytest

# Run specific test categories
pytest -m unit
pytest -m integration
pytest -m security
pytest -m performance
pytest -m e2e

# Run with coverage
pytest --cov=megabot --cov-report=html

# Run slow tests
pytest -m slow

# Run tests in parallel
pytest -n auto

# Run specific test file
pytest tests/unit/test_orchestrator.py

# Run specific test
pytest tests/unit/test_orchestrator.py::TestMegaBotOrchestrator::test_initialization
```

### Continuous Integration

#### GitHub Actions Workflow (`.github/workflows/test.yml`)

```yaml
name: Tests
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: [3.9, 3.10, 3.11]

    steps:
    - uses: actions/checkout@v3
    - name: Set up Python ${{ matrix.python-version }}
      uses: actions/setup-python@v4
      with:
        python-version: ${{ matrix.python-version }}

    - name: Install dependencies
      run: |
        pip install -r requirements.txt
        pip install -r requirements-test.txt

    - name: Run unit tests
      run: pytest tests/unit/ -v --tb=short

    - name: Run integration tests
      run: pytest tests/integration/ -v --tb=short

    - name: Run security tests
      run: pytest tests/security/ -v --tb=short

    - name: Generate coverage report
      run: pytest --cov=megabot --cov-report=xml

    - name: Upload coverage
      uses: codecov/codecov-action@v3
      with:
        file: ./coverage.xml
```

### Test Quality Metrics

#### Coverage Requirements

```ini
# .coveragerc
[run]
source = megabot
omit =
    tests/*
    megabot/__main__.py

[report]
exclude_lines =
    pragma: no cover
    def __repr__
    raise AssertionError
    raise NotImplementedError

[html]
directory = htmlcov

fail_under = 85
```

#### Quality Gates

```bash
# Pre-commit quality checks
#!/bin/bash
set -e

# Lint code
flake8 megabot/ --max-line-length=100 --extend-ignore=E203,W503

# Type check
mypy megabot/ --ignore-missing-imports

# Security scan
bandit -r megabot/ -f json -o security-report.json

# Run tests with coverage
pytest --cov=megabot --cov-fail-under=85

# Check for vulnerabilities
safety check
```

This testing guide provides a comprehensive framework for ensuring MegaBot's reliability, security, and performance. The multi-layered approach ensures that both individual components and the system as a whole function correctly under various conditions.</content>
<parameter name="filePath">docs/development/testing.md