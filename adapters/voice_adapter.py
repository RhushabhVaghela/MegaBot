"""
Voice Adapter for MegaBot
Provides integration with telephony services (Twilio) for voice calls.
"""

import asyncio
import uuid
from typing import Any, Dict, List, Optional

from core.interfaces import VoiceInterface

try:
    from twilio.rest import Client
except ImportError:
    # Fallback mock
    class Client:
        def __init__(self, *args, **kwargs):
            pass

        class Calls:
            def create(self, *args, **kwargs):
                class MockCall:
                    sid = "CA" + uuid.uuid4().hex

                return MockCall()

        calls = Calls()


class VoiceAdapter(VoiceInterface):
    """
    Voice platform adapter using Twilio.

    Features:
    - Outbound phone calls with scripts (TwiML)
    - Audio transcription (simulated/API)
    - Text-to-Speech (simulated/API)
    """

    def __init__(
        self,
        account_sid: str,
        auth_token: str,
        from_number: str,
        callback_url: Optional[str] = None,
    ):
        """
        Initialize the Voice adapter.

        Args:
            account_sid: Twilio account SID
            auth_token: Twilio auth token
            from_number: Twilio phone number
            callback_url: Webhook URL for call status/events
        """
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.from_number = from_number
        self.callback_url = callback_url

        try:
            self.client = Client(account_sid, auth_token)
            self.is_connected = True
        except Exception as e:
            print(f"[Voice] Failed to initialize Twilio client: {e}")
            self.client = None
            self.is_connected = False

    async def make_call(
        self,
        recipient_phone: str,
        script: str,
        ivr: bool = False,
        action_id: Optional[str] = None,
    ) -> str:
        """
        Initiate a phone call.

        Args:
            recipient_phone: Phone number to call
            script: Text to speak or URL to TwiML
            ivr: If True, set up an IVR flow to collect input
            action_id: The ID of the action being approved (required for IVR)

        Returns:
            Call SID
        """
        try:
            # If script doesn't look like a URL, treat it as text to speak
            if not script.startswith("http"):
                if ivr and action_id and self.callback_url:
                    # TwiML for IVR: Say script, then wait for digit 1
                    # Append action_id to the callback URL
                    action_url = f"{self.callback_url}/ivr?action_id={action_id}"
                    twiml = f"""
                    <Response>
                        <Gather numDigits="1" timeout="10" action="{action_url}">
                            <Say>{script} Press 1 to authorize this action, or any other key to reject.</Say>
                        </Gather>
                        <Say>We did not receive any input. Goodbye.</Say>
                    </Response>
                    """
                else:
                    twiml = f"<Response><Say>{script}</Say></Response>"
            else:
                twiml = None

            kwargs = {
                "to": recipient_phone,
                "from_": self.from_number,
            }

            if twiml:
                kwargs["twiml"] = twiml
            else:
                kwargs["url"] = script

            if self.callback_url:
                kwargs["status_callback"] = self.callback_url
                kwargs["status_callback_event"] = [
                    "initiated",
                    "ringing",
                    "answered",
                    "completed",
                ]

            # Run in executor because twilio-python is synchronous
            if not self.client:
                print("[Voice] Cannot make call: Twilio client not initialized.")
                return "error_no_client"

            call = await asyncio.to_thread(lambda: self.client.calls.create(**kwargs))

            print(f"[Voice] Call initiated to {recipient_phone}: {call.sid} (IVR={ivr})")
            return call.sid

        except Exception as e:
            print(f"[Voice] Make call error: {e}")
            return f"error_{uuid.uuid4().hex[:8]}"

    async def transcribe_audio(self, audio_data: bytes) -> str:
        """
        Transcribe audio data to text using Whisper or Twilio Transcription.

        Args:
            audio_data: Raw audio bytes

        Returns:
            Transcribed text, or an error message if no STT service is configured.
        """
        # Attempt OpenAI Whisper if available
        try:
            import openai  # noqa: F811

            client = openai.OpenAI()
            import tempfile, os

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(audio_data)
                tmp_path = f.name
            try:
                with open(tmp_path, "rb") as audio_file:
                    transcript = await asyncio.to_thread(
                        lambda: client.audio.transcriptions.create(model="whisper-1", file=audio_file)
                    )
                return transcript.text
            finally:
                os.unlink(tmp_path)
        except ImportError:
            pass
        except Exception as e:
            print(f"[Voice] Whisper transcription failed: {e}")

        print("[Voice] No STT service configured. Returning empty transcription.")
        return ""

    async def speak(self, text: str) -> bytes:
        """
        Convert text to speech using OpenAI TTS or Google TTS.

        Args:
            text: Text to speak

        Returns:
            Audio data bytes, or empty bytes if no TTS service is configured.
        """
        # Attempt OpenAI TTS if available
        try:
            import openai  # noqa: F811

            client = openai.OpenAI()
            response = await asyncio.to_thread(
                lambda: client.audio.speech.create(model="tts-1", voice="alloy", input=text)
            )
            return response.content
        except ImportError:
            pass
        except Exception as e:
            print(f"[Voice] OpenAI TTS failed: {e}")

        print("[Voice] No TTS service configured. Returning empty audio.")
        return b""

    async def get_call_logs(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent call logs from Twilio.

        Args:
            limit: Maximum number of logs to return

        Returns:
            List of call log dictionaries, or empty list if Twilio is unavailable.
        """
        if not self.client:
            print("[Voice] Cannot fetch call logs: Twilio client not initialized.")
            return []

        try:
            calls = await asyncio.to_thread(lambda: list(self.client.calls.list(limit=limit)))
            return [
                {
                    "sid": call.sid,
                    "from": call.from_formatted if hasattr(call, "from_formatted") else str(getattr(call, "from_", "")),
                    "to": call.to_formatted if hasattr(call, "to_formatted") else str(getattr(call, "to", "")),
                    "status": str(getattr(call, "status", "unknown")),
                    "direction": str(getattr(call, "direction", "unknown")),
                    "duration": str(getattr(call, "duration", "0")),
                    "start_time": str(getattr(call, "start_time", "")),
                }
                for call in calls
            ]
        except Exception as e:
            print(f"[Voice] Failed to retrieve call logs: {e}")
            return []

    async def shutdown(self):
        """Clean up resources"""
        self.is_connected = False
        print("[Voice] Adapter shutdown complete")
