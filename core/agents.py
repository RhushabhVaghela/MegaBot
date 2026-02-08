import logging
from typing import List, Dict

logger = logging.getLogger(__name__)


class SubAgent:
    ROLE_BOUNDARIES = {
        "Senior Dev": [
            "filesystem.read",
            "filesystem.write",
            "shell.test",
            "rag.query",
        ],
        "Security Reviewer": ["filesystem.read", "rag.query", "security.audit"],
        "QA Engineer": ["filesystem.read", "shell.test", "rag.query"],
        "Assistant": ["rag.query", "memory.search"],
        "Data Scientist": ["filesystem.read", "rag.query", "data.execute"],
    }

    def __init__(self, name: str, role: str, task: str, parent_orchestrator):
        self.name = name
        self.role = role if role in self.ROLE_BOUNDARIES else "Assistant"
        self.task = task
        self.parent = parent_orchestrator
        self.history = []
        self.max_steps = 5
        self.plan = []

    async def generate_plan(self) -> List[str]:
        """Ask the LLM to generate a step-by-step plan for the task"""
        prompt = f"As a {self.role}, create a step-by-step plan to achieve this task: {self.task}. Return only the steps as a list."
        response = await self.parent.llm.generate(
            context=f"Planning phase for {self.name}",
            messages=[{"role": "user", "content": prompt}],
        )
        if isinstance(response, str):
            # Basic parsing of numbered list or bullet points
            self.plan = [
                line.strip()
                for line in response.split("\n")
                if line.strip() and (line.strip()[0].isdigit() or line.strip().startswith("-"))
            ]
        return self.plan

    async def run(self) -> str:
        """Execute the sub-agent loop"""
        logger.info("Sub-Agent %s (%s) starting task: %s", self.name, self.role, self.task)

        # Pre-flight check: Ensure plan exists
        if not self.plan:
            await self.generate_plan()

        # Initial context
        context = f"You are a specialized sub-agent.\nName: {self.name}\nRole: {self.role}\nBoundaries: {self.ROLE_BOUNDARIES[self.role]}\nParent Goal: {self.task}\nPlanned Steps: {self.plan}"
        messages = [{"role": "user", "content": f"Perform the following task: {self.task}"}]

        for step in range(self.max_steps):
            try:
                # Sub-agents use the parent's LLM but can have restricted tools
                response = await self.parent.llm.generate(
                    context=context,
                    messages=messages,
                    # Sub-agents can use a subset of tools or just text
                    tools=self._get_sub_tools(),
                )

                if isinstance(response, str):
                    self.history.append({"role": "assistant", "content": response})
                    return response

                if isinstance(response, list):
                    # Handle tool use (delegated back to parent or handled locally)
                    # For now, sub-agents report what they want to do
                    tool_calls = [b for b in response if b.get("type") == "tool_use"]
                    if not tool_calls:
                        text = "".join([b["text"] for b in response if b.get("type") == "text"])
                        return text

                    # Simple delegation back to parent for actual execution
                    results = []
                    for call in tool_calls:
                        res = await self.parent._execute_tool_for_sub_agent(self.name, call)
                        results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": call["id"],
                                "content": res,
                            }
                        )

                    messages.append({"role": "assistant", "content": response})  # type: ignore
                    messages.append({"role": "user", "content": results})  # type: ignore

            except Exception as e:
                return f"Sub-agent error: {str(e)}"

        return "Sub-agent reached max steps without final answer."

    def _get_sub_tools(self) -> List[Dict]:
        """Define tools available to sub-agents based on role boundaries"""
        all_tools = [
            {
                "name": "read_file",
                "description": "Read a file from the project workspace.",
                "scope": "filesystem.read",
                "input_schema": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
            {
                "name": "write_file",
                "description": "Write or update a file.",
                "scope": "filesystem.write",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["path", "content"],
                },
            },
            {
                "name": "run_test",
                "description": "Execute a test command.",
                "scope": "shell.test",
                "input_schema": {
                    "type": "object",
                    "properties": {"command": {"type": "string"}},
                    "required": ["command"],
                },
            },
            {
                "name": "query_rag",
                "description": "Query project documentation.",
                "scope": "rag.query",
                "input_schema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
            {
                "name": "analyze_data",
                "description": "Perform deep analysis or execute python code on a loaded dataset.",
                "scope": "data.execute",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "dataset_name": {"type": "string"},
                        "query": {"type": "string"},
                        "python_code": {
                            "type": "string",
                            "description": "Optional python code for execution",
                        },
                    },
                    "required": ["dataset_name"],
                },
            },
        ]

        allowed_scopes = self.ROLE_BOUNDARIES.get(self.role, [])
        return [t for t in all_tools if t.get("scope") in allowed_scopes]
