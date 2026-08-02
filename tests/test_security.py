"""Tests for A2A authentication middleware."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from src.protocol.security import A2AAuthMiddleware


@pytest.fixture
def mock_request():
    def _make(headers: dict = None):
        req = MagicMock()
        req.headers = headers or {}
        return req
    return _make


class TestA2AAuthMiddleware:
    def test_no_key_configured_allows_all(self, mock_request):
        middleware = A2AAuthMiddleware(api_key=None)
        req = mock_request()
        assert middleware.authenticate(req) is True

    def test_valid_key(self, mock_request):
        middleware = A2AAuthMiddleware(api_key="secret-123")
        req = mock_request({"X-A2A-API-Key": "secret-123"})
        assert middleware.authenticate(req) is True

    def test_invalid_key(self, mock_request):
        middleware = A2AAuthMiddleware(api_key="secret-123")
        req = mock_request({"X-A2A-API-Key": "wrong"})
        assert middleware.authenticate(req) is False

    def test_missing_key(self, mock_request):
        middleware = A2AAuthMiddleware(api_key="secret-123")
        req = mock_request({})
        assert middleware.authenticate(req) is False
