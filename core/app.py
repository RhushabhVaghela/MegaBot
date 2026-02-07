"""FastAPI application factory, lifespan, CORS middleware, and route handlers.

Extracted from the monolithic ``core/orchestrator.py`` to separate HTTP
concerns from orchestration logic.  The canonical ``orchestrator`` variable
lives in ``core.orchestrator`` — route handlers access it lazily via
``_get_orchestrator()`` so that tests which set
``core.orchestrator.orchestrator = mock`` are honoured automatically.
"""

import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, Request, Query, Response  # type: ignore
from fastapi.responses import JSONResponse  # type: ignore
from starlette.middleware.cors import CORSMiddleware  # type: ignore

from core.config import load_config


# ---------------------------------------------------------------------------
# Module-level config (orchestrator lives in core.orchestrator ONLY)
# ---------------------------------------------------------------------------
config = load_config()
config.validate_environment()


def _get_orchestrator():
    """Return the current orchestrator instance from ``core.orchestrator``.

    The canonical ``orchestrator`` variable lives in ``core.orchestrator``.
    Tests set it there (``orch_module.orchestrator = mock``), and route
    handlers call this function to read it — so both production and test
    code see the same value.
    """
    orch_mod = sys.modules.get("core.orchestrator")
    if orch_mod is not None:
        return getattr(orch_mod, "orchestrator", None)
    return None


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan context manager for orchestrator initialization and cleanup.

    Handles the startup and shutdown lifecycle of the MegaBot orchestrator,
    ensuring proper initialization of all adapters and services.
    """
    import core.orchestrator as orch_mod

    skip_startup = os.environ.get("MEGABOT_SKIP_STARTUP", "").lower() in (
        "1",
        "true",
        "yes",
    )

    # Startup
    if not skip_startup:
        if not orch_mod.orchestrator:  # pragma: no cover
            orch_mod.orchestrator = orch_mod.MegaBotOrchestrator(config)
            await orch_mod.orchestrator.start()

    yield

    # Shutdown
    if not skip_startup and orch_mod.orchestrator:  # pragma: no cover
        await orch_mod.orchestrator.shutdown()


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------
app = FastAPI(lifespan=lifespan)

# --- CORS Middleware ---
_allowed_origins = os.environ.get("MEGABOT_CORS_ORIGINS", "").split(",")
_allowed_origins = [o.strip() for o in _allowed_origins if o.strip()]
if not _allowed_origins:
    _allowed_origins = ["http://localhost:5173", "http://127.0.0.1:5173"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Twilio signature validation
# ---------------------------------------------------------------------------
def _validate_twilio_signature(request: Request, form_data: dict) -> bool:
    """Validate Twilio request signature (VULN-012 CSRF fix).

    Uses HMAC-SHA1 per Twilio's webhook signing spec:
    https://www.twilio.com/docs/usage/security#validating-requests

    Returns True if signature is valid, False otherwise.
    If TWILIO_AUTH_TOKEN is not set, rejects all requests (fail-closed).
    """
    import base64
    import hmac
    import hashlib

    auth_token = os.environ.get("TWILIO_AUTH_TOKEN", "")
    if not auth_token:
        print("[IVR] TWILIO_AUTH_TOKEN not set — rejecting request (fail-closed)")
        return False

    signature = request.headers.get("X-Twilio-Signature", "")
    if not signature:
        print("[IVR] Missing X-Twilio-Signature header")
        return False

    url = str(request.url)
    data_str = url
    for key in sorted(form_data.keys()):
        data_str += key + str(form_data[key])

    computed = base64.b64encode(
        hmac.new(
            auth_token.encode("utf-8"),
            data_str.encode("utf-8"),
            hashlib.sha1,
        ).digest()
    ).decode("utf-8")

    return hmac.compare_digest(computed, signature)


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------
@app.post("/ivr")
async def ivr_callback(request: Request, action_id: str = Query(...)):
    form_data = await request.form()
    form_dict = dict(form_data)

    if not _validate_twilio_signature(request, form_dict):
        return Response(
            content="<Response><Say>Unauthorized request.</Say></Response>",
            media_type="application/xml",
            status_code=403,
        )

    digits = form_dict.get("Digits")

    orch = _get_orchestrator()
    if orch:
        if digits == "1":  # pragma: no cover
            await orch.admin_handler._process_approval(action_id, approved=True)
            response_text = "Action approved. Thank you."
        else:  # pragma: no cover
            await orch.admin_handler._process_approval(
                action_id,
                approved=False,
            )
            response_text = "Action rejected."
    else:
        response_text = "System error."  # pragma: no cover

    return Response(
        content=f"<Response><Say>{response_text}</Say></Response>",
        media_type="application/xml",
    )


@app.get("/")
async def root():
    return {
        "status": "online",
        "message": "MegaBot API is running",
        "version": "1.0.0",
        "endpoints": ["/ws", "/health"],
    }


@app.get("/health")
async def health():
    """Deep health check — verifies all critical components.

    Returns 200 with component statuses when the orchestrator is running and
    at least partially healthy. Returns 503 when the orchestrator has not been
    initialised or every component is down.
    """
    orch = _get_orchestrator()
    if orch is None:
        return JSONResponse(
            status_code=503,
            content={"status": "unavailable", "detail": "orchestrator not initialised"},
        )

    try:
        component_health = await orch.get_system_health()
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content={"status": "error", "detail": str(exc)},
        )

    statuses = [v.get("status") for v in component_health.values()]
    if all(s == "down" for s in statuses):
        overall = "unhealthy"
        http_code = 503
    elif all(s == "up" for s in statuses):
        overall = "healthy"
        http_code = 200
    else:
        overall = "degraded"
        http_code = 200

    return JSONResponse(
        status_code=http_code,
        content={"status": overall, "components": component_health},
    )


@app.websocket("/ws")  # pragma: no cover
async def websocket_endpoint(websocket: WebSocket):  # pragma: no cover
    # --- WebSocket Authentication (SEC-FIX-001) ---
    # Validate token from query parameter before accepting connection.
    ws_token = os.environ.get("WS_AUTH_TOKEN") or os.environ.get("OPENCLAW_AUTH_TOKEN")
    client_token = websocket.query_params.get("token")
    if not ws_token or client_token != ws_token:
        await websocket.close(code=1008)  # Policy Violation
        return
    orch = _get_orchestrator()
    if orch:  # pragma: no cover
        await orch.handle_client(websocket)  # pragma: no cover
    else:
        await websocket.accept()
        await websocket.send_text("Orchestrator not initialized")
        await websocket.close()  # pragma: no cover
