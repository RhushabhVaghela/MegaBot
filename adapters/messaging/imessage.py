"""
iMessage Adapter for MegaBot

Provides integration with Apple iMessage via AppleScript on macOS.

IMPORTANT LIMITATIONS:
- macOS only: Requires the Messages.app and osascript (AppleScript runtime).
  Will not work on Linux, Windows, or Docker containers.
- Text only: iMessage does not expose media sending via AppleScript.
  send_media() is a no-op stub.
- No inbound webhooks: Apple does not provide a webhook API for incoming
  iMessages. handle_webhook() is a no-op stub. For incoming message
  handling, consider using a third-party bridge (e.g., BlueBubbles,
  AirMessage) and adapting their webhook format here.
- No read receipts or typing indicators via AppleScript.
"""

import asyncio
import logging
import platform
import subprocess
import uuid
from typing import Any

from .server import PlatformAdapter, PlatformMessage

logger = logging.getLogger(__name__)


def _escape_applescript_string(value: str) -> str:
    """
    Escape a string for safe inclusion in AppleScript double-quoted strings.
    Prevents injection via backslash and double-quote characters.
    """
    return value.replace("\\", "\\\\").replace('"', '\\"')


class IMessageAdapter(PlatformAdapter):
    """
    iMessage adapter using macOS AppleScript.

    Only supports outbound text messages on macOS. See module docstring
    for full list of limitations.
    """

    def __init__(self, platform_name: str, server: Any, config: dict[str, Any] | None = None):
        super().__init__(platform_name, server)
        self.config = config or {}
        self.is_macos = platform.system() == "Darwin"

        if not self.is_macos:
            logger.warning(
                "[iMessage] Running on %s — iMessage sending is only supported on macOS. "
                "All send operations will return None.",
                platform.system(),
            )

    async def send_text(self, chat_id: str, text: str, reply_to: str | None = None) -> PlatformMessage | None:
        """
        Send a text message via iMessage (macOS only).

        Args:
            chat_id: Recipient phone number or Apple ID email
            text: Message text to send
            reply_to: Unused (iMessage AppleScript doesn't support replies)

        Returns:
            PlatformMessage on success, None on failure or non-macOS
        """
        msg_id = str(uuid.uuid4())

        if not self.is_macos:
            logger.warning("[iMessage] Cannot send message: not running on macOS.")
            return None

        try:
            # Escape user input to prevent AppleScript injection
            safe_chat_id = _escape_applescript_string(chat_id)
            safe_text = _escape_applescript_string(text)

            applescript = (
                'tell application "Messages"\n'
                "    set targetService to 1st service whose service type is iMessage\n"
                f'    set targetBuddy to buddy "{safe_chat_id}" of targetService\n'
                f'    send "{safe_text}" to targetBuddy\n'
                "end tell"
            )
            process = await asyncio.create_subprocess_exec(
                "osascript",
                "-e",
                applescript,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                logger.error(
                    "[iMessage] AppleScript failed (exit %d): %s",
                    process.returncode,
                    stderr.decode().strip(),
                )
                return None

            logger.info("[iMessage] Sent message to %s (%d chars)", chat_id, len(text))

        except Exception as e:
            logger.error("[iMessage] Send failed: %s", e)
            return None

        return PlatformMessage(
            id=msg_id,
            platform="imessage",
            sender_id="megabot",
            sender_name="MegaBot",
            chat_id=chat_id,
            content=text,
            reply_to=reply_to,
        )

    async def send_media(
        self,
        chat_id: str,
        media_url: str,
        media_type: str = "image",
        caption: str | None = None,
    ) -> PlatformMessage | None:
        """
        Send media via iMessage.

        NOTE: Not supported. Apple's Messages AppleScript interface does not
        expose media/attachment sending. This is a no-op stub.

        Args:
            chat_id: Recipient identifier
            media_url: URL or path to media file
            media_type: Type of media (image, video, etc.)
            caption: Optional caption text

        Returns:
            None (always — not supported)
        """
        logger.warning(
            "[iMessage] send_media is not supported via AppleScript. "
            "Media sending requires a third-party bridge (e.g., BlueBubbles)."
        )
        return None

    async def handle_webhook(self, webhook_data: dict[str, Any]) -> PlatformMessage | None:
        """
        Handle incoming webhook data.

        NOTE: Not supported. Apple does not provide incoming message webhooks.
        This is a no-op stub for interface compatibility. For inbound message
        handling, integrate a third-party bridge and implement parsing here.

        Args:
            webhook_data: Raw webhook payload

        Returns:
            None (always — not supported)
        """
        logger.warning(
            "[iMessage] handle_webhook is not supported. Apple does not provide "
            "incoming message webhooks. Consider BlueBubbles or AirMessage."
        )
        return None

    async def shutdown(self):
        """Clean up resources (no-op for iMessage)."""
        logger.info("[iMessage] Adapter shutdown complete")
