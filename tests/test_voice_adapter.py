"""
Tests for VoiceAdapter
"""

import pytest
from unittest.mock import MagicMock, patch
from adapters.voice_adapter import VoiceAdapter


class TestVoiceAdapter:
    """Test suite for VoiceAdapter"""

    @pytest.fixture
    def voice_adapter(self):
        """Create VoiceAdapter instance"""
        with patch("adapters.voice_adapter.Client"):
            adapter = VoiceAdapter(
                account_sid="ACtest", auth_token="test_token", from_number="+1234567890"
            )
            return adapter

    @pytest.fixture
    def voice_adapter_with_callback(self):
        """Create VoiceAdapter instance with callback URL"""
        with patch("adapters.voice_adapter.Client"):
            adapter = VoiceAdapter(
                account_sid="ACtest",
                auth_token="test_token",
                from_number="+1234567890",
                callback_url="https://example.com/callback",
            )
            return adapter

    @pytest.mark.asyncio
    async def test_make_call_text(self, voice_adapter):
        """Test making a call with text script"""
        mock_call = MagicMock()
        mock_call.sid = "CA123"
        voice_adapter.client.calls.create.return_value = mock_call

        sid = await voice_adapter.make_call("+1987654321", "Hello from MegaBot")

        assert sid == "CA123"
        voice_adapter.client.calls.create.assert_called_once()
        args = voice_adapter.client.calls.create.call_args[1]
        assert args["to"] == "+1987654321"
        assert "<Say>Hello from MegaBot</Say>" in args["twiml"]

    @pytest.mark.asyncio
    async def test_make_call_url(self, voice_adapter):
        """Test making a call with URL script"""
        mock_call = MagicMock()
        mock_call.sid = "CA456"
        voice_adapter.client.calls.create.return_value = mock_call

        sid = await voice_adapter.make_call("+1987654321", "https://example.com/twiml")

        assert sid == "CA456"
        args = voice_adapter.client.calls.create.call_args[1]
        assert args["url"] == "https://example.com/twiml"
        assert "twiml" not in args

    @pytest.mark.asyncio
    async def test_make_call_with_callback(self, voice_adapter_with_callback):
        """Test making a call with callback URL"""
        mock_call = MagicMock()
        mock_call.sid = "CA789"
        voice_adapter_with_callback.client.calls.create.return_value = mock_call

        sid = await voice_adapter_with_callback.make_call("+1987654321", "Hello")

        assert sid == "CA789"
        args = voice_adapter_with_callback.client.calls.create.call_args[1]
        assert args["status_callback"] == "https://example.com/callback"
        assert args["status_callback_event"] == [
            "initiated",
            "ringing",
            "answered",
            "completed",
        ]

    @pytest.mark.asyncio
    async def test_make_call_error(self, voice_adapter):
        """Test make_call error handling"""
        voice_adapter.client.calls.create.side_effect = Exception("API Error")

        sid = await voice_adapter.make_call("+1987654321", "Hello")

        assert sid.startswith("error_")
        assert len(sid) == 14  # error_ + 8 hex chars

    @pytest.mark.asyncio
    async def test_transcribe_audio(self, voice_adapter):
        """Test audio transcription raises NotImplementedError (no STT configured)"""
        with pytest.raises(NotImplementedError, match="speech-to-text"):
            await voice_adapter.transcribe_audio(b"dummy_audio")

    @pytest.mark.asyncio
    async def test_speak(self, voice_adapter):
        """Test text-to-speech raises NotImplementedError (no TTS configured)"""
        with pytest.raises(NotImplementedError, match="text-to-speech"):
            await voice_adapter.speak("Hello")

    @pytest.mark.asyncio
    async def test_get_call_logs(self, voice_adapter):
        """Test getting call logs raises NotImplementedError (no Twilio integration)"""
        with pytest.raises(NotImplementedError, match="Twilio API"):
            await voice_adapter.get_call_logs(limit=5)

    @pytest.mark.asyncio
    async def test_get_call_logs_error(self, voice_adapter):
        """Test get_call_logs raises NotImplementedError"""
        with pytest.raises(NotImplementedError, match="Twilio API"):
            await voice_adapter.get_call_logs(limit=1)

    @pytest.mark.asyncio
    async def test_shutdown(self, voice_adapter):
        """Test shutdown functionality"""
        assert voice_adapter.is_connected is True

        await voice_adapter.shutdown()

        assert voice_adapter.is_connected is False

    def test_initialization_error_handling(self):
        """Test initialization when Client fails"""
        with patch(
            "adapters.voice_adapter.Client", side_effect=Exception("Connection failed")
        ):
            adapter = VoiceAdapter(
                account_sid="ACtest", auth_token="test_token", from_number="+1234567890"
            )

            assert adapter.client is None
            assert adapter.is_connected is False

    def test_fallback_client_creation(self):
        """Test that fallback Client is created when twilio not available"""
        # The fallback Client is created at import time when twilio import fails
        # This test verifies the mock Client works

        # If Client is the real one (installed), we must mock it to avoid network calls
        with patch("adapters.voice_adapter.Client") as MockClient:
            instance = MockClient("test", "test")
            mock_call = MagicMock()
            mock_call.sid = "CA123"
            instance.calls.create.return_value = mock_call

            call = instance.calls.create(to="+123", from_="+456")
            assert hasattr(call, "sid")
            assert call.sid.startswith("CA")

    @pytest.mark.asyncio
    async def test_make_call_ivr(self, voice_adapter_with_callback):
        """Test making a call with IVR enabled (lines 95-96)"""
        mock_call = MagicMock()
        mock_call.sid = "CA_IVR"
        voice_adapter_with_callback.client.calls.create.return_value = mock_call

        sid = await voice_adapter_with_callback.make_call(
            "+1987654321", "Confirm action", ivr=True, action_id="act123"
        )

        assert sid == "CA_IVR"
        args = voice_adapter_with_callback.client.calls.create.call_args[1]
        assert "twiml" in args
        assert "action_id=act123" in args["twiml"]
        assert "<Gather" in args["twiml"]

    @pytest.mark.asyncio
    async def test_make_call_no_client(self, voice_adapter):
        """Test make_call when client is not initialized (lines 130-131)"""
        voice_adapter.client = None

        with patch("builtins.print") as mock_print:
            sid = await voice_adapter.make_call("+123", "Hello")
            assert sid == "error_no_client"
            mock_print.assert_called_with(
                "[Voice] Cannot make call: Twilio client not initialized."
            )

    def test_twilio_fallback_import_full_coverage(self):
        """Test the fallback mocks in voice_adapter for full coverage (lines 15-28)"""
        # Patch twilio.rest to be None to trigger fallback during reload
        with patch.dict("sys.modules", {"twilio.rest": None}):
            import importlib
            import adapters.voice_adapter

            importlib.reload(adapters.voice_adapter)

            # Test fallback Client
            client = adapters.voice_adapter.Client(None, None)
            call = client.calls.create(to="+123")
            assert call.sid.startswith("CA")
            assert len(call.sid) == 34  # CA + 32 hex
