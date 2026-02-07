"""Tests for projects and secrets modules"""

import os
from core.projects import ProjectManager
from core.secrets import SecretManager


class TestProjectManager:
    def test_project_init(self, tmp_path):
        pm = ProjectManager(str(tmp_path))
        assert pm.base_path == str(tmp_path)
        assert pm.current_project is None

    def test_create_project(self, tmp_path):
        pm = ProjectManager(str(tmp_path))
        ctx = pm.create_project("test_proj")
        assert ctx.name == "test_proj"
        assert os.path.exists(ctx.base_path)

    def test_switch_project(self, tmp_path):
        pm = ProjectManager(str(tmp_path))
        pm.switch_project("proj1")
        assert pm.current_project.name == "proj1"

    def test_delete_project(self, tmp_path):
        pm = ProjectManager(str(tmp_path))
        ctx = pm.create_project("proj_to_del")
        pm.delete_project("proj_to_del")
        assert not os.path.exists(ctx.base_path)

    def test_project_context_methods(self, tmp_path):
        """Test ProjectContext methods (lines 26, 31)"""
        pm = ProjectManager(str(tmp_path))
        ctx = pm.create_project("test_methods")

        # get_system_prompt exists (line 26)
        system_file = ctx.prompts_path / "system.md"
        system_file.write_text("Hello Prompt")
        assert ctx.get_system_prompt() == "Hello Prompt"

        # list_files (line 31)
        test_file = ctx.files_path / "test.txt"
        test_file.write_text("content")
        files = ctx.list_files()
        assert "test.txt" in files

        # get_system_prompt not exists (line 27)
        ctx2 = pm.create_project("test_methods2")
        assert ctx2.get_system_prompt() == ""

    def test_delete_current_project(self, tmp_path):
        """Test deleting the current project (line 53)"""
        pm = ProjectManager(str(tmp_path))
        pm.switch_project("current")
        assert pm.current_project is not None
        pm.delete_project("current")
        assert pm.current_project is None


class TestSecretManager:
    def test_secret_init(self):
        sm = SecretManager()
        assert isinstance(sm.secrets, dict)

    def test_load_from_env(self, monkeypatch):
        monkeypatch.setenv("MEGABOT_SECRET_API_KEY", "secret-value")
        sm = SecretManager()
        assert sm.get_secret("API_KEY") == "secret-value"

    def test_inject_secrets(self):
        sm = SecretManager()
        sm.secrets["DB_PASS"] = "p4ssw0rd"
        text = "Connect with {{DB_PASS}}"
        assert sm.inject_secrets(text) == "Connect with p4ssw0rd"

    def test_scrub_secrets(self):
        sm = SecretManager()
        sm.secrets["TOKEN"] = "abc-123"
        text = "Your token is abc-123"
        assert sm.scrub_secrets(text) == "Your token is {{TOKEN}}"

    def test_load_from_files(self, tmp_path):
        """Test loading secrets from files (lines 24-28)"""
        secrets_dir = tmp_path / "secrets"
        secrets_dir.mkdir()

        # Create a secret file
        secret_file = secrets_dir / "API_KEY"
        secret_file.write_text("file-secret-value")

        # Create a directory (should be skipped by isfile check)
        sub_dir = secrets_dir / "not_a_secret"
        sub_dir.mkdir()

        sm = SecretManager(secrets_dir=str(secrets_dir))
        assert sm.get_secret("API_KEY") == "file-secret-value"
        assert "not_a_secret" not in sm.secrets

    def test_inject_secrets_nonexistent(self):
        """Test inject_secrets with nonexistent secret (line 38)"""
        sm = SecretManager()
        text = "Hello {{NONEXISTENT}}"
        assert sm.inject_secrets(text) == "Hello {{NONEXISTENT}}"
