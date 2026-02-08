"""Tests for PermissionManager"""

from core.permissions import PermissionLevel, PermissionManager


class TestPermissionManager:
    def test_permission_init(self):
        pm = PermissionManager("AUTO")
        assert pm.default_level == PermissionLevel.AUTO

        pm_invalid = PermissionManager("INVALID")
        assert pm_invalid.default_level == PermissionLevel.ASK_EACH

    def test_set_policy(self):
        pm = PermissionManager()
        pm.set_policy("shell.run", "AUTO")
        assert pm.overrides["shell.run"] == PermissionLevel.AUTO

    def test_get_effective_level_exact(self):
        pm = PermissionManager()
        pm.set_policy("filesystem.write", "NEVER")
        assert pm.get_effective_level("filesystem.write") == PermissionLevel.NEVER

    def test_get_effective_level_wildcard(self):
        pm = PermissionManager()
        pm.set_policy("*", "NEVER")
        assert pm.get_effective_level("any.scope") == PermissionLevel.NEVER

    def test_get_effective_level_parent(self):
        pm = PermissionManager()
        pm.set_policy("filesystem", "AUTO")
        assert pm.get_effective_level("filesystem.read") == PermissionLevel.AUTO

    def test_get_effective_level_shell_prefix(self):
        pm = PermissionManager()
        pm.set_policy("shell.rm", "NEVER")
        assert pm.get_effective_level("shell.rm -rf /") == PermissionLevel.NEVER

    def test_is_authorized(self):
        pm = PermissionManager()
        pm.set_policy("allow.me", "AUTO")
        pm.set_policy("block.me", "NEVER")
        pm.set_policy("ask.me", "ASK_EACH")

        assert pm.is_authorized("allow.me") is True
        assert pm.is_authorized("block.me") is False
        assert pm.is_authorized("ask.me") is None

    def test_load_from_config(self):
        pm = PermissionManager()
        config = {
            "policies": {"allow": ["ls", "pwd"], "deny": ["rm", "sudo"]},
            "default_permission": "NEVER",
        }
        pm.load_from_config(config)
        assert pm.get_effective_level("ls") == PermissionLevel.AUTO
        assert pm.get_effective_level("rm") == PermissionLevel.NEVER
        assert pm.default_level == PermissionLevel.NEVER

    def test_set_policy_invalid(self):
        """Test set_policy with invalid level (lines 35-36)"""
        pm = PermissionManager()
        pm.set_policy("test", "INVALID")
        assert "test" not in pm.overrides

    def test_load_from_config_invalid_default(self):
        """Test load_from_config with invalid default_permission (lines 101-102)"""
        pm = PermissionManager("AUTO")
        pm.load_from_config({"default_permission": "INVALID"})
        # Should remain at AUTO (previous level)
        assert pm.default_level == PermissionLevel.AUTO

    def test_get_effective_level_default(self):
        """Test get_effective_level returns default when no match (line 69)"""
        pm = PermissionManager("NEVER")
        assert pm.get_effective_level("some.unknown.scope") == PermissionLevel.NEVER
