from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from megabot.adapters.messaging.telegram import TelegramAdapter


@pytest.fixture
def telegram_adapter():
    return TelegramAdapter("test_token", MagicMock())


class TestTelegramAdapter:
    @pytest.mark.asyncio
    async def test_send_text_success(self, telegram_adapter):
        """Test send_text with successful response"""
        with patch.object(telegram_adapter, "_make_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"message_id": 123}
            result = await telegram_adapter.send_text("chat123", "Hello world")

            assert result is not None
            assert result.id == "123"
            assert result.platform == "telegram"
            assert result.sender_id == "megabot"
            assert result.chat_id == "chat123"
            assert result.content == "Hello world"

    @pytest.mark.asyncio
    async def test_send_text_failure(self, telegram_adapter):
        """Test send_text with failed response"""
        with patch.object(telegram_adapter, "_make_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = None
            result = await telegram_adapter.send_text("chat123", "Hello world")

            assert result is not None
            assert result.platform == "telegram"
            assert result.sender_id == "megabot"
            assert result.chat_id == "chat123"
            assert result.content == "Hello world"

    @pytest.mark.asyncio
    async def test_send_photo(self, telegram_adapter):
        """Test send_photo method"""
        with patch.object(telegram_adapter, "_make_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"message_id": 456}
            result = await telegram_adapter.send_photo("chat123", "photo.jpg", caption="Test photo")

            mock_req.assert_called_once_with(
                "sendPhoto",
                {"chat_id": "chat123", "photo": "photo.jpg", "caption": "Test photo"},
            )

    @pytest.mark.asyncio
    async def test_send_document(self, telegram_adapter):
        """Test send_document method"""
        with patch.object(telegram_adapter, "_make_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"message_id": 789}
            result = await telegram_adapter.send_document("chat123", "doc.pdf")

            mock_req.assert_called_once_with("sendDocument", {"chat_id": "chat123", "document": "doc.pdf"})

    @pytest.mark.asyncio
    async def test_send_contact(self, telegram_adapter):
        """Test send_contact method"""
        with patch.object(telegram_adapter, "_make_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"message_id": 151}
            result = await telegram_adapter.send_contact("chat123", "+1234567890", "John")

            mock_req.assert_called_once_with(
                "sendContact",
                {
                    "chat_id": "chat123",
                    "phone_number": "+1234567890",
                    "first_name": "John",
                },
            )

    @pytest.mark.asyncio
    async def test_send_poll(self, telegram_adapter):
        """Test send_poll method"""
        with patch.object(telegram_adapter, "_make_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"message_id": 161}
            result = await telegram_adapter.send_poll("chat123", "What's your favorite?", ["A", "B", "C"])

            mock_req.assert_called_once_with(
                "sendPoll",
                {
                    "chat_id": "chat123",
                    "question": "What's your favorite?",
                    "options": ["A", "B", "C"],
                },
            )

    @pytest.mark.asyncio
    async def test_edit_message_text(self, telegram_adapter):
        """Test edit_message_text method"""
        with patch.object(telegram_adapter, "_make_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"message_id": 171}
            result = await telegram_adapter.edit_message_text("chat123", 123, "Updated text")

            mock_req.assert_called_once_with(
                "editMessageText",
                {"chat_id": "chat123", "message_id": 123, "text": "Updated text"},
            )

    @pytest.mark.asyncio
    async def test_delete_message(self, telegram_adapter):
        """Test delete_message method"""
        with patch.object(telegram_adapter, "_make_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"ok": True}
            result = await telegram_adapter.delete_message("chat123", 123)

            assert result is True
            mock_req.assert_called_once_with("deleteMessage", {"chat_id": "chat123", "message_id": 123})

    @pytest.mark.asyncio
    async def test_delete_message_failure(self, telegram_adapter):
        """Test delete_message method with failure"""
        with patch.object(telegram_adapter, "_make_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = None
            result = await telegram_adapter.delete_message("chat123", 123)

            assert result is False

    @pytest.mark.asyncio
    async def test_answer_callback_query(self, telegram_adapter):
        """Test answer_callback_query method"""
        with patch.object(telegram_adapter, "_make_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"ok": True}
            result = await telegram_adapter.answer_callback_query("query123", text="Answered")

            assert result is True
            mock_req.assert_called_once_with(
                "answerCallbackQuery",
                {"callback_query_id": "query123", "text": "Answered"},
            )

    @pytest.mark.asyncio
    async def test_create_chat_invite_link(self, telegram_adapter):
        """Test create_chat_invite_link method"""
        with patch.object(telegram_adapter, "_make_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"invite_link": "https://t.me/joinchat/abc123"}
            result = await telegram_adapter.create_chat_invite_link("chat123")

            mock_req.assert_called_once_with("createChatInviteLink", {"chat_id": "chat123"})

    @pytest.mark.asyncio
    async def test_export_chat_invite_link(self, telegram_adapter):
        """Test export_chat_invite_link method"""
        with patch.object(telegram_adapter, "_make_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"invite_link": "https://t.me/joinchat/def456"}
            result = await telegram_adapter.export_chat_invite_link("chat123")

            mock_req.assert_called_once_with("exportChatInviteLink", {"chat_id": "chat123"})

    @pytest.mark.asyncio
    async def test_get_chat(self, telegram_adapter):
        """Test get_chat method"""
        with patch.object(telegram_adapter, "_make_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"id": 123, "type": "group"}
            result = await telegram_adapter.get_chat("chat123")

            mock_req.assert_called_once_with("getChat", {"chat_id": "chat123"})

    @pytest.mark.asyncio
    async def test_get_chat_administrators(self, telegram_adapter):
        """Test get_chat_administrators method"""
        with patch.object(telegram_adapter, "_make_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = [{"user": {"id": 1}, "status": "creator"}]
            result = await telegram_adapter.get_chat_administrators("chat123")

            assert result == [{"user": {"id": 1}, "status": "creator"}]
            mock_req.assert_called_once_with("getChatAdministrators", {"chat_id": "chat123"})

    @pytest.mark.asyncio
    async def test_get_chat_administrators_failure(self, telegram_adapter):
        """Test get_chat_administrators method with failure"""
        with patch.object(telegram_adapter, "_make_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = None
            result = await telegram_adapter.get_chat_administrators("chat123")

            assert result == []

    @pytest.mark.asyncio
    async def test_get_chat_members_count(self, telegram_adapter):
        """Test get_chat_members_count method"""
        with patch.object(telegram_adapter, "_make_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = 150
            result = await telegram_adapter.get_chat_members_count("chat123")

            assert result == 150
            mock_req.assert_called_once_with("getChatMembersCount", {"chat_id": "chat123"})

    @pytest.mark.asyncio
    async def test_get_chat_members_count_failure(self, telegram_adapter):
        """Test get_chat_members_count method with failure"""
        with patch.object(telegram_adapter, "_make_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = None
            result = await telegram_adapter.get_chat_members_count("chat123")

            assert result == 0

    @pytest.mark.asyncio
    async def test_get_chat_member(self, telegram_adapter):
        """Test get_chat_member method"""
        with patch.object(telegram_adapter, "_make_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"user": {"id": 123}, "status": "member"}
            result = await telegram_adapter.get_chat_member("chat123", 123)

            mock_req.assert_called_once_with("getChatMember", {"chat_id": "chat123", "user_id": 123})

    @pytest.mark.asyncio
    async def test_ban_chat_member(self, telegram_adapter):
        """Test ban_chat_member method"""
        with patch.object(telegram_adapter, "_make_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"ok": True}
            result = await telegram_adapter.ban_chat_member("chat123", 123)

            assert result is True
            mock_req.assert_called_once_with("banChatMember", {"chat_id": "chat123", "user_id": 123})

    @pytest.mark.asyncio
    async def test_ban_chat_member_failure(self, telegram_adapter):
        """Test ban_chat_member method with failure"""
        with patch.object(telegram_adapter, "_make_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = None
            result = await telegram_adapter.ban_chat_member("chat123", 123)

            assert result is False

    @pytest.mark.asyncio
    async def test_unban_chat_member(self, telegram_adapter):
        """Test unban_chat_member method"""
        with patch.object(telegram_adapter, "_make_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"ok": True}
            result = await telegram_adapter.unban_chat_member("chat123", 123)

            assert result is True
            mock_req.assert_called_once_with("unbanChatMember", {"chat_id": "chat123", "user_id": 123})

    @pytest.mark.asyncio
    async def test_restrict_chat_member(self, telegram_adapter):
        """Test restrict_chat_member method"""
        with patch.object(telegram_adapter, "_make_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"ok": True}
            permissions = {"can_send_messages": False}
            result = await telegram_adapter.restrict_chat_member("chat123", 123, permissions)

            assert result is True
            mock_req.assert_called_once_with(
                "restrictChatMember",
                {"chat_id": "chat123", "user_id": 123, "permissions": permissions},
            )

    @pytest.mark.asyncio
    async def test_promote_chat_member(self, telegram_adapter):
        """Test promote_chat_member method"""
        with patch.object(telegram_adapter, "_make_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"ok": True}
            result = await telegram_adapter.promote_chat_member("chat123", 123, can_manage_chat=True)

            assert result is True
            mock_req.assert_called_once_with(
                "promoteChatMember",
                {"chat_id": "chat123", "user_id": 123, "can_manage_chat": True},
            )

    @pytest.mark.asyncio
    async def test_pin_chat_message(self, telegram_adapter):
        """Test pin_chat_message method"""
        with patch.object(telegram_adapter, "_make_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"ok": True}
            result = await telegram_adapter.pin_chat_message("chat123", 123)

            assert result is True
            mock_req.assert_called_once_with("pinChatMessage", {"chat_id": "chat123", "message_id": 123})

    @pytest.mark.asyncio
    async def test_unpin_chat_message(self, telegram_adapter):
        """Test unpin_chat_message method"""
        with patch.object(telegram_adapter, "_make_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"ok": True}
            result = await telegram_adapter.unpin_chat_message("chat123")

            assert result is True
            mock_req.assert_called_once_with("unpinChatMessage", {"chat_id": "chat123"})

    @pytest.mark.asyncio
    async def test_leave_chat(self, telegram_adapter):
        """Test leave_chat method"""
        with patch.object(telegram_adapter, "_make_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"ok": True}
            result = await telegram_adapter.leave_chat("chat123")

            assert result is True
            mock_req.assert_called_once_with("leaveChat", {"chat_id": "chat123"})

    @pytest.mark.asyncio
    async def test_get_me(self, telegram_adapter):
        """Test get_me method"""
        with patch.object(telegram_adapter, "_make_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"id": 123456, "username": "testbot"}
            result = await telegram_adapter.get_me()

            assert result == {"id": 123456, "username": "testbot"}
            mock_req.assert_called_once_with("getMe")

    @pytest.mark.asyncio
    async def test_get_me_exception(self, telegram_adapter):
        """Test get_me method with exception"""
        with patch.object(telegram_adapter, "_make_request", new_callable=AsyncMock) as mock_req:
            mock_req.side_effect = aiohttp.ClientError("Network error")
            result = await telegram_adapter.get_me()

            assert result is None

    @pytest.mark.asyncio
    async def test_get_updates(self, telegram_adapter):
        """Test get_updates method"""
        with patch.object(telegram_adapter, "_make_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = [{"update_id": 1}, {"update_id": 2}]
            result = await telegram_adapter.get_updates(offset=100)

            assert result == [{"update_id": 1}, {"update_id": 2}]
            mock_req.assert_called_once_with("getUpdates", {"offset": 100})

    @pytest.mark.asyncio
    async def test_get_updates_exception(self, telegram_adapter):
        """Test get_updates method with exception"""
        with patch.object(telegram_adapter, "_make_request", new_callable=AsyncMock) as mock_req:
            mock_req.side_effect = aiohttp.ClientError("Network error")
            result = await telegram_adapter.get_updates()

            assert result == []

    @pytest.mark.asyncio
    async def test_delete_webhook(self, telegram_adapter):
        """Test delete_webhook method"""
        with patch.object(telegram_adapter, "_make_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"ok": True}
            result = await telegram_adapter.delete_webhook()

            assert result is True
            mock_req.assert_called_once_with("deleteWebhook")

    @pytest.mark.asyncio
    async def test_delete_webhook_exception(self, telegram_adapter):
        """Test delete_webhook method with exception"""
        with patch.object(telegram_adapter, "_make_request", new_callable=AsyncMock) as mock_req:
            mock_req.side_effect = aiohttp.ClientError("Network error")
            result = await telegram_adapter.delete_webhook()

            assert result is False

    @pytest.mark.asyncio
    async def test_handle_webhook_valid(self, telegram_adapter):
        """Test handle_webhook with valid message data"""
        webhook_data = {
            "update_id": 123,
            "message": {
                "message_id": 456,
                "chat": {"id": 789},
                "from": {"id": 101112},
                "text": "Hello bot",
            },
        }
        result = await telegram_adapter.handle_webhook(webhook_data)

        assert result is not None
        assert result.id == "tg_456"
        assert result.platform == "telegram"
        assert result.sender_id == "101112"
        assert result.chat_id == "789"
        assert result.content == "Hello bot"

    @pytest.mark.asyncio
    async def test_handle_webhook_invalid(self, telegram_adapter):
        """Test handle_webhook with invalid data"""
        result = await telegram_adapter.handle_webhook({})
        assert result is None

    @pytest.mark.asyncio
    async def test_shutdown(self, telegram_adapter):
        """Test shutdown method"""
        # Create a mock session
        mock_session = AsyncMock()
        telegram_adapter.session = mock_session

        await telegram_adapter.shutdown()

        mock_session.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown_no_session(self, telegram_adapter):
        """Test shutdown method with no session"""
        telegram_adapter.session = None

        await telegram_adapter.shutdown()
        # Should not raise any exception

    @pytest.mark.asyncio
    async def test_forward_message(self, telegram_adapter):
        """Test forward_message method"""
        with patch.object(telegram_adapter, "_make_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"message_id": 123}
            result = await telegram_adapter.forward_message("chat123", "from_chat456", 789)

            mock_req.assert_called_once_with(
                "forwardMessage",
                {
                    "chat_id": "chat123",
                    "from_chat_id": "from_chat456",
                    "message_id": 789,
                },
            )

    @pytest.mark.asyncio
    async def test_handle_webhook_callback_query(self, telegram_adapter):
        """Test handle_webhook with callback_query data"""
        webhook_data = {
            "update_id": 123,
            "callback_query": {
                "id": "callback123",
                "from": {"id": 101112, "first_name": "TestUser"},
                "data": "button_clicked",
                "message": {
                    "message_id": 456,
                    "chat": {"id": 789},
                    "from": {"id": 101112},
                    "text": "Callback message",
                },
            },
        }
        with patch.object(telegram_adapter, "_make_request", new_callable=AsyncMock):
            result = await telegram_adapter.handle_webhook(webhook_data)

        assert result is not None
        assert result.id == "tg_cb_callback123"
        assert result.platform == "telegram"
        assert result.sender_id == "101112"
        assert result.chat_id == "789"
        assert result.content == "button_clicked"

    @pytest.mark.asyncio
    async def test_make_request_exception_path(self, telegram_adapter):
        """Test _make_request exception handling"""
        from unittest.mock import AsyncMock, MagicMock

        import aiohttp

        mock_session = MagicMock()
        telegram_adapter.session = mock_session

        # Mock the post method to raise aiohttp.ClientError (which _make_request catches)
        mock_cm = AsyncMock()
        mock_cm.__aenter__.side_effect = aiohttp.ClientError("Network error")
        mock_cm.__aexit__ = AsyncMock(return_value=None)
        mock_session.post.return_value = mock_cm

        result = await telegram_adapter._make_request("testMethod", {"param": "value"}, retries=1)

        assert result is None


class TestTelegramUploadMedia:
    """Tests for _upload_media file handle cleanup (Phase 6B-3 security fix)."""

    @pytest.mark.asyncio
    async def test_upload_media_closes_file_on_success(self, telegram_adapter, tmp_path):
        """Test that the file handle is closed after a successful upload."""
        test_file = tmp_path / "test.jpg"
        test_file.write_bytes(b"fake image data")

        mock_session = MagicMock()
        telegram_adapter.session = mock_session

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"ok": True, "result": {"file_id": "abc"}})

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_cm.__aexit__ = AsyncMock(return_value=None)
        mock_session.post.return_value = mock_cm

        mock_fh = MagicMock()
        mock_fh.close = MagicMock()

        with patch("builtins.open", return_value=mock_fh) as mock_open:
            result = await telegram_adapter._upload_media(
                "sendPhoto", "chat123", "photo", str(test_file), caption="test"
            )

            mock_open.assert_called_once_with(str(test_file), "rb")
            mock_fh.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_upload_media_closes_file_on_exception(self, telegram_adapter, tmp_path):
        """Test that the file handle is closed even when an exception occurs."""
        test_file = tmp_path / "test.jpg"
        test_file.write_bytes(b"fake image data")

        mock_session = MagicMock()
        telegram_adapter.session = mock_session

        # Make post() raise an exception
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(side_effect=aiohttp.ClientError("Network error"))
        mock_cm.__aexit__ = AsyncMock(return_value=None)
        mock_session.post.return_value = mock_cm

        mock_fh = MagicMock()
        mock_fh.close = MagicMock()

        with patch("builtins.open", return_value=mock_fh):
            result = await telegram_adapter._upload_media("sendPhoto", "chat123", "photo", str(test_file))

            assert result is None
            # File handle must still be closed via finally block
            mock_fh.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_upload_media_no_close_when_open_fails(self, telegram_adapter):
        """Test that no close is attempted when open() itself fails."""
        with patch("builtins.open", side_effect=FileNotFoundError("no such file")):
            result = await telegram_adapter._upload_media("sendPhoto", "chat123", "photo", "/nonexistent/file.jpg")
            # Should return None (caught by except block), no crash
            assert result is None
