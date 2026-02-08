"""Tests for additional LLM providers (LM Studio, llama.cpp, vLLM)"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.llm_providers import (
    LlamaCppProvider,
    LMStudioProvider,
    VLLMProvider,
    get_llm_provider,
)


class TestExtraLLMProviders:
    """Test suite for LM Studio, llama.cpp, and vLLM providers"""

    @pytest.mark.asyncio
    async def test_lmstudio_provider_success(self):
        """Test LM Studio provider success path"""
        provider = LMStudioProvider(
            model="test-model", base_url="http://local-lm:1234/v1"
        )
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(
            return_value={"choices": [{"message": {"content": "LM Studio Response"}}]}
        )

        with patch(
            "aiohttp.ClientSession.post", new_callable=AsyncMock, return_value=mock_resp
        ):
            result = await provider.generate("hello")
            assert result == "LM Studio Response"
            assert provider.base_url == "http://local-lm:1234/v1"

    @pytest.mark.asyncio
    async def test_llamacpp_provider_success(self):
        """Test llama.cpp provider success path"""
        provider = LlamaCppProvider(
            model="test-model", base_url="http://local-cpp:8080/v1"
        )
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(
            return_value={"choices": [{"message": {"content": "llama.cpp Response"}}]}
        )

        with patch(
            "aiohttp.ClientSession.post", new_callable=AsyncMock, return_value=mock_resp
        ):
            result = await provider.generate("hello")
            assert result == "llama.cpp Response"

    @pytest.mark.asyncio
    async def test_vllm_provider_success(self):
        """Test vLLM provider success path"""
        provider = VLLMProvider(
            model="test-model",
            api_key="vllm-token",
            base_url="http://vllm-server:8000/v1",
        )
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(
            return_value={"choices": [{"message": {"content": "vLLM Response"}}]}
        )

        with patch(
            "aiohttp.ClientSession.post", new_callable=AsyncMock, return_value=mock_resp
        ):
            result = await provider.generate("hello")
            assert result == "vLLM Response"
            assert provider.api_key == "vllm-token"

    def test_get_llm_provider_factory_extra(self):
        """Test factory method for getting new providers"""
        assert isinstance(get_llm_provider({"provider": "lmstudio"}), LMStudioProvider)
        assert isinstance(get_llm_provider({"provider": "llamacpp"}), LlamaCppProvider)
        assert isinstance(get_llm_provider({"provider": "vllm"}), VLLMProvider)
