import pytest
from unittest.mock import AsyncMock, patch
from core.llm_providers import (
    LLMProvider,
    OllamaProvider,
    AnthropicProvider,
    GeminiProvider,
    MistralProvider,
    OpenRouterProvider,
    GitHubCopilotProvider,
    get_llm_provider,
    OpenAICompatibleProvider,
)


class ConcreteProvider(LLMProvider):
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
    provider = ConcreteProvider()

    # Mocking generate specifically for reason steps
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

    # Test without search_tool
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
    provider = OllamaProvider(model="test-model")

    # Error status
    mock_resp = AsyncMock()
    mock_resp.status = 500
    mock_resp.__aenter__.return_value = mock_resp

    with patch("aiohttp.ClientSession.post", return_value=mock_resp):
        result = await provider.generate(prompt="test")
        assert "Ollama error: 500" in result

    # Exception
    with patch(
        "aiohttp.ClientSession.post", side_effect=Exception("Connection failed")
    ):
        result = await provider.generate(prompt="test")
        assert "Ollama connection failed: Connection failed" in result


@pytest.mark.asyncio
async def test_anthropic_provider_error_and_exception():
    provider = AnthropicProvider(api_key="test-key")

    # Error status
    mock_resp = AsyncMock()
    mock_resp.status = 403
    mock_resp.__aenter__.return_value = mock_resp

    with patch("aiohttp.ClientSession.post", return_value=mock_resp):
        result = await provider.generate(prompt="test")
        assert "Anthropic error: 403" in result

    # Exception
    with patch("aiohttp.ClientSession.post", side_effect=Exception("Timeout")):
        result = await provider.generate(prompt="test")
        assert "Anthropic connection failed: Timeout" in result


@pytest.mark.asyncio
async def test_gemini_provider_extended():
    provider = GeminiProvider(api_key="test-key")

    # Messages handling
    messages = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": "response"}]}}]
    }
    mock_resp.__aenter__.return_value = mock_resp

    with patch("aiohttp.ClientSession.post", return_value=mock_resp) as mock_post:
        await provider.generate(messages=messages, tools=[{"name": "test_tool"}])
        args, kwargs = mock_post.call_args
        payload = kwargs["json"]
        assert len(payload["contents"]) == 2
        assert payload["contents"][0]["role"] == "user"
        assert payload["contents"][1]["role"] == "model"
        assert "tools" in payload

    # Error status
    mock_resp.status = 400
    with patch("aiohttp.ClientSession.post", return_value=mock_resp):
        result = await provider.generate(prompt="test")
        assert "Gemini error: 400" in result

    # No candidates
    mock_resp.status = 200
    mock_resp.json.return_value = {"candidates": []}
    with patch("aiohttp.ClientSession.post", return_value=mock_resp):
        result = await provider.generate(prompt="test")
        assert "No candidates in Gemini response" in result

    # Exception
    with patch("aiohttp.ClientSession.post", side_effect=Exception("API Error")):
        result = await provider.generate(prompt="test")
        assert "Gemini connection failed: API Error" in result


@pytest.mark.asyncio
async def test_openrouter_provider():
    provider = OpenRouterProvider(api_key="test-key")

    # Success
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": "openrouter response"}}]
    }
    mock_resp.__aenter__.return_value = mock_resp

    with patch("aiohttp.ClientSession.post", return_value=mock_resp):
        result = await provider.generate(prompt="test", tools=[{"name": "t"}])
        assert result == "openrouter response"

    # Tool call
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": None, "tool_calls": [{"id": "1"}]}}]
    }
    with patch("aiohttp.ClientSession.post", return_value=mock_resp):
        result = await provider.generate(prompt="test")
        assert result["tool_calls"] == [{"id": "1"}]

    # Missing API key
    provider.api_key = None
    result = await provider.generate(prompt="test")
    assert "OpenRouter API key missing" in result

    # Error status
    provider.api_key = "test-key"
    mock_resp.status = 502
    mock_resp.text.return_value = "Bad Gateway"
    with patch("aiohttp.ClientSession.post", return_value=mock_resp):
        result = await provider.generate(prompt="test")
        assert "OpenRouter error: 502" in result

    # Exception
    with patch("aiohttp.ClientSession.post", side_effect=Exception("Fail")):
        result = await provider.generate(prompt="test")
        assert "OpenRouter connection failed: Fail" in result


@pytest.mark.asyncio
async def test_github_copilot_provider():
    provider = GitHubCopilotProvider(api_key="test-key")

    # Success
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": "copilot response"}}]
    }
    mock_resp.__aenter__.return_value = mock_resp

    with patch("aiohttp.ClientSession.post", return_value=mock_resp):
        result = await provider.generate(prompt="test", tools=[{"name": "t"}])
        assert result == "copilot response"

    # Tool call
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": None, "tool_calls": [{"id": "1"}]}}]
    }
    with patch("aiohttp.ClientSession.post", return_value=mock_resp):
        result = await provider.generate(prompt="test")
        assert result["tool_calls"] == [{"id": "1"}]

    # Missing API key
    provider.api_key = None
    result = await provider.generate(prompt="test")
    assert "GitHub Token missing" in result

    # Error status
    provider.api_key = "test-key"
    mock_resp.status = 401
    mock_resp.text.return_value = "Unauthorized"
    with patch("aiohttp.ClientSession.post", return_value=mock_resp):
        result = await provider.generate(prompt="test")
        assert "GitHub Copilot error: 401" in result

    # Exception
    with patch("aiohttp.ClientSession.post", side_effect=Exception("Fail")):
        result = await provider.generate(prompt="test")
        assert "GitHub Copilot connection failed: Fail" in result


def test_get_llm_provider_all_branches():
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
    p = MistralProvider(api_key="key")
    assert p.api_key == "key"
    assert p.base_url == "https://api.mistral.ai/v1/chat/completions"


@pytest.mark.asyncio
async def test_openai_compatible_provider_missing_key():
    p = OpenAICompatibleProvider("model", None, "url")
    result = await p.generate(prompt="test")
    assert "OpenAICompatibleProvider API key missing" in result
