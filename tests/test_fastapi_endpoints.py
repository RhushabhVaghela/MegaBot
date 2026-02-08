"""
Tests for FastAPI lifespan and websocket endpoints.

These tests are separated because they test module-level globals
and need to run in isolation.
"""

from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from megabot.core.orchestrator import lifespan, websocket_endpoint


@pytest.mark.asyncio
async def test_websocket_endpoint_auth_rejected():
    """Test websocket endpoint rejects connection without valid auth token (SEC-FIX-001)"""
    mock_ws = AsyncMock()
    mock_ws.query_params = {"token": "wrong-token"}
    with patch.dict("os.environ", {"WS_AUTH_TOKEN": "correct-token"}):
        await websocket_endpoint(mock_ws)
        mock_ws.close.assert_called_once_with(code=1008)


@pytest.mark.asyncio
async def test_lifespan():
    """Test FastAPI lifespan context manager"""
    import megabot.core.orchestrator as orch_module

    original_orchestrator = orch_module.orchestrator
    orch_module.orchestrator = None  # Reset to None before test

    try:
        with patch("megabot.core.orchestrator.MegaBotOrchestrator") as mock_orc_class:
            mock_instance = Mock()
            mock_instance.start = AsyncMock()
            mock_instance.shutdown = AsyncMock()
            mock_orc_class.return_value = mock_instance
            mock_app = MagicMock()

            # Actually call the async context manager
            async with lifespan(mock_app):
                # Verify orchestrator was created and started
                assert mock_orc_class.called, "MegaBotOrchestrator should be instantiated"

            # Verify start and shutdown were called
            assert mock_instance.start.called, "orchestrator.start() should be called"
            assert mock_instance.shutdown.called, "orchestrator.shutdown() should be called"
    finally:
        orch_module.orchestrator = original_orchestrator


@pytest.mark.asyncio
async def test_websocket_endpoint():
    """Test websocket endpoint when orchestrator is available"""
    import megabot.core.orchestrator as orch_module

    original_orchestrator = orch_module.orchestrator

    try:
        with patch("megabot.core.orchestrator.orchestrator") as mock_orc:
            mock_orc.handle_client = AsyncMock()
            mock_ws = AsyncMock()
            # SEC-FIX-001: WebSocket auth requires a valid token
            with patch.dict("os.environ", {"WS_AUTH_TOKEN": "test-token"}):
                mock_ws.query_params = {"token": "test-token"}
                await websocket_endpoint(mock_ws)
                mock_orc.handle_client.assert_called_once_with(mock_ws)
    finally:
        orch_module.orchestrator = original_orchestrator


@pytest.mark.asyncio
async def test_websocket_endpoint_uninitialized():
    """Test websocket endpoint when orchestrator is None"""
    import megabot.core.orchestrator as orch_module

    original_orchestrator = orch_module.orchestrator
    orch_module.orchestrator = None  # Ensure it's None for this test

    try:
        mock_ws = AsyncMock()
        # SEC-FIX-001: WebSocket auth requires a valid token
        with patch.dict("os.environ", {"WS_AUTH_TOKEN": "test-token"}):
            mock_ws.query_params = {"token": "test-token"}
            await websocket_endpoint(mock_ws)
            assert mock_ws.accept.called
            assert mock_ws.send_text.called
            assert mock_ws.close.called
    finally:
        orch_module.orchestrator = original_orchestrator


@pytest.mark.asyncio
async def test_health_endpoint():
    """Test the /health endpoint returns correct responses.

    The security sprint changed health() to return JSONResponse objects with
    deep component health checks instead of a plain dict.
    """
    from starlette.responses import JSONResponse

    import megabot.core.orchestrator as orch_module
    from megabot.core.orchestrator import health

    original_orchestrator = orch_module.orchestrator

    try:
        # When orchestrator is None → 503 unavailable
        orch_module.orchestrator = None
        result = await health()
        assert isinstance(result, JSONResponse)
        assert result.status_code == 503

        # When orchestrator is available and all healthy → 200
        mock_orc = MagicMock()
        mock_orc.get_system_health = AsyncMock(return_value={"llm": {"status": "up"}, "memory": {"status": "up"}})
        orch_module.orchestrator = mock_orc
        result = await health()
        assert isinstance(result, JSONResponse)
        assert result.status_code == 200
    finally:
        orch_module.orchestrator = original_orchestrator
