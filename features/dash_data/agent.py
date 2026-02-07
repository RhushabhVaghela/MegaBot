import csv
import json
import logging
from typing import Any, Dict, List, Union
from core.llm_providers import LLMProvider

logger = logging.getLogger("megabot.features.dash_data")


class DashDataAgent:
    """
    Advanced agent for data analysis tasks in MegaBot.
    Provides tools for deep CSV/JSON analysis using SearchR1 reasoning loops.
    """

    def __init__(self, llm: LLMProvider, orchestrator: Any = None):
        self.llm = llm
        self.orchestrator = orchestrator
        self.datasets: Dict[str, Union[List[Dict[str, Any]], Dict[str, Any]]] = {}

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

            count = (
                len(self.datasets[name]) if isinstance(self.datasets[name], list) else 1
            )
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
                    if row.get(col) is not None
                    and str(row[col]).replace(".", "", 1).isdigit()
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
                description = (
                    f"Data Analysis (Python): Execute code on dataset '{name}'"
                )

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

        # --- Sandboxed execution ---
        # Restrict builtins to a safe subset; block import, eval, exec, compile, open.
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
            "type": type,
            "zip": zip,
            "True": True,
            "False": False,
            "None": None,
            # Common exceptions needed for data analysis code
            "Exception": Exception,
            "ValueError": ValueError,
            "TypeError": TypeError,
            "KeyError": KeyError,
            "IndexError": IndexError,
            "RuntimeError": RuntimeError,
            "ArithmeticError": ArithmeticError,
            "ZeroDivisionError": ZeroDivisionError,
            "StopIteration": StopIteration,
            "AttributeError": AttributeError,
        }
        sandbox_globals = {"__builtins__": _SAFE_BUILTINS}
        local_vars = {"data": data, "result": None}

        # Block obvious escape attempts in source
        _BLOCKED_PATTERNS = [
            "__import__",
            "importlib",
            "subprocess",
            "os.",
            "sys.",
            "open(",
            "eval(",
            "exec(",
            "compile(",
            "getattr(",
            "__subclasses__",
            "__globals__",
            "__code__",
            "__builtins__",
        ]
        code_lower = python_code.lower()
        for pattern in _BLOCKED_PATTERNS:
            if pattern.lower() in code_lower:
                return f"Security Error: Blocked pattern '{pattern}' detected in code."

        try:
            exec(python_code, sandbox_globals, local_vars)  # noqa: S102
            return str(
                local_vars.get("result", "Code executed but no 'result' variable set.")
            )
        except Exception as e:
            return f"Python execution error: {e}"
