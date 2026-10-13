"""Admin authentication for control endpoints (start / stop / manual cycles).

These endpoints change the live experiment or trigger paid LLM calls, so they
require the `ADMIN_TOKEN` secret in the `X-Admin-Token` header. Fails closed:
if `ADMIN_TOKEN` is not configured, the endpoints are disabled entirely.
"""

from __future__ import annotations

import os
import secrets

from fastapi import Header, HTTPException


def require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    """FastAPI dependency: reject the request unless it carries the admin token."""
    expected = os.getenv("ADMIN_TOKEN")
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="Admin endpoints are disabled (ADMIN_TOKEN not configured)",
        )
    if not x_admin_token or not secrets.compare_digest(x_admin_token, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing admin token")
