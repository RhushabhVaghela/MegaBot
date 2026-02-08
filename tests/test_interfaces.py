from megabot.core.interfaces import Message, MessagingInterface


def test_message_model():
    msg = Message(content="hello", sender="user", metadata={"time": "now"})
    assert msg.content == "hello"
    assert msg.sender == "user"
    assert msg.metadata["time"] == "now"

def test_interfaces_runtime_checkable():
    class MockMessaging:
        async def send_message(self, message: Message) -> None: pass
        async def receive_message(self) -> Message: pass
    
    assert isinstance(MockMessaging(), MessagingInterface)
