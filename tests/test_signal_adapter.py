"""
Tests for Signal Adapter
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from megabot.adapters.messaging import MessageType
from megabot.adapters.signal_adapter import (
    SignalAdapter,
    SignalAttachment,
    SignalGroup,
    SignalGroupType,
    SignalMessage,
    SignalMessageType,
    SignalQuote,
    SignalReaction,
    SignalRecipient,
)


class TestSignalDataClasses:
    """Test Signal data classes"""

    def test_signal_recipient(self):
        r = SignalRecipient.from_dict({"uuid": "u", "number": "n", "username": "un"})
        assert r.uuid == "u"
        assert r.number == "n"
        assert r.username == "un"

    def test_signal_attachment(self):
        a = SignalAttachment.from_dict(
            {
                "id": "1",
                "contentType": "t",
                "filename": "f",
                "size": 10,
                "url": "u",
                "thumbnail": "th",
            }
        )
        assert a.id == "1"
        assert a.content_type == "t"

    def test_signal_quote(self):
        q = SignalQuote.from_dict({"id": 1, "author": "a", "text": "t", "attachments": [{"id": "1"}]})
        assert q.id == 1
        assert len(q.attachments) == 1

    def test_signal_reaction(self):
        r = SignalReaction.from_dict({"emoji": "e", "targetAuthor": "a", "targetTimestamp": 1})
        assert r.emoji == "e"

    def test_signal_message_full_data(self):
        """Test SignalMessage.from_dict with all optional fields"""
        full_data = {
            "envelopeId": "test_id",
            "source": "+1234567890",
            "timestamp": 1234567890,
            "type": "dataMessage",
            "dataMessage": {
                "message": "Hello world",
                "attachments": [
                    {
                        "id": "att1",
                        "contentType": "image/jpeg",
                        "filename": "test.jpg",
                        "size": 1024,
                        "url": "http://example.com/att1",
                        "thumbnail": "http://example.com/thumb1",
                    }
                ],
                "groupInfo": {"id": "group123", "name": "Test Group", "type": "MASTER"},
                "quote": {
                    "id": 123,
                    "author": "+0987654321",
                    "text": "Quoted message",
                    "attachments": [{"id": "quote_att", "contentType": "text/plain"}],
                },
                "reaction": {
                    "emoji": "👍",
                    "targetAuthor": "+0987654321",
                    "targetTimestamp": 1234567800,
                },
            },
            "isUnidentified": True,
        }

        msg = SignalMessage.from_dict(full_data)
        assert msg.id == "test_id"
        assert msg.source == "+1234567890"
        assert msg.timestamp == 1234567890
        assert msg.message_type == SignalMessageType.DATA_MESSAGE
        assert msg.content == "Hello world"
        assert len(msg.attachments) == 1
        assert msg.attachments[0].content_type == "image/jpeg"
        assert msg.group_info is not None
        assert msg.quote is not None
        assert msg.quote.text == "Quoted message"
        assert msg.reaction is not None
        assert msg.reaction.emoji == "👍"
        assert msg.is_receipt is False
        assert msg.is_unidentified is True

    def test_signal_group_full_data(self):
        """Test SignalGroup.from_dict with all fields"""
        full_data = {
            "id": "group123",
            "name": "Test Group",
            "description": "A test group",
            "members": ["+123", "+456"],
            "admins": ["+123"],
            "type": "MASTER",
            "avatar": "http://example.com/avatar.jpg",
            "createdAt": 1234567890,
            "isArchived": True,
        }

        group = SignalGroup.from_dict(full_data)
        assert group.id == "group123"
        assert group.name == "Test Group"
        assert group.description == "A test group"
        assert group.members == ["+123", "+456"]
        assert group.admins == ["+123"]
        assert group.group_type == SignalGroupType.MASTER
        assert group.avatar == "http://example.com/avatar.jpg"
        assert group.created_at == 1234567890
        assert group.is_archived is True


class TestSignalAdapter:
    """Test Signal adapter functionality"""

    @pytest.fixture
    def adapter(self):
        return SignalAdapter(phone_number="+123", socket_path="/tmp/test.sock")

    @pytest.mark.asyncio
    async def test_initialize_socket(self, adapter):
        with (
            patch.object(adapter, "_start_daemon", new_callable=AsyncMock) as mock_daemon,
            patch.object(adapter, "_send_json_rpc", new_callable=AsyncMock) as mock_rpc,
        ):
            # Mock successful RPC calls for load operations
            mock_rpc.side_effect = lambda method, params: {
                "listGroups": [{"id": "g1", "name": "Group 1"}],
                "listContacts": [{"number": "+123"}],
            }.get(method, True)

            assert await adapter.initialize() is True
            assert adapter.is_initialized is True

            # Verify RPC calls were made
            assert mock_rpc.call_count >= 2  # At least listGroups and listContacts

            # Test fail
            mock_daemon.side_effect = Exception("error")
            adapter.is_initialized = False
            assert await adapter.initialize() is False

    @pytest.mark.asyncio
    async def test_initialize_stdout(self, adapter):
        adapter.receive_mode = "stdout"
        with (
            patch.object(adapter, "_start_receive_process", new_callable=AsyncMock) as mock_recv,
            patch.object(adapter, "_send_json_rpc", new_callable=AsyncMock) as mock_rpc,
        ):
            # Mock successful RPC calls
            mock_rpc.side_effect = lambda method, params: {
                "listGroups": [{"id": "g1", "name": "Group 1"}],
                "listContacts": [{"number": "+123"}],
            }.get(method, True)

            assert await adapter.initialize() is True

    @pytest.mark.asyncio
    async def test_shutdown(self, adapter):
        adapter.process = MagicMock()
        adapter.process.terminate = MagicMock()
        adapter.process.wait = AsyncMock()

        async def mock_task():
            try:
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                pass

        adapter.reader_task = asyncio.create_task(mock_task())

        await adapter.shutdown()
        assert adapter.process is None
        assert adapter.reader_task is None

        # Test with exceptions
        adapter.process = MagicMock()
        adapter.process.terminate = MagicMock(side_effect=Exception("terminate failed"))
        adapter.process.wait = AsyncMock()
        adapter.reader_task = asyncio.create_task(mock_task())

        # Should not raise exception despite failures
        await adapter.shutdown()
        assert adapter.process is None
        assert adapter.reader_task is None

    @pytest.mark.asyncio
    async def test_handle_message_types(self, adapter):
        msg_handler = AsyncMock()
        adapter.register_message_handler(msg_handler)

        # Data message
        await adapter._handle_message(
            {
                "envelopeId": "1",
                "source": "s",
                "timestamp": 1,
                "dataMessage": {"message": "m"},
            }
        )
        msg_handler.assert_called_once()

        # Typing
        ty_handler = AsyncMock()
        adapter.register_reaction_handler(ty_handler)
        await adapter._handle_message({"typing": {}})
        ty_handler.assert_called_once()

        # Receipt
        re_handler = AsyncMock()
        adapter.register_receipt_handler(re_handler)
        await adapter._handle_message({"type": "read"})
        re_handler.assert_called_once()

        # Error case
        with patch(
            "megabot.adapters.signal_adapter.SignalMessage.from_dict",
            side_effect=Exception("error"),
        ):
            await adapter._handle_message({"dataMessage": {}})  # Should log error and not crash

    @pytest.mark.asyncio
    async def test_to_platform_message(self, adapter):
        # Image
        m = SignalMessage(
            id="1",
            source="s",
            timestamp=1,
            attachments=[SignalAttachment(content_type="image/png")],
        )
        pm = await adapter._to_platform_message(m)
        assert pm.message_type == MessageType.IMAGE

        # Video
        m.attachments = [SignalAttachment(content_type="video/mp4")]
        pm = await adapter._to_platform_message(m)
        assert pm.message_type == MessageType.VIDEO

        # Audio
        m.attachments = [SignalAttachment(content_type="audio/mpeg")]
        pm = await adapter._to_platform_message(m)
        assert pm.message_type == MessageType.AUDIO

        # Document
        m.attachments = [SignalAttachment(content_type="application/pdf")]
        pm = await adapter._to_platform_message(m)
        assert pm.message_type == MessageType.DOCUMENT

        # Group
        m = SignalMessage(id="2", source="s", timestamp=1, group_info={"id": "gid"})
        pm = await adapter._to_platform_message(m)
        assert pm.chat_id == "group_gid"

    @pytest.mark.asyncio
    async def test_send_socket_rpc(self, adapter):
        mock_reader = AsyncMock()
        mock_writer = MagicMock()
        mock_writer.write = MagicMock()
        mock_writer.drain = AsyncMock()
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        mock_reader.readline.return_value = json.dumps({"result": "ok"}).encode() + b"\n"

        with patch("asyncio.open_unix_connection", return_value=(mock_reader, mock_writer)):
            res = await adapter._send_socket_rpc("m", {})
            assert res == "ok"

        # Error case
        with patch("asyncio.open_unix_connection", side_effect=Exception("error")):
            assert await adapter._send_socket_rpc("m", {}) is None

        # Empty response case
        mock_reader.readline.return_value = b""
        with patch("asyncio.open_unix_connection", return_value=(mock_reader, mock_writer)):
            res = await adapter._send_socket_rpc("m", {})
            assert res is None

    @pytest.mark.asyncio
    async def test_send_stdout_rpc(self, adapter):
        adapter.receive_mode = "stdout"
        adapter.process = MagicMock()

        # Create a mock stdin that supports both sync write and async drain
        mock_stdin = MagicMock()
        mock_stdin.write = MagicMock(return_value=None)
        mock_stdin.drain = AsyncMock()
        adapter.process.stdin = mock_stdin

        adapter.process.stdout = AsyncMock()

        adapter.process.stdout.readline.return_value = json.dumps({"result": "ok"}).encode() + b"\n"

        res = await adapter._send_stdout_rpc("m", {})
        assert res == "ok"

    @pytest.mark.asyncio
    async def test_send_message_full(self, adapter):
        with patch.object(adapter, "_send_json_rpc", new_callable=AsyncMock) as mock_rpc:
            mock_rpc.return_value = {"envelopeId": "e"}

            # With all params
            res = await adapter.send_message("r", "m", quote_message_id="q_123", mentions=["m"], attachments=["a"])
            assert res == "e"
            assert mock_rpc.call_count == 1

            # Fail case
            mock_rpc.return_value = None
            assert await adapter.send_message("r", "m") is None

            # Exception case
            mock_rpc.side_effect = Exception("error")
            assert await adapter.send_message("r", "m") is None

    @pytest.mark.asyncio
    async def test_group_methods(self, adapter):
        with patch.object(adapter, "_send_json_rpc", new_callable=AsyncMock) as mock_rpc:
            mock_rpc.return_value = {"id": "gid"}

            # Create
            g = await adapter.create_group("n", ["m"], description="d", avatar_path="a")
            assert g.id == "gid"

            # Update
            mock_rpc.return_value = True
            assert await adapter.update_group("gid", name="new", members_to_add=["m2"]) is True

            # Leave
            assert await adapter.leave_group("gid") is True

            # Get list
            mock_rpc.return_value = [{"id": "g1", "name": "N"}]
            adapter.groups = {}  # Clear cache
            groups = await adapter.get_groups()
            assert len(groups) == 1

            # Get single
            mock_rpc.return_value = {"id": "g1", "name": "N"}
            g = await adapter.get_group("g1")
            assert g.id == "g1"

    @pytest.mark.asyncio
    async def test_send_reaction(self, adapter):
        with patch.object(adapter, "_send_json_rpc", new_callable=AsyncMock) as mock_rpc:
            mock_rpc.return_value = True

            result = await adapter.send_reaction("recipient", "👍", "author", 1234567890)
            assert result is True
            mock_rpc.assert_called_once_with(
                "react",
                {
                    "recipient": "recipient",
                    "emoji": "👍",
                    "targetAuthor": "author",
                    "targetTimestamp": 1234567890,
                },
            )

            # Test failure
            mock_rpc.return_value = None
            assert await adapter.send_reaction("recipient", "👍", "author", 1234567890) is False

            # Test exception
            mock_rpc.side_effect = Exception("error")
            assert await adapter.send_reaction("recipient", "👍", "author", 1234567890) is False
            # Should filter out invalid IDs and send valid ones

    @pytest.mark.asyncio
    async def test_create_group_cache_update(self, adapter):
        """Test group creation and cache update"""
        with patch.object(adapter, "_send_json_rpc", new_callable=AsyncMock) as mock_rpc:
            mock_rpc.return_value = {"id": "new_group_id", "name": "Test Group"}

            group = await adapter.create_group("Test Group", ["+123"])
            assert group.id == "new_group_id"
            assert "new_group_id" in adapter.groups

    @pytest.mark.asyncio
    async def test_load_groups_cache_update(self, adapter):
        """Test loading groups and cache population"""
        with patch.object(adapter, "_send_json_rpc", new_callable=AsyncMock) as mock_rpc:
            mock_rpc.return_value = [
                {"id": "g1", "name": "Group 1"},
                {"id": "g2", "name": "Group 2"},
            ]

            await adapter._load_groups()
            assert len(adapter.groups) == 2
            assert "g1" in adapter.groups
            assert "g2" in adapter.groups

    @pytest.mark.asyncio
    async def test_load_contacts_duplicate_handling(self, adapter):
        """Test loading contacts with duplicates"""
        with patch.object(adapter, "_send_json_rpc", new_callable=AsyncMock) as mock_rpc:
            mock_rpc.return_value = [
                {"number": "+123"},
                {"number": "+456"},
                {"number": "+123"},  # Duplicate
            ]

            await adapter._load_contacts()
            # Should deduplicate automatically in list
            assert "+123" in adapter.registered_numbers
            assert "+456" in adapter.registered_numbers

    @pytest.mark.asyncio
    async def test_block_unblock_cache_management(self, adapter):
        """Test blocking/unblocking and cache updates"""
        with patch.object(adapter, "_send_json_rpc", new_callable=AsyncMock) as mock_rpc:
            mock_rpc.return_value = True

            # Test blocking
            result = await adapter.block_contact("+123")
            assert result is True
            assert "+123" in adapter.blocked_numbers

            # Test unblocking
            result = await adapter.unblock_contact("+123")
            assert result is True
            assert "+123" not in adapter.blocked_numbers

    @pytest.mark.asyncio
    async def test_handle_webhook_missing_envelope_fields(self, adapter):
        """Test webhook handling with missing fields"""
        # Test missing envelopeId
        result = await adapter.handle_webhook({"dataMessage": {"message": "test"}})
        assert result is not None  # Should generate UUID

        # Test missing dataMessage
        result = await adapter.handle_webhook({"envelopeId": "test"})
        assert result is None

        # Test with non-dataMessage
        result = await adapter.handle_webhook({"envelopeId": "test", "typing": {}})
        assert result is None

    @pytest.mark.asyncio
    async def test_to_platform_message_attachment_types(self, adapter):
        """Test platform message conversion for different attachment types"""
        # Test image attachment
        msg = SignalMessage(
            id="1",
            source="+123",
            timestamp=1234567890,
            attachments=[SignalAttachment(content_type="image/jpeg")],
        )
        pm = await adapter._to_platform_message(msg)
        assert pm.message_type == MessageType.IMAGE

        # Test video attachment
        msg.attachments = [SignalAttachment(content_type="video/mp4")]
        pm = await adapter._to_platform_message(msg)
        assert pm.message_type == MessageType.VIDEO

        # Test audio attachment
        msg.attachments = [SignalAttachment(content_type="audio/ogg")]
        pm = await adapter._to_platform_message(msg)
        assert pm.message_type == MessageType.AUDIO

        # Test document attachment (unknown type)
        msg.attachments = [SignalAttachment(content_type="application/pdf")]
        pm = await adapter._to_platform_message(msg)
        assert pm.message_type == MessageType.DOCUMENT

        # Test multiple attachments (takes first)
        msg.attachments = [
            SignalAttachment(content_type="image/png"),
            SignalAttachment(content_type="video/mp4"),
        ]
        pm = await adapter._to_platform_message(msg)
        assert pm.message_type == MessageType.IMAGE

    @pytest.mark.asyncio
    async def test_to_platform_message_group_handling(self, adapter):
        """Test group message handling in platform conversion"""
        msg = SignalMessage(
            id="1",
            source="+123",
            timestamp=1234567890,
            content="group message",
            group_info={"id": "group123", "name": "Test Group"},
        )
        pm = await adapter._to_platform_message(msg)
        assert pm.chat_id == "group_group123"
        assert "[Group]" in pm.content

    @pytest.mark.asyncio
    async def test_shutdown_partial_failure(self, adapter):
        """Test shutdown with partial failures"""
        adapter.process = MagicMock()
        adapter.process.terminate = MagicMock()
        adapter.process.wait = AsyncMock(side_effect=Exception("terminate failed"))

        async def dummy_task():
            await asyncio.sleep(1)

        adapter.reader_task = asyncio.create_task(dummy_task())
        adapter.reader_task.cancel()  # Cancel it so await raises CancelledError

        # Should not raise exception despite failures
        await adapter.shutdown()
        assert adapter.process is None
        assert adapter.reader_task is None

    @pytest.mark.asyncio
    async def test_send_receipt(self, adapter):
        """Test sending delivery/read receipts"""
        with patch.object(adapter, "_send_json_rpc", new_callable=AsyncMock) as mock_rpc:
            mock_rpc.return_value = True

            # Test successful receipt
            result = await adapter.send_receipt("+1234567890", ["signal_123", "signal_456"], "read")
            assert result is True
            mock_rpc.assert_called_once_with(
                "sendReceipt",
                {
                    "recipient": "+1234567890",
                    "type": "read",
                    "timestamps": [123, 456],
                },
            )

            # Test failure
            mock_rpc.return_value = None
            assert await adapter.send_receipt("+1234567890", ["signal_123"]) is False

    @pytest.mark.asyncio
    async def test_add_contact_exception_handling(self, adapter):
        """Test add_contact exception handling"""
        with patch.object(adapter, "_send_json_rpc", new_callable=AsyncMock) as mock_rpc:
            mock_rpc.side_effect = Exception("RPC error")

            result = await adapter.add_contact("+999", "Test Contact")
            assert result is False
            # Should not have added to cache
            assert "+999" not in adapter.registered_numbers

    @pytest.mark.asyncio
    async def test_block_contact_exception_handling(self, adapter):
        """Test block_contact exception handling"""
        with patch.object(adapter, "_send_json_rpc", new_callable=AsyncMock) as mock_rpc:
            mock_rpc.side_effect = Exception("RPC error")

            result = await adapter.block_contact("+999")
            assert result is False
            # Should not have added to cache
            assert "+999" not in adapter.blocked_numbers

    @pytest.mark.asyncio
    async def test_unblock_contact_exception_handling(self, adapter):
        """Test unblock_contact exception handling"""
        with patch.object(adapter, "_send_json_rpc", new_callable=AsyncMock) as mock_rpc:
            mock_rpc.side_effect = Exception("RPC error")

            result = await adapter.unblock_contact("+999")
            assert result is False

    @pytest.mark.asyncio
    async def test_register_exception_handling(self, adapter):
        """Test register exception handling"""
        with patch.object(adapter, "_send_json_rpc", new_callable=AsyncMock) as mock_rpc:
            mock_rpc.side_effect = Exception("RPC error")

            result = await adapter.register(voice=True)
            assert result is False

    @pytest.mark.asyncio
    async def test_verify_exception_handling(self, adapter):
        """Test verify exception handling"""
        with patch.object(adapter, "_send_json_rpc", new_callable=AsyncMock) as mock_rpc:
            mock_rpc.side_effect = Exception("RPC error")

            result = await adapter.verify("123456")
            assert result is False

    @pytest.mark.asyncio
    async def test_send_profile(self, adapter):
        """Test profile updates"""
        with patch.object(adapter, "_send_json_rpc", new_callable=AsyncMock) as mock_rpc:
            mock_rpc.return_value = True

            result = await adapter.send_profile(name="Test Bot", avatar_path="/tmp/avatar.jpg", about="Test bot")
            assert result is True
            mock_rpc.assert_called_once_with(
                "updateProfile",
                {
                    "number": "+123",
                    "name": "Test Bot",
                    "avatar": "/tmp/avatar.jpg",
                    "about": "Test bot",
                },
            )

    @pytest.mark.asyncio
    async def test_upload_attachment(self, adapter):
        """Test attachment uploads"""
        with patch.object(adapter, "_send_json_rpc", new_callable=AsyncMock) as mock_rpc:
            mock_rpc.return_value = "attachment_123"

            result = await adapter.upload_attachment("/tmp/test.jpg")
            assert result == "attachment_123"
            mock_rpc.assert_called_once_with("uploadAttachment", {"file": "/tmp/test.jpg"})

    @pytest.mark.asyncio
    async def test_send_note_to_self(self, adapter):
        """Test sending notes to self"""
        with patch.object(adapter, "send_message", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = "msg_123"

            result = await adapter.send_note_to_self("Test note")
            assert result == "msg_123"
            mock_send.assert_called_once_with(recipient="+123", message="Test note")

    @pytest.mark.asyncio
    async def test_mark_read(self, adapter):
        """Test marking messages as read"""
        with patch.object(adapter, "send_receipt", new_callable=AsyncMock) as mock_receipt:
            mock_receipt.return_value = True

            result = await adapter.mark_read(["msg_1", "msg_2"])
            assert result is True
            mock_receipt.assert_called_once_with(recipient="+123", message_ids=["msg_1", "msg_2"], receipt_type="read")

    @pytest.mark.asyncio
    async def test_signal_message_types_read_delivered_session_reset(self):
        """Test SignalMessage parsing for read, delivered, and sessionReset types"""
        # Test read message type
        read_data = {
            "envelopeId": "read_123",
            "source": "+1234567890",
            "timestamp": 1234567890,
            "type": "read",
        }
        msg = SignalMessage.from_dict(read_data)
        assert msg.message_type == SignalMessageType.READ
        assert msg.is_receipt is True

        # Test delivered message type
        delivered_data = {
            "envelopeId": "delivered_123",
            "source": "+1234567890",
            "timestamp": 1234567890,
            "type": "delivered",
        }
        msg = SignalMessage.from_dict(delivered_data)
        assert msg.message_type == SignalMessageType.DELIVERED
        assert msg.is_receipt is True

        # Test sessionReset message type
        reset_data = {
            "envelopeId": "reset_123",
            "source": "+1234567890",
            "timestamp": 1234567890,
            "type": "sessionReset",
        }
        msg = SignalMessage.from_dict(reset_data)
        assert msg.message_type == SignalMessageType.SESSION_RESET
        assert msg.is_receipt is False

    @pytest.mark.asyncio
    async def test_start_daemon(self, adapter):
        """Test _start_daemon method"""
        mock_process = MagicMock()
        mock_process.returncode = None
        mock_process.communicate = AsyncMock(return_value=(b"", b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_create:
            await adapter._start_daemon()

            # Verify subprocess was created with correct args
            mock_create.assert_called_once()
            args, kwargs = mock_create.call_args
            assert "signal-cli" in args
            assert "daemon" in args
            assert "--socket" in args
            assert adapter.socket_path in args

            # Verify environment was set
            assert "SIGNAL_CLI_CONFIG" in kwargs["env"]

        # Test failure case
        mock_process.returncode = 1
        mock_process.communicate = AsyncMock(return_value=(b"", b"error"))
        with (
            patch("asyncio.create_subprocess_exec", return_value=mock_process),
            pytest.raises(Exception, match="signal-cli daemon failed"),
        ):
            await adapter._start_daemon()

    @pytest.mark.asyncio
    async def test_start_receive_process(self, adapter):
        """Test _start_receive_process method"""
        mock_process = MagicMock()
        mock_process.returncode = None

        # Mock stdout as AsyncMock and ensure readline returns empty bytes to stop the task
        mock_stdout = AsyncMock()
        mock_stdout.readline = AsyncMock(return_value=b"")  # Return empty bytes to stop reading
        mock_process.stdout = mock_stdout

        with patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_create:
            await adapter._start_receive_process()

            # Verify subprocess was created with correct args
            mock_create.assert_called_once()
            args, kwargs = mock_create.call_args
            assert "signal-cli" in args
            assert "receive" in args
            assert "--json" in args

            # Verify environment was set
            assert "SIGNAL_CLI_CONFIG" in kwargs["env"]

            # Verify reader task was created
            assert adapter.reader_task is not None

            # Clean up the task to prevent it from running in background
            if adapter.reader_task and not adapter.reader_task.done():
                adapter.reader_task.cancel()
                try:
                    await adapter.reader_task
                except asyncio.CancelledError:
                    pass

    @pytest.mark.asyncio
    async def test_read_messages(self, adapter):
        """Test _read_messages method"""
        # Mock stdout as AsyncMock
        mock_stdout = AsyncMock()
        mock_stdout.readline = AsyncMock()

        # First call returns data, second returns empty (EOF)
        mock_stdout.readline.side_effect = [
            json.dumps({"envelopeId": "1", "dataMessage": {"message": "test"}}).encode() + b"\n",
            b"",
        ]

        adapter.process = MagicMock()
        adapter.process.stdout = mock_stdout

        # Mock _handle_message to avoid full processing
        with patch.object(adapter, "_handle_message", new_callable=AsyncMock) as mock_handle:
            await adapter._read_messages()

            # Verify message was handled
            mock_handle.assert_called_once()
            args = mock_handle.call_args[0][0]
            assert args["envelopeId"] == "1"
            assert "dataMessage" in args

    @pytest.mark.asyncio
    async def test_update_group_full_params(self, adapter):
        """Test update_group with all parameters"""
        with patch.object(adapter, "_send_json_rpc", new_callable=AsyncMock) as mock_rpc:
            mock_rpc.return_value = True

            result = await adapter.update_group(
                group_id="test_group",
                name="New Name",
                description="New Description",
                avatar_path="/tmp/avatar.jpg",
                members_to_add=["+111", "+222"],
                members_to_remove=["+333"],
                set_admin=["+111"],
                remove_admin=["+444"],
            )

            assert result is True
            mock_rpc.assert_called_once_with(
                "updateGroup",
                {
                    "groupId": "test_group",
                    "name": "New Name",
                    "description": "New Description",
                    "avatar": "/tmp/avatar.jpg",
                    "addMembers": ["+111", "+222"],
                    "removeMembers": ["+333"],
                    "setAdmin": ["+111"],
                    "removeAdmin": ["+444"],
                },
            )

    @pytest.mark.asyncio
    async def test_leave_group_error_handling(self, adapter):
        """Test leave_group with error handling"""
        with patch.object(adapter, "_send_json_rpc", new_callable=AsyncMock) as mock_rpc:
            mock_rpc.return_value = True

            result = await adapter.leave_group("test_group")
            assert result is True
            mock_rpc.assert_called_once_with("leaveGroup", {"groupId": "test_group"})

            # Test failure
            mock_rpc.return_value = None
            result = await adapter.leave_group("test_group")
            assert result is False

    @pytest.mark.asyncio
    async def test_get_group_exception_handling(self, adapter):
        """Test get_group exception handling"""
        with patch.object(adapter, "_send_json_rpc", new_callable=AsyncMock) as mock_rpc:
            mock_rpc.side_effect = Exception("RPC error")

            result = await adapter.get_group("test_group")
            assert result is None

    @pytest.mark.asyncio
    async def test_load_groups_and_contacts_rpc_calls(self, adapter):
        """Test _load_groups and _load_contacts RPC calls"""
        with patch.object(adapter, "_send_json_rpc", new_callable=AsyncMock) as mock_rpc:
            # Test _load_groups
            mock_rpc.return_value = [
                {"id": "g1", "name": "Group 1"},
                {"id": "g2", "name": "Group 2"},
            ]
            await adapter._load_groups()
            mock_rpc.assert_called_with("listGroups", {})

            # Test _load_contacts
            mock_rpc.return_value = [
                {"number": "+111"},
                {"number": "+222"},
            ]
            await adapter._load_contacts()
            mock_rpc.assert_called_with("listContacts", {})

    @pytest.mark.asyncio
    async def test_add_contact_cache_update(self, adapter):
        """Test add_contact cache update"""
        with patch.object(adapter, "_send_json_rpc", new_callable=AsyncMock) as mock_rpc:
            mock_rpc.return_value = True

            result = await adapter.add_contact("+999", "New Contact")
            assert result is True
            assert "+999" in adapter.registered_numbers

            # Test without result
            mock_rpc.return_value = None
            result = await adapter.add_contact("+888")
            assert result is False
            assert "+888" not in adapter.registered_numbers

    @pytest.mark.asyncio
    async def test_block_unblock_contact_cache_updates(self, adapter):
        """Test block_contact and unblock_contact cache updates"""
        with patch.object(adapter, "_send_json_rpc", new_callable=AsyncMock) as mock_rpc:
            mock_rpc.return_value = True

            # Test block
            result = await adapter.block_contact("+999")
            assert result is True
            assert "+999" in adapter.blocked_numbers

            # Test unblock
            result = await adapter.unblock_contact("+999")
            assert result is True
            assert "+999" not in adapter.blocked_numbers

    @pytest.mark.asyncio
    async def test_register_verify_rpc_calls(self, adapter):
        """Test register and verify RPC calls"""
        with patch.object(adapter, "_send_json_rpc", new_callable=AsyncMock) as mock_rpc:
            mock_rpc.return_value = True

            # Test register with voice
            result = await adapter.register(voice=True)
            assert result is True
            mock_rpc.assert_called_with("register", {"number": "+123", "voice": True})

            # Test verify
            result = await adapter.verify("123456")
            assert result is True
            mock_rpc.assert_called_with("verify", {"number": "+123", "code": "123456"})

    @pytest.mark.asyncio
    async def test_send_profile_rpc_call(self, adapter):
        """Test send_profile RPC call"""
        with patch.object(adapter, "_send_json_rpc", new_callable=AsyncMock) as mock_rpc:
            mock_rpc.return_value = True

            result = await adapter.send_profile(name="Bot Name", avatar_path="/tmp/avatar.png", about="Bot description")
            assert result is True
            mock_rpc.assert_called_with(
                "updateProfile",
                {
                    "number": "+123",
                    "name": "Bot Name",
                    "avatar": "/tmp/avatar.png",
                    "about": "Bot description",
                },
            )

    @pytest.mark.asyncio
    async def test_send_profile_exception_handling(self, adapter):
        """Test send_profile exception handling"""
        with patch.object(adapter, "_send_json_rpc", new_callable=AsyncMock) as mock_rpc:
            mock_rpc.side_effect = Exception("RPC error")

            result = await adapter.send_profile(name="Test Bot")
            assert result is False

    @pytest.mark.asyncio
    async def test_upload_attachment_exception_handling(self, adapter):
        """Test upload_attachment exception handling"""
        with patch.object(adapter, "_send_json_rpc") as mock_rpc:
            mock_rpc.side_effect = Exception("RPC error")

            result = await adapter.upload_attachment("/tmp/test.jpg")
            assert result is None

    @pytest.mark.asyncio
    async def test_handle_webhook_exception_handling(self, adapter):
        """Test handle_webhook exception handling"""
        with patch(
            "megabot.adapters.signal_adapter.SignalMessage.from_dict",
            side_effect=Exception("parse error"),
        ):
            # Test with dataMessage that causes exception
            webhook_data = {
                "envelopeId": "webhook_123",
                "dataMessage": {"message": "test"},
            }

            result = await adapter.handle_webhook(webhook_data)
            assert result is None  # Should return None on exception

        # Test general exception
        with patch.object(adapter, "_to_platform_message", side_effect=Exception("conversion error")):
            webhook_data = {
                "envelopeId": "webhook_456",
                "dataMessage": {"message": "test"},
            }

            result = await adapter.handle_webhook(webhook_data)
            assert result is None  # Should return None on exception

    @pytest.mark.asyncio
    async def test_send_json_rpc_mode_selection(self, adapter):
        """Test _send_json_rpc mode selection"""
        # Test socket mode
        adapter.receive_mode = "socket"
        with patch.object(adapter, "_send_socket_rpc", new_callable=AsyncMock) as mock_socket:
            mock_socket.return_value = "socket_result"
            result = await adapter._send_json_rpc("test", {})
            assert result == "socket_result"
            mock_socket.assert_called_once_with("test", {})

        # Test stdout mode
        adapter.receive_mode = "stdout"
        with patch.object(adapter, "_send_stdout_rpc", new_callable=AsyncMock) as mock_stdout:
            mock_stdout.return_value = "stdout_result"
            result = await adapter._send_json_rpc("test", {})
            assert result == "stdout_result"
            mock_stdout.assert_called_once_with("test", {})

    @pytest.mark.asyncio
    async def test_send_stdout_rpc_return_none_case(self, adapter):
        """Test _send_stdout_rpc return None case"""
        adapter.receive_mode = "stdout"
        adapter.process = MagicMock()
        adapter.process.stdin = MagicMock()
        adapter.process.stdin.write = MagicMock()
        adapter.process.stdin.drain = AsyncMock()
        adapter.process.stdout = AsyncMock()
        adapter.process.stdout.readline = AsyncMock(return_value=b"")

        result = await adapter._send_stdout_rpc("test", {})
        assert result is None

    @pytest.mark.asyncio
    async def test_send_message_quote_parsing_errors(self, adapter):
        """Test send_message quote parsing with invalid inputs"""
        with patch.object(adapter, "_send_json_rpc", new_callable=AsyncMock) as mock_rpc:
            mock_rpc.return_value = {"envelopeId": "quote_test"}

            # Test with invalid quote ID (no underscore)
            result = await adapter.send_message("recipient", "message", quote_message_id="invalid_quote_id")
            assert result == "quote_test"
            # Should not have quote parameter
            call_args = mock_rpc.call_args[0]
            params = call_args[1]
            assert "quote" not in params

            # Test with malformed quote ID
            result = await adapter.send_message("recipient", "message", quote_message_id="signal_abc")
            assert result == "quote_test"
            # Should not have quote parameter due to ValueError
            call_args = mock_rpc.call_args[0]
            params = call_args[1]
            assert "quote" not in params

    @pytest.mark.asyncio
    async def test_send_reaction_full_method(self, adapter):
        """Test send_reaction full method execution"""
        with patch.object(adapter, "_send_json_rpc", new_callable=AsyncMock) as mock_rpc:
            mock_rpc.return_value = True

            result = await adapter.send_reaction("recipient", "😊", "author", 1234567890)
            assert result is True

            mock_rpc.assert_called_once_with(
                "react",
                {
                    "recipient": "recipient",
                    "emoji": "😊",
                    "targetAuthor": "author",
                    "targetTimestamp": 1234567890,
                },
            )

    @pytest.mark.asyncio
    async def test_send_receipt_timestamp_parsing_errors(self, adapter):
        """Test send_receipt timestamp parsing with invalid message IDs"""
        with patch.object(adapter, "_send_json_rpc", new_callable=AsyncMock) as mock_rpc:
            mock_rpc.return_value = True

            # Test with invalid message IDs (no numbers after underscore)
            result = await adapter.send_receipt("recipient", ["invalid_msg", "another_invalid"], "read")
            assert result is True

            # Verify timestamps list is empty due to parsing failures
            call_args = mock_rpc.call_args[0]
            params = call_args[1]
            assert params["timestamps"] == []

            # Test with malformed message IDs
            result = await adapter.send_receipt("recipient", ["signal_abc", "signal_xyz"], "read")
            assert result is True

            # Should have empty timestamps due to ValueError/IndexError
            call_args = mock_rpc.call_args[0]
            params = call_args[1]
            assert params["timestamps"] == []

    @pytest.mark.asyncio
    async def test_update_group_exception_handling(self, adapter):
        """Test update_group exception handling"""
        with patch.object(adapter, "_send_json_rpc", new_callable=AsyncMock) as mock_rpc:
            mock_rpc.side_effect = Exception("RPC error")

            result = await adapter.update_group("test_group", name="New Name")
            assert result is False

    @pytest.mark.asyncio
    async def test_leave_group_exception_handling(self, adapter):
        """Test leave_group exception handling"""
        with patch.object(adapter, "_send_json_rpc", new_callable=AsyncMock) as mock_rpc:
            mock_rpc.side_effect = Exception("RPC error")

            result = await adapter.leave_group("test_group")
            assert result is False

    @pytest.mark.asyncio
    async def test_handle_message_exception_handling(self, adapter):
        """Test _handle_message exception handling in handlers"""
        # Mock handlers that raise exceptions
        msg_handler = AsyncMock(side_effect=Exception("msg error"))
        ty_handler = AsyncMock(side_effect=Exception("ty error"))
        re_handler = AsyncMock(side_effect=Exception("re error"))

        adapter.register_message_handler(msg_handler)
        adapter.register_reaction_handler(ty_handler)
        adapter.register_receipt_handler(re_handler)

        # Test message handler exception
        await adapter._handle_message({"envelopeId": "1", "dataMessage": {"message": "test"}})

        # Test typing handler exception
        await adapter._handle_message({"typing": {}})

        # Test receipt handler exception
        await adapter._handle_message({"type": "read"})

        # Handlers should have been called despite exceptions
        msg_handler.assert_called_once()
        ty_handler.assert_called_once()
        re_handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_initialize_load_exceptions(self, adapter):
        """Test initialize with load method exceptions"""
        with (
            patch.object(adapter, "_start_daemon", new_callable=AsyncMock) as mock_daemon,
            patch.object(
                adapter,
                "_load_groups",
                new_callable=AsyncMock,
                side_effect=Exception("load groups failed"),
            ) as mock_load_groups,
            patch.object(
                adapter,
                "_load_contacts",
                new_callable=AsyncMock,
                side_effect=Exception("load contacts failed"),
            ) as mock_load_contacts,
        ):
            # Should still succeed despite load failures
            result = await adapter.initialize()
            assert result is True
            assert adapter.is_initialized is True

    @pytest.mark.asyncio
    async def test_read_messages_json_error_handling(self, adapter):
        """Test _read_messages with JSON decode error"""
        mock_stdout = AsyncMock()
        mock_stdout.readline = AsyncMock()

        # First call returns invalid JSON, second returns valid data, third returns empty
        mock_stdout.readline.side_effect = [
            b"invalid json\n",
            json.dumps({"envelopeId": "2", "dataMessage": {"message": "test"}}).encode() + b"\n",
            b"",
        ]

        adapter.process = MagicMock()
        adapter.process.stdout = mock_stdout

        with patch.object(adapter, "_handle_message", new_callable=AsyncMock) as mock_handle:
            await adapter._read_messages()

            # Should have handled the valid message despite the invalid JSON
            mock_handle.assert_called_once()

    @pytest.mark.asyncio
    async def test_signal_message_typing_type_parsing(self):
        """Test SignalMessage.from_dict with typing type"""
        typing_data = {
            "envelopeId": "typing_123",
            "source": "+1234567890",
            "timestamp": 1234567890,
            "type": "typing",
        }
        msg = SignalMessage.from_dict(typing_data)
        assert msg.message_type == SignalMessageType.TYPING
        assert msg.is_receipt is False

    @pytest.mark.asyncio
    async def test_register_error_handler_coverage(self, adapter):
        """Test register_error_handler method"""

        def test_handler(error):
            pass

        # Should not raise exception
        adapter.register_error_handler(test_handler)
        assert test_handler in adapter.error_handlers

    @pytest.mark.asyncio
    async def test_handle_webhook_no_data_message(self, adapter):
        """Test handle_webhook returns None when no dataMessage"""
        # Test various non-dataMessage scenarios
        result = await adapter.handle_webhook({"envelopeId": "test", "typing": {}})
        assert result is None

        result = await adapter.handle_webhook({"envelopeId": "test", "type": "read"})
        assert result is None

        result = await adapter.handle_webhook({"envelopeId": "test"})
        assert result is None

    @pytest.mark.asyncio
    async def test_read_messages_early_return(self, adapter):
        """Test _read_messages early return when process.stdout is None"""
        # Test case where process.stdout is None
        adapter.process = MagicMock()
        adapter.process.stdout = None

        # Should return early without error
        await adapter._read_messages()

        # Test case where process is None
        adapter.process = None
        await adapter._read_messages()

    @pytest.mark.asyncio
    async def test_create_group_exception_handling(self, adapter):
        """Test create_group exception handling"""
        with patch.object(adapter, "_send_json_rpc", new_callable=AsyncMock) as mock_rpc:
            mock_rpc.side_effect = Exception("RPC error")

            result = await adapter.create_group("Test Group", ["+111", "+222"])
            assert result is None


@pytest.mark.asyncio
async def test_signal_adapter_gaps_more():
    adapter = SignalAdapter(phone_number="+1", socket_path="/tmp/sig")
    adapter.process = MagicMock()
    adapter.process.stdout.readline = AsyncMock(side_effect=asyncio.CancelledError)
    await adapter._read_messages()

    # 1. _send_socket_rpc exception (510-512)
    adapter.receive_mode = "socket"
    with patch("asyncio.open_unix_connection", side_effect=Exception("Socket fail")):
        assert await adapter._send_json_rpc("method", {}) is None

    # 2. send_receipt exception (654-656)
    with patch.object(adapter, "_send_json_rpc", side_effect=Exception("Receipt fail")):
        assert await adapter.send_receipt("recipient", ["msg_1"]) is False

    # 3. create_group returns None (698)
    with patch.object(adapter, "_send_json_rpc", AsyncMock(return_value=None)):
        assert await adapter.create_group("name", ["+1"]) is None

    # 4. get_group result check (786-789)
    with patch.object(
        adapter,
        "_send_json_rpc",
        AsyncMock(return_value={"id": "new_g1", "name": "G1", "members": []}),
    ):
        group = await adapter.get_group("new_g1")
        assert group.id == "new_g1"

    # 5. _load_groups exception (802-803)
    with patch.object(adapter, "_send_json_rpc", side_effect=Exception("Load fail")):
        await adapter._load_groups()

    # 6. _load_contacts exception (813-814)
    with patch.object(adapter, "_send_json_rpc", side_effect=Exception("Load fail")):
        await adapter._load_contacts()

    assert adapter._generate_id() is not None

    from megabot.adapters.signal_adapter import main as signal_main

    with (
        patch(
            "megabot.adapters.signal_adapter.SignalAdapter.initialize",
            AsyncMock(return_value=True),
        ),
        patch("megabot.adapters.signal_adapter.SignalAdapter.send_message", AsyncMock()),
        patch("asyncio.sleep", AsyncMock(side_effect=[None, asyncio.CancelledError])),
    ):
        try:
            await signal_main()
        except asyncio.CancelledError:
            pass
