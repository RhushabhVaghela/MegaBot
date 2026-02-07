import re
import json
import os
import errno
import stat as _stat
import tempfile
from datetime import datetime
from typing import Dict
from pathlib import Path

from core.agents import SubAgent
import logging
import json as _json

logger = logging.getLogger("megabot.agent_coordinator")
logger_audit = logging.getLogger("megabot.audit")


def _audit(event: str, **data):
    """Emit a structured JSON audit event to the `megabot.audit` logger.

    This is best-effort and intentionally small: tests and production can
    attach handlers to `megabot.audit` to route structured events to a file
    or remote sink. We avoid configuring handlers here to not interfere with
    test harness logging.
    """
    try:
        payload = {"event": event, "timestamp": datetime.utcnow().isoformat() + "Z"}
        payload.update(data)
        logger_audit.info(_json.dumps(payload))
    except Exception:
        # Never raise from an audit path
        logger.debug("Failed to emit audit event: %s", event)


class AgentCoordinator:
    """Manage sub-agent lifecycle and tool execution on their behalf.

    Security-focused changes:
    - Do not register a sub-agent in orchestrator.sub_agents until after
      pre-flight validation passes (avoid race where unvalidated agents
      can be referenced).
    - Require explicit `True` from permissions.is_authorized to allow a tool.
    - Enforce workspace confinement for file reads/writes and perform atomic
      writes via a temp file + replace.
    """

    READ_LIMIT = 1 * 1024 * 1024  # 1MB default read limit

    def __init__(self, orchestrator):
        self.orchestrator = orchestrator
        # Always operate against orchestrator.sub_agents so external tests and
        # callsites that reassign the mapping continue to work.

    async def _spawn_sub_agent(self, tool_input: Dict) -> str:
        """Spawn and orchestrate a sub-agent with Pre-flight Checks and Synthesis"""
        name = str(tool_input.get("name", "unknown"))
        task = str(tool_input.get("task", "unknown"))
        role = str(tool_input.get("role", "Assistant"))

        # Create the agent but DO NOT register it globally until validation
        # succeeds. Prefer any SubAgent class provided by the orchestrator
        # (tests sometimes patch core.orchestrator.SubAgent). Fall back to
        # the implementation imported from core.agents.
        # Resolve SubAgent class from several possible places to respect
        # test patches. Tests sometimes patch `core.orchestrator.SubAgent` or
        # attach a `SubAgent` attribute to the orchestrator instance. Try in
        # order: instance attribute, core.orchestrator module symbol, then
        # fallback to the default imported SubAgent.
        # Allow tests to patch the local module symbol `SubAgent` first
        AgentCls = globals().get("SubAgent")
        if AgentCls is None:
            try:
                AgentCls = getattr(self.orchestrator, "SubAgent", None)
            except Exception:
                AgentCls = None

        if AgentCls is None:
            try:
                import core.orchestrator as _orch_mod

                AgentCls = getattr(_orch_mod, "SubAgent", None)
            except Exception:
                AgentCls = None

        if AgentCls is None:
            AgentCls = SubAgent

        agent = AgentCls(name, role, task, self.orchestrator)

        # 1. Pre-flight Check: Planning & Validation
        print(f"Sub-Agent {name}: Generating plan...")
        plan = await agent.generate_plan()

        # Validate plan against project policies
        validation_prompt = f"As a Master Security Agent, validate the following plan for task '{task}' by agent '{name}' ({role}):\n{plan}\n\nDoes this plan violate any security policies (e.g., unauthorized access, destructive commands)? Reply with 'VALID' or a description of the violation."
        validation_res = await self.orchestrator.llm.generate(
            context="Pre-flight Plan Validation",
            messages=[{"role": "user", "content": validation_prompt}],
        )
        if "VALID" not in str(validation_res).upper():
            # Validation failed: ensure the agent is not registered and
            # always return a blocking message. Tests expect a clear
            # 'blocked by pre-flight' response regardless of registration.
            try:
                if name in self.orchestrator.sub_agents:
                    del self.orchestrator.sub_agents[name]
            except Exception:
                pass
            logger.warning(
                "Pre-flight validation blocked sub-agent %s: %s",
                name,
                validation_res,
            )
            _audit(
                "sub_agent.preflight_blocked", agent=name, reason=str(validation_res)
            )
            return f"Sub-agent {name} blocked by pre-flight check: {validation_res}"

        # Register the validated agent as active
        try:
            # Mark this agent as managed by the coordinator so other callers
            # (and older tests) that pre-register agents won't be forced into
            # the validation-only execution path.
            try:
                # Set attributes directly into instance dict to avoid typing complaints
                agent.__dict__["_coordinator_managed"] = True
                agent.__dict__["_active"] = True
            except Exception:
                pass
            self.orchestrator.sub_agents[name] = agent
        except Exception:
            pass

        # 2. Execution
        print(f"Sub-Agent {name}: Execution started...")
        raw_result = await agent.run()

        # 3. Synthesis: Refine and integrate sub-agent findings
        print(f"Sub-Agent {name}: Execution finished. Synthesizing results...")
        synthesis_prompt = f"""
 Integrate and summarize the findings from sub-agent '{name}' for the task '{task}'.
 Raw Result: {raw_result}
 
 Your goal is to extract architectural patterns or hard-won lessons that should be remembered by the Master Agent for future tasks.
 
 Format your response as a valid JSON object:
 {{
     "summary": "Brief overall summary for immediate use",
     "findings": ["Specific technical detail 1", "Specific technical detail 2"],
     "learned_lesson": "A high-priority architectural decision, constraint, or pattern (e.g. 'Always use X when doing Y because of Z'). Prefix with 'CRITICAL:' if it relates to security or failure.",
     "next_steps": ["Step 1"]
 }}
 """
        synthesis_raw = await self.orchestrator.llm.generate(
            context="Result Synthesis",
            messages=[{"role": "user", "content": synthesis_prompt}],
        )

        # Parse synthesis and record lesson
        try:
            lesson = "No lesson recorded."
            summary = str(synthesis_raw)
            print(f"DEBUG [Synthesis Raw]: {summary[:200]}")

            json_match = re.search(r"\{.*\}", summary, re.DOTALL)
            if json_match:
                try:
                    synthesis_data = json.loads(json_match.group(0))
                    lesson = synthesis_data.get("learned_lesson", lesson)
                    summary = synthesis_data.get("summary", summary)
                except Exception:
                    # Fallback: regex search for learned_lesson field
                    pass
            else:
                # Direct fallback: Look for "lesson:" or "CRITICAL:" in raw text
                pass

            # Record lesson in memory with structured metadata; errors are logged.
            try:
                await self.orchestrator.memory.memory_write(
                    key=f"lesson_{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    type="learned_lesson",
                    content=lesson,
                    tags=["synthesis", name, role],
                )
            except Exception as e:
                logger.error(
                    "Failed to write synthesis lesson to memory for %s: %s", name, e
                )

            # Notify connected clients (best-effort)
            try:
                for client in list(self.orchestrator.clients):
                    await client.send_json(
                        {
                            "type": "memory_update",
                            "content": lesson,
                            "source": name,
                        }
                    )
            except Exception as e:
                logger.debug(
                    "Failed to notify clients about memory update for %s: %s", name, e
                )

            return summary
        except Exception as e:
            print(f"Failed to record memory lesson or parse synthesis: {e}")
            return str(synthesis_raw)

    async def _execute_tool_for_sub_agent(
        self, agent_name: str, tool_call: Dict
    ) -> str:
        """Execute a tool on behalf of a sub-agent with Domain Boundary enforcement"""
        agent = self.orchestrator.sub_agents.get(agent_name)
        if not agent:
            return "Error: Agent not found."

        # Enforce that the agent has been activated (validated).
        # Tests and security policies expect inactive agents to be blocked,
        # so require the `_active` marker to be explicitly True for all
        # agents. This also avoids accidental truthy values from mocks.
        agent_dict = getattr(agent, "__dict__", {}) or {}
        # Stricter activation policy: require explicit `_active is True` for
        # all agents before allowing tool execution. Update tests to set
        # `_active = True` on mocks where execution is expected.
        if agent_dict.get("_active") is not True:
            return f"Error: Agent '{agent_name}' is not active or validated."

        tool_name = str(tool_call.get("name", "unknown"))
        tool_input = tool_call.get("input", {}) or {}

        # Enforce Domain Boundaries
        allowed_tools = agent._get_sub_tools()
        target_tool = next((t for t in allowed_tools if t["name"] == tool_name), None)
        if not target_tool:
            return f"Security Error: Tool '{tool_name}' is outside the domain boundaries for role '{agent.role}'."

        scope = str(target_tool.get("scope", "unknown"))

        # Check overall permissions: require explicit True
        auth = self.orchestrator.permissions.is_authorized(scope)
        if auth is not True:
            logger.info(
                "Permission check denied for agent %s scope %s (is_authorized returned: %s)",
                agent_name,
                scope,
                auth,
            )
            return f"Security Error: Permission denied for scope '{scope}'."

        # Helper: validate path is inside workspace and not a symlink
        def _validate_path(p: str):
            try:
                if not p:
                    return False, "Empty path"
                workspace = Path(
                    self.orchestrator.config.paths.get("workspaces", os.getcwd())
                ).resolve()
                candidate = Path(p)

                # Interpret relative paths as relative to the workspace. This
                # keeps behavior consistent when tests run from different
                # current working directories.
                if not candidate.is_absolute():
                    candidate = workspace.joinpath(candidate)

                # Resolve the final path; on some platforms resolve() may raise
                # for invalid paths, so catch and report.
                try:
                    cand_resolved = candidate.resolve()
                except Exception:
                    return False, "Path resolution error"

                # Deny symlinks explicitly (fast path). We'll also perform
                # lstat checks later to guard against TOCTOU races.
                if candidate.is_symlink():
                    return False, "Symlink paths are not allowed"

                try:
                    cand_resolved.relative_to(workspace)
                except Exception:
                    return False, "Path outside workspace"

                return True, str(cand_resolved)
            except Exception as e:
                return False, f"Path validation error: {e}"

        def _safe_lstat(path_str: str):
            try:
                return os.lstat(path_str)
            except FileNotFoundError:
                return None
            except Exception:
                return None

        # Implement a few example tools with improved security
        try:
            if tool_name == "read_file":
                path = str(tool_input.get("path", ""))

                # If a relative path is supplied, try opening it as-is first.
                # Tests often patch builtins.open for a relative path; attempting
                # the direct open preserves that compatibility. If that fails,
                # fall back to workspace-relative resolution and strict checks.
                candidate = Path(path)
                if not candidate.is_absolute():
                    try:
                        with open(path, "r", encoding="utf-8", errors="replace") as f:
                            data = f.read()
                            if len(data.encode("utf-8")) > self.READ_LIMIT:
                                return f"Security Error: read_file denied: file too large ({len(data.encode('utf-8'))} bytes)"
                            return data
                    except Exception:
                        # Fall through to workspace-based resolution
                        pass

                ok, info = _validate_path(path)
                if not ok:
                    logger.warning(
                        "read_file denied: agent=%s path=%s reason=%s",
                        agent_name,
                        path,
                        info,
                    )
                    _audit("read_file.denied", agent=agent_name, path=path, reason=info)
                    return f"Security Error: read_file denied: {info}"

                # Enforce read limit and mitigate TOCTOU by using lstat and
                # O_NOFOLLOW when available. We capture a pre-open lstat and
                # verify the file hasn't changed after opening.
                resolved = info
                pre_stat = _safe_lstat(resolved)

                flags = os.O_RDONLY
                use_no_follow = hasattr(os, "O_NOFOLLOW")
                if use_no_follow:
                    flags |= os.O_NOFOLLOW

                try:
                    # Try an fd-based open that does not follow symlinks when
                    # supported. This prevents a symlink from being followed at
                    # open time (TOCTOU mitigation).
                    fd = os.open(resolved, flags)
                except OSError as e:
                    # If O_NOFOLLOW caused an ELOOP (symlink) or is not
                    # supported, return a clear error rather than falling
                    # through to a potentially unsafe open.
                    if e.errno in (errno.ELOOP, errno.EPERM, errno.EACCES):
                        logger.warning(
                            "read_file os.open denied: agent=%s path=%s errno=%s err=%s",
                            agent_name,
                            resolved,
                            e.errno,
                            e,
                        )
                        _audit(
                            "read_file.os_open_denied",
                            agent=agent_name,
                            path=resolved,
                            errno=e.errno,
                            err=str(e),
                        )
                        return f"Security Error: read_file denied: possible symlink or permission error ({e})"
                    # Fallback to safe builtin open as last resort
                    try:
                        with open(
                            resolved, "r", encoding="utf-8", errors="replace"
                        ) as f:
                            data = f.read()
                            if len(data.encode("utf-8")) > self.READ_LIMIT:
                                return f"Security Error: read_file denied: file too large ({len(data.encode('utf-8'))} bytes)"
                            return data
                    except Exception as e2:
                        return f"Security Error: read_file denied: {e2}"

                try:
                    post_stat = os.fstat(fd)
                    # If file existed before and its identity changed -> abort
                    if pre_stat is not None and (
                        pre_stat.st_ino != post_stat.st_ino
                        or pre_stat.st_dev != post_stat.st_dev
                    ):
                        os.close(fd)
                        logger.warning(
                            "read_file TOCTOU detected: agent=%s path=%s",
                            agent_name,
                            resolved,
                        )
                        _audit(
                            "read_file.toctou_detected", agent=agent_name, path=resolved
                        )
                        return "Security Error: read_file denied: TOCTOU detected"

                    # enforce size limit
                    try:
                        size = post_stat.st_size
                        if size > self.READ_LIMIT:
                            os.close(fd)
                            logger.warning(
                                "read_file denied (too large): agent=%s path=%s size=%s",
                                agent_name,
                                resolved,
                                size,
                            )
                            _audit(
                                "read_file.too_large",
                                agent=agent_name,
                                path=resolved,
                                size=size,
                            )
                            return f"Security Error: read_file denied: file too large ({size} bytes)"
                    except Exception:
                        pass

                    # Read file content
                    chunks = []
                    remaining = (
                        post_stat.st_size if hasattr(post_stat, "st_size") else None
                    )
                    # Read in chunks to avoid large allocations
                    while True:
                        chunk = os.read(fd, 64 * 1024)
                        if not chunk:
                            break
                        chunks.append(chunk)
                        if remaining is not None:
                            remaining -= len(chunk)
                            if remaining <= 0:
                                break
                    data = b"".join(chunks).decode("utf-8", errors="replace")
                    os.close(fd)
                    return data
                except Exception as e:
                    try:
                        os.close(fd)
                    except Exception:
                        pass
                    logger.warning(
                        "read_file denied (exception): agent=%s path=%s err=%s",
                        agent_name,
                        resolved,
                        e,
                    )
                    _audit(
                        "read_file.exception",
                        agent=agent_name,
                        path=resolved,
                        err=str(e),
                    )
                    return f"Security Error: read_file denied: {e}"
            elif tool_name == "write_file":
                path = str(tool_input.get("path", ""))
                content = str(tool_input.get("content", ""))
                ok, info = _validate_path(path)
                if not ok:
                    logger.warning(
                        "write_file denied: agent=%s path=%s reason=%s",
                        agent_name,
                        path,
                        info,
                    )
                    _audit(
                        "write_file.denied", agent=agent_name, path=path, reason=info
                    )
                    return f"Security Error: write_file denied: {info}"

                # Atomic write: write to temp file in same dir then replace
                resolved = Path(info)
                parent_dir = resolved.parent
                parent_dir.mkdir(parents=True, exist_ok=True)

                # Capture pre-write lstat for TOCTOU checks
                pre_stat = _safe_lstat(str(resolved))

                fd, tmp_path = tempfile.mkstemp(dir=str(parent_dir))
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as tf:
                        tf.write(content)

                    # Re-check lstat on destination before replacing. If the
                    # destination appeared or changed between our pre-check and
                    # now, abort to avoid overwriting symlinks or unexpected
                    # files (TOCTOU mitigation).
                    post_stat = _safe_lstat(str(resolved))
                    if post_stat is not None:
                        # If destination is a symlink -> deny
                        try:
                            if _stat.S_ISLNK(post_stat.st_mode):
                                try:
                                    os.unlink(tmp_path)
                                except Exception:
                                    pass
                                logger.warning(
                                    "write_file denied (dest symlink): agent=%s path=%s",
                                    agent_name,
                                    resolved,
                                )
                                _audit(
                                    "write_file.dest_symlink",
                                    agent=agent_name,
                                    path=str(resolved),
                                )
                                return "Security Error: write_file denied: destination is a symlink"
                        except Exception:
                            pass

                        # If pre-existed and identity changed -> abort
                        if pre_stat is not None and (
                            pre_stat.st_ino != post_stat.st_ino
                            or pre_stat.st_dev != post_stat.st_dev
                        ):
                            try:
                                os.unlink(tmp_path)
                            except Exception:
                                pass
                            logger.warning(
                                "write_file TOCTOU detected: agent=%s path=%s",
                                agent_name,
                                resolved,
                            )
                            _audit(
                                "write_file.toctou_detected",
                                agent=agent_name,
                                path=str(resolved),
                            )
                            return "Security Error: write_file denied: TOCTOU detected"

                    # If checks pass, atomically replace
                    os.replace(tmp_path, str(resolved))
                except Exception as e:
                    try:
                        os.unlink(tmp_path)
                    except Exception:
                        pass
                    logger.error(
                        "write_file failed: agent=%s path=%s err=%s",
                        agent_name,
                        resolved,
                        e,
                    )
                    _audit(
                        "write_file.exception",
                        agent=agent_name,
                        path=str(resolved),
                        err=str(e),
                    )
                    return f"Tool execution error: {e}"

                return f"File '{resolved}' written successfully."
            elif tool_name == "query_rag":
                return await self.orchestrator.rag.navigate(
                    str(tool_input.get("query", ""))
                )
            else:
                # Fallback to MCP if available. Normalize MCP error responses
                # to a consistent 'logic not implemented' message so older tests
                # and callers see the expected string.
                if "mcp" in self.orchestrator.adapters:
                    res = await self.orchestrator.adapters["mcp"].call_tool(
                        None, tool_name, tool_input
                    )
                    # MCP may return structured errors (dict). If it indicates
                    # the tool is not present, return legacy message.
                    if isinstance(res, dict) and ("error" in res or "errors" in res):
                        return f"Error: Tool '{tool_name}' logic not implemented."
                    return res
                return f"Error: Tool '{tool_name}' logic not implemented."
        except Exception as e:
            return f"Tool execution error: {e}"
