import os

import pytest

from core.discovery import ModuleDiscovery


@pytest.fixture
def mock_repo_dir(tmp_path):
    repo_dir = tmp_path / "repos"
    repo_dir.mkdir()
    (repo_dir / "ui-ux-pro-max-skill").mkdir()
    (repo_dir / "antigravity-kit").mkdir()
    awesome_skills = repo_dir / "antigravity-awesome-skills"
    awesome_skills.mkdir()
    (awesome_skills / "skills").mkdir()
    (awesome_skills / "skills" / "test-skill").mkdir()
    return str(repo_dir)

def test_module_discovery(mock_repo_dir):
    discovery = ModuleDiscovery(mock_repo_dir)
    discovery.scan()
    
    assert "ui-ux-pro-max-skill" in discovery.capabilities
    assert "antigravity-kit" in discovery.capabilities
    assert "antigravity-awesome-skills" in discovery.capabilities
    assert "skills" in discovery.capabilities
    assert "test-skill" in discovery.capabilities["skills"]
    
    assert discovery.get_capability_path("ui-ux-pro-max-skill") == os.path.join(mock_repo_dir, "ui-ux-pro-max-skill")

def test_module_discovery_not_found():
    discovery = ModuleDiscovery("/non/existent/path")
    discovery.scan()
    assert discovery.capabilities == {}
