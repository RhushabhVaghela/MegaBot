import os
import pytest
from unittest.mock import patch
from core.config import load_config, Config, SystemConfig, SecurityConfig


def test_load_config(temp_config_file):
    config = load_config(temp_config_file)
    assert config.system.name == "TestBot"
    assert config.adapters["openclaw"].port == 18789
    assert config.paths["external_repos"] == "/tmp/mock_repos"


def test_load_config_with_web_search(tmp_path):
    config_data = {
        "system": {
            "name": "Test",
            "local_only": True,
            "bind_address": "127.0.0.1",
            "telemetry": False,
            "default_mode": "plan",
        },
        "adapters": {
            "openclaw": {
                "web_search": {
                    "active_provider": "perplexity",
                    "providers": {"perplexity": {"api_key": "abc"}},
                }
            }
        },
        "paths": {"external_repos": "/tmp"},
    }
    config_file = tmp_path / "meta.yaml"
    import yaml

    with open(config_file, "w") as f:
        yaml.dump(config_data, f)

    config = load_config(str(config_file))
    assert config.adapters["openclaw"].web_search["active_provider"] == "perplexity"
    assert config.adapters["openclaw"].web_search["providers"]["perplexity"]["api_key"] == "abc"


def test_config_save(tmp_path):
    config_data = {
        "system": {
            "name": "Test",
            "local_only": True,
            "bind_address": "127.0.0.1",
            "telemetry": False,
            "default_mode": "plan",
        },
        "adapters": {"openclaw": {"host": "127.0.0.1", "port": 1234}},
        "paths": {"external_repos": "/tmp"},
        "policies": {"allow": ["pattern1"], "deny": ["pattern2"]},
    }
    config_file = tmp_path / "meta_save.yaml"
    from core.config import Config

    config = Config(**config_data)
    config.save(str(config_file))

    # Reload and verify
    reloaded = load_config(str(config_file))
    assert reloaded.policies["allow"] == ["pattern1"]
    assert reloaded.policies["deny"] == ["pattern2"]


def test_populate_from_environment(tmp_path, monkeypatch):
    """Test that environment variables are populated into config"""
    # Set environment variables
    monkeypatch.setenv("OPENAI_API_KEY", "test_openai_key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test_anthropic_key")
    monkeypatch.setenv("MEGABOT_BACKUP_KEY", "test_backup_key")

    config_data = {
        "system": {"name": "Test"},
        "adapters": {},
        "paths": {"workspaces": "/tmp", "external_repos": "/tmp"},
        "llm": {},
        "security": {},
    }
    config_file = tmp_path / "env_test.yaml"
    import yaml

    with open(config_file, "w") as f:
        yaml.dump(config_data, f)

    config = load_config(str(config_file))
    assert config.llm.openai_api_key == "test_openai_key"
    assert config.llm.anthropic_api_key == "test_anthropic_key"
    assert config.security.megabot_backup_key == "test_backup_key"


def test_load_api_credentials(tmp_path, monkeypatch):
    import os

    # Create a dummy api-credentials.py in tmp_path
    cred_file = tmp_path / "api-credentials.py"
    cred_file.write_text("TEST_KEY = 'test-value'\nAUTHORIZED_ADMINS = ['user1', 'user2']\n")

    # Change current working directory to tmp_path
    monkeypatch.chdir(tmp_path)

    from core.config import load_api_credentials

    load_api_credentials()

    assert os.environ.get("TEST_KEY") == "test-value"
    assert os.environ.get("AUTHORIZED_ADMINS") == "user1,user2"


def test_load_api_credentials_exception(tmp_path, monkeypatch, caplog):
    """Test that invalid lines are safely skipped (VULN-004: no code execution).

    The safe regex parser simply skips lines that don't match
    KEY = "value" format — no exception is raised for 'invalid Python'
    because no Python code is executed at all.
    """
    monkeypatch.chdir(tmp_path)
    # Create file with non-matching content — should be silently skipped
    cred_file = tmp_path / "api-credentials.py"
    cred_file.write_text("INVALID PYTHON")

    import logging
    from core.config import load_api_credentials

    with caplog.at_level(logging.INFO):
        load_api_credentials()

    # Safe parser succeeds (skips invalid lines) — no error expected
    assert "Loaded API credentials" in caplog.text


def test_load_api_credentials_file_error(tmp_path, monkeypatch, caplog):
    """Test exception handling when the file cannot be read."""
    monkeypatch.chdir(tmp_path)
    cred_file = tmp_path / "api-credentials.py"
    cred_file.write_text("KEY = 'value'")
    # Make file unreadable
    cred_file.chmod(0o000)

    import logging
    from core.config import load_api_credentials

    with caplog.at_level(logging.ERROR):
        load_api_credentials()

    # Should hit the except branch
    assert "Error loading" in caplog.text

    # Restore permissions for cleanup
    cred_file.chmod(0o644)


def test_security_config_validation(monkeypatch):
    """Test SecurityConfig validation when not in test mode (lines 71-82)"""
    from core.config import SecurityConfig
    import pytest
    from pydantic import ValidationError

    # Remove PYTEST_CURRENT_TEST to trigger production validation
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    # Test missing salt
    with pytest.raises(ValidationError) as excinfo:
        SecurityConfig(MEGABOT_ENCRYPTION_SALT="")
    assert "MEGABOT_ENCRYPTION_SALT is required" in str(excinfo.value)

    # Test short salt
    with pytest.raises(ValidationError) as excinfo:
        SecurityConfig(MEGABOT_ENCRYPTION_SALT="too-short")
    assert "must be at least 16 characters" in str(excinfo.value)


def test_validate_environment_full(monkeypatch):
    """Test Config.validate_environment with various scenarios (lines 127, 129, 144, 154)"""
    from core.config import Config, SystemConfig, AdapterConfig

    monkeypatch.delenv("OPENCLAW_AUTH_TOKEN", raising=False)

    config = Config(
        system=SystemConfig(),
        adapters={
            "openai": AdapterConfig(),
            "anthropic": AdapterConfig(),
            "openclaw": AdapterConfig(auth_token="config-token"),
        },
        paths={},
    )

    # Missing LLM keys but openclaw token is in config (line 144)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert config.validate_environment() is False

    # All present
    monkeypatch.setenv("OPENAI_API_KEY", "o")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    assert config.validate_environment() is True


def test_load_config_default_creation(tmp_path):
    """Test load_config when file doesn't exist (lines 168-179)"""
    config_file = tmp_path / "nonexistent.yaml"
    from core.config import load_config

    # This should create the file and return a default config
    config = load_config(str(config_file))

    assert config_file.exists()
    assert config.system.name == "MegaBot"


def test_load_config_adapter_env_injection(tmp_path, monkeypatch):
    """Test injection of environment variables into adapter config (lines 194, 196, 198)"""
    config_data = {
        "system": {"name": "Test"},
        "adapters": {"custom": {"host": "", "port": 0, "auth_token": ""}},
        "paths": {"workspaces": "/tmp", "external_repos": "/tmp"},
    }
    config_file = tmp_path / "inject.yaml"
    import yaml

    with open(config_file, "w") as f:
        yaml.dump(config_data, f)

    monkeypatch.setenv("CUSTOM_HOST", "1.2.3.4")
    monkeypatch.setenv("CUSTOM_PORT", "9999")
    monkeypatch.setenv("CUSTOM_AUTH_TOKEN", "secret-token")

    from core.config import load_config

    config = load_config(str(config_file))

    assert config.adapters["custom"].host == "1.2.3.4"
    assert config.adapters["custom"].port == 9999
    assert config.adapters["custom"].auth_token == "secret-token"


def test_set_nested_attr_no_attr():
    """Test _set_nested_attr with missing attribute (line 252)"""
    from core.config import _set_nested_attr

    class MockObj:
        pass

    obj = MockObj()
    # Should return early without raising
    _set_nested_attr(obj, "nonexistent.attr", "val")
    assert not hasattr(obj, "nonexistent")


# =====================================================================
# FROM test_coverage_completion_final.py
# =====================================================================


class TestConfigCoverage:
    """Target missing lines in core/config.py"""

    def test_validate_environment_missing(self):
        c = Config(system=SystemConfig(), adapters={}, paths={}, security=SecurityConfig())
        # Force missing env
        with patch.dict("os.environ", {}, clear=True):
            assert c.validate_environment() is False

    def test_load_config_not_found(self, tmp_path):
        path = str(tmp_path / "notfound.yaml")
        # Should create default and return it
        cfg = load_config(path)
        assert cfg.system.name == "MegaBot"
        assert os.path.exists(path)
