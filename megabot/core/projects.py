import shutil
from pathlib import Path


class ProjectContext:
    def __init__(self, name: str, base_path: str):
        self.name = name
        self.base_path = Path(base_path) / "projects" / name
        self.files_path = self.base_path / "files"
        self.prompts_path = self.base_path / "prompts"
        self.memory_path = self.base_path / "memory"
        self.logs_path = self.base_path / "logs"
        self.config_path = self.base_path / "project-config.yaml"

        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        """Create project structure if it doesn't exist"""
        for path in [self.files_path, self.prompts_path, self.memory_path, self.logs_path]:
            path.mkdir(parents=True, exist_ok=True)

    def get_system_prompt(self) -> str:
        """Load project-specific system prompt if exists, otherwise return default"""
        prompt_file = self.prompts_path / "system.md"
        if prompt_file.exists():
            return prompt_file.read_text()
        return ""

    def list_files(self) -> list[str]:
        """List files in the project workspace"""
        return [str(p.relative_to(self.files_path)) for p in self.files_path.rglob("*") if p.is_file()]


class ProjectManager:
    def __init__(self, base_path: str):
        self.base_path = base_path
        self.current_project: ProjectContext | None = None

    def create_project(self, name: str) -> ProjectContext:
        """Create a new project workspace"""
        return ProjectContext(name, self.base_path)

    def switch_project(self, name: str) -> ProjectContext:
        """Switch to an existing project or create it"""
        self.current_project = ProjectContext(name, self.base_path)
        return self.current_project

    def delete_project(self, name: str) -> None:
        """Delete a project workspace"""
        project_path = Path(self.base_path) / "projects" / name
        if project_path.exists():
            shutil.rmtree(project_path)
        if self.current_project and self.current_project.name == name:
            self.current_project = None
