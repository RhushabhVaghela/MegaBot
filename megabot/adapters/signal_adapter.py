"""
Signal Adapter for MegaBot
Provides integration with Signal using signal-cli (JSON-RPC interface)

Features:
- Text messages
- Media sharing (images, videos, documents)
- Group management
- Reactions
- Mentions
- Delivery receipts
- Webhook support for incoming messages
- Retry with exponential backoff on RPC calls

Note: Requires signal-cli to be installed and running in JSON-RPC mode:
    signal-cli daemon --socket /tmp/signal.socket --dbus=system
"""

import asyncio
import json
import logging
import os
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from megabot.adapters.messaging import MessageType, PlatformMessage
from megabot.core.resource_guard import LRUCache

logger = logging.getLogger(__name__)

# Retry configuration
MAX_RETRIES = 3
RETRY_BASE_DELAY = 1.0  # seconds, doubles each retry


class SignalMessageType(Enum):
    """Types of Signal messages"""

    TEXT = "text"
    DATA_MESSAGE = "dataMessage"
    TYPING = "typing"
    READ = "read"
    DELIVERED = "delivered"
    SESSION_RESET = "sessionReset"


class SignalGroupType(Enum):
    """Signal group types"""

    MASTER = "MASTER"
    UNKNOWN = "UNKNOWN"


@dataclass
class SignalRecipient:
    """Signal recipient information"""

    uuid: str | None = None
    number: str | None = None
    username: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SignalRecipient":
        return cls(
            uuid=data.get("uuid"),
            number=data.get("number"),
            username=data.get("username"),
        )


@dataclass
class SignalAttachment:
    """Signal attachment information"""

    id: str | None = None
    content_type: str | None = None
    filename: str | None = None
    size: int | None = None
    url: str | None = None
    thumbnail: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SignalAttachment":
        return cls(
            id=data.get("id"),
            content_type=data.get("contentType"),
            filename=data.get("filename"),
            size=data.get("size"),
            url=data.get("url"),
            thumbnail=data.get("thumbnail"),
        )


@dataclass
class SignalQuote:
    """Quoted message info"""

    id: int
    author: str
    text: str | None = None
    attachments: list[SignalAttachment] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SignalQuote":
        return cls(
            id=data.get("id", 0),
            author=data.get("author", ""),
            text=data.get("text"),
            attachments=[SignalAttachment.from_dict(a) for a in data.get("attachments", [])],
        )


@dataclass
class SignalReaction:
    """Reaction to a message"""

    emoji: str
    target_author: str
    target_timestamp: int

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SignalReaction":
        return cls(
            emoji=data.get("emoji", ""),
            target_author=data.get("targetAuthor", ""),
            target_timestamp=data.get("targetTimestamp", 0),
        )


@dataclass
class SignalMessage:
    """Complete Signal message"""

    id: str
    source: str
    timestamp: int
    message_type: SignalMessageType = SignalMessageType.TEXT
    content: str | None = None
    attachments: list[SignalAttachment] = field(default_factory=list)
    group_info: dict[str, Any] | None = None
    quote: SignalQuote | None = None
    reaction: SignalReaction | None = None
    is_receipt: bool = False
    is_unidentified: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SignalMessage":
        msg_type_str = data.get("type", "text")
        if msg_type_str == "typing":
            msg_type = SignalMessageType.TYPING
        elif msg_type_str == "read":
            msg_type = SignalMessageType.READ
        elif msg_type_str == "delivered":
            msg_type = SignalMessageType.DELIVERED
        elif msg_type_str == "sessionReset":
            msg_type = SignalMessageType.SESSION_RESET
        else:
            msg_type = SignalMessageType.DATA_MESSAGE

        return cls(
            id=data.get("envelopeId", str(uuid.uuid4())),
            source=data.get("source", ""),
            timestamp=data.get("timestamp", 0),
            message_type=msg_type,
            content=data.get("dataMessage", {}).get("message") if "dataMessage" in data else data.get("message"),
            attachments=[
                SignalAttachment.from_dict(a)
                for a in data.get("dataMessage", {}).get("attachments", data.get("attachments", []))
            ],
            group_info=data.get("dataMessage", {}).get("groupInfo"),
            quote=SignalQuote.from_dict(data.get("dataMessage", {}).get("quote", {})),
            reaction=SignalReaction.from_dict(data.get("dataMessage", {}).get("reaction", {}))
            if "reaction" in data.get("dataMessage", {})
            else None,
            is_receipt=msg_type in [SignalMessageType.READ, SignalMessageType.DELIVERED],
            is_unidentified=data.get("isUnidentified", False),
        )


@dataclass
class SignalGroup:
    """Signal group information"""

    id: str
    name: str
    description: str | None = None
    members: list[str] = field(default_factory=list)
    admins: list[str] = field(default_factory=list)
    group_type: SignalGroupType = SignalGroupType.UNKNOWN
    avatar: str | None = None
    created_at: int | None = None
    is_archived: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SignalGroup":
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            description=data.get("description"),
            members=data.get("members", []),
            admins=data.get("admins", []),
            group_type=SignalGroupType(data.get("type", "UNKNOWN")),
            avatar=data.get("avatar"),
            created_at=data.get("createdAt"),
            is_archived=data.get("isArchived", False),
        )


class SignalAdapter:
    """
    Signal Messenger Adapter using signal-cli JSON-RPC interface.

    Provides comprehensive Signal integration:
    - Text and media messaging
    - Group creation and management
    - Reactions and replies
    - Delivery and read receipts
    - Webhook for incoming messages
    - Contact management
    """

    def __init__(
        self,
        phone_number: str,
        socket_path: str = "/tmp/signal.socket",
        config_path: str | None = None,
        signal_cli_path: str = "signal-cli",
        receive_mode: str = "socket",
        webhook_path: str = "/webhooks/signal",
        admin_numbers: list[str] | None = None,
    ):
        """
        Initialize the Signal adapter.

        Args:
            phone_number: Your Signal phone number (with country code)
            socket_path: Path to signal-cli JSON-RPC socket
            config_path: Path to signal-cli configuration directory
            signal_cli_path: Path to signal-cli executable
            receive_mode: 'socket' or 'stdout' for receiving messages
            webhook_path: Webhook endpoint path
            admin_numbers: List of phone numbers with admin privileges
        """
        self.phone_number = phone_number
        self.socket_path = socket_path
        self.config_path = config_path or os.path.expanduser("~/.config/signal")
        self.signal_cli_path = signal_cli_path
        self.receive_mode = receive_mode
        self.webhook_path = webhook_path
        self.admin_numbers = admin_numbers or []

        self.process: asyncio.subprocess.Process | None = None
        self.reader_task: asyncio.Task | None = None
        self.is_initialized = False

        self.registered_numbers: list[str] = []
        self.blocked_numbers: list[str] = []
        self.groups: dict[str, SignalGroup] = {}

        self.message_cache: LRUCache[str, dict[str, Any]] = LRUCache(maxsize=1024)
        self.pending_messages: LRUCache[str, dict[str, Any]] = LRUCache(maxsize=256)

        self.message_handlers: list[Callable] = []
        self.reaction_handlers: list[Callable] = []
        self.receipt_handlers: list[Callable] = []
        self.error_handlers: list[Callable] = []

    async def initialize(self) -> bool:
        """
        Initialize the Signal adapter.

        Returns:
            True if initialization successful
        """
        try:
            if self.receive_mode == "socket":
                await self._start_daemon()
            else:
                await self._start_receive_process()

            self.is_initialized = True
            logger.info("[Signal] Adapter initialized for %s", self.phone_number)

            # These might fail if no daemon/process is actually running
            try:
                await self._load_groups()
                await self._load_contacts()
            except Exception as e:
                logger.warning("[Signal] Failed to load groups/contacts during init: %s", e)

            return True

        except Exception as e:
            logger.error("[Signal] Initialization failed: %s", e)
            return False

    async def shutdown(self) -> None:
        """Clean up resources"""
        if self.process:
            try:
                self.process.terminate()
                await self.process.wait()
            except Exception as e:
                logger.debug("[Signal] Error terminating process during shutdown: %s", e)
            self.process = None

        if self.reader_task:
            self.reader_task.cancel()
            try:
                await self.reader_task
            except asyncio.CancelledError:
                pass
            self.reader_task = None

        self.is_initialized = False
        logger.info("[Signal] Adapter shutdown complete")

    async def _start_daemon(self) -> None:
        """Start signal-cli daemon in JSON-RPC mode"""
        cmd = [
            self.signal_cli_path,
            "daemon",
            "--socket",
            self.socket_path,
            "--dbus",
            "system",
        ]

        env = os.environ.copy()
        env["SIGNAL_CLI_CONFIG"] = self.config_path

        self.process = await asyncio.create_subprocess_exec(
            *cmd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        await asyncio.sleep(2)

        if self.process.returncode is not None:
            _, stderr = await self.process.communicate()
            raise Exception(f"signal-cli daemon failed: {stderr.decode()}")

    async def _start_receive_process(self) -> None:
        """Start signal-cli in receive mode for stdout"""
        cmd = [self.signal_cli_path, "receive", "--json"]

        env = os.environ.copy()
        env["SIGNAL_CLI_CONFIG"] = self.config_path

        self.process = await asyncio.create_subprocess_exec(
            *cmd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        self.reader_task = asyncio.create_task(self._read_messages())

    async def _read_messages(self) -> None:
        """Read messages from signal-cli stdout"""
        if not self.process or not self.process.stdout:
            return

        try:
            while True:
                line = await self.process.stdout.readline()
                if not line:
                    break

                try:
                    data = json.loads(line.decode())
                    await self._handle_message(data)
                except json.JSONDecodeError:
                    logger.debug("[Signal] Skipping non-JSON line from signal-cli")

        except asyncio.CancelledError:
            logger.debug("[Signal] Message reader cancelled")

    async def _handle_message(self, data: dict[str, Any]) -> None:
        """Handle incoming message from signal-cli"""
        try:
            envelope_id = data.get("envelopeId", str(uuid.uuid4()))

            if "dataMessage" in data:
                message = SignalMessage.from_dict(data)
                self.message_cache[envelope_id] = message.__dict__

                platform_msg = await self._to_platform_message(message)

                for handler in self.message_handlers:
                    try:
                        result = handler(platform_msg)
                        if asyncio.iscoroutine(result):
                            await result
                    except Exception as e:
                        logger.error("[Signal] Message handler error: %s", e)

            elif "typing" in data:
                for handler in self.reaction_handlers:
                    try:
                        result = handler(data)
                        if asyncio.iscoroutine(result):
                            await result
                    except Exception as e:
                        logger.error("[Signal] Typing handler error: %s", e)

            elif data.get("type") in ["read", "delivered"]:
                for handler in self.receipt_handlers:
                    try:
                        result = handler(data)
                        if asyncio.iscoroutine(result):
                            await result
                    except Exception as e:
                        logger.error("[Signal] Receipt handler error: %s", e)

        except Exception as e:
            logger.error("[Signal] Message handling error: %s", e)

    async def _to_platform_message(self, message: SignalMessage) -> PlatformMessage:
        """Convert Signal message to PlatformMessage"""
        chat_id = message.source
        content = message.content or ""

        if message.attachments:
            if any(a.content_type and a.content_type.startswith("image/") for a in message.attachments):
                msg_type = MessageType.IMAGE
            elif any(a.content_type and a.content_type.startswith("video/") for a in message.attachments):
                msg_type = MessageType.VIDEO
            elif any(a.content_type and a.content_type.startswith("audio/") for a in message.attachments):
                msg_type = MessageType.AUDIO
            else:
                msg_type = MessageType.DOCUMENT
        elif message.group_info:
            msg_type = MessageType.TEXT
            chat_id = f"group_{message.group_info.get('id', '')}"
            content = f"[Group] {content}"
        else:
            msg_type = MessageType.TEXT

        return PlatformMessage(
            id=f"signal_{message.id}",
            platform="signal",
            sender_id=message.source,
            sender_name=message.source,
            chat_id=chat_id,
            content=content,
            message_type=msg_type,
            metadata={
                "signal_message_id": message.id,
                "signal_timestamp": message.timestamp,
                "signal_source": message.source,
                "signal_group_id": message.group_info.get("id") if message.group_info else None,
                "attachments": [a.__dict__ for a in message.attachments],
                "is_unidentified": message.is_unidentified,
            },
        )

    async def _send_json_rpc(self, method: str, params: dict[str, Any]) -> Any:
        """Send JSON-RPC request to signal-cli"""
        if self.receive_mode == "socket":
            return await self._send_socket_rpc(method, params)
        else:
            return await self._send_stdout_rpc(method, params)

    async def _send_socket_rpc(self, method: str, params: dict[str, Any]) -> Any:
        """Send JSON-RPC request via socket with retry and exponential backoff."""
        last_error: Exception | None = None

        for attempt in range(MAX_RETRIES):
            writer = None
            try:
                reader, writer = await asyncio.open_unix_connection(self.socket_path)

                request_id = str(uuid.uuid4())
                request = (
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "method": method,
                            "params": params,
                        }
                    )
                    + "\n"
                )

                writer.write(request.encode())
                await writer.drain()

                line = await asyncio.wait_for(reader.readline(), timeout=30.0)
                writer.close()
                await writer.wait_closed()
                writer = None

                if line:
                    result = json.loads(line.decode())
                    if "error" in result:
                        error_msg = result["error"].get("message", "Unknown RPC error")
                        logger.warning(
                            "[Signal] RPC error response for %s: %s (attempt %d/%d)",
                            method,
                            error_msg,
                            attempt + 1,
                            MAX_RETRIES,
                        )
                        last_error = Exception(error_msg)
                        # Don't retry on semantic errors (method not found, invalid params)
                        error_code = result["error"].get("code", 0)
                        if error_code in (-32601, -32602):
                            return None
                        # Retry on other errors
                        if attempt < MAX_RETRIES - 1:
                            delay = RETRY_BASE_DELAY * (2**attempt)
                            await asyncio.sleep(delay)
                            continue
                        return None
                    return result.get("result")
                return None

            except asyncio.TimeoutError:
                last_error = TimeoutError(f"Socket RPC timeout for {method}")
                logger.warning(
                    "[Signal] Socket RPC timeout for %s (attempt %d/%d)",
                    method,
                    attempt + 1,
                    MAX_RETRIES,
                )
            except ConnectionRefusedError as e:
                last_error = e
                logger.warning(
                    "[Signal] Socket connection refused for %s (attempt %d/%d)",
                    method,
                    attempt + 1,
                    MAX_RETRIES,
                )
            except Exception as e:
                last_error = e
                logger.warning(
                    "[Signal] Socket RPC error for %s: %s (attempt %d/%d)",
                    method,
                    e,
                    attempt + 1,
                    MAX_RETRIES,
                )
            finally:
                if writer is not None:
                    try:
                        writer.close()
                        await writer.wait_closed()
                    except Exception:
                        logger.debug("[Signal] Error closing writer during RPC cleanup")

            if attempt < MAX_RETRIES - 1:
                delay = RETRY_BASE_DELAY * (2**attempt)
                logger.info("[Signal] Retrying %s in %.1fs...", method, delay)
                await asyncio.sleep(delay)

        logger.error(
            "[Signal] Socket RPC failed for %s after %d attempts: %s",
            method,
            MAX_RETRIES,
            last_error,
        )
        return None

    async def _send_stdout_rpc(self, method: str, params: dict[str, Any]) -> Any:
        """Send JSON-RPC request via stdin/stdout with retry and exponential backoff."""
        last_error: Exception | None = None

        for attempt in range(MAX_RETRIES):
            try:
                request_id = str(uuid.uuid4())
                request = (
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "method": method,
                            "params": params,
                        }
                    )
                    + "\n"
                )

                if not self.process or not self.process.stdin:
                    logger.error("[Signal] No process available for stdout RPC")
                    return None

                self.process.stdin.write(request.encode())
                await self.process.stdin.drain()

                if self.process.stdout:
                    # Use a timeout instead of a fragile fixed sleep
                    line = await asyncio.wait_for(self.process.stdout.readline(), timeout=10.0)
                    if line:
                        result = json.loads(line.decode())
                        if "error" in result:
                            error_msg = result["error"].get("message", "Unknown RPC error")
                            logger.warning(
                                "[Signal] Stdout RPC error for %s: %s (attempt %d/%d)",
                                method,
                                error_msg,
                                attempt + 1,
                                MAX_RETRIES,
                            )
                            last_error = Exception(error_msg)
                            error_code = result["error"].get("code", 0)
                            if error_code in (-32601, -32602):
                                return None
                            if attempt < MAX_RETRIES - 1:
                                delay = RETRY_BASE_DELAY * (2**attempt)
                                await asyncio.sleep(delay)
                                continue
                            return None
                        return result.get("result")

                return None

            except asyncio.TimeoutError:
                last_error = TimeoutError(f"Stdout RPC timeout for {method}")
                logger.warning(
                    "[Signal] Stdout RPC timeout for %s (attempt %d/%d)",
                    method,
                    attempt + 1,
                    MAX_RETRIES,
                )
            except Exception as e:
                last_error = e
                logger.warning(
                    "[Signal] Stdout RPC error for %s: %s (attempt %d/%d)",
                    method,
                    e,
                    attempt + 1,
                    MAX_RETRIES,
                )

            if attempt < MAX_RETRIES - 1:
                delay = RETRY_BASE_DELAY * (2**attempt)
                logger.info("[Signal] Retrying %s in %.1fs...", method, delay)
                await asyncio.sleep(delay)

        logger.error(
            "[Signal] Stdout RPC failed for %s after %d attempts: %s",
            method,
            MAX_RETRIES,
            last_error,
        )
        return None

    async def send_message(
        self,
        recipient: str,
        message: str,
        quote_message_id: str | None = None,
        mentions: list[str] | None = None,
        attachments: list[str] | None = None,
    ) -> str | None:
        """
        Send a text message to a recipient.

        Args:
            recipient: Phone number or group ID
            message: Message text
            quote_message_id: ID of message to quote
            mentions: List of mentioned phone numbers
            attachments: List of file paths to attach

        Returns:
            Message ID or None on failure
        """
        try:
            params: dict[str, Any] = {"message": message, "recipient": recipient}

            if quote_message_id:
                try:
                    quote_id = int(quote_message_id.split("_")[-1])
                    params["quote"] = {"id": quote_id}
                except (ValueError, IndexError):
                    logger.debug("[Signal] Could not parse quote_message_id: %s", quote_message_id)
            if mentions:
                params["mentions"] = mentions
            if attachments:
                params["attachments"] = attachments

            result = await self._send_json_rpc("send", params)

            if result:
                message_id = result.get("envelopeId", str(uuid.uuid4()))
                self.pending_messages[message_id] = {
                    "recipient": recipient,
                    "content": message,
                }
                return message_id

            return None

        except Exception as e:
            logger.error("[Signal] Send message error: %s", e)
            return None

    async def send_reaction(self, recipient: str, emoji: str, target_author: str, target_timestamp: int) -> bool:
        """
        Send a reaction to a message.

        Args:
            recipient: Phone number or group ID
            emoji: Reaction emoji
            target_author: Author of the message to react to
            target_timestamp: Timestamp of message to react to

        Returns:
            True on success
        """
        try:
            params = {
                "recipient": recipient,
                "emoji": emoji,
                "targetAuthor": target_author,
                "targetTimestamp": target_timestamp,
            }

            result = await self._send_json_rpc("react", params)
            return bool(result)

        except Exception as e:
            logger.error("[Signal] Send reaction error: %s", e)
            return False

    async def send_receipt(self, recipient: str, message_ids: list[str], receipt_type: str = "read") -> bool:
        """
        Send a delivery or read receipt.

        Args:
            recipient: Phone number
            message_ids: List of message IDs
            receipt_type: 'delivered' or 'read'

        Returns:
            True on success
        """
        try:
            timestamps = []
            for m in message_ids:
                try:
                    timestamps.append(int(m.split("_")[-1]))
                except (ValueError, IndexError):
                    logger.debug("[Signal] Could not parse message_id for receipt: %s", m)

            params = {
                "recipient": recipient,
                "type": receipt_type,
                "timestamps": timestamps,
            }

            result = await self._send_json_rpc("sendReceipt", params)
            return bool(result)

        except Exception as e:
            logger.error("[Signal] Send receipt error: %s", e)
            return False

    async def create_group(
        self,
        name: str,
        members: list[str],
        description: str | None = None,
        avatar_path: str | None = None,
    ) -> SignalGroup | None:
        """
        Create a new Signal group.

        Args:
            name: Group name
            members: List of member phone numbers
            description: Group description
            avatar_path: Path to avatar image

        Returns:
            Created group or None on failure
        """
        try:
            params: dict[str, Any] = {"name": name, "members": members}

            if description:
                params["description"] = description
            if avatar_path:
                params["avatar"] = avatar_path

            result = await self._send_json_rpc("createGroup", params)

            if result:
                group = SignalGroup(
                    id=result.get("id", ""),
                    name=name,
                    members=members,
                    description=description,
                    created_at=int(datetime.now().timestamp() * 1000),
                )
                self.groups[group.id] = group
                return group

            return None

        except Exception as e:
            logger.error("[Signal] Create group error: %s", e)
            return None

    async def update_group(
        self,
        group_id: str,
        name: str | None = None,
        description: str | None = None,
        avatar_path: str | None = None,
        members_to_add: list[str] | None = None,
        members_to_remove: list[str] | None = None,
        set_admin: list[str] | None = None,
        remove_admin: list[str] | None = None,
    ) -> bool:
        """
        Update group settings.

        Args:
            group_id: Group ID
            name: New group name
            description: New group description
            avatar_path: Path to avatar image
            members_to_add: Members to add
            members_to_remove: Members to remove
            set_admin: Members to promote to admin
            remove_admin: Members to demote from admin

        Returns:
            True on success
        """
        try:
            params: dict[str, Any] = {"groupId": group_id}

            if name:
                params["name"] = name
            if description:
                params["description"] = description
            if avatar_path:
                params["avatar"] = avatar_path
            if members_to_add:
                params["addMembers"] = members_to_add
            if members_to_remove:
                params["removeMembers"] = members_to_remove
            if set_admin:
                params["setAdmin"] = set_admin
            if remove_admin:
                params["removeAdmin"] = remove_admin

            result = await self._send_json_rpc("updateGroup", params)
            return bool(result)

        except Exception as e:
            logger.error("[Signal] Update group error: %s", e)
            return False

    async def leave_group(self, group_id: str) -> bool:
        """
        Leave a group.

        Args:
            group_id: Group ID to leave

        Returns:
            True on success
        """
        try:
            params = {"groupId": group_id}
            result = await self._send_json_rpc("leaveGroup", params)
            return bool(result)
        except Exception as e:
            logger.error("[Signal] Leave group error: %s", e)
            return False

    async def get_groups(self) -> list[SignalGroup]:
        """Get list of all groups"""
        await self._load_groups()
        return list(self.groups.values())

    async def get_group(self, group_id: str) -> SignalGroup | None:
        """Get information about a specific group"""
        if group_id in self.groups:
            return self.groups[group_id]
        try:
            params = {"groupId": group_id}
            result = await self._send_json_rpc("getGroup", params)
            if result:
                group = SignalGroup.from_dict(result)
                self.groups[group.id] = group
                return group
        except Exception as e:
            logger.error("[Signal] Get group error: %s", e)
        return None

    async def _load_groups(self) -> None:
        """Load groups from signal-cli"""
        try:
            result = await self._send_json_rpc("listGroups", {})
            if result:
                for group_data in result:
                    group = SignalGroup.from_dict(group_data)
                    self.groups[group.id] = group
        except Exception as e:
            logger.error("[Signal] Load groups error: %s", e)

    async def _load_contacts(self) -> None:
        """Load contacts from signal-cli"""
        try:
            result = await self._send_json_rpc("listContacts", {})
            if result:
                self.registered_numbers = [c.get("number") for c in result if c.get("number")]
        except Exception as e:
            logger.error("[Signal] Load contacts error: %s", e)

    async def add_contact(self, number: str, name: str | None = None) -> bool:
        """
        Add a contact.

        Args:
            number: Phone number
            name: Contact name

        Returns:
            True on success
        """
        try:
            params: dict[str, Any] = {"number": number}
            if name:
                params["name"] = name
            result = await self._send_json_rpc("addContact", params)
            if result:
                self.registered_numbers.append(number)
            return bool(result)
        except Exception as e:
            logger.error("[Signal] Add contact error: %s", e)
            return False

    async def block_contact(self, number: str) -> bool:
        """
        Block a contact.

        Args:
            number: Phone number to block

        Returns:
            True on success
        """
        try:
            params = {"recipient": number}
            result = await self._send_json_rpc("block", params)
            if result and number not in self.blocked_numbers:
                self.blocked_numbers.append(number)
            return bool(result)
        except Exception as e:
            logger.error("[Signal] Block contact error: %s", e)
            return False

    async def unblock_contact(self, number: str) -> bool:
        """
        Unblock a contact.

        Args:
            number: Phone number to unblock

        Returns:
            True on success
        """
        try:
            params = {"recipient": number}
            result = await self._send_json_rpc("unblock", params)
            if result and number in self.blocked_numbers:
                self.blocked_numbers.remove(number)
            return bool(result)
        except Exception as e:
            logger.error("[Signal] Unblock contact error: %s", e)
            return False

    async def register(self, voice: bool = False) -> bool:
        """
        Register this number with Signal.

        Args:
            voice: Use voice call instead of SMS

        Returns:
            True if verification code sent
        """
        try:
            params: dict[str, Any] = {"number": self.phone_number}
            if voice:
                params["voice"] = True
            result = await self._send_json_rpc("register", params)
            return bool(result)
        except Exception as e:
            logger.error("[Signal] Register error: %s", e)
            return False

    async def verify(self, code: str) -> bool:
        """
        Verify registration with code.

        Args:
            code: Verification code

        Returns:
            True on success
        """
        try:
            params = {"number": self.phone_number, "code": code}
            result = await self._send_json_rpc("verify", params)
            return bool(result)
        except Exception as e:
            logger.error("[Signal] Verify error: %s", e)
            return False

    async def send_profile(
        self,
        name: str | None = None,
        avatar_path: str | None = None,
        about: str | None = None,
    ) -> bool:
        """
        Update and send profile.

        Args:
            name: Profile name
            avatar_path: Path to avatar image
            about: About text

        Returns:
            True on success
        """
        try:
            params: dict[str, Any] = {"number": self.phone_number}

            if name:
                params["name"] = name
            if avatar_path:
                params["avatar"] = avatar_path
            if about:
                params["about"] = about

            result = await self._send_json_rpc("updateProfile", params)
            return bool(result)
        except Exception as e:
            logger.error("[Signal] Update profile error: %s", e)
            return False

    async def upload_attachment(self, file_path: str) -> str | None:
        """
        Upload an attachment to Signal.

        Args:
            file_path: Path to file

        Returns:
            Attachment ID or None
        """
        try:
            params = {"file": file_path}
            result = await self._send_json_rpc("uploadAttachment", params)
            return result
        except Exception as e:
            logger.error("[Signal] Upload attachment error: %s", e)
            return None

    async def send_note_to_self(self, message: str) -> str | None:
        """
        Send a note to yourself (Saved Messages).

        Args:
            message: Message text

        Returns:
            Message ID or None
        """
        return await self.send_message(recipient=self.phone_number, message=message)

    async def mark_read(self, message_ids: list[str]) -> bool:
        """
        Mark messages as read.

        Args:
            message_ids: List of message IDs

        Returns:
            True on success
        """
        return await self.send_receipt(recipient=self.phone_number, message_ids=message_ids, receipt_type="read")

    def register_message_handler(self, handler: Callable) -> None:
        """Register a message handler"""
        self.message_handlers.append(handler)

    def register_reaction_handler(self, handler: Callable) -> None:
        """Register a reaction/typing handler"""
        self.reaction_handlers.append(handler)

    def register_receipt_handler(self, handler: Callable) -> None:
        """Register a receipt handler"""
        self.receipt_handlers.append(handler)

    def register_error_handler(self, handler: Callable) -> None:
        """Register an error handler"""
        self.error_handlers.append(handler)

    async def handle_webhook(self, webhook_data: dict[str, Any]) -> PlatformMessage | None:
        """
        Handle incoming webhook from signal-cli-http-gateway.

        Args:
            webhook_data: Raw webhook payload

        Returns:
            Processed PlatformMessage or None
        """
        try:
            envelope_id = webhook_data.get("envelopeId", str(uuid.uuid4()))

            if "dataMessage" in webhook_data:
                message = SignalMessage.from_dict(webhook_data)
                self.message_cache[envelope_id] = message.__dict__
                return await self._to_platform_message(message)

            return None

        except Exception as e:
            logger.error("[Signal] Webhook error: %s", e)
            return None

    def _generate_id(self) -> str:
        """Generate unique message ID"""
        return str(uuid.uuid4())


async def main():
    """Example usage of Signal adapter"""
    adapter = SignalAdapter(phone_number="+1234567890", socket_path="/tmp/signal.socket")

    if await adapter.initialize():
        print(f"Signal adapter ready for {adapter.phone_number}")

        adapter.register_message_handler(lambda msg: print(f"Received: {msg.content}"))

        await adapter.send_message(recipient="+0987654321", message="Hello from MegaBot Signal Adapter!")


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(main())
