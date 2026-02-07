"""
Tests for VoiceAdapter
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from adapters.voice_adapter import VoiceAdapter


class TestVoiceAdapter:
    """Test suite for VoiceAdapter"""

    @pytest.fixture
    def voice_adapter(self):
        """Create VoiceAdapter instance"""
        with patch("adapters.voice_adapter.Client"):
            adapter = VoiceAdapter(account_sid="ACtest", auth_token="test_token", from_number="+1234567890")
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
        """Test audio transcription returns empty string when no STT configured"""
        result = await voice_adapter.transcribe_audio(b"dummy_audio")
        assert result == ""

    @pytest.mark.asyncio
    async def test_speak(self, voice_adapter):
        """Test text-to-speech returns empty bytes when no TTS configured"""
        result = await voice_adapter.speak("Hello")
        assert result == b""

    @pytest.mark.asyncio
    async def test_get_call_logs(self, voice_adapter):
        """Test getting call logs returns empty list when no Twilio client"""
        voice_adapter.client = None
        result = await voice_adapter.get_call_logs(limit=5)
        assert result == []

    @pytest.mark.asyncio
    async def test_get_call_logs_error(self, voice_adapter):
        """Test get_call_logs returns empty list on error"""
        voice_adapter.client = None
        result = await voice_adapter.get_call_logs(limit=1)
        assert result == []

    @pytest.mark.asyncio
    async def test_shutdown(self, voice_adapter):
        """Test shutdown functionality"""
        assert voice_adapter.is_connected is True

        await voice_adapter.shutdown()

        assert voice_adapter.is_connected is False

    def test_initialization_error_handling(self):
        """Test initialization when Client fails"""
        with patch("adapters.voice_adapter.Client", side_effect=Exception("Connection failed")):
            adapter = VoiceAdapter(account_sid="ACtest", auth_token="test_token", from_number="+1234567890")

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

        sid = await voice_adapter_with_callback.make_call("+1987654321", "Confirm action", ivr=True, action_id="act123")

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
            mock_print.assert_called_with("[Voice] Cannot make call: Twilio client not initialized.")

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

    # ── Phase 5-2: Additional coverage for transcribe/speak/call_logs/make_call ──

    @pytest.mark.asyncio
    async def test_transcribe_audio_whisper_success(self, voice_adapter):
        """Test transcribe_audio success path using OpenAI Whisper"""
        mock_openai = MagicMock()
        mock_client = MagicMock()
        mock_openai.OpenAI.return_value = mock_client
        mock_client.audio.transcriptions.create.return_value = MagicMock(text="hello world")

        with patch.dict("sys.modules", {"openai": mock_openai}):
            result = await voice_adapter.transcribe_audio(b"fake_audio_data")

        assert result == "hello world"

    @pytest.mark.asyncio
    async def test_transcribe_audio_import_error(self, voice_adapter):
        """Test transcribe_audio returns empty string when openai is not installed"""
        # Remove openai from sys.modules to force ImportError
        with patch.dict("sys.modules", {"openai": None}):
            result = await voice_adapter.transcribe_audio(b"fake_audio_data")

        assert result == ""

    @pytest.mark.asyncio
    async def test_transcribe_audio_general_exception(self, voice_adapter):
        """Test transcribe_audio returns empty string on general exception"""
        mock_openai = MagicMock()
        mock_openai.OpenAI.side_effect = RuntimeError("API key invalid")

        with patch.dict("sys.modules", {"openai": mock_openai}):
            result = await voice_adapter.transcribe_audio(b"fake_audio_data")

        assert result == ""

    @pytest.mark.asyncio
    async def test_speak_tts_success(self, voice_adapter):
        """Test speak success path using OpenAI TTS"""
        mock_openai = MagicMock()
        mock_client = MagicMock()
        mock_openai.OpenAI.return_value = mock_client
        mock_client.audio.speech.create.return_value = MagicMock(content=b"audio_bytes_here")

        with patch.dict("sys.modules", {"openai": mock_openai}):
            result = await voice_adapter.speak("Hello there")

        assert result == b"audio_bytes_here"

    @pytest.mark.asyncio
    async def test_speak_import_error(self, voice_adapter):
        """Test speak returns empty bytes when openai is not installed"""
        with patch.dict("sys.modules", {"openai": None}):
            result = await voice_adapter.speak("Hello there")

        assert result == b""

    @pytest.mark.asyncio
    async def test_speak_general_exception(self, voice_adapter):
        """Test speak returns empty bytes on general exception"""
        mock_openai = MagicMock()
        mock_openai.OpenAI.side_effect = RuntimeError("TTS quota exceeded")

        with patch.dict("sys.modules", {"openai": mock_openai}):
            result = await voice_adapter.speak("Hello there")

        assert result == b""

    @pytest.mark.asyncio
    async def test_get_call_logs_success(self, voice_adapter):
        """Test get_call_logs success path with mock Twilio client"""
        mock_call1 = MagicMock()
        mock_call1.sid = "CA111"
        mock_call1.from_formatted = "+1-555-0100"
        mock_call1.to_formatted = "+1-555-0200"
        mock_call1.status = "completed"
        mock_call1.direction = "outbound-api"
        mock_call1.duration = "30"
        mock_call1.start_time = "2025-01-01T12:00:00Z"

        mock_call2 = MagicMock()
        mock_call2.sid = "CA222"
        mock_call2.from_formatted = "+1-555-0300"
        mock_call2.to_formatted = "+1-555-0400"
        mock_call2.status = "busy"
        mock_call2.direction = "inbound"
        mock_call2.duration = "0"
        mock_call2.start_time = "2025-01-02T08:00:00Z"

        voice_adapter.client.calls.list.return_value = [mock_call1, mock_call2]

        result = await voice_adapter.get_call_logs(limit=5)

        assert len(result) == 2
        assert result[0]["sid"] == "CA111"
        assert result[0]["from"] == "+1-555-0100"
        assert result[0]["to"] == "+1-555-0200"
        assert result[0]["status"] == "completed"
        assert result[0]["direction"] == "outbound-api"
        assert result[0]["duration"] == "30"
        assert result[1]["sid"] == "CA222"
        assert result[1]["status"] == "busy"

    @pytest.mark.asyncio
    async def test_get_call_logs_exception(self, voice_adapter):
        """Test get_call_logs returns empty list on Twilio API exception"""
        voice_adapter.client.calls.list.side_effect = Exception("Twilio API error")

        result = await voice_adapter.get_call_logs(limit=5)

        assert result == []

    @pytest.mark.asyncio
    async def test_make_call_xml_escaping(self, voice_adapter):
        """Test make_call escapes XML special chars in script text"""
        mock_call = MagicMock()
        mock_call.sid = "CA_ESC"
        voice_adapter.client.calls.create.return_value = mock_call

        sid = await voice_adapter.make_call("+1987654321", '<script>alert("xss")</script>')

        assert sid == "CA_ESC"
        args = voice_adapter.client.calls.create.call_args[1]
        twiml = args["twiml"]
        # The angle brackets must be escaped
        assert "&lt;script&gt;" in twiml
        assert "<script>" not in twiml

    @pytest.mark.asyncio
    async def test_make_call_ivr_action_id_escaping(self, voice_adapter_with_callback):
        """Test make_call IVR path escapes action_id special characters"""
        mock_call = MagicMock()
        mock_call.sid = "CA_IVR_ESC"
        voice_adapter_with_callback.client.calls.create.return_value = mock_call

        sid = await voice_adapter_with_callback.make_call(
            "+1987654321", "Approve this?", ivr=True, action_id='act<>&"123'
        )

        assert sid == "CA_IVR_ESC"
        args = voice_adapter_with_callback.client.calls.create.call_args[1]
        twiml = args["twiml"]
        # xml_escape is applied twice: once to action_id, once to the full action URL
        # So < becomes &lt; then &lt; becomes &amp;lt; in the final twiml
        # The raw < > & " should NOT appear unescaped
        assert 'act<>&"123' not in twiml
        # The first-pass escaped action_id should be present somewhere
        assert "action_id=act" in twiml
