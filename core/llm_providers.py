import os
import asyncio
import random
import logging
import aiohttp  # type: ignore
import json
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, List, Set
from core.instrumentation import track_telemetry

logger = logging.getLogger(__name__)

# HTTP status codes that are safe to retry
_RETRYABLE_STATUSES: Set[int] = {429, 500, 502, 503, 504}
_MAX_RETRIES = 3
_BASE_DELAY = 1.0  # seconds


class LLMProvider(ABC):
    """Abstract base class for all LLM providers."""

    def __init__(self) -> None:
        self._session: Optional[aiohttp.ClientSession] = None

    def _get_session(self) -> aiohttp.ClientSession:
        """Get or create a persistent aiohttp session (connection pooling)."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        """Close the persistent HTTP session. Call on shutdown."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def _request_with_retry(
        self,
        url: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        json_payload: Optional[Dict[str, Any]] = None,
        timeout: Optional[aiohttp.ClientTimeout] = None,
    ) -> aiohttp.ClientResponse:
        """Execute a POST request with exponential backoff retry on transient errors.

        Returns the aiohttp response object. Caller is responsible for
        checking status and reading the body.
        """
        session = self._get_session()
        last_exc: Optional[Exception] = None

        for attempt in range(_MAX_RETRIES + 1):
            try:
                resp = await session.post(
                    url,
                    headers=headers,
                    json=json_payload,
                    timeout=timeout or aiohttp.ClientTimeout(total=60),
                )
                # Don't retry on success or non-retryable errors
                if resp.status not in _RETRYABLE_STATUSES or attempt == _MAX_RETRIES:
                    return resp

                # Retryable status — read body to release connection, then retry
                await resp.read()
                retry_after = resp.headers.get("Retry-After")
                if retry_after:
                    try:
                        delay = float(retry_after)
                    except ValueError:
                        delay = _BASE_DELAY * (2**attempt)
                else:
                    delay = _BASE_DELAY * (2**attempt)
                delay += random.uniform(0, 0.5)  # jitter
                logger.warning(
                    "Retryable HTTP %d from %s (attempt %d/%d), retrying in %.1fs",
                    resp.status,
                    url,
                    attempt + 1,
                    _MAX_RETRIES,
                    delay,
                )
                await asyncio.sleep(delay)

            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                last_exc = exc
                if attempt == _MAX_RETRIES:
                    raise
                delay = _BASE_DELAY * (2**attempt) + random.uniform(0, 0.5)
                logger.warning(
                    "Request to %s failed (attempt %d/%d): %s, retrying in %.1fs",
                    url,
                    attempt + 1,
                    _MAX_RETRIES,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)

        # Should not reach here, but satisfy type checker
        raise last_exc or RuntimeError("Retry loop exited unexpectedly")  # pragma: no cover

    @abstractmethod
    @track_telemetry
    async def generate(
        self,
        prompt: Optional[str] = None,
        context: Optional[Any] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        messages: Optional[List[Dict[str, Any]]] = None,
    ) -> Any:
        pass  # pragma: no cover

    async def reason(
        self,
        prompt: str,
        context: Optional[Any] = None,
        search_tool: Optional[Any] = None,
    ) -> str:
        """
        Deep reasoning pattern: <think>-<search>-<answer>.
        Executes a multi-step loop to solve complex queries.
        """
        # 1. THINK
        think_msg = f"Task: {prompt}\n\nThink deeply about this task. Breakdown the problem and identify what you need to search for."
        thought = await self.generate(prompt=think_msg, context=context)
        print(f"DEBUG [SearchR1-Think]: {thought[:100]}...")

        # 2. SEARCH (if tool provided, otherwise internal reasoning)
        search_info = ""
        if search_tool:
            search_msg = f"Thought: {thought}\n\nGenerate search queries for the tools."
            queries = await self.generate(prompt=search_msg, context=context)
            search_info = await search_tool.search(queries)
            print(f"DEBUG [SearchR1-Search]: Found {len(search_info)} bytes of data.")
        else:
            # Internal 'knowledge retrieval' step
            search_msg = f"Thought: {thought}\n\nRecall relevant facts or simulate search results for this problem."
            search_info = await self.generate(prompt=search_msg, context=context)

        # 3. ANSWER
        final_msg = f"Task: {prompt}\n\nThought: {thought}\n\nContext/Search Data: {search_info}\n\nProvide the final comprehensive answer."
        return await self.generate(prompt=final_msg, context=context)


class OpenAICompatibleProvider(LLMProvider):
    """Base class for any provider that supports the OpenAI Chat Completions API format."""

    def __init__(self, model: str, api_key: Optional[str], base_url: str):
        super().__init__()
        self.model = model
        self.api_key = api_key
        self.base_url = base_url

    @track_telemetry
    async def generate(
        self,
        prompt: Optional[str] = None,
        context: Optional[Any] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        messages: Optional[List[Dict[str, Any]]] = None,
    ) -> Any:
        if not self.api_key:
            return f"{self.__class__.__name__} API key missing"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        final_messages = messages or []
        if prompt:
            final_messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": f"Context: {context}"}] + final_messages,
        }
        if tools:
            payload["tools"] = tools

        try:
            resp = await self._request_with_retry(
                self.base_url,
                headers=headers,
                json_payload=payload,
                timeout=aiohttp.ClientTimeout(total=60),
            )
            if resp.status == 200:
                res_data = await resp.json()
                message = res_data["choices"][0]["message"]
                if message.get("tool_calls"):
                    return message
                return message["content"]
            return f"{self.__class__.__name__} error: {resp.status} - {await resp.text()}"
        except Exception as e:
            return f"{self.__class__.__name__} connection failed: {e}"


class OpenAIProvider(OpenAICompatibleProvider):
    def __init__(self, model: str = "gpt-4-turbo", api_key: Optional[str] = None):
        super().__init__(
            model=model,
            api_key=api_key or os.environ.get("OPENAI_API_KEY"),
            base_url="https://api.openai.com/v1/chat/completions",
        )


class GroqProvider(OpenAICompatibleProvider):
    def __init__(self, model: str = "llama3-70b-8192", api_key: Optional[str] = None):
        super().__init__(
            model=model,
            api_key=api_key or os.environ.get("GROQ_API_KEY"),
            base_url="https://api.groq.com/openai/v1/chat/completions",
        )


class DeepSeekProvider(OpenAICompatibleProvider):
    def __init__(self, model: str = "deepseek-chat", api_key: Optional[str] = None):
        super().__init__(
            model=model,
            api_key=api_key or os.environ.get("DEEPSEEK_API_KEY"),
            base_url="https://api.deepseek.com/chat/completions",
        )


class XAIProvider(OpenAICompatibleProvider):
    def __init__(self, model: str = "grok-beta", api_key: Optional[str] = None):
        super().__init__(
            model=model,
            api_key=api_key or os.environ.get("XAI_API_KEY"),
            base_url="https://api.x.ai/v1/chat/completions",
        )


class PerplexityProvider(OpenAICompatibleProvider):
    def __init__(
        self,
        model: str = "llama-3-sonar-large-32k-online",
        api_key: Optional[str] = None,
    ):
        super().__init__(
            model=model,
            api_key=api_key or os.environ.get("PERPLEXITY_API_KEY"),
            base_url="https://api.perplexity.ai/chat/completions",
        )


class CerebrasProvider(OpenAICompatibleProvider):
    def __init__(self, model: str = "llama3.1-70b", api_key: Optional[str] = None):
        super().__init__(
            model=model,
            api_key=api_key or os.environ.get("CEREBRAS_API_KEY"),
            base_url="https://api.cerebras.ai/v1/chat/completions",
        )


class SambaNovaProvider(OpenAICompatibleProvider):
    def __init__(self, model: str = "llama3-70b", api_key: Optional[str] = None):
        super().__init__(
            model=model,
            api_key=api_key or os.environ.get("SAMBANOVA_API_KEY"),
            base_url="https://api.sambanova.ai/v1/chat/completions",
        )


class FireworksProvider(OpenAICompatibleProvider):
    def __init__(
        self,
        model: str = "accounts/fireworks/models/llama-v3p1-70b-instruct",
        api_key: Optional[str] = None,
    ):
        super().__init__(
            model=model,
            api_key=api_key or os.environ.get("FIREWORKS_API_KEY"),
            base_url="https://api.fireworks.ai/inference/v1/chat/completions",
        )


class DeepInfraProvider(OpenAICompatibleProvider):
    def __init__(
        self,
        model: str = "meta-llama/Meta-Llama-3-70B-Instruct",
        api_key: Optional[str] = None,
    ):
        super().__init__(
            model=model,
            api_key=api_key or os.environ.get("DEEPINFRA_API_KEY"),
            base_url="https://api.deepinfra.com/v1/openai/chat/completions",
        )


class LMStudioProvider(OpenAICompatibleProvider):
    def __init__(self, model: str = "local-model", base_url: Optional[str] = None):
        super().__init__(
            model=model,
            api_key="lm-studio",  # LM Studio doesn't require a real key
            base_url=base_url or os.environ.get("LM_STUDIO_URL", "http://localhost:1234/v1/chat/completions"),
        )


class LlamaCppProvider(OpenAICompatibleProvider):
    def __init__(self, model: str = "local-model", base_url: Optional[str] = None):
        super().__init__(
            model=model,
            api_key="llama-cpp",  # llama.cpp doesn't require a real key
            base_url=base_url or os.environ.get("LLAMA_CPP_URL", "http://localhost:8080/v1/chat/completions"),
        )


class VLLMProvider(OpenAICompatibleProvider):
    def __init__(self, model: str, api_key: Optional[str] = None, base_url: Optional[str] = None):
        super().__init__(
            model=model,
            api_key=api_key or os.environ.get("VLLM_API_KEY", "vllm-key"),
            base_url=base_url or os.environ.get("VLLM_URL", "http://localhost:8000/v1/chat/completions"),
        )


class OllamaProvider(LLMProvider):
    def __init__(self, model: str = "llama3", url: Optional[str] = None):
        super().__init__()
        self.model = model
        self.url = url or os.environ.get("OLLAMA_URL", "http://localhost:11434/api/generate")

    @track_telemetry
    async def generate(
        self,
        prompt: Optional[str] = None,
        context: Optional[Any] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        messages: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        # Simplified for messages support
        if messages:
            full_prompt = "\n".join([f"{m['role']}: {m['content']}" for m in messages])
        else:
            full_prompt = prompt or ""

        tool_prompt = f"\nAvailable Tools: {json.dumps(tools)}" if tools else ""
        payload = {
            "model": self.model,
            "prompt": f"Context: {context}{tool_prompt}\n\nTask: {full_prompt}\n\nPlan the tool usage and return a concise summary.",
            "stream": False,
        }
        try:
            resp = await self._request_with_retry(
                self.url,
                json_payload=payload,
                timeout=aiohttp.ClientTimeout(total=30),
            )
            if resp.status == 200:
                res_data = await resp.json()
                return res_data.get("response", "No response from LLM")
            return f"Ollama error: {resp.status}"
        except Exception as e:
            return f"Ollama connection failed: {e}"


class AnthropicProvider(LLMProvider):
    def __init__(self, model: str = "claude-3-5-sonnet-20240620", api_key: Optional[str] = None):
        super().__init__()
        self.model = model
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")

    @track_telemetry
    async def generate(
        self,
        prompt: Optional[str] = None,
        context: Optional[Any] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        messages: Optional[List[Dict[str, Any]]] = None,
    ) -> Any:
        if not self.api_key:
            return "Anthropic API key missing"

        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

        # Anthropic beta header for computer use if applicable
        if tools and any(t.get("name") == "computer" for t in tools):
            headers["anthropic-beta"] = "computer-use-2024-10-22"

        final_messages = messages or []
        if prompt:
            final_messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "max_tokens": 1024,
            "system": f"Context: {context}",
            "messages": final_messages,
        }
        if tools:
            payload["tools"] = tools

        try:
            resp = await self._request_with_retry(
                url,
                headers=headers,
                json_payload=payload,
                timeout=aiohttp.ClientTimeout(total=30),
            )
            if resp.status == 200:
                res_data = await resp.json()
                # Handle tool use in response
                if res_data.get("stop_reason") == "tool_use":
                    return res_data["content"]
                return res_data["content"][0]["text"]
            return f"Anthropic error: {resp.status}"
        except Exception as e:
            return f"Anthropic connection failed: {e}"


class GeminiProvider(LLMProvider):
    def __init__(self, model: str = "gemini-1.5-pro", api_key: Optional[str] = None):
        super().__init__()
        self.model = model
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")

    @track_telemetry
    async def generate(
        self,
        prompt: Optional[str] = None,
        context: Optional[Any] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        messages: Optional[List[Dict[str, Any]]] = None,
    ) -> Any:
        if not self.api_key:
            return "Gemini API key missing"

        # VULN-010 fix: send API key via header, not query string
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key,
        }

        contents = []
        if messages:
            for m in messages:
                role = "user" if m["role"] == "user" else "model"
                contents.append({"role": role, "parts": [{"text": m["content"]}]})

        if prompt:
            contents.append({"role": "user", "parts": [{"text": prompt}]})

        payload = {
            "contents": contents,
            "systemInstruction": {"parts": [{"text": f"Context: {context}"}]},
            "generationConfig": {"temperature": 1.0, "maxOutputTokens": 2048},
        }

        if tools:
            # Gemini tool format is slightly different, but we'll try to map common ones
            # or just pass them through if they are already in Gemini format
            payload["tools"] = [{"functionDeclarations": tools}]

        try:
            resp = await self._request_with_retry(
                url,
                headers=headers,
                json_payload=payload,
                timeout=aiohttp.ClientTimeout(total=30),
            )
            if resp.status == 200:
                res_data = await resp.json()
                candidates = res_data.get("candidates", [])
                if candidates:
                    content = candidates[0].get("content", {})
                    parts = content.get("parts", [])
                    if parts:
                        if "functionCall" in parts[0]:
                            return parts  # Return full parts for tool handling
                        return parts[0].get("text", "No text in response")
                return "No candidates in Gemini response"
            return f"Gemini error: {resp.status}"
        except Exception as e:
            return f"Gemini connection failed: {e}"


class MistralProvider(OpenAICompatibleProvider):
    def __init__(self, model: str = "mistral-large-latest", api_key: Optional[str] = None):
        super().__init__(
            model=model,
            api_key=api_key or os.environ.get("MISTRAL_API_KEY"),
            base_url="https://api.mistral.ai/v1/chat/completions",
        )


class OpenRouterProvider(OpenAICompatibleProvider):
    def __init__(self, model: str = "anthropic/claude-3.5-sonnet", api_key: Optional[str] = None):
        super().__init__(
            model=model,
            api_key=api_key or os.environ.get("OPENROUTER_API_KEY"),
            base_url="https://openrouter.ai/api/v1/chat/completions",
        )

    @track_telemetry
    async def generate(
        self,
        prompt: Optional[str] = None,
        context: Optional[Any] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        messages: Optional[List[Dict[str, Any]]] = None,
    ) -> Any:
        # OpenRouter expects some extra headers for their rankings
        if not self.api_key:
            return "OpenRouter API key missing"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/RhushabhVaghela/MegaBot",
            "X-Title": "MegaBot",
        }

        final_messages = messages or []
        if prompt:
            final_messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": f"Context: {context}"}] + final_messages,
        }
        if tools:
            payload["tools"] = tools

        try:
            resp = await self._request_with_retry(
                self.base_url,
                headers=headers,
                json_payload=payload,
                timeout=aiohttp.ClientTimeout(total=60),
            )
            if resp.status == 200:
                res_data = await resp.json()
                message = res_data["choices"][0]["message"]
                if message.get("tool_calls"):
                    return message
                return message["content"]
            return f"OpenRouter error: {resp.status} - {await resp.text()}"
        except Exception as e:
            return f"OpenRouter connection failed: {e}"


class GitHubCopilotProvider(OpenAICompatibleProvider):
    """
    Provider for GitHub Copilot.
    Note: Requires a valid GitHub token with copilot access.
    The base_url is typically the GitHub Copilot API endpoint.
    """

    def __init__(self, model: str = "gpt-4", api_key: Optional[str] = None):
        super().__init__(
            model=model,
            api_key=api_key or os.environ.get("GITHUB_TOKEN"),
            base_url="https://api.githubcopilot.com/chat/completions",
        )

    @track_telemetry
    async def generate(
        self,
        prompt: Optional[str] = None,
        context: Optional[Any] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        messages: Optional[List[Dict[str, Any]]] = None,
    ) -> Any:
        if not self.api_key:
            return "GitHub Token missing (GITHUB_TOKEN env var required)"

        # GitHub Copilot API headers differ from standard OpenAI
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Editor-Version": "vscode/1.90.0",
        }

        final_messages = messages or []
        if prompt:
            final_messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": f"Context: {context}"}] + final_messages,
        }
        # Note: Github Copilot API support for tools may vary by model/tier
        if tools:
            payload["tools"] = tools

        try:
            resp = await self._request_with_retry(
                self.base_url,
                headers=headers,
                json_payload=payload,
                timeout=aiohttp.ClientTimeout(total=60),
            )
            if resp.status == 200:
                res_data = await resp.json()
                message = res_data["choices"][0]["message"]
                if message.get("tool_calls"):
                    return message
                return message["content"]
            return f"GitHub Copilot error: {resp.status} - {await resp.text()}"
        except Exception as e:
            return f"GitHub Copilot connection failed: {e}"


def get_llm_provider(config: Dict[str, Any]) -> LLMProvider:
    provider_type = config.get("provider", "ollama").lower()
    model = config.get("model")

    if provider_type == "openai":
        return OpenAIProvider(model=model or "gpt-4-turbo")
    elif provider_type == "anthropic":
        return AnthropicProvider(model=model or "claude-3-5-sonnet-20240620")
    elif provider_type == "gemini":
        return GeminiProvider(model=model or "gemini-1.5-pro")
    elif provider_type == "groq":
        return GroqProvider(model=model or "llama3-70b-8192")
    elif provider_type == "deepseek":
        return DeepSeekProvider(model=model or "deepseek-chat")
    elif provider_type == "xai":
        return XAIProvider(model=model or "grok-beta")
    elif provider_type == "perplexity":
        return PerplexityProvider(model=model or "llama-3-sonar-large-32k-online")
    elif provider_type == "cerebras":
        return CerebrasProvider(model=model or "llama3.1-70b")
    elif provider_type == "sambanova":
        return SambaNovaProvider(model=model or "llama3-70b")
    elif provider_type == "fireworks":
        return FireworksProvider(model=model or "accounts/fireworks/models/llama-v3p1-70b-instruct")
    elif provider_type == "deepinfra":
        return DeepInfraProvider(model=model or "meta-llama/Meta-Llama-3-70B-Instruct")
    elif provider_type == "mistral":
        return MistralProvider(model=model or "mistral-large-latest")
    elif provider_type == "openrouter":
        return OpenRouterProvider(model=model or "anthropic/claude-3.5-sonnet")
    elif provider_type == "github-copilot":
        return GitHubCopilotProvider(model=model or "gpt-4")
    elif provider_type == "lmstudio":
        return LMStudioProvider(model=model or "local-model")
    elif provider_type == "llamacpp":
        return LlamaCppProvider(model=model or "local-model")
    elif provider_type == "vllm":
        return VLLMProvider(model=model or "local-model")
    else:
        return OllamaProvider(model=model or "llama3")
