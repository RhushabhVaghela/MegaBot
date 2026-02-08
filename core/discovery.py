import logging
import os

logger = logging.getLogger(__name__)


class ModuleDiscovery:
    def __init__(self, base_path: str):
        self.base_path = base_path
        self.capabilities = {}

    def scan(self):
        logger.info("Scanning for capabilities in %s...", self.base_path)
        # Scan all directories in base_path for skills and kits
        if not os.path.exists(self.base_path):
            logger.warning("Base path %s not found.", self.base_path)
            return

        for item in os.listdir(self.base_path):
            path = os.path.join(self.base_path, item)
            if os.path.isdir(path):
                self.capabilities[item] = path
                logger.info("Found capability: %s at %s", item, path)

                # Check for nested skills
                skills_path = os.path.join(path, "skills")
                if os.path.exists(skills_path):
                    found_skills = [d for d in os.listdir(skills_path) if os.path.isdir(os.path.join(skills_path, d))]
                    if "skills" not in self.capabilities:
                        self.capabilities["skills"] = []
                    self.capabilities["skills"].extend(found_skills)
                    logger.info("Indexed %d skills from %s.", len(found_skills), item)

    def get_capability_path(self, name: str):
        return self.capabilities.get(name)
