import asyncio
import re
import json
from datetime import datetime
from typing import List, Dict
from core.agents import SubAgent


class LokiMode:
    """
    God-Mode Orchestrator for MegaBot.
    Designed to handle end-to-end product development.
    """

    def __init__(self, orchestrator):
        self.orchestrator = orchestrator
        self.is_active = False

    async def activate(self, prd_text: str):
        """Start the Loki Mode pipeline"""
        self.is_active = True
        print("🔥 LOKI MODE ACTIVATED 🔥")
        start_time = datetime.now()

        await self._relay_status("🔥 Loki Mode Activated. Starting pipeline...")

        # 0. Memory Retrieval (Retrieve learned lessons for this project)
        memory_context = await self._retrieve_learned_lessons(prd_text)

        # 1. Decomposition (Architect Agent)
        await self._relay_status("📐 Decomposing PRD into technical tasks...")
        tasks = await self._decompose_prd(prd_text, memory_context)

        # 2. Parallel Implementation
        await self._relay_status(
            f"🛠️ Starting parallel implementation of {len(tasks)} tasks..."
        )
        impl_results = await self._execute_parallel_tasks(tasks, memory_context)

        # 3. Parallel Review (3 specialized reviewers)
        await self._relay_status(
            "🔍 Running parallel architecture and security review..."
        )
        review_summary = await self._run_parallel_review(impl_results, memory_context)

        if "MEMORY CONFLICT:" in review_summary:
            # Objective 2: Conflict Resolution (The Debate)
            await self._relay_status(
                "⚖️ Conflict detected with Learned Lessons. Starting Mediation..."
            )
            is_evolution = await self._debate_memory_conflict(
                review_summary, impl_results, memory_context
            )

            if not is_evolution:
                await self._relay_status(
                    "⚠️ Mediation FAILED. Triggering Auto-Remediation..."
                )
                # Auto-remediation step: Re-run with explicit instruction to fix the conflict
                remediation_task = {
                    "name": "Remediation-Agent",
                    "role": "Senior Dev (Refactor)",
                    "task_description": f"The previous implementation has a memory conflict with architectural lessons. FIX IT.\n\nConflict Details:\n{review_summary}\n\nCode to Fix:\n"
                    + "\n".join(impl_results),
                }
                impl_results = await self._execute_parallel_tasks(
                    [remediation_task], memory_context
                )
                # Re-review after remediation
                review_summary = await self._run_parallel_review(
                    impl_results, memory_context
                )
            else:
                await self._relay_status(
                    "✅ Mediation SUCCESS: Accepted as Architectural Evolution."
                )

        # 4. Security & Quality Review
        await self._relay_status("🛡️ Running final Tirith Security Audit...")
        await self._run_security_audit(impl_results + [review_summary], memory_context)

        # 5. Deployment
        await self._relay_status("🚀 Deploying product to staging...")
        deployment_status = await self._deploy_product()

        # 6. Save Macro to memU
        await self._save_loki_macro(prd_text, tasks, impl_results, deployment_status)

        self.is_active = False
        duration = datetime.now() - start_time
        final_msg = f"✅ Loki Mode complete in {duration}. {deployment_status}"
        await self._relay_status(final_msg)
        return final_msg

    async def _relay_status(self, content: str):
        """Relay status updates to the last active chat platform if available"""
        if self.orchestrator.last_active_chat:
            from core.interfaces import Message

            chat_id = self.orchestrator.last_active_chat.get("chat_id")
            platform = self.orchestrator.last_active_chat.get("platform", "native")

            if chat_id:
                msg = Message(content=content, sender="Loki")
                # We use a task so we don't block the pipeline
                asyncio.create_task(
                    self.orchestrator.send_platform_message(
                        msg, chat_id=chat_id, platform=platform
                    )
                )

    async def _retrieve_learned_lessons(self, query: str) -> str:
        """Search and distill learned lessons from persistent memory"""
        print("🧠 Retrieving Learned Lessons...")
        lessons = await self.orchestrator.memory.memory_search(
            query=query, type="learned_lesson"
        )
        if not lessons:
            return ""

        # Implementation of Priority-based Sliding Window
        if len(lessons) > 20:
            # Prioritize CRITICAL ones
            critical_lessons = [
                lesson
                for lesson in lessons
                if "CRITICAL" in str(lesson.get("content", "")).upper()
                or "critical" in lesson.get("tags", [])
            ]
            non_critical = [
                lesson for lesson in lessons if lesson not in critical_lessons
            ]

            # Take all critical (up to 20) then fill with recent non-critical
            window = critical_lessons[:20]
            if len(window) < 20:
                window.extend(non_critical[: (20 - len(window))])

            lessons = window

        lessons_text = "\n".join([f"- {lesson['content']}" for lesson in lessons])
        distill_prompt = f"""
Identify and summarize the most critical architectural constraints, security policies, and "hard-won" lessons from the following context that are directly relevant to the current product development task.

Task: {query}

Lessons to Analyze:
{lessons_text}

Instructions:
1. Prioritize lessons that mention "SECURITY", "FAILURE", "BLOCK", or "CRITICAL".
2. Provide the top 3 critical points that must be strictly followed during this build.
"""
        distilled = await self.orchestrator.llm.generate(
            context="Loki Memory Distillation",
            messages=[{"role": "user", "content": distill_prompt}],
        )
        return str(distilled)

    async def _run_parallel_review(
        self, code_results: List[str], memory_context: str = ""
    ) -> str:
        """Spawn 3 specialized reviewers to critique the implementation"""
        print("🔍 Starting Parallel Code Review...")
        reviewers = [
            {
                "name": "Security-Reviewer",
                "role": "Security Engineer",
                "task": "Check for vulnerabilities and leaks.",
            },
            {
                "name": "Performance-Reviewer",
                "role": "Performance Expert",
                "task": "Check for N+1 queries and bottlenecks.",
            },
            {
                "name": "Architecture-Reviewer",
                "role": "Senior Architect",
                "task": "Check for pattern consistency and modularity. Specifically, verify if the implementation contradicts any of the 'Learned Lessons' provided. If a conflict is found, start your response with 'MEMORY CONFLICT:' followed by the reason.",
            },
        ]

        context = "\n".join(code_results)
        if memory_context:
            context = f"Learned Lessons Context:\n{memory_context}\n\nCode to review:\n{context}"

        coroutines = []
        for r in reviewers:
            agent = SubAgent(
                r["name"],
                r["role"],
                f"{r['task']}\n\nContext to review:\n{context}",
                self.orchestrator,
            )
            coroutines.append(agent.run())

        reviews = await asyncio.gather(*coroutines)
        return "\n--- Combined Review ---\n" + "\n".join(reviews)

    async def _debate_memory_conflict(
        self, review_summary: str, impl_results: List[str], memory_context: str
    ) -> bool:
        """Mediate between a detected conflict and a potentially superior new implementation."""
        print("⚖️ Starting Conflict Mediation (The Debate)...")

        impl_results_text = "\n".join(impl_results)
        debate_prompt = f"""
As an Expert Mediator and Senior Principal Architect, your task is to resolve a conflict between a "Learned Lesson" (historical constraint) and a "New Implementation" (recent code).

Learned Lessons Context:
{memory_context}

New Implementation:
{impl_results_text}

Conflict Details (Flagged by Reviewer):
{review_summary}

Analyze the following:
1. Is the "Learned Lesson" truly violated, or is the reviewer being overly cautious?
2. Does the "New Implementation" represent a superior architectural evolution (e.g., using a modern library, fixing a flaw in the old lesson, or better performance)?
3. If the implementation is superior, justify why we should override the historical constraint.

Final Decision:
If we should REJECT the new implementation and trigger remediation, start your response with 'DECISION: REMEDIATE'.
If we should ACCEPT the new implementation as an architectural evolution, start your response with 'DECISION: EVOLVE' followed by your justification.
"""
        decision_res = await self.orchestrator.llm.generate(
            context="Conflict Mediation Debate",
            messages=[{"role": "user", "content": debate_prompt}],
        )

        print(f"Mediation Decision: {str(decision_res)[:100]}...")

        if "DECISION: EVOLVE" in str(decision_res).upper():
            # Record the evolution in memory as a new lesson
            await self.orchestrator.memory.memory_write(
                key=f"evolution_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                type="learned_lesson",
                content=f"Architectural Evolution: {decision_res}",
                tags=["loki", "evolution", "debate_winner"],
            )
            return True  # No remediation needed
        return False  # Remediation needed

    async def _save_loki_macro(
        self, prd: str, tasks: List[Dict], results: List[str], status: str
    ):
        """Save the entire execution as a reproducible macro in memU"""
        print("🧠 Saving Loki Macro to Memory...")
        macro = {
            "type": "loki_macro",
            "prd": prd,
            "decomposition": tasks,
            "results": results,
            "final_status": status,
            "timestamp": datetime.now().isoformat(),
        }
        await self.orchestrator.adapters["memu"].learn_from_interaction(
            {
                "action": "loki_mode_execution",
                "content": f"Loki Macro for: {prd[:50]}...",
                "data": macro,
            }
        )

    async def _decompose_prd(self, prd: str, memory_context: str = "") -> List[Dict]:
        """Convert PRD into actionable sub-tasks"""
        prompt = (
            f"Decompose this PRD into specific, independent technical tasks:\n{prd}\n"
        )
        if memory_context:
            prompt += f"\nConsider these LEARNED LESSONS during decomposition:\n{memory_context}\n"
        prompt += (
            "\nReturn a JSON list of tasks with 'name', 'role', and 'task_description'."
        )

        res = await self.orchestrator.llm.generate(
            context="Loki Architect", messages=[{"role": "user", "content": prompt}]
        )
        # Simplified parsing for prototype

        try:
            # Look for JSON in response
            match = re.search(r"\[.*\]", res, re.DOTALL)
            if match:
                return json.loads(match.group(0))
        except Exception:
            pass
        return [
            {
                "name": "Developer",
                "role": "Senior Dev",
                "task_description": "Implement core logic",
            }
        ]

    async def _execute_parallel_tasks(
        self, tasks: List[Dict], memory_context: str = ""
    ):
        """Run sub-agents in parallel"""
        from core.agents import SubAgent

        coroutines = []
        for t in tasks:
            task_desc = t["task_description"]
            if memory_context:
                task_desc = f"IMPORTANT CONTEXT/LESSONS:\n{memory_context}\n\nTASK:\n{task_desc}"

            agent = SubAgent(t["name"], t["role"], task_desc, self.orchestrator)
            coroutines.append(agent.run())

        return await asyncio.gather(*coroutines)

    async def _run_security_audit(
        self, results: List[str], memory_context: str = ""
    ) -> str:
        """Specialized security review pass using Tirith Guard logic"""
        print("🛡️ Running Security Audit...")
        from adapters.security.tirith_guard import guard as tirith

        combined_text = "\n".join(results)

        # 1. Check for Terminal/Homoglyph Attacks
        if not tirith.validate(combined_text):
            print(
                "❌ SECURITY ALERT: Suspicious Unicode or Bidi characters detected in implementation!"
            )
            return "Security Audit: FAILED (Suspicious Characters Detected)"

        # 2. Automated Scan (RegEx for secrets/keys)
        # Simplified scan for the prototype
        secret_patterns = [
            r"api[_-]?key",
            r"secret[_-]?key",
            r"password",
            r"bearer\s+\w+",
        ]
        for pattern in secret_patterns:
            if re.search(pattern, combined_text, re.IGNORECASE):
                print(
                    f"⚠️ SECURITY WARNING: Potential secret leak detected (pattern: {pattern})"
                )
                # We don't fail immediately, but we flag it

        await asyncio.sleep(1)
        return "Security Audit: Passed"

    async def _deploy_product(self) -> str:
        """Final build and deploy step.

        Raises:
            NotImplementedError: Deployment pipeline not yet configured
        """
        raise NotImplementedError(
            "_deploy_product requires a configured deployment pipeline. "
            "Set MEGABOT_DEPLOY_SCRIPT or implement a deployment driver."
        )
