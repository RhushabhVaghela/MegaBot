"""
Tests for LLM Providers
"""

from unittest.mock import AsyncMock, MagicMock, Mock, patch

import aiohttp
import pytest

from megabot.core.llm_providers import (
    AnthropicProvider,
    GeminiProvider,
    GitHubCopilotProvider,
    LLMProvider,
    MistralProvider,
    OllamaProvider,
    OpenAICompatibleProvider,
    OpenAIProvider,
    OpenRouterProvider,
    get_llm_provider,
)


@pytest.fixture
def mock_session():
    """Mock aiohttp ClientSession"""
    return AsyncMock()


class TestOpenAICompatibleProvider:
    """Test OpenAICompatibleProvider base class"""

    def test_init(self):
        """Test initialization"""
        provider = OpenAICompatibleProvider("gpt-4", "test_key", "https://api.test.com")
        assert provider.model == "gpt-4"
        assert provider.api_key == "test_key"
        assert provider.base_url == "https://api.test.com"

    @pytest.mark.asyncio
    async def test_generate_missing_api_key(self):
        """Test generate with missing API key"""
        provider = OpenAICompatibleProvider("gpt-4", None, "https://api.test.com")
        result = await provider.generate(prompt="test")
        assert "API key missing" in result

    @pytest.mark.asyncio
    async def test_generate_success_text(self):
        """Test successful generate with text response"""
        provider = OpenAICompatibleProvider("gpt-4", "test_key", "https://api.test.com")

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"choices": [{"message": {"content": "test response"}}]})

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = Mock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session.post = AsyncMock(return_value=mock_response)
            mock_session_class.return_value = mock_session

            result = await provider.generate(prompt="test prompt", context="test context")
            assert result == "test response"

    @pytest.mark.asyncio
    async def test_generate_success_with_tools(self):
        """Test successful generate with tool calls"""
        provider = OpenAICompatibleProvider("gpt-4", "test_key", "https://api.test.com")

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"choices": [{"message": {"tool_calls": [{"id": "call_1"}]}}]})

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = Mock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session.post = AsyncMock(return_value=mock_response)
            mock_session_class.return_value = mock_session

            result = await provider.generate(prompt="test", tools=[{"name": "test_tool"}])
            assert "tool_calls" in result

    @pytest.mark.asyncio
    async def test_generate_with_messages(self):
        """Test generate with messages parameter"""
        provider = OpenAICompatibleProvider("gpt-4", "test_key", "https://api.test.com")

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"choices": [{"message": {"content": "response"}}]})

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = Mock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session.post = AsyncMock(return_value=mock_response)
            mock_session_class.return_value = mock_session

            messages = [{"role": "user", "content": "test message"}]
            result = await provider.generate(messages=messages)
            assert result == "response"

    @pytest.mark.asyncio
    async def test_generate_http_error(self):
        """Test generate with HTTP error"""
        provider = OpenAICompatibleProvider("gpt-4", "test_key", "https://api.test.com")

        mock_response = AsyncMock()
        mock_response.status = 400
        mock_response.text = AsyncMock(return_value="Bad Request")

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = Mock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session.post = AsyncMock(return_value=mock_response)
            mock_session_class.return_value = mock_session

            result = await provider.generate(prompt="test")
            assert "error: 400" in result

    @pytest.mark.asyncio
    async def test_generate_connection_error(self):
        """Test generate with connection error"""
        provider = OpenAICompatibleProvider("gpt-4", "test_key", "https://api.test.com")

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session_class.side_effect = aiohttp.ClientError("Connection failed")

            result = await provider.generate(prompt="test")
            assert "connection failed" in result


class TestAnthropicProvider:
    """Test AnthropicProvider"""

    def test_init(self):
        """Test initialization"""
        provider = AnthropicProvider("claude-3", "test_key")
        assert provider.model == "claude-3"
        assert provider.api_key == "test_key"

    @pytest.mark.asyncio
    async def test_generate_missing_api_key(self, monkeypatch):
        """Test generate with missing API key"""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        provider = AnthropicProvider("claude-3", None)
        result = await provider.generate(prompt="test")
        assert "API key missing" in result

    @pytest.mark.asyncio
    async def test_generate_success(self):
        """Test successful generate"""
        provider = AnthropicProvider("claude-3", "test_key")

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"content": [{"text": "test response"}]})

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = Mock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session.post = AsyncMock(return_value=mock_response)
            mock_session_class.return_value = mock_session

            result = await provider.generate(prompt="test")
            assert result == "test response"

    @pytest.mark.asyncio
    async def test_generate_with_tools(self):
        """Test generate with computer use tools"""
        provider = AnthropicProvider("claude-3", "test_key")

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"stop_reason": "tool_use", "content": [{"tool_call": "data"}]})

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = Mock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session.post = AsyncMock(return_value=mock_response)
            mock_session_class.return_value = mock_session

            tools = [{"name": "computer"}]
            result = await provider.generate(prompt="test", tools=tools)
            assert result == [{"tool_call": "data"}]


class TestGeminiProvider:
    """Test GeminiProvider"""

    def test_init(self):
        """Test initialization"""
        provider = GeminiProvider("gemini-1.5", "test_key")
        assert provider.model == "gemini-1.5"
        assert provider.api_key == "test_key"

    @pytest.mark.asyncio
    async def test_generate_missing_api_key(self):
        """Test generate with missing API key"""
        provider = GeminiProvider("gemini-1.5", None)
        result = await provider.generate(prompt="test")
        assert "API key missing" in result

    @pytest.mark.asyncio
    async def test_generate_success(self):
        """Test successful generate"""
        provider = GeminiProvider("gemini-1.5", "test_key")

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(
            return_value={"candidates": [{"content": {"parts": [{"text": "test response"}]}}]}
        )

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = Mock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session.post = AsyncMock(return_value=mock_response)
            mock_session_class.return_value = mock_session

            result = await provider.generate(prompt="test")
            assert result == "test response"

    @pytest.mark.asyncio
    async def test_generate_with_function_call(self):
        """Test generate with function call response"""
        provider = GeminiProvider("gemini-1.5", "test_key")

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(
            return_value={"candidates": [{"content": {"parts": [{"functionCall": "call_data"}]}}]}
        )

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = Mock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session.post = AsyncMock(return_value=mock_response)
            mock_session_class.return_value = mock_session

            result = await provider.generate(prompt="test")
            assert result == [{"functionCall": "call_data"}]


class TestOllamaProvider:
    """Test OllamaProvider"""

    def test_init(self):
        """Test initialization"""
        provider = OllamaProvider("llama3", "http://localhost:11434/api/generate")
        assert provider.model == "llama3"
        assert provider.url == "http://localhost:11434/api/generate"

    @pytest.mark.asyncio
    async def test_generate_success(self):
        """Test successful generate"""
        provider = OllamaProvider("llama3")

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"response": "test response"})

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = Mock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session.post = AsyncMock(return_value=mock_response)
            mock_session_class.return_value = mock_session

            result = await provider.generate(prompt="test prompt", context="context")
            assert result == "test response"

    @pytest.mark.asyncio
    async def test_generate_with_messages(self):
        """Test generate with messages"""
        provider = OllamaProvider("llama3")

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"response": "response"})

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = Mock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session.post = AsyncMock(return_value=mock_response)
            mock_session_class.return_value = mock_session

            messages = [{"role": "user", "content": "test"}]
            result = await provider.generate(messages=messages)
            assert result == "response"

    @pytest.mark.asyncio
    async def test_generate_with_tools(self):
        """Test generate with tools"""
        provider = OllamaProvider("llama3")

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"response": "response"})

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = Mock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session.post = AsyncMock(return_value=mock_response)
            mock_session_class.return_value = mock_session

            tools = [{"name": "tool1"}]
            result = await provider.generate(prompt="test", tools=tools)
            assert result == "response"


class TestGetLLMProvider:
    """Test get_llm_provider factory function"""

    def test_get_openai_provider(self):
        """Test getting OpenAI provider"""
        config = {"provider": "openai", "model": "gpt-4"}
        provider = get_llm_provider(config)
        assert isinstance(provider, OpenAIProvider)
        assert provider.model == "gpt-4"

    def test_get_anthropic_provider(self):
        """Test getting Anthropic provider"""
        config = {"provider": "anthropic", "model": "claude-3"}
        provider = get_llm_provider(config)
        assert isinstance(provider, AnthropicProvider)
        assert provider.model == "claude-3"

    def test_get_gemini_provider(self):
        """Test getting Gemini provider"""
        config = {"provider": "gemini", "model": "gemini-1.5"}
        provider = get_llm_provider(config)
        assert isinstance(provider, GeminiProvider)
        assert provider.model == "gemini-1.5"

    def test_get_ollama_provider_default(self):
        """Test getting default Ollama provider"""
        config = {"provider": "unknown"}
        provider = get_llm_provider(config)
        assert isinstance(provider, OllamaProvider)
        assert provider.model == "llama3"

    def test_get_provider_with_defaults(self):
        """Test provider creation with default models"""
        config = {"provider": "groq"}
        provider = get_llm_provider(config)
        assert provider.model == "llama3-70b-8192"  # Default for Groq


# ---------------------------------------------------------------------------
# Tests migrated from test_llm_providers_coverage.py
# ---------------------------------------------------------------------------


class ConcreteProvider(LLMProvider):
    """Concrete subclass to test the abstract LLMProvider.reason() method."""

    async def generate(self, prompt=None, context=None, tools=None, messages=None):
        if prompt == "think_msg":
            return "thought"
        if "Thought: thought" in (prompt or ""):
            if "search results" in prompt:
                return "search_info"
            return "queries"
        if "Context/Search Data: search_info" in (prompt or ""):
            return "final answer"
        return "default"


@pytest.mark.asyncio
async def test_llm_provider_reason():
    """Test the 3-step reason() method with and without search_tool."""
    provider = ConcreteProvider()

    # With search_tool
    with patch.object(
        provider,
        "generate",
        side_effect=[
            "thought",  # THINK
            "queries",  # SEARCH queries
            "final answer",  # ANSWER
        ],
    ) as mock_gen:
        search_tool = AsyncMock()
        search_tool.search.return_value = "search_info"

        result = await provider.reason("test prompt", search_tool=search_tool)
        assert result == "final answer"
        assert mock_gen.call_count == 3

    # Without search_tool
    with patch.object(
        provider,
        "generate",
        side_effect=[
            "thought",  # THINK
            "search_info",  # SEARCH (internal)
            "final answer",  # ANSWER
        ],
    ) as mock_gen:
        result = await provider.reason("test prompt", search_tool=None)
        assert result == "final answer"
        assert mock_gen.call_count == 3


@pytest.mark.asyncio
async def test_ollama_provider_errors():
    """Test Ollama provider error status and connection exception."""
    provider = OllamaProvider(model="test-model")

    # Error status (non-retryable)
    mock_resp = AsyncMock()
    mock_resp.status = 400

    with patch("aiohttp.ClientSession.post", new_callable=AsyncMock, return_value=mock_resp):
        result = await provider.generate(prompt="test")
        assert "Ollama error: 400" in result

    # Exception
    with patch(
        "aiohttp.ClientSession.post",
        new_callable=AsyncMock,
        side_effect=aiohttp.ClientError("Connection failed"),
    ):
        result = await provider.generate(prompt="test")
        assert "Ollama connection failed: Connection failed" in result


@pytest.mark.asyncio
async def test_anthropic_provider_error_and_exception():
    """Test Anthropic provider error 403 and timeout exception."""
    provider = AnthropicProvider(api_key="test-key")

    # Error status
    mock_resp = AsyncMock()
    mock_resp.status = 403

    with patch("aiohttp.ClientSession.post", new_callable=AsyncMock, return_value=mock_resp):
        result = await provider.generate(prompt="test")
        assert "Anthropic error: 403" in result

    # Exception
    with patch(
        "aiohttp.ClientSession.post",
        new_callable=AsyncMock,
        side_effect=aiohttp.ClientError("Timeout"),
    ):
        result = await provider.generate(prompt="test")
        assert "Anthropic connection failed: Timeout" in result


@pytest.mark.asyncio
async def test_gemini_provider_extended():
    """Test Gemini messages handling, tools, error status, no candidates, exception."""
    provider = GeminiProvider(api_key="test-key")

    # Messages handling
    messages = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json.return_value = {"candidates": [{"content": {"parts": [{"text": "response"}]}}]}

    with patch("aiohttp.ClientSession.post", new_callable=AsyncMock, return_value=mock_resp) as mock_post:
        await provider.generate(messages=messages, tools=[{"name": "test_tool"}])
        args, kwargs = mock_post.call_args
        payload = kwargs["json"]
        assert len(payload["contents"]) == 2
        assert payload["contents"][0]["role"] == "user"
        assert payload["contents"][1]["role"] == "model"
        assert "tools" in payload

    # Error status (non-retryable)
    mock_resp.status = 400
    with patch("aiohttp.ClientSession.post", new_callable=AsyncMock, return_value=mock_resp):
        result = await provider.generate(prompt="test")
        assert "Gemini error: 400" in result

    # No candidates
    mock_resp.status = 200
    mock_resp.json.return_value = {"candidates": []}
    with patch("aiohttp.ClientSession.post", new_callable=AsyncMock, return_value=mock_resp):
        result = await provider.generate(prompt="test")
        assert "No candidates in Gemini response" in result

    # Exception
    with patch(
        "aiohttp.ClientSession.post",
        new_callable=AsyncMock,
        side_effect=aiohttp.ClientError("API Error"),
    ):
        result = await provider.generate(prompt="test")
        assert "Gemini connection failed: API Error" in result


@pytest.mark.asyncio
async def test_openrouter_provider():
    """Test OpenRouter provider: success, tool_call, missing key, error, exception."""
    provider = OpenRouterProvider(api_key="test-key")

    # Success
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json.return_value = {"choices": [{"message": {"content": "openrouter response"}}]}

    with patch("aiohttp.ClientSession.post", new_callable=AsyncMock, return_value=mock_resp):
        result = await provider.generate(prompt="test", tools=[{"name": "t"}])
        assert result == "openrouter response"

    # Tool call
    mock_resp.json.return_value = {"choices": [{"message": {"content": None, "tool_calls": [{"id": "1"}]}}]}
    with patch("aiohttp.ClientSession.post", new_callable=AsyncMock, return_value=mock_resp):
        result = await provider.generate(prompt="test")
        assert result["tool_calls"] == [{"id": "1"}]

    # Missing API key
    provider.api_key = None
    result = await provider.generate(prompt="test")
    assert "OpenRouter API key missing" in result

    # Error status (non-retryable)
    provider.api_key = "test-key"
    mock_resp.status = 400
    mock_resp.text.return_value = "Bad Request"
    with patch("aiohttp.ClientSession.post", new_callable=AsyncMock, return_value=mock_resp):
        result = await provider.generate(prompt="test")
        assert "OpenRouter error: 400" in result

    # Exception
    with patch(
        "aiohttp.ClientSession.post",
        new_callable=AsyncMock,
        side_effect=aiohttp.ClientError("Fail"),
    ):
        result = await provider.generate(prompt="test")
        assert "OpenRouter connection failed: Fail" in result


@pytest.mark.asyncio
async def test_github_copilot_provider():
    """Test GitHub Copilot provider: success, tool_call, missing key, error, exception."""
    provider = GitHubCopilotProvider(api_key="test-key")

    # Success
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json.return_value = {"choices": [{"message": {"content": "copilot response"}}]}

    with patch("aiohttp.ClientSession.post", new_callable=AsyncMock, return_value=mock_resp):
        result = await provider.generate(prompt="test", tools=[{"name": "t"}])
        assert result == "copilot response"

    # Tool call
    mock_resp.json.return_value = {"choices": [{"message": {"content": None, "tool_calls": [{"id": "1"}]}}]}
    with patch("aiohttp.ClientSession.post", new_callable=AsyncMock, return_value=mock_resp):
        result = await provider.generate(prompt="test")
        assert result["tool_calls"] == [{"id": "1"}]

    # Missing API key
    provider.api_key = None
    result = await provider.generate(prompt="test")
    assert "GitHub Token missing" in result

    # Error status (non-retryable)
    provider.api_key = "test-key"
    mock_resp.status = 401
    mock_resp.text.return_value = "Unauthorized"
    with patch("aiohttp.ClientSession.post", new_callable=AsyncMock, return_value=mock_resp):
        result = await provider.generate(prompt="test")
        assert "GitHub Copilot error: 401" in result

    # Exception
    with patch(
        "aiohttp.ClientSession.post",
        new_callable=AsyncMock,
        side_effect=aiohttp.ClientError("Fail"),
    ):
        result = await provider.generate(prompt="test")
        assert "GitHub Copilot connection failed: Fail" in result


def test_get_llm_provider_all_branches():
    """Test factory function covers all 18 provider strings."""
    providers = [
        "openai",
        "anthropic",
        "gemini",
        "groq",
        "deepseek",
        "xai",
        "perplexity",
        "cerebras",
        "sambanova",
        "fireworks",
        "deepinfra",
        "mistral",
        "openrouter",
        "github-copilot",
        "lmstudio",
        "llamacpp",
        "vllm",
        "other",
    ]
    for p in providers:
        provider = get_llm_provider({"provider": p, "model": "test"})
        assert provider is not None


def test_mistral_init():
    """Test MistralProvider init sets correct base_url."""
    p = MistralProvider(api_key="key")
    assert p.api_key == "key"
    assert p.base_url == "https://api.mistral.ai/v1/chat/completions"


# =====================================================================
# FROM test_coverage_completion.py & test_coverage_completion_final.py
# =====================================================================


@pytest.mark.asyncio
async def test_orchestrator_llm_dispatch_tool_use(orchestrator):
    # Test line 100-101 in llm_providers (tool_calls)
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(
        return_value={"choices": [{"message": {"tool_calls": [{"id": "1", "function": {"name": "test"}}]}}]}
    )

    with patch("aiohttp.ClientSession.post", new_callable=AsyncMock, return_value=mock_resp):
        provider = OpenAIProvider(api_key="test")
        res = await provider.generate(prompt="test", tools=[{"name": "test"}])
        assert "tool_calls" in res


@pytest.mark.asyncio
async def test_anthropic_provider_computer_use():
    provider = AnthropicProvider(api_key="test")
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(
        return_value={
            "stop_reason": "tool_use",
            "content": [{"type": "tool_use", "id": "1", "name": "computer"}],
        }
    )

    with patch("aiohttp.ClientSession.post", new_callable=AsyncMock, return_value=mock_resp):
        res = await provider.generate(prompt="test", tools=[{"name": "computer"}])
        assert res[0]["type"] == "tool_use"


@pytest.mark.asyncio
async def test_gemini_provider_tool_use():
    provider = GeminiProvider(api_key="test")
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(
        return_value={"candidates": [{"content": {"parts": [{"functionCall": {"name": "test"}}]}}]}
    )

    with patch("aiohttp.ClientSession.post", new_callable=AsyncMock, return_value=mock_resp):
        res = await provider.generate(prompt="test", tools=[{"name": "test"}])
        assert "functionCall" in res[0]


class TestLLMProviderCoverage:
    """Target missing lines in core/llm_providers.py"""

    @pytest.mark.asyncio
    async def test_openai_provider_error_paths(self):
        p = OpenAIProvider(api_key="key")

        # API missing key
        p.api_key = None
        assert "key missing" in await p.generate("hi")

        # Connection failed
        p.api_key = "key"
        with patch(
            "aiohttp.ClientSession.post",
            new_callable=AsyncMock,
            side_effect=aiohttp.ClientError("Conn fail"),
        ):
            assert "connection failed" in await p.generate("hi")

        # Error status (use 400 to avoid retry delays)
        mock_resp = MagicMock()
        mock_resp.status = 400
        mock_resp.text = AsyncMock(return_value="Bad request")
        with patch("aiohttp.ClientSession.post", new_callable=AsyncMock, return_value=mock_resp):
            assert "error: 400" in await p.generate("hi")

    @pytest.mark.asyncio
    async def test_anthropic_provider_error_paths(self):
        p = AnthropicProvider(api_key="key")
        p.api_key = None
        assert "key missing" in await p.generate("hi")

        p.api_key = "key"
        with patch(
            "aiohttp.ClientSession.post",
            new_callable=AsyncMock,
            side_effect=aiohttp.ClientError("Fail"),
        ):
            assert "connection failed" in await p.generate("hi")

    @pytest.mark.asyncio
    async def test_gemini_provider_error_paths(self):
        p = GeminiProvider(api_key="key")
        p.api_key = None
        assert "key missing" in await p.generate("hi")

        p.api_key = "key"
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"candidates": []})  # No candidates
        with patch("aiohttp.ClientSession.post", new_callable=AsyncMock, return_value=mock_resp):
            assert "No candidates" in await p.generate("hi")


@pytest.mark.asyncio
async def test_llm_providers_mopup():
    from megabot.core.llm_providers import (
        GeminiProvider,
        OllamaProvider,
        OpenAIProvider,
    )

    # 1. OpenAI error response (use 400 to avoid retry delays)
    mock_resp = MagicMock()
    mock_resp.status = 400
    mock_resp.text = AsyncMock(return_value="Bad Request")

    with patch("aiohttp.ClientSession.post", new_callable=AsyncMock, return_value=mock_resp):
        p = OpenAIProvider(api_key="test")
        res = await p.generate(prompt="test")
        assert "error: 400" in res

    # 2. Ollama error response
    mock_resp = MagicMock()
    mock_resp.status = 404

    with patch("aiohttp.ClientSession.post", new_callable=AsyncMock, return_value=mock_resp):
        p = OllamaProvider()
        res = await p.generate(prompt="test")
        assert "Ollama error: 404" in res

    # 3. Gemini no parts
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={"candidates": [{"content": {"parts": []}}]})

    with patch("aiohttp.ClientSession.post", new_callable=AsyncMock, return_value=mock_resp):
        p = GeminiProvider(api_key="test")
        res = await p.generate(prompt="test")
        assert "No text in response" in res or "No candidates" in res
