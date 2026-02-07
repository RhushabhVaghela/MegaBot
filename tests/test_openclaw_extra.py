"""Coverage for OpenClaw secure token generation"""

import os
from unittest.mock import patch
from adapters.openclaw_adapter import OpenClawAdapter


def test_openclaw_token_generation():
    """Test generating a secure token when none is provided"""
    # Ensure no tokens in environment
    with patch.dict(os.environ, {}, clear=True):
        adapter = OpenClawAdapter("localhost", 1234)
        assert adapter.auth_token is not None
        assert len(adapter.auth_token) > 20
