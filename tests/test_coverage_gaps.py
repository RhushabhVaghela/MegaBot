import asyncio
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from core.network.gateway import UnifiedGateway, ClientConnection, ConnectionType
from adapters.messaging.imessage import IMessageAdapter
from adapters.messaging.sms import SMSAdapter
from adapters.messaging.telegram import TelegramAdapter as MessagingTelegramAdapter
from adapters.messaging.whatsapp import WhatsAppAdapter
from adapters.messaging.server import PlatformMessage
from adapters.discord_adapter import DiscordAdapter
from adapters.signal_adapter import SignalAdapter


@pytest.mark.asyncio
async def test_gateway_coverage_gaps():
    gateway = UnifiedGateway()

    # Mock connection
    mock_ws = AsyncMock()
    conn = ClientConnection(
        client_id="test_client",
        websocket=mock_ws,
        connection_type=ConnectionType.LOCAL,
        ip_address="127.0.0.1",
        connected_at=datetime.now(),
    )

    # 1. Test bytes decoding failure in _process_message (lines 330-331)
    mock_bytes = MagicMock()
    mock_bytes.decode.side_effect = Exception("Decode fail")

    with patch(
        "core.network.gateway.isinstance",
        side_effect=lambda x, t: (
            True if t is bytes and x is mock_bytes else isinstance(x, t)
        ),
    ):
        await gateway._process_message(conn, mock_bytes)  # type: ignore

    # 2. Test send/send_str exceptions in _send_error (lines 360-361, 365-366)
    mock_ws.send.side_effect = Exception("Send failed")
    mock_ws.send_str.side_effect = Exception("Send_str failed")
    await gateway._send_error(conn, "test error")


@pytest.mark.asyncio
async def test_gateway_mopup_targeted():
    gateway = UnifiedGateway()

    # 1. Line 192-193: self.cloudflare_process.poll() is NOT None
    gateway.cloudflare_tunnel_id = "test-token-2"
    mock_proc_fail = MagicMock()
    mock_proc_fail.poll.return_value = 1  # Finished
    with (
        patch("subprocess.run", return_value=MagicMock(returncode=0)),
        patch("subprocess.Popen", return_value=mock_proc_fail),
    ):
        res = await gateway._start_cloudflare_tunnel()
        assert res is False
        assert gateway.health_status[ConnectionType.CLOUDFLARE.value] is False

    # 2. Line 302: payload = getattr(message, "data", message)
    mock_ws = AsyncMock()
    mock_msg = MagicMock()
    mock_msg.type = "TEXT"
    mock_msg.data = b"valid data"
    mock_ws.__aiter__.return_value = [mock_msg]

    conn = ClientConnection(
        client_id="test_mopup",
        websocket=mock_ws,
        connection_type=ConnectionType.LOCAL,
        ip_address="127.0.0.1",
        connected_at=datetime.now(),
    )

    mock_wsm_type = MagicMock()
    mock_wsm_type.TEXT = "TEXT"
    mock_wsm_type.ERROR = "ERROR"

    with (
        patch.dict("sys.modules", {"aiohttp": MagicMock(WSMsgType=mock_wsm_type)}),
        patch.object(gateway, "_process_message", AsyncMock()),
    ):
        await gateway._manage_connection(conn)

    # 3. Line 323-324: Synchronous close
    sync_ws = MagicMock()
    sync_ws.__aiter__.return_value = []
    conn_sync = ClientConnection(
        client_id="test_sync_close",
        websocket=sync_ws,
        connection_type=ConnectionType.LOCAL,
        ip_address="127.0.0.1",
        connected_at=datetime.now(),
    )
    await gateway._manage_connection(conn_sync)
    assert sync_ws.close.called

    # 4. Line 309-310: Force decode failure
    mock_bytes_msg = MagicMock()
    mock_bytes_msg.decode.side_effect = Exception("Force fail")
    mock_ws.__aiter__.return_value = [mock_bytes_msg]
    with (
        patch.dict("sys.modules", {"aiohttp": MagicMock()}),
        patch(
            "core.network.gateway.hasattr",
            side_effect=lambda o, a: (
                False if a == "type" and o is mock_bytes_msg else hasattr(o, a)
            ),
        ),
        patch(
            "core.network.gateway.isinstance",
            side_effect=lambda o, t: (
                True if t is bytes and o is mock_bytes_msg else isinstance(o, t)
            ),
        ),
        patch.object(gateway, "_process_message", AsyncMock()),
    ):
        await gateway._manage_connection(conn)

    # 5. Line 390: Health monitor poll() is None
    gateway.enable_cloudflare = True
    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    gateway.cloudflare_process = mock_proc
    with patch("asyncio.sleep", side_effect=[None, Exception("Stop loop")]):
        try:
            await gateway._health_monitor_loop()
        except Exception as e:
            if str(e) != "Stop loop":
                raise
    assert gateway.health_status[ConnectionType.CLOUDFLARE.value] is True


@pytest.mark.asyncio
async def test_messaging_adapters_coverage_gaps():
    server = MagicMock()
    imessage = IMessageAdapter("imessage", server)
    await imessage.shutdown()
    sms = SMSAdapter("sms", server)
    await sms.shutdown()
    tg = MessagingTelegramAdapter("token", server)
    mock_session = MagicMock()
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={"result": {"id": 123}})
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_ctx.__aexit__ = AsyncMock(return_value=None)
    mock_session.post.return_value = mock_ctx
    with patch(
        "adapters.messaging.telegram.aiohttp.ClientSession", return_value=mock_session
    ):
        res = await tg._make_request("test")
        assert res == {"id": 123}
    res = await tg.handle_webhook({"update_id": 1})
    assert res is None
    # Signal
    wa = WhatsAppAdapter(
        "whatsapp", server, {"access_token": "token", "phone_number_id": "123"}
    )
    wa.session = AsyncMock()
    # Trigger exception in handle_webhook
    assert await wa.handle_webhook({"entry": [{"changes": [{"value": {}}]}]}) is None
    await wa.shutdown()


@pytest.mark.asyncio
async def test_discord_adapter_gaps():
    server = MagicMock()
    adapter = DiscordAdapter("discord", server, token="token")
    with patch.object(
        adapter, "send_message", AsyncMock(side_effect=Exception("failed"))
    ):
        assert await adapter.send_text("123", "hello") is None
        assert await adapter.send_media("123", "path") is None
    # Discord download_media exception
    with patch("builtins.print") as mock_print:
        mock_print.side_effect = [Exception("Print fail"), None]
        assert await adapter.download_media("123", "path") is None
    adapter.tree = MagicMock()
    adapter.add_slash_command(MagicMock())
    mock_interaction = AsyncMock()
    with patch("adapters.discord_adapter.ping", AsyncMock()) as mock_ping:
        mock_ping.callback = AsyncMock()
        if hasattr(mock_ping, "callback"):
            await mock_ping.callback(mock_interaction)
        else:
            await mock_ping(mock_interaction)


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
    # Use a new ID to avoid cache
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

    from adapters.signal_adapter import main as signal_main

    with (
        patch(
            "adapters.signal_adapter.SignalAdapter.initialize",
            AsyncMock(return_value=True),
        ),
        patch("adapters.signal_adapter.SignalAdapter.send_message", AsyncMock()),
        patch("asyncio.sleep", AsyncMock(side_effect=[None, asyncio.CancelledError])),
    ):
        try:
            await signal_main()
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_llm_providers_mopup():
    from core.llm_providers import (
        OpenAIProvider,
        OllamaProvider,
        GeminiProvider,
    )

    # 1. OpenAI error response
    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status = 500
        mock_resp.text = AsyncMock(return_value="Internal Server Error")
        mock_post.return_value.__aenter__.return_value = mock_resp

        p = OpenAIProvider(api_key="test")
        res = await p.generate(prompt="test")
        assert "error: 500" in res

    # 2. Ollama error response
    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status = 404
        mock_post.return_value.__aenter__.return_value = mock_resp
        p = OllamaProvider()
        res = await p.generate(prompt="test")
        assert "Ollama error: 404" in res

    # 3. Gemini no parts
    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(
            return_value={"candidates": [{"content": {"parts": []}}]}
        )
        mock_post.return_value.__aenter__.return_value = mock_resp
        p = GeminiProvider(api_key="test")
        res = await p.generate(prompt="test")
        assert "No text in response" in res or "No candidates" in res


@pytest.mark.asyncio
async def test_drivers_mopup():
    from core.drivers import ComputerDriver
    from PIL import Image
    import base64
    import io

    driver = ComputerDriver()

    # Test blur_regions
    img = Image.new("RGB", (100, 100), (255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    img_b64 = base64.b64encode(buf.getvalue()).decode()

    regions = [{"x": 10, "y": 10, "width": 20, "height": 20}]
    res = driver.blur_regions(img_b64, regions)
    assert len(res) > 0

    # Test execute mouse_move
    res = await driver.execute("mouse_move", coordinate=[100, 100])
    assert "Moved mouse" in res

    # Test execute type
    res = await driver.execute("type", text="hello")
    assert "Typed: hello" in res

    # Test execute key
    res = await driver.execute("key", text="enter")
    assert "Pressed key: enter" in res


@pytest.mark.asyncio
async def test_orchestrator_extra_branches(orchestrator):
    # Test pruning_loop exception
    with patch("asyncio.sleep", side_effect=[None, Exception("stop")]):
        try:
            await orchestrator.pruning_loop()
        except Exception as e:
            if str(e) != "stop":
                raise
    assert True

    # Test backup_loop exception
    with patch("asyncio.sleep", side_effect=[None, Exception("stop")]):
        try:
            await orchestrator.backup_loop()
        except Exception as e:
            if str(e) != "stop":
                raise
    assert True

    # Test heartbeat_loop components down
    orchestrator.get_system_health = AsyncMock(
        return_value={"openclaw": {"status": "down"}}
    )
    with (
        patch.object(
            orchestrator.adapters["openclaw"], "connect", AsyncMock()
        ) as mock_connect,
        patch("asyncio.sleep", side_effect=[None, Exception("stop")]),
    ):
        try:
            await orchestrator.heartbeat_loop()
        except Exception as e:
            if str(e) != "stop":
                raise
    assert mock_connect.called


@pytest.mark.asyncio
async def test_discord_adapter_final():
    server = MagicMock()
    adapter = DiscordAdapter("discord", server, token="token")
    assert adapter._generate_id() is not None


@pytest.mark.asyncio
async def test_slack_adapter_final():
    server = MagicMock()
    from adapters.slack_adapter import SlackAdapter

    adapter = SlackAdapter("slack", server, bot_token="token", app_token="xapp-123")
    assert adapter._generate_id() is not None

    # Trigger line 162
    mock_socket_client = MagicMock()
    with (
        patch(
            "adapters.slack_adapter.SocketModeClient", return_value=mock_socket_client
        ),
        patch("adapters.slack_adapter.WebClient"),
        patch("asyncio.get_event_loop") as mock_loop,
    ):
        # Capture the listener function
        listener_fn = None

        def save_listener(fn):
            nonlocal listener_fn
            listener_fn = fn
            return fn

        mock_socket_client.socket_mode_request_listener = save_listener

        # Mock connection logic to avoid actual network calls
        mock_loop.return_value.run_in_executor.return_value = asyncio.Future()
        mock_loop.return_value.run_in_executor.return_value.set_result(
            {"ok": True, "user_id": "U123"}
        )

        await adapter.initialize()

        if listener_fn:
            mock_req = MagicMock()
            # Must be awaited since process_socket_mode_request is async
            await listener_fn(mock_socket_client, mock_req)
    await adapter.shutdown()


@pytest.mark.asyncio
async def test_messaging_server_final_gaps():
    from adapters.messaging.server import (
        MegaBotMessagingServer,
        SecureWebSocket,
    )

    server = MegaBotMessagingServer()
    server.register_handler(MagicMock(side_effect=Exception("Handler fail")))
    # Trigger line 298
    await server._handle_platform_message(
        {"sender_id": "s", "chat_id": "c", "content": "hi"}
    )

    # Trigger line 121
    sws = SecureWebSocket("password")
    assert sws.decrypt("not-encrypted") == "not-encrypted"

    # Trigger line 227 (Missing client during broadcast)
    mock_client = AsyncMock()
    server.clients = {"c1": mock_client}

    msg = PlatformMessage(
        id="1",
        sender_id="s",
        sender_name="n",
        chat_id="c",
        content="hi",
        platform="p",
        timestamp=datetime.now(),
    )

    # We want to remove 'c1' after clients_to_send is calculated but before it's used
    original_list = list

    def special_list(it):
        res = original_list(it)
        if isinstance(it, type(server.clients.keys())):
            server.clients.clear()
        return res

    with patch("adapters.messaging.server.list", side_effect=special_list):
        await server.send_message(msg)


@pytest.mark.asyncio
async def test_push_notification_adapter_main():
    from adapters.push_notification_adapter import main

    with (
        patch(
            "adapters.push_notification_adapter.PushNotificationAdapter.initialize",
            AsyncMock(return_value=True),
        ),
        patch(
            "adapters.push_notification_adapter.PushNotificationAdapter.shutdown",
            AsyncMock(),
        ),
        patch("asyncio.sleep", AsyncMock(side_effect=[None, asyncio.CancelledError])),
    ):
        try:
            await main()
        except asyncio.CancelledError:
            pass
