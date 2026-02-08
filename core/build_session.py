"""Autonomous build session logic extracted from ``core/orchestrator.py``.

Contains the autonomous build loop (WebSocket and gateway variants) and the
proactive memory-lesson injection helper that both build paths depend on.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, TYPE_CHECKING

logger = logging.getLogger(__name__)

from fastapi import WebSocket  # type: ignore

from core.interfaces import Message
from core.resource_guard import can_allocate, InsufficientResourcesError
from core.task_utils import safe_create_task as _safe_create_task

if TYPE_CHECKING:
    from core.orchestrator import MegaBotOrchestrator


# ------------------------------------------------------------------
# Proactive memory injection
# ------------------------------------------------------------------


async def get_relevant_lessons(orchestrator: "MegaBotOrchestrator", prompt: str) -> str:
    """Extract keywords and fetch broadened architectural lessons from memory.

    Args:
        orchestrator: The MegaBotOrchestrator instance.
        prompt: The user prompt to extract keywords from.

    Returns:
        A formatted string of lessons to inject into the context, or empty string.
    """
    try:
        extract_prompt = (
            f"Identify the primary technologies, libraries, and architectural patterns "
            f"in this request: '{prompt}'. Return only a comma-separated list of keywords."
        )
        keywords_raw = await orchestrator.llm.generate(
            context="Keyword Extraction",
            messages=[{"role": "user", "content": extract_prompt}],
        )
        keywords = [k.strip() for k in str(keywords_raw).split(",") if k.strip()]

        all_lessons: List[Dict[str, Any]] = []
        seen_content: set = set()

        direct_search = await orchestrator.memory.memory_search(query=prompt, type="learned_lesson", limit=5)
        all_lessons.extend(direct_search)

        # PERF-10: Parallelize keyword searches
        if keywords[:5]:
            search_tasks = [
                orchestrator.memory.memory_search(query=kw, type="learned_lesson", limit=3) for kw in keywords[:5]
            ]
            results_lists = await asyncio.gather(*search_tasks)
            for results in results_lists:
                for res in results:
                    content = res.get("content", "")
                    if content not in seen_content:
                        all_lessons.append(res)
                        seen_content.add(content)

        if not all_lessons:
            return ""

        if len(all_lessons) > 3:
            lessons_text = "\n".join([f"- {lesson['content']}" for lesson in all_lessons])
            distill_prompt = (
                f"Summarize the following architectural lessons into a concise, "
                f"high-priority list (max 3 points):\n\n{lessons_text}"
            )
            distilled = await orchestrator.llm.generate(
                context="Memory Distillation",
                messages=[{"role": "user", "content": distill_prompt}],
            )
            return f"\n[DISTILLED LESSONS FROM MEMORY]:\n{distilled}\n"

        formatted = "\n[PROACTIVE LESSONS FROM MEMORY]:\n"
        for lesson in all_lessons[:10]:
            prefix = "CRITICAL: " if "CRITICAL" in lesson["content"].upper() else "- "
            formatted += f"{prefix}{lesson['content']}\n"
        return formatted
    except Exception as e:  # pragma: no cover
        logger.error("Lesson injection failed: %s", e)
        return ""


# ------------------------------------------------------------------
# Gateway build
# ------------------------------------------------------------------


async def run_autonomous_gateway_build(
    orchestrator: "MegaBotOrchestrator",
    message: Message,
    original_data: Dict,
) -> None:
    """Autonomous build for gateway clients (relays back to gateway instead of UI websocket).

    Args:
        orchestrator: The MegaBotOrchestrator instance.
        message: The user message triggering the build.
        original_data: The raw gateway message data (contains _meta with client info).

    Raises:
        InsufficientResourcesError: If RAM headroom is too low to start the build.
    """
    # Pre-flight resource check
    try:
        ram_needed = int(orchestrator.config.system.resources.estimated_ram_per_build_mb)
    except (AttributeError, TypeError, ValueError):
        ram_needed = 512
    can_allocate(ram_mb=ram_needed, raise_on_failure=True)

    # Proactive Memory Injection
    lessons = await get_relevant_lessons(orchestrator, message.content)
    if lessons:
        message.content = lessons + "\n" + message.content

    tools_res = await orchestrator.adapters["mcp"].call_tool(None, "list_allowed_directories", {})
    await orchestrator.adapters["openclaw"].send_message(message)

    client_id = original_data.get("_meta", {}).get("client_id")
    platform = original_data.get("_meta", {}).get("connection_type", "gateway")
    if client_id:
        msg = Message(content=f"Build started. Auth paths: {tools_res}", sender="MegaBot")
        await orchestrator.send_platform_message(msg, platform=platform, target_client=client_id)


# ------------------------------------------------------------------
# WebSocket build
# ------------------------------------------------------------------


async def run_autonomous_build(
    orchestrator: "MegaBotOrchestrator",
    message: Message,
    websocket: WebSocket,
) -> None:  # pragma: no cover
    """Run autonomous build session via WebSocket.

    Implements a multi-step agentic loop that:
    1. Retrieves relevant memories and lessons
    2. Iteratively consults the LLM with tool support
    3. Executes tool calls (computer use, sub-agents, RAG, MCP)
    4. Learns from the interaction at completion

    Args:
        orchestrator: The MegaBotOrchestrator instance.
        message: The user message triggering the build.
        websocket: The WebSocket connection to relay status updates to.

    Raises:
        InsufficientResourcesError: If RAM headroom is too low to start the build.
    """
    # Pre-flight resource check
    try:
        ram_needed = int(orchestrator.config.system.resources.estimated_ram_per_build_mb)
    except (AttributeError, TypeError, ValueError):
        ram_needed = 512
    if not can_allocate(ram_mb=ram_needed):
        await websocket.send_json(
            {
                "type": "error",
                "content": f"Build blocked: insufficient RAM ({ram_needed} MB needed). Try again later.",
            }
        )
        return

    await websocket.send_json({"type": "status", "content": "MegaBot is starting autonomous session..."})

    await websocket.send_json({"type": "status", "content": "Searching memory for relevant skills..."})
    memories = await orchestrator.adapters["memu"].search(message.content)

    await websocket.send_json({"type": "status", "content": "Consulting persistent memory for lessons..."})
    lessons = await get_relevant_lessons(orchestrator, message.content)

    skill_context = ""
    if memories:
        skill_context += "\nRelevant Previous Plans found in memory:\n"
        for m in memories[:3]:
            content = m.get("content", "")
            skill_context += f"- {content}\n"

    if lessons:
        skill_context += lessons

    tools_res = await orchestrator.adapters["mcp"].call_tool("filesystem", "list_allowed_directories", {})

    native_tools = [
        {
            "type": "computer_20241022",
            "name": "computer",
            "display_width_px": 1024,
            "display_height_px": 768,
            "display_number": 0,
        },
        {
            "name": "spawn_sub_agent",
            "description": "Create a specialized sub-agent for a specific task.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Unique name for the sub-agent",
                    },
                    "task": {
                        "type": "string",
                        "description": "The specific task for the sub-agent to perform",
                    },
                    "role": {
                        "type": "string",
                        "description": "The persona/role of the sub-agent (e.g., 'Security Expert', 'Senior Dev')",
                    },
                },
                "required": ["name", "task"],
            },
        },
        {
            "name": "query_project_rag",
            "description": "Query the local project documentation and code structure.",
            "input_schema": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "The search query"}},
                "required": ["query"],
            },
        },
    ]

    messages: List[Dict[str, Any]] = [{"role": "user", "content": message.content}]
    max_steps = 10

    project = orchestrator.project_manager.current_project
    project_prompt = project.get_system_prompt() if project else ""

    for step in range(max_steps):
        try:
            await websocket.send_json({"type": "status", "content": f"Step {step + 1}: Consulting LLM..."})

            project_context = f"\nCurrent Project Workspace: {project.files_path if project else 'N/A'}"
            full_context = f"Allowed Paths: {tools_res}{skill_context}{project_context}\n{project_prompt}"

            llm_response = await orchestrator.llm.generate(context=full_context, tools=native_tools, messages=messages)

            if isinstance(llm_response, list):
                tool_use_found = False
                messages.append({"role": "assistant", "content": llm_response})

                for block in llm_response:
                    if block.get("type") == "text":
                        await websocket.send_json({"type": "status", "content": f"Thought: {block['text']}"})

                    if block.get("type") == "tool_use":
                        tool_use_found = True
                        tool_name = block.get("name")
                        tool_input = block.get("input")
                        action_id = block.get("id")

                        if tool_name == "computer":
                            loop = asyncio.get_running_loop()
                            future = loop.create_future()

                            def on_executed(result):
                                if not future.done():
                                    future.set_result(result)

                            await orchestrator._handle_computer_tool(
                                tool_input,
                                websocket,
                                action_id,
                                callback=on_executed,
                            )
                            await websocket.send_json(
                                {
                                    "type": "status",
                                    "content": f"Waiting for approval of: {tool_input.get('action')}...",
                                }
                            )
                            result = await future

                        elif tool_name == "spawn_sub_agent":
                            await websocket.send_json(
                                {"type": "status", "content": f"Spawning sub-agent '{tool_input.get('name')}'..."}
                            )
                            result = await orchestrator._spawn_sub_agent(tool_input)

                        elif tool_name == "query_project_rag":
                            await websocket.send_json(
                                {"type": "status", "content": f"Querying RAG for '{tool_input.get('query')}'..."}
                            )
                            result = await orchestrator.rag.navigate(tool_input.get("query"))

                        else:
                            result = await orchestrator.adapters["mcp"].call_tool(
                                None,
                                tool_name,
                                tool_input,
                            )

                        messages.append(
                            {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "tool_result",
                                        "tool_use_id": action_id,
                                        "content": result,
                                    }
                                ],
                            }
                        )

                if not tool_use_found:
                    break

            elif isinstance(llm_response, str):
                await websocket.send_json({"type": "message", "content": llm_response, "sender": "MegaBot"})
                break

        except Exception as e:
            logger.error("Autonomous build error at step %s: %s", step, e)
            await websocket.send_json({"type": "status", "content": f"Error: {str(e)}"})
            break

    await orchestrator.adapters["memu"].learn_from_interaction(
        {
            "action": "autonomous_build",
            "prompt": message.content,
            "session_log": messages,
            "timestamp": datetime.now().isoformat(),
        }
    )
    await websocket.send_json({"type": "status", "content": "Autonomous build session completed."})
