import logging
from enum import Enum

logger = logging.getLogger(__name__)


class PermissionLevel(Enum):
    """
    AUTO: Action is performed without asking.
    ASK_EACH: Action requires manual approval every time.
    NEVER: Action is always blocked.
    """

    AUTO = "AUTO"
    ASK_EACH = "ASK_EACH"
    NEVER = "NEVER"


class PermissionManager:
    """
    Tiered Permission Manager: Enforces security levels across MegaBot tools.
    Supports granular overrides (e.g., 'shell.execute', 'filesystem.write').
    """

    def __init__(self, default_level: str = "ASK_EACH"):
        try:
            self.default_level = PermissionLevel(default_level.upper())
        except ValueError:
            self.default_level = PermissionLevel.ASK_EACH

        self.overrides: dict[str, PermissionLevel] = {}

    def set_policy(self, scope: str, level: str) -> None:
        """Set a policy for a specific scope."""
        try:
            self.overrides[scope] = PermissionLevel(level.upper())
        except ValueError as e:
            logger.warning("Invalid permission level %r for scope %r: %s", level, scope, e)

    def get_effective_level(self, scope: str) -> PermissionLevel:
        """Determine the effective permission level for a scope."""
        # 1. Global wildcard check
        if "*" in self.overrides:
            return self.overrides["*"]

        # 2. Exact match
        if scope in self.overrides:
            return self.overrides[scope]

        # 3. Shell command prefix match (space-separated)
        # Allows matching 'rm -rf' for 'rm -rf /'
        # Only apply this to shell commands or ensure exact word boundary
        target_cmd = scope[6:] if scope.startswith("shell.") else scope
        for override_scope, level in self.overrides.items():
            override_cmd = override_scope[6:] if override_scope.startswith("shell.") else override_scope
            # Check if target command matches or starts with override + space
            if target_cmd == override_cmd or target_cmd.startswith(override_cmd + " "):
                return level

        # 4. Parent match (e.g., 'filesystem' for 'filesystem.read')
        parts = scope.split(".")
        for i in range(len(parts) - 1, 0, -1):
            parent = ".".join(parts[:i])
            if parent in self.overrides:
                return self.overrides[parent]

        return self.default_level

    def is_authorized(self, scope: str) -> bool | None:
        """
        Returns:
            True if AUTO
            False if NEVER
            None if ASK_EACH (requires external approval)
        """
        level = self.get_effective_level(scope)
        if level == PermissionLevel.AUTO:
            return True
        if level == PermissionLevel.NEVER:
            return False
        return None  # ASK_EACH

    def load_from_config(self, config_dict: dict) -> None:
        """Load policies from a configuration dictionary."""
        policies = config_dict.get("policies", {})

        # Map from config structure (lists of allowed/denied) to overrides
        for cmd in policies.get("allow", []):
            self.set_policy(cmd, "AUTO")
        for cmd in policies.get("deny", []):
            self.set_policy(cmd, "NEVER")

        # Set default if specified
        if "default_permission" in config_dict:
            try:
                self.default_level = PermissionLevel(config_dict["default_permission"].upper())
            except ValueError as e:
                logger.warning("Invalid default_permission %r in config: %s", config_dict["default_permission"], e)
