import logging
import os
import re
import json
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class PageIndexRAG:
    """
    Structural, Vectorless RAG system.
    Instead of vector similarity, it uses a hierarchical index (Page Index)
    and LLM-guided navigation to reason over a codebase.
    """

    def __init__(self, root_dir: str, llm: Optional[Any] = None):
        self.root_dir = root_dir
        self.llm = llm
        self.index: Dict[str, Any] = {}
        self.index_path = os.path.join(root_dir, ".megabot_index.json")

    async def build_index(self, force_rebuild: bool = False):
        """Creates a hierarchical map of the codebase with summaries. Uses cache if available."""
        if not force_rebuild and os.path.exists(self.index_path):
            try:
                logger.info("RAG: Loading cached index from %s...", self.index_path)
                with open(self.index_path, "r") as f:
                    self.index = json.load(f)
                return
            except Exception as e:
                logger.warning("RAG: Failed to load cache: %s", e)

        logger.info("RAG: Building structural index for %s...", self.root_dir)
        self.index = {"root": self.root_dir, "files": {}, "folders": {}}

        self._walk_and_index(self.root_dir, self.index)

        # Save to cache
        try:
            with open(self.index_path, "w") as f:
                json.dump(self.index, f)
            logger.info("RAG: Index cached to %s", self.index_path)
        except Exception as e:
            logger.warning("RAG: Failed to save cache: %s", e)

    def _walk_and_index(self, root_dir, current_index):
        for root, dirs, files in os.walk(root_dir):
            # Avoid hidden folders and common noise
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ["node_modules", "__pycache__", "venv"]]

            rel_path = os.path.relpath(root, root_dir)
            current = current_index
            if rel_path != ".":
                for part in rel_path.split(os.sep):
                    if part not in current["folders"]:
                        current["folders"][part] = {"files": {}, "folders": {}}
                    current = current["folders"][part]

            for file in files:
                if file.endswith((".md", ".py", ".js", ".ts", ".txt", ".yaml", ".yml", ".json")):
                    file_path = os.path.join(root, file)
                    try:
                        with open(file_path, "r", encoding="utf-8") as f:
                            content = f.read()

                        current["files"][file] = {
                            "size": len(content),
                            "headers": self._extract_symbols(content, file),
                            "summary": self._generate_quick_summary(content),
                        }
                    except Exception:
                        continue
        # Since os.walk already visits everything, we don't need to manually recurse here
        # but the way I structured build_index previously was a bit different.
        # Let's keep it consistent.

    def _extract_symbols(self, content: str, filename: str) -> List[str]:
        if filename.endswith(".py"):
            return re.findall(r"^(?:class|def)\s+([a-zA-Z_][a-zA-Z0-9_]*)", content, re.MULTILINE)
        if filename.endswith((".js", ".ts")):
            return re.findall(
                r"^(?:class|function|const)\s+([a-zA-Z_][a-zA-Z0-9_]*)",
                content,
                re.MULTILINE,
            )
        if filename.endswith(".md"):
            return re.findall(r"^#+\s+(.+)$", content, re.MULTILINE)
        return []

    def _generate_quick_summary(self, content: str) -> str:
        # Take the first few non-empty lines
        lines = [line.strip() for line in content.split("\n") if line.strip()]
        return " ".join(lines[:3])[:200] + "..."

    async def navigate(self, query: str) -> str:
        """
        Reasoning loop for navigation.
        If an LLM is provided, it uses it to 'decide' where to look.
        Otherwise, it does a structural keyword search.
        """
        if not self.index:
            await self.build_index()

        if self.llm:
            return await self._reasoned_navigation(query)

        return self._keyword_navigation(query)

    def _keyword_navigation(self, query: str) -> str:
        results = []
        q = query.lower()

        def search_dict(d, path=""):
            for fname, info in d.get("files", {}).items():
                fpath = os.path.join(path, fname)
                if q in fpath.lower() or q in info["summary"].lower() or any(q in s.lower() for s in info["headers"]):
                    results.append(f"File: {fpath}\n  Summary: {info['summary']}\n  Symbols: {info['headers'][:5]}")

            for dname, sub in d.get("folders", {}).items():
                search_dict(sub, os.path.join(path, dname))

        search_dict(self.index)
        if not results:
            return "No matching files found in structural index."
        return "\n\n".join(results[:5])

    async def _reasoned_navigation(self, query: str) -> str:
        """Uses LLM to navigate the structural index."""
        if not self.llm:
            return self._keyword_navigation(query)

        index_str = json.dumps(self._get_collapsed_index(), indent=2)
        prompt = f"""
        You are a Structural Navigation Agent. 
        Given the following high-level 'Page Index' of a codebase, identify the 3 most relevant files to answer the user query.
        
        QUERY: {query}
        INDEX:
        {index_str}
        
        Return a JSON list of relative file paths.
        """
        try:
            res = await self.llm.generate(
                context="PageIndex Reasoning",
                messages=[{"role": "user", "content": prompt}],
            )
            # Basic JSON extraction
            paths = re.findall(r'["\']([^"\']+\.[a-z0-9]+)["\']', str(res))
            if not paths:
                return self._keyword_navigation(query)

            detailed_results = []
            for p in paths:
                content = await self.get_file_context(p)
                detailed_results.append(f"--- {p} ---\n{content}")

            return "\n\n".join(detailed_results)
        except Exception as e:
            return f"Reasoning RAG failed: {e}. Falling back to keywords.\n" + self._keyword_navigation(query)

    def _get_collapsed_index(self, max_depth=2) -> Dict:
        """Returns a simplified version of the index for LLM context."""

        def collapse(d, depth):
            if depth > max_depth:
                return {"note": "Max depth reached"}
            res = {
                "files": list(d["files"].keys()),
                "folders": {k: collapse(v, depth + 1) for k, v in d["folders"].items()},
            }
            return res

        return collapse(self.index, 0)

    async def get_file_context(self, rel_path: str) -> str:
        """Retrieve actual content snippets for a specific path."""
        abs_path = os.path.join(self.root_dir, rel_path)
        if not os.path.exists(abs_path):
            return f"Error: File {rel_path} not found."

        try:
            with open(abs_path, "r", encoding="utf-8") as f:
                # Read first 100 lines for context
                lines = f.readlines()
                return "".join(lines[:100])
        except Exception as e:
            return f"Error reading file: {e}"
