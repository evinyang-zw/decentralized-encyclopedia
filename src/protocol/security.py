"""A2A API Key authentication."""
from __future__ import annotations
import hmac
from typing import Any


class A2AAuthMiddleware:
    def __init__(self, api_key: str | None):
        self.api_key = api_key

    def authenticate(self, request: Any) -> bool:
        if self.api_key is None:
            return True
        provided = request.headers.get("X-A2A-API-Key", "")
        return hmac.compare_digest(provided, self.api_key)
