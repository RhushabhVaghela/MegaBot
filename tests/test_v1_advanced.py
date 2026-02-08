import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from core.interfaces import Message
from core.memory.mcp_server import MemoryServer
from core.orchestrator import MegaBotOrchestrator


@pytest.fixture
def memory_server(tmp_path):
    db_path = str(tmp_path / "test_memory.db")
    return MemoryServer(db_path=db_path)


@pytest.fixture
def mock_orchestrator(mock_config):
    with (
        patch("core.orchestrator.ModuleDiscovery"),
        patch("core.orchestrator.OpenClawAdapter"),
        patch("core.orchestrator.MemUAdapter"),
        patch("core.orchestrator.MCPManager"),
    ):
        orc = MegaBotOrchestrator(mock_config)
        orc.adapters["openclaw"] = AsyncMock()
        orc.adapters["memu"] = AsyncMock()
        orc.adapters["mcp"] = AsyncMock()
        orc.adapters["messaging"] = AsyncMock()
        return orc


@pytest.mark.asyncio
async def test_memory_identity_link(memory_server):
    # Link Telegram ID to 'admin'
    await memory_server.link_identity("admin", "telegram", "tg123")

    # Retrieve unified ID
    unified = await memory_server.get_unified_id("telegram", "tg123")
    assert unified == "admin"

    # Check unlinked ID
    unlinked = await memory_server.get_unified_id("signal", "sig456")
    assert unlinked == "sig456"


@pytest.mark.asyncio
async def test_orchestrator_redaction(mock_orchestrator):
    # Mock vision driver analysis
    mock_orchestrator.computer_driver.execute = AsyncMock(
        side_effect=[
            # 1. Analyze finds sensitive regions
            json.dumps({"sensitive_regions": [{"x": 10, "y": 10, "width": 100, "height": 20}]}),
            # 2. Blur returns "redacted_data"
            "redacted_data",
            # 3. Verify pass finds NO sensitive regions
            json.dumps({"sensitive_regions": []}),
        ]
    )

    msg = Message(
        content="Check this",
        sender="MegaBot",
        attachments=[{"type": "image", "data": "raw_data"}],
    )

    # Mock permissions to ALLOW vision.outbound so it doesn't queue for approval
    mock_orchestrator.permissions.is_authorized = MagicMock(return_value=True)

    await mock_orchestrator.send_platform_message(msg, platform="native")

    assert msg.attachments[0]["data"] == "redacted_data"
    assert msg.attachments[0].get("metadata", {}).get("redacted") is True


def test_ivr_callback():
    from core.orchestrator import app as current_app

    client = TestClient(current_app)
    # Patch the global orchestrator variable in the module
    with (
        patch("core.orchestrator.orchestrator") as mock_orc,
        patch("core.app._validate_twilio_signature", return_value=True),
        patch("fastapi.Request.form", new_callable=AsyncMock) as mock_form,
    ):
        mock_orc.admin_handler._process_approval = AsyncMock()
        mock_form.return_value = {"Digits": "1"}

        response = client.post("/ivr?action_id=test-id")
        assert response.status_code == 200
        assert "Action approved" in response.text
        mock_orc.admin_handler._process_approval.assert_called_once_with("test-id", approved=True)
