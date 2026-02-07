import ast
import csv
import json
import logging
import signal
import threading
from typing import Any, Dict, List, Union
from core.llm_providers import LLMProvider
from core.resource_guard import LRUCache

logger = logging.getLogger("megabot.features.dash_data")

# ---------------------------------------------------------------------------
# AST-based sandbox validator
# ---------------------------------------------------------------------------

# Dunder attributes that enable sandbox escapes via class hierarchy traversal,
# frame introspection, or code object manipulation.
_BLOCKED_DUNDER_ATTRS = frozenset(
    {
        "__class__",
        "__bases__",
        "__mro__",
        "__subclasses__",
        "__dict__",
        "__globals__",
        "__code__",
        "__builtins__",
        "__import__",
        "__loader__",
        "__spec__",
        "__init__",
        "__new__",
        "__del__",
        "__getattr__",
        "__setattr__",
        "__delattr__",
        "__traceback__",
        "__cause__",
        "__context__",
        "__reduce__",
        "__reduce_ex__",
    }
)

# Function names that must never be called, even if somehow available.
_BLOCKED_CALL_NAMES = frozenset(
    {
        "eval",
        "exec",
        "compile",
        "open",
        "getattr",
        "setattr",
        "delattr",
        "__import__",
        "globals",
        "locals",
        "vars",
        "dir",
        "breakpoint",
        "input",
        "memoryview",
        "classmethod",
        "staticmethod",
        "property",
        "super",
        "type",
    }
)


def _validate_ast(tree: ast.AST) -> str | None:
    """Walk the AST and return an error message if unsafe nodes are found.

    Returns ``None`` if the code is safe, otherwise a human-readable
    error string describing the violation.
    """
    for node in ast.walk(tree):
        # Block all import statements (import x, from x import y)
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = ", ".join(alias.name for alias in getattr(node, "names", []))
            module = getattr(node, "module", None)
            target = module or names
            return f"Blocked pattern 'import' detected in code. Cannot import '{target}'."

        # Block attribute access to dangerous dunder names
        if isinstance(node, ast.Attribute):
            if node.attr in _BLOCKED_DUNDER_ATTRS:
                return f"Blocked pattern '{node.attr}' detected in code."
            # Also block any attribute starting+ending with __ not in our
            # known-safe set (belt-and-suspenders).
            if node.attr.startswith("__") and node.attr.endswith("__"):
                return f"Blocked pattern '{node.attr}' detected in code."

        # Block calls to dangerous function names
        if isinstance(node, ast.Call):
            func = node.func
            # Direct call: eval(...), exec(...), open(...), getattr(...)
            if isinstance(func, ast.Name) and func.id in _BLOCKED_CALL_NAMES:
                return f"Blocked pattern '{func.id}(' detected in code."
            # Method call on module-like names: os.system(...), sys.exit(...)
            if isinstance(func, ast.Attribute):
                if isinstance(func.value, ast.Name):
                    prefix = func.value.id
                    if prefix in ("os", "sys", "subprocess", "importlib", "shutil"):
                        return f"Blocked pattern '{prefix}.' detected in code."

        # Block Name nodes referencing dunder globals
        if isinstance(node, ast.Name):
            if node.id in (
                "__import__",
                "__builtins__",
                "__globals__",
                "__code__",
                "__loader__",
                "__spec__",
            ):
                return f"Blocked pattern '{node.id}' detected in code."

    return None


class DashDataAgent:
    """
    Advanced agent for data analysis tasks in MegaBot.
    Provides tools for deep CSV/JSON analysis using SearchR1 reasoning loops.
    """

    def __init__(self, llm: LLMProvider, orchestrator: Any = None):
        self.llm = llm
        self.orchestrator = orchestrator
        self.datasets: LRUCache[str, Union[List[Dict[str, Any]], Dict[str, Any]]] = LRUCache(maxsize=64)

    async def load_data(self, name: str, file_path: str) -> str:
        """Load a dataset into memory from a local file."""
        try:
            if file_path.endswith(".csv"):
                with open(file_path, mode="r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    self.datasets[name] = list(reader)
            elif file_path.endswith(".json"):
                with open(file_path, mode="r", encoding="utf-8") as f:
                    self.datasets[name] = json.load(f)
            else:
                return f"Error: Unsupported file format for '{file_path}'. Use CSV or JSON."

            count = len(self.datasets[name]) if isinstance(self.datasets[name], list) else 1
            return f"Successfully loaded dataset '{name}' with {count} records."
        except Exception as e:
            logger.error(f"Failed to load dataset '{name}': {e}")
            return f"Error loading data: {e}"

    async def get_summary(self, name: str) -> str:
        """Generate a technical summary of the dataset (schema, stats)."""
        if name not in self.datasets:
            return f"Dataset '{name}' not found."

        data = self.datasets[name]
        if not isinstance(data, list) or len(data) == 0:
            return f"Dataset '{name}' is empty or not a list."

        columns = list(data[0].keys())
        total_records = len(data)

        # Simple stats for numerical columns
        stats = {}
        for col in columns:
            try:
                values = [
                    float(row[col])
                    for row in data
                    if row.get(col) is not None and str(row[col]).replace(".", "", 1).isdigit()
                ]
                if values:
                    stats[col] = {
                        "min": min(values),
                        "max": max(values),
                        "avg": sum(values) / len(values),
                        "count": len(values),
                    }
            except (ValueError, TypeError):
                continue

        summary = {
            "name": name,
            "columns": columns,
            "total_records": total_records,
            "numerical_stats": stats,
            "sample": data[:2],
        }
        return json.dumps(summary, indent=2)

    async def analyze(self, name: str, query: str) -> str:
        """
        Perform a deep analysis on a dataset using the SearchR1 loop.
        """
        if name not in self.datasets:
            return f"Dataset '{name}' not found."

        # Use the reason() method if available on the LLM provider for deep analysis
        if hasattr(self.llm, "reason"):
            summary = await self.get_summary(name)
            prompt = f"Perform data analysis on dataset '{name}'.\nSummary: {summary}\nQuery: {query}"
            return await self.llm.reason(prompt=prompt)

        # Fallback to standard generate
        summary = await self.get_summary(name)
        prompt = f"""
        You are a Data Science expert.
        Analyze the following dataset metadata and answer the user query.
        
        Dataset Summary:
        {summary}
        
        User Query: {query}
        
        Provide a technical analysis including any trends or anomalies you suspect based on the summary.
        If you need to see more data, specify which columns or slices.
        """
        return await self.llm.generate(prompt=prompt)

    async def execute_python_analysis(self, name: str, python_code: str) -> str:
        """
        DANGEROUS: Executes generated python code on the dataset.
        Should be used with caution and permissions.
        """
        if name not in self.datasets:
            return f"Dataset '{name}' not found."

        # Security Interlock
        if self.orchestrator:
            auth = self.orchestrator.permissions.is_authorized("data.execute")
            if auth is False:
                return "Security Error: Permission denied for 'data.execute'."
            if auth == "ask" or auth is None:
                # Queue for approval
                import uuid

                action_id = str(uuid.uuid4())
                description = f"Data Analysis (Python): Execute code on dataset '{name}'"

                # Check if we can queue it
                if hasattr(self.orchestrator, "approval_queue"):
                    action = {
                        "id": action_id,
                        "type": "data_execution",
                        "payload": {"name": name, "code": python_code},
                        "description": description,
                    }
                    self.orchestrator.admin_handler.approval_queue.append(action)

                    # Notify admins
                    from core.interfaces import Message

                    admin_resp = Message(
                        content=f"📊 Approval Required: {description}\nType `!approve {action_id}` to authorize.",
                        sender="Security",
                    )
                    import asyncio

                    asyncio.create_task(
                        self.orchestrator.adapters["messaging"].send_message(
                            self.orchestrator._to_platform_message(admin_resp)
                        )
                    )
                    return f"Action queued for approval (ID: {action_id}). Please authorize via UI or Admin command."

        data = self.datasets[name]

        # --- Sandboxed execution with AST validation ---
        # Step 1: Parse the code into an AST and validate it structurally.
        # This replaces the old string-pattern blocklist which was bypassable
        # via whitespace, string concatenation, and other trivial tricks.
        try:
            tree = ast.parse(python_code, mode="exec")
        except SyntaxError as e:
            return f"Python execution error: {e}"

        validation_error = _validate_ast(tree)
        if validation_error:
            return f"Security Error: {validation_error}"

        # Step 2: Restrict builtins to a safe subset.
        # NOTE: 'type' is excluded (enables class hierarchy traversal).
        # NOTE: Exception classes are excluded (enable __traceback__ frame escape).
        _SAFE_BUILTINS = {
            "abs": abs,
            "all": all,
            "any": any,
            "bool": bool,
            "dict": dict,
            "enumerate": enumerate,
            "filter": filter,
            "float": float,
            "frozenset": frozenset,
            "int": int,
            "isinstance": isinstance,
            "len": len,
            "list": list,
            "map": map,
            "max": max,
            "min": min,
            "print": print,
            "range": range,
            "reversed": reversed,
            "round": round,
            "set": set,
            "sorted": sorted,
            "str": str,
            "sum": sum,
            "tuple": tuple,
            "zip": zip,
            "True": True,
            "False": False,
            "None": None,
        }
        sandbox_globals = {"__builtins__": _SAFE_BUILTINS}
        local_vars = {"data": data, "result": None}

        try:
            # Run exec() in a thread with a 5-second timeout to prevent
            # infinite loops or CPU-intensive code from blocking the server.
            exec_error: List[Exception] = []

            def _run_sandboxed():
                try:
                    exec(python_code, sandbox_globals, local_vars)  # noqa: S102
                except Exception as e:
                    exec_error.append(e)

            t = threading.Thread(target=_run_sandboxed, daemon=True)
            t.start()
            t.join(timeout=5.0)
            if t.is_alive():
                return "Python execution error: code exceeded 5-second time limit"
            if exec_error:
                return f"Python execution error: {exec_error[0]}"
            result_str = str(local_vars.get("result", "Code executed but no 'result' variable set."))
            # Cap output size to prevent memory exhaustion
            if len(result_str) > 100_000:
                result_str = result_str[:100_000] + "\n... [output truncated at 100KB]"
            return result_str
        except Exception as e:
            return f"Python execution error: {e}"
