import logging
import os
import re
import stat
from typing import Dict, Optional

logger = logging.getLogger("megabot.secrets")


class SecretManager:
    def __init__(self, secrets_dir: str = "secrets"):
        self.secrets_dir = secrets_dir
        self.secrets: Dict[str, str] = {}
        self._load_from_env()
        self._load_from_files()

    def _load_from_env(self):
        """Load secrets from environment variables starting with MEGABOT_SECRET_"""
        for key, value in os.environ.items():
            if key.startswith("MEGABOT_SECRET_"):
                secret_name = key[len("MEGABOT_SECRET_") :]
                self.secrets[secret_name] = value

    def _load_from_files(self):
        """Load secrets from files in the secrets directory"""
        if not os.path.exists(self.secrets_dir):
            return

        # Check directory permissions — warn if world-readable
        try:
            dir_stat = os.stat(self.secrets_dir)
            if dir_stat.st_mode & stat.S_IROTH:
                logger.warning(
                    "Secrets directory '%s' is world-readable (mode %o). Consider restricting with chmod 700.",
                    self.secrets_dir,
                    stat.S_IMODE(dir_stat.st_mode),
                )
        except OSError as e:
            logger.warning("Could not check permissions on secrets dir: %s", e)

        for filename in os.listdir(self.secrets_dir):
            file_path = os.path.join(self.secrets_dir, filename)
            if os.path.isfile(file_path):
                with open(file_path, "r") as f:
                    self.secrets[filename] = f.read().strip()

    def get_secret(self, name: str) -> Optional[str]:
        return self.secrets.get(name)

    # Maximum allowed length for a secret placeholder name to prevent
    # abuse via extremely long injection patterns.
    _MAX_SECRET_NAME_LEN = 128

    def inject_secrets(self, text: str) -> str:
        """Replace {{SECRET_NAME}} with actual secret values.

        Only replaces names that exist in the loaded secrets. Unknown
        placeholders are left as-is. Names exceeding _MAX_SECRET_NAME_LEN
        are ignored to prevent abuse.
        """

        def replace(match: re.Match) -> str:
            secret_name = match.group(1)
            if len(secret_name) > self._MAX_SECRET_NAME_LEN:
                return match.group(0)
            val = self.secrets.get(secret_name)
            return val if val is not None else match.group(0)

        return re.sub(r"\{\{([A-Z0-9_]+)\}\}", replace, text)

    def scrub_secrets(self, text: str) -> str:
        """Replace actual secret values with placeholders in text (for logging)"""
        scrubbed = text
        for name, value in self.secrets.items():
            if value:
                scrubbed = scrubbed.replace(value, f"{{{{{name}}}}}")
        return scrubbed
