import asyncio
import websockets
import json
import uuid
import os
from typing import Any, Optional
from core.interfaces import MessagingInterface, Message
from core.resource_guard import LRUCache


class OpenClawAdapter(MessagingInterface):
    def __init__(self, host: str, port: int, auth_token: Optional[str] = None):
        self.uri = f"wss://{host}:{port}"
        self.websocket = None
        self.on_event = None
        self.pending_requests: LRUCache[str, Any] = LRUCache(maxsize=256)
        # Use provided auth token, or environment variable, or generate secure random
        self.auth_token = (
            auth_token
            or os.environ.get("OPENCLAW_AUTH_TOKEN")
            or os.environ.get("MEGABOT_AUTH_TOKEN")
            or self._generate_secure_token()
        )

    def _generate_secure_token(self) -> str:
        """Generate a secure random token for authentication."""
        import secrets

        token = secrets.token_urlsafe(32)
        print("WARNING: No auth token provided. Generated temporary token (see logs for first 8 chars).")
        print(f"  Token prefix: {token[:8]}...")
        return token

    async def connect(self, on_event=None):
        self.websocket = await websockets.connect(self.uri)
        self.on_event = on_event
        # Perform handshake
        connect_req = {
            "type": "req",
            "id": str(uuid.uuid4()),
            "method": "connect",
            "params": {
                "minProtocol": 3,
                "maxProtocol": 3,
                "client": {"id": "megabot", "version": "0.1.0", "platform": "linux", "mode": "operator"},
                "role": "operator",
                "scopes": ["operator.read", "operator.write"],
                "auth": {"token": self.auth_token},
                "device": {"id": "megabot-device-id", "publicKey": "megabot-pk"},
            },
        }
        await self.websocket.send(json.dumps(connect_req))
        response = await self.websocket.recv()
        print(f"OpenClaw Handshake Response: {response}")

        # Start background listener
        asyncio.create_task(self._listen())

    async def _listen(self):
        if not self.websocket:
            return
        try:
            async for message in self.websocket:
                data = json.loads(message)
                msg_id = data.get("id")

                # Check if this is a response to a pending request
                if msg_id in self.pending_requests:
                    future = self.pending_requests.pop(msg_id)
                    if not future.done():
                        future.set_result(data)
                elif self.on_event:
                    # Otherwise, it's a notification or unexpected event
                    await self.on_event(data)
        except Exception as e:
            print(f"OpenClaw connection closed: {e}")

    async def execute_tool(self, method: str, params: dict) -> Any:
        if not self.websocket:
            await self.connect()

        if not self.websocket:
            return {"error": "Failed to connect to OpenClaw"}

        req_id = str(uuid.uuid4())
        payload = {"type": "req", "id": req_id, "method": method, "params": params}

        # Create a future to wait for the response
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self.pending_requests[req_id] = future

        await self.websocket.send(json.dumps(payload))

        try:
            # Wait for response with timeout
            response = await asyncio.wait_for(future, timeout=30.0)
            return response
        except asyncio.TimeoutError:
            self.pending_requests.pop(req_id, None)
            return {"type": "res", "id": req_id, "error": "Request timed out"}

    async def send_message(self, message: Message) -> None:
        await self.execute_tool("chat.send", {"content": message.content, "sender": message.sender})

    async def receive_message(self) -> Message:
        # receive_message in this context usually means waiting for a push message
        # but if the interface requires a poll, we use this
        if not self.websocket:
            await self.connect()

        if self.websocket:
            data = await self.websocket.recv()
            msg_data = json.loads(data)
            return Message(
                content=msg_data.get("payload", {}).get("content", ""),
                sender=msg_data.get("payload", {}).get("sender", "unknown"),
            )
        return Message(content="", sender="error")

    async def subscribe_events(self, events: list[str]):
        await self.execute_tool("gateway.subscribe", {"events": events})

    async def schedule_task(self, name: str, schedule: str, method: str, params: dict):
        return await self.execute_tool(
            "cron.add", {"name": name, "schedule": schedule, "method": method, "params": params}
        )
