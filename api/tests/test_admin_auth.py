"""Tests for the admin token guard on control endpoints (start/stop/manual cycles).

The scheduler is mocked so no test ever triggers a real trading cycle or LLM call.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import trading

CONTROL_ENDPOINTS = ["/api/cycle", "/api/cycle/tw", "/api/start", "/api/stop"]


@pytest.fixture
def client(monkeypatch):
    scheduler = MagicMock()
    scheduler.is_running = False
    scheduler.run_cycle_now.return_value = []
    scheduler.run_tw_cycle_now.return_value = []
    scheduler.cycle_count = 0
    scheduler.tw_cycle_count = 0
    monkeypatch.setattr(trading, "trading_scheduler", scheduler)

    app = FastAPI()
    app.include_router(trading.router)
    return TestClient(app), scheduler


@pytest.mark.parametrize("path", CONTROL_ENDPOINTS)
def test_disabled_when_admin_token_not_configured(client, monkeypatch, path):
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    http, scheduler = client
    resp = http.post(path, headers={"X-Admin-Token": "anything"})
    assert resp.status_code == 503
    scheduler.start.assert_not_called()
    scheduler.run_cycle_now.assert_not_called()


@pytest.mark.parametrize("path", CONTROL_ENDPOINTS)
def test_rejects_missing_token(client, monkeypatch, path):
    monkeypatch.setenv("ADMIN_TOKEN", "s3cret")
    http, scheduler = client
    assert http.post(path).status_code == 401
    scheduler.stop.assert_not_called()
    scheduler.run_tw_cycle_now.assert_not_called()


@pytest.mark.parametrize("path", CONTROL_ENDPOINTS)
def test_rejects_wrong_token(client, monkeypatch, path):
    monkeypatch.setenv("ADMIN_TOKEN", "s3cret")
    http, _ = client
    assert http.post(path, headers={"X-Admin-Token": "wrong"}).status_code == 401


def test_accepts_correct_token(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "s3cret")
    http, scheduler = client
    resp = http.post("/api/start", headers={"X-Admin-Token": "s3cret"})
    assert resp.status_code == 200
    assert resp.json() == {"status": "started"}
    scheduler.start.assert_called_once()


def test_read_only_endpoints_stay_public(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "s3cret")
    http, _ = client
    assert http.get("/api/strategies").status_code == 200
