import os
import sys

# Set test environment variables before any imports
os.environ["PYTEST_CURRENT_TEST"] = "true"
os.environ["MEGABOT_ENCRYPTION_SALT"] = "test-salt-minimum-16-chars"
os.environ["MEGABOT_BACKUP_KEY"] = "test-backup-key-32-chars-long-string"
os.environ["MEGABOT_WS_PASSWORD"] = "test-ws-password-for-ci"

from unittest.mock import MagicMock

import pytest
import yaml

# Ensure the project root is on sys.path so `core` package is importable when
# tests are executed from different working directories or isolation layers.
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Import core config dataclasses used by fixtures
from megabot.core.config import AdapterConfig, Config, SecurityConfig, SystemConfig

# Global mocking for firebase_admin to prevent import errors in tests
sys.modules["firebase_admin"] = MagicMock()
sys.modules["firebase_admin.credentials"] = MagicMock()
sys.modules["firebase_admin.messaging"] = MagicMock()
sys.modules["firebase_admin.app"] = MagicMock()
sys.modules["jwt"] = MagicMock()


@pytest.fixture(autouse=True)
def reset_orchestrator_global():
    """Reset orchestrator global state before/after each test"""
    import megabot.core.orchestrator as orch_module

    original = getattr(orch_module, "orchestrator", None)
    yield
    orch_module.orchestrator = original


@pytest.fixture
def mock_config():
    return Config(
        system=SystemConfig(
            name="TestBot",
            local_only=True,
            bind_address="127.0.0.1",
            telemetry=False,
            default_mode="plan",
        ),
        adapters={
            "openclaw": AdapterConfig(host="127.0.0.1", port=18789),
            "memu": AdapterConfig(database_url="sqlite:///:memory:", vector_db="sqlite"),
            "mcp": AdapterConfig(servers=[]),
        },
        paths={"external_repos": "/tmp/mock_repos"},
        security=SecurityConfig(
            megabot_encryption_salt="test-salt-minimum-16-chars",
            megabot_backup_key="test-backup-key-32-chars-long-string",
        ),
    )


@pytest.fixture
def temp_config_file(tmp_path):
    config_data = {
        "system": {
            "name": "TestBot",
            "local_only": True,
            "bind_address": "127.0.0.1",
            "telemetry": False,
            "default_mode": "plan",
        },
        "adapters": {
            "openclaw": {"host": "127.0.0.1", "port": 18789},
            "memu": {"database_url": "sqlite:///:memory:", "vector_db": "sqlite"},
        },
        "paths": {"external_repos": "/tmp/mock_repos"},
        "llm_profiles": {},
        "security": {
            "megabot_encryption_salt": "test-salt-minimum-16-chars",
            "megabot_backup_key": "test-backup-key-32-chars-long-string",
        },
    }
    config_file = tmp_path / "test-config.yaml"
    with open(config_file, "w") as f:
        yaml.dump(config_data, f)
    return str(config_file)


@pytest.fixture
def orchestrator(mock_config):
    """Provide an Orchestrator instance for testing"""
    from megabot.core.orchestrator import MegaBotOrchestrator

    orch = MegaBotOrchestrator(mock_config)
    return orch


@pytest.fixture
def active_mock_agent():
    """Return a MagicMock configured as an active sub-agent for tests.

    Usage: pass `active_mock_agent` into tests that need a mock agent with
    `_active = True` already set to match the stricter activation policy.
    """
    m = MagicMock()
    # Most tests expect the agent to have a role attribute
    m.role = "Tester"
    m._active = True
    # default stub for allowed tools
    m._get_sub_tools.return_value = []
    return m
