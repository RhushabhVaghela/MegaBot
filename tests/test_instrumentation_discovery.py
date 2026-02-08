"""Tests for ModuleDiscovery and Instrumentation"""

from unittest.mock import patch

import pytest

from megabot.core.discovery import ModuleDiscovery
from megabot.core.instrumentation import track_telemetry


class TestModuleDiscovery:
    def test_discovery_init(self):
        discovery = ModuleDiscovery("/tmp")
        assert discovery.base_path == "/tmp"
        assert discovery.capabilities == {}

    def test_scan_modules(self):
        discovery = ModuleDiscovery("/tmp")
        with (
            patch("os.path.exists", return_value=True),
            patch("os.listdir", return_value=["skill1", "skill2"]),
            patch("os.path.isdir", return_value=True),
        ):
            discovery.scan()
            assert "skill1" in discovery.capabilities
            assert "skill2" in discovery.capabilities

    def test_get_capability_path(self):
        discovery = ModuleDiscovery("/tmp")
        discovery.capabilities["test"] = "/tmp/test"
        assert discovery.get_capability_path("test") == "/tmp/test"
        assert discovery.get_capability_path("unknown") is None


class TestInstrumentation:
    @pytest.mark.asyncio
    async def test_track_telemetry_success(self):
        """Test track_telemetry decorator success path"""

        class MockProvider:
            model = "test-model"

            @track_telemetry
            async def generate(self, prompt):
                return {"choices": [{"text": "hello"}], "usage": {"total_tokens": 10}}

        provider = MockProvider()
        with patch("megabot.core.instrumentation.logger") as mock_logger:
            result = await provider.generate("hi")
            assert result["usage"]["total_tokens"] == 10
            assert mock_logger.info.called

    @pytest.mark.asyncio
    async def test_track_telemetry_error(self):
        """Test track_telemetry decorator error path"""

        class MockProvider:
            model = "test-model"

            @track_telemetry
            async def generate(self, prompt):
                raise Exception("API Error")

        provider = MockProvider()
        with patch("megabot.core.instrumentation.logger") as mock_logger:
            with pytest.raises(Exception, match="API Error"):
                await provider.generate("hi")
            assert mock_logger.error.called

    @pytest.mark.asyncio
    async def test_track_telemetry_extended_token_ids(self):
        """Test track_telemetry with extended token ID tracking (lines 50, 57, 61)"""
        from megabot.core.instrumentation import track_telemetry

        class MockProvider:
            model = "test-model"

            @track_telemetry
            async def generate(self, result_data):
                return result_data

        provider = MockProvider()

        # Test line 50 (prompt_token_ids)
        result1 = {"prompt_token_ids": [1, 2, 3], "usage": {}}
        await provider.generate(result1)

        # Test line 57 (response_token_ids)
        result2 = {"choices": [{"response_token_ids": [4, 5, 6]}], "usage": {}}
        await provider.generate(result2)

        # Test line 61 (token_ids)
        result3 = {"choices": [{"token_ids": [7, 8, 9]}], "usage": {}}
        await provider.generate(result3)

    @pytest.mark.asyncio
    async def test_track_telemetry_list_response(self):
        """Test track_telemetry with list response (lines 63-66)"""
        from megabot.core.instrumentation import track_telemetry

        class MockProvider:
            model = "test-model"

            @track_telemetry
            async def generate(self, result_list):
                return result_list

        provider = MockProvider()
        await provider.generate([{"type": "text", "text": "hello"}])
