"""MegaBot Orchestrator — central coordination hub.

This module contains the ``MegaBotOrchestrator`` class which coordinates
all MegaBot subsystems.  FastAPI app creation, route handlers, and CORS
configuration have been extracted to ``core.app``.  WebSocket client
handling lives in ``core.websocket_handler`` and lifecycle management
(start/shutdown/restart) in ``core.lifecycle``.  Autonomous build sessions
live in ``core.build_session``, OpenClaw event routing in
``core.openclaw_handler``, and approval/security workflows in
``core.approval_workflows``.

For backward compatibility every public name that previously lived here
is re-exported at the bottom of this file so that existing import sites
(``from core.orchestrator import app, health, ...``) continue to work.
"""

import os
import sys
import json
import re
from typing import Any, Dict, Optional, List

from fastapi import WebSocket  # type: ignore


# Defensive task scheduling: centralised in core.task_utils so that
# every module can import the same helper without circular deps.
from core.task_utils import (
    safe_create_task as _safe_create_task,
    _tracked_tasks as _orchestrator_tasks,
    sanitize_action as _sanitize_action,
    sanitize_queue as _sanitize_queue,
)  # noqa: F401


from core.dependencies import (
    register_service,
    register_factory,
    register_singleton,
    resolve_service,
)


# Re-export for backward compat (websocket_handler etc. cannot import
# directly from orchestrator without circular deps).
_sanitize_action_compat = _sanitize_action


from core.discovery import ModuleDiscovery
from core.config import load_config, Config, AdapterConfig
from core.interfaces import Message
from core.llm_providers import get_llm_provider, LLMProvider
from core.drivers import ComputerDriver
from core.projects import ProjectManager
from core.secrets import SecretManager
from core.rag.pageindex import PageIndexRAG
from core.loki import LokiMode
from core.resource_guard import ResourceGuard
from core.permissions import PermissionManager
from core.memory.mcp_server import MemoryServer
from adapters.openclaw_adapter import OpenClawAdapter
from adapters.memu_adapter import MemUAdapter
from adapters.mcp_adapter import MCPManager
from adapters.messaging import MegaBotMessagingServer
from adapters.unified_gateway import UnifiedGateway
from adapters.security.tirith_guard import guard as tirith

# Import extracted components
from core.orchestrator_components import MessageHandler, HealthMonitor, BackgroundTasks
from core.admin_handler import AdminHandler
from core.message_router import MessageRouter
from core.agent_coordinator import AgentCoordinator
from core.logging_setup import attach_audit_file_handler

# Shared constants (avoids circular import with websocket_handler)
from core.constants import GREETING_TEXT  # noqa: F401

# Extracted modules
from core import lifecycle as _lifecycle
from core import websocket_handler as _ws_handler
from core import build_session as _build_session
from core import openclaw_handler as _openclaw_handler
from core import approval_workflows as _approval_workflows


class MegaBotOrchestrator:
    """Central orchestrator for MegaBot's unified AI assistant.

    This class coordinates all MegaBot activities including:
    - Message routing across multiple platforms
    - Agent lifecycle management and coordination
    - Memory augmentation and context management
    - Security approval workflows
    - Tool execution via MCP and OpenClaw
    - Background task management

    The orchestrator implements a multi-mode architecture supporting:
    - ask: Direct question answering
    - plan: Structured planning and task breakdown
    - build: Code generation and implementation
    - loki: Autonomous full-project development

    Attributes:
        config: Application configuration object
        adapters: Dictionary of initialized platform and tool adapters
        memory: Persistent memory server for cross-session context
        permissions: Security permission manager
        llm: Language model provider for AI capabilities
    """

    def __init__(self, config):
        """Initialize the MegaBot orchestrator with configuration.

        Args:
            config: Application configuration object containing adapter configs,
                   security policies, and system settings.
        """
        self.config = config

        # Optionally attach audit file handler early so structured audit events
        # emitted by AgentCoordinator and other components are persisted to
        # disk in deployed runs.
        try:
            enable_env = os.environ.get("MEGABOT_ENABLE_AUDIT_LOG", "").lower() in (
                "1",
                "true",
                "yes",
            )

            is_ci = os.environ.get("CI") is not None or os.environ.get("GITHUB_ACTIONS") is not None
            looks_like_pytest = "pytest" in " ".join(sys.argv)

            if enable_env or (not is_ci and not looks_like_pytest):
                audit_path = self.config.paths.get("audit_log", "logs/audit.log")
                attach_audit_file_handler(audit_path)
        except Exception:
            pass

        # Register core services with DI container
        register_service(Config, config)
        register_singleton(MemoryServer, MemoryServer())
        register_factory(ComputerDriver, lambda: ComputerDriver())

        project_path = self.config.paths.get("workspaces", os.getcwd())

        register_factory(
            ProjectManager,
            lambda: ProjectManager(self.config.paths.get("workspaces", os.getcwd())),
        )
        register_factory(SecretManager, lambda: SecretManager())
        register_factory(
            PageIndexRAG,
            lambda: PageIndexRAG(
                project_path,
                llm=resolve_service(LLMProvider),
            ),
        )

        # Resolve services
        self.discovery = ModuleDiscovery(self.config.paths["external_repos"])
        self.mode = self.config.system.default_mode

        # Initialize LLM Provider
        llm_config = self.config.adapters.get("llm", {})
        if isinstance(llm_config, AdapterConfig):
            llm_config = llm_config.model_dump()
        self.llm = get_llm_provider(llm_config)
        register_singleton(LLMProvider, self.llm)

        # Initialize component handlers
        self.message_handler = MessageHandler(self)
        self.admin_handler = AdminHandler(self)
        self.health_monitor = HealthMonitor(self)
        self.background_tasks = BackgroundTasks(self)
        self.message_router = MessageRouter(self)

        # Resolve other services
        self.computer_driver = resolve_service(ComputerDriver)
        self.project_manager = resolve_service(ProjectManager)
        self.project_manager.switch_project("default")
        self.secret_manager = resolve_service(SecretManager)
        self.rag = resolve_service(PageIndexRAG)
        self.permissions = PermissionManager(
            default_level=getattr(self.config.system, "default_permission", "ASK_EACH")
        )
        self.permissions.load_from_config(self.config.model_dump())
        self.memory = resolve_service(MemoryServer)
        self.sub_agents = {}
        self.last_active_chat = None
        self.loki = LokiMode(self)
        self.resource_guard = ResourceGuard()
        self.clients = set()
        self.agent_coordinator = AgentCoordinator(self)

        # Initialize High-Level Features
        from features.dash_data.agent import DashDataAgent

        self.features = {"dash_data": DashDataAgent(self.llm, self)}

        self.adapters = {
            "openclaw": OpenClawAdapter(
                self.config.adapters["openclaw"].host,
                self.config.adapters["openclaw"].port,
            ),
            "memu": MemUAdapter(
                self.config.paths["external_repos"] + "/memU",
                self.config.adapters["memu"].database_url,
            ),
            "mcp": MCPManager(self.config.adapters["mcp"].servers if "mcp" in self.config.adapters else []),
            "messaging": MegaBotMessagingServer(
                host=self.config.system.messaging_host,
                port=self.config.system.messaging_port,
                enable_encryption=True,
            ),
            "gateway": UnifiedGateway(
                megabot_server_port=self.config.system.messaging_port,
                enable_cloudflare=True,
                enable_vpn=True,
                on_message=self.on_gateway_message,
            ),
        }
        self.adapters["messaging"].on_connect = self.on_messaging_connect

    # ------------------------------------------------------------------
    # Lifecycle (delegated to core.lifecycle)
    # ------------------------------------------------------------------

    async def start(self):
        """Start the orchestrator — delegates to ``core.lifecycle.start``."""
        await _lifecycle.start(self)

    async def shutdown(self):
        """Gracefully shutdown — delegates to ``core.lifecycle.shutdown``."""
        await _lifecycle.shutdown(self)

    async def restart_component(self, name: str):  # pragma: no cover
        """Restart a specific component — delegates to ``core.lifecycle``."""
        await _lifecycle.restart_component(self, name)

    # ------------------------------------------------------------------
    # Backward-compatible delegation to orchestrator_components
    # ------------------------------------------------------------------
    # These methods were extracted to BackgroundTasks / HealthMonitor
    # but many tests still call them on the orchestrator directly.

    async def heartbeat_loop(self):
        """Delegate to ``self.health_monitor.start_monitoring()``."""
        await self.health_monitor.start_monitoring()

    async def proactive_loop(self):
        """Delegate to ``self.background_tasks.proactive_loop()``."""
        await self.background_tasks.proactive_loop()

    async def backup_loop(self):
        """Delegate to ``self.background_tasks.backup_loop()``."""
        await self.background_tasks.backup_loop()

    async def pruning_loop(self):
        """Delegate to ``self.background_tasks.pruning_loop()``."""
        await self.background_tasks.pruning_loop()

    async def sync_loop(self):
        """Delegate to ``self.background_tasks.sync_loop()``."""
        await self.background_tasks.sync_loop()

    async def get_system_health(self):
        """Delegate to ``self.health_monitor.get_system_health()``."""
        return await self.health_monitor.get_system_health()

    # ------------------------------------------------------------------
    # WebSocket handling (delegated to core.websocket_handler)
    # ------------------------------------------------------------------

    async def handle_client(self, websocket: WebSocket):
        """Handle a WebSocket client — delegates to ``core.websocket_handler``."""
        await _ws_handler.handle_client(self, websocket)

    # ------------------------------------------------------------------
    # Messaging callbacks
    # ------------------------------------------------------------------

    async def on_messaging_connect(self, client_id: Optional[str], platform: str):
        """Handle new messaging platform connections."""
        print(f"Greeting new connection: {platform} ({client_id or 'all'})")
        greeting = Message(content=GREETING_TEXT, sender="MegaBot")
        await self.send_platform_message(greeting, platform=platform, target_client=client_id)

    async def _handle_admin_command(
        self,
        text: str,
        sender_id: str,
        chat_id: Optional[str] = None,
        platform: str = "native",
    ) -> bool:
        """Delegate to AdminHandler (kept for backward compatibility)."""
        return await self.admin_handler.handle_command(text, sender_id, chat_id, platform)

    async def on_gateway_message(self, data: Dict):
        """Process messages received through the unified gateway."""
        await self.message_handler.process_gateway_message(data)

    # ------------------------------------------------------------------
    # Business logic methods
    # ------------------------------------------------------------------

    async def run_autonomous_gateway_build(self, message: Message, original_data: Dict):
        """Delegate to ``core.build_session.run_autonomous_gateway_build``."""
        await _build_session.run_autonomous_gateway_build(self, message, original_data)

    def _to_platform_message(self, message: Message, chat_id: Optional[str] = None) -> Any:
        """Delegate to MessageRouter to convert to PlatformMessage."""
        return self.message_router._to_platform_message(message, chat_id)

    async def send_platform_message(
        self,
        message: Message,
        chat_id: Optional[str] = None,
        platform: str = "native",
        target_client: Optional[str] = None,
    ):  # pragma: no cover
        """Delegate to MessageRouter for sending platform messages."""
        return await self.message_router.send_platform_message(
            message, chat_id=chat_id, platform=platform, target_client=target_client
        )

    async def _verify_redaction(self, image_data: str) -> bool:
        """Use a separate vision pass to verify that redaction was successful."""
        try:
            analysis_raw = await self.computer_driver.execute(
                "analyze_image",
                text=image_data,
            )
            analysis = json.loads(analysis_raw)
            remaining_sensitive = analysis.get("sensitive_regions", [])

            if remaining_sensitive:
                print(f"Redaction-Verification: FAILED. Found {len(remaining_sensitive)} remaining areas.")
                return False

            print("Redaction-Verification: PASSED.")
            return True
        except Exception as e:  # pragma: no cover
            print(f"Redaction-Verification: Error during check: {e}")
            return False

    async def _start_approval_escalation(self, action: Dict):
        """Delegate to ``core.approval_workflows.start_approval_escalation``."""
        await _approval_workflows.start_approval_escalation(self, action)

    async def _check_identity_claims(self, content: str, platform: str, platform_id: str, chat_id: str):
        """Delegate to ``core.approval_workflows.check_identity_claims``."""
        await _approval_workflows.check_identity_claims(self, content, platform, platform_id, chat_id)

    async def _get_relevant_lessons(self, prompt: str) -> str:
        """Delegate to ``core.build_session.get_relevant_lessons``."""
        return await _build_session.get_relevant_lessons(self, prompt)

    async def run_autonomous_build(self, message: Message, websocket: WebSocket):  # pragma: no cover
        """Delegate to ``core.build_session.run_autonomous_build``."""
        await _build_session.run_autonomous_build(self, message, websocket)

    async def _spawn_sub_agent(self, tool_input: Dict) -> str:
        """Delegate sub-agent spawning to AgentCoordinator (keeps API stable)."""
        return await self.agent_coordinator._spawn_sub_agent(tool_input)

    async def _execute_tool_for_sub_agent(self, agent_name: str, tool_call: Dict) -> str:
        """Delegate sub-agent tool execution to AgentCoordinator (keeps API stable)."""
        return await self.agent_coordinator._execute_tool_for_sub_agent(agent_name, tool_call)

    async def _handle_computer_tool(
        self,
        tool_input: Dict,
        websocket: WebSocket,
        action_id: str,
        callback: Optional[Any] = None,
    ):
        """Delegate to ``core.approval_workflows.handle_computer_tool``."""
        await _approval_workflows.handle_computer_tool(self, tool_input, websocket, action_id, callback)

    async def _llm_dispatch(self, prompt: str, context: Any, tools: Optional[List[Dict[str, Any]]] = None) -> Any:
        """Unified tool selection logic using configured LLM provider."""
        return await self.llm.generate(prompt, context, tools=tools)

    def _check_policy(self, data: Dict) -> str:
        """Delegate to ``core.openclaw_handler.check_policy``."""
        return _openclaw_handler.check_policy(self, data)

    async def on_openclaw_event(self, data):
        """Delegate to ``core.openclaw_handler.on_openclaw_event``."""
        await _openclaw_handler.on_openclaw_event(self, data)

    def _sanitize_output(self, text: str) -> str:
        """Strip ANSI escape sequences and other dangerous terminal characters."""
        if not text:
            return ""
        ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
        sanitized = ansi_escape.sub("", text)
        sanitized = "".join(ch for ch in sanitized if ch >= " " or ch in "\n\r\t")
        return sanitized

    async def _safe_ws_send(self, ws, payload: dict) -> bool:
        """Send JSON to a WebSocket, returning False if the connection is stale."""
        if ws is None:
            return False
        try:
            close_code = getattr(ws, "close_code", None)
            if isinstance(close_code, int):
                return False
            closed = getattr(ws, "closed", None)
            if closed is True:
                return False
            await ws.send_json(payload)
            return True
        except Exception:
            return False

    async def _process_approval(self, action_id: str, approved: bool):
        """Delegate approval processing to admin_handler (SEC-FIX-002)."""
        await self.admin_handler._process_approval(action_id, approved)

        safe_queue = _sanitize_queue(self.admin_handler.approval_queue)
        for client in list(self.clients):
            try:
                await client.send_json(
                    {
                        "type": "approval_queue_updated",
                        "queue": safe_queue,
                    }
                )
            except Exception as e:
                print(f"Failed to notify client of queue update: {e}")
                self.clients.discard(client)


# ======================================================================
# Module-level orchestrator instance
# ======================================================================
# The canonical location for the running orchestrator instance.
# Tests set this directly (``orch_module.orchestrator = mock``),
# route handlers in ``core.app`` read it via ``_get_orchestrator()``.
orchestrator: Optional["MegaBotOrchestrator"] = None


# ======================================================================
# Backward-compatible re-exports
# ======================================================================
# Many modules do ``from core.orchestrator import app, health, ...``.
# The actual objects now live in ``core.app`` but we re-export them here
# so existing import sites continue to work unchanged.

from core.app import (  # noqa: E402, F401
    app,
    lifespan,
    ivr_callback,
    root,
    health,
    websocket_endpoint,
    _validate_twilio_signature,
    config,
)


if __name__ == "__main__":  # pragma: no cover
    import uvicorn  # type: ignore

    uvicorn.run(app, host=config.system.bind_address, port=config.system.port)
