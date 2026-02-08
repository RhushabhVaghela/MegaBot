from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel


class Message(BaseModel):
    content: str
    sender: str
    attachments: list[dict[str, Any]] = []
    metadata: dict[str, Any] = {}


@runtime_checkable
class MessagingInterface(Protocol):
    async def send_message(self, message: Message) -> None: ...
    async def receive_message(self) -> Message: ...


@runtime_checkable
class MemoryInterface(Protocol):
    async def store(self, key: str, value: Any) -> None: ...
    async def retrieve(self, key: str) -> Any: ...
    async def search(self, query: str) -> list[Any]: ...


@runtime_checkable
class ToolInterface(Protocol):
    async def execute(self, **kwargs) -> Any: ...


@runtime_checkable
class VoiceInterface(Protocol):
    """Interface for Voice/Phone calling services"""

    async def make_call(
        self,
        recipient_phone: str,
        script: str,
        ivr: bool = False,
        action_id: str | None = None,
    ) -> str: ...
    async def transcribe_audio(self, audio_data: bytes) -> str: ...
    async def speak(self, text: str) -> bytes: ...


@runtime_checkable
class ProductivityInterface(Protocol):
    """Interface for Email and Calendar services"""

    async def get_upcoming_events(self, limit: int = 5) -> list[dict]: ...
    async def get_recent_emails(self, limit: int = 5) -> list[dict]: ...
    async def send_email(self, recipient: str, subject: str, body: str) -> bool: ...
