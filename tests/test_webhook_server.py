# tests/test_webhook_server.py
import pytest
from fastapi.testclient import TestClient
from claudeclaw.channels.webhook_server import app, register_route


def test_app_is_fastapi_instance():
    from fastapi import FastAPI
    assert isinstance(app, FastAPI)


def test_register_route_adds_endpoint():
    async def dummy_handler():
        return {"ok": True}

    register_route("GET", "/test-register", dummy_handler)
    client = TestClient(app)
    resp = client.get("/test-register")
    assert resp.status_code == 200


def test_health_endpoint_returns_ok():
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
