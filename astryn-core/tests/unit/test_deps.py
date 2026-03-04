"""Tests for api/deps.py — API key verification."""

import pytest
from fastapi import HTTPException

from api.deps import verify_api_key


class TestVerifyApiKey:
    def test_valid_key_passes(self):
        # Should not raise
        verify_api_key(x_api_key="test-key")

    def test_invalid_key_raises_401(self):
        with pytest.raises(HTTPException) as exc_info:
            verify_api_key(x_api_key="wrong-key")
        assert exc_info.value.status_code == 401

    def test_empty_key_raises_401(self):
        with pytest.raises(HTTPException) as exc_info:
            verify_api_key(x_api_key="")
        assert exc_info.value.status_code == 401
