"""Smoke tests for the operator API."""

from __future__ import annotations

import os

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from applypilot.api.app import create_app


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("APPLYPILOT_API_TOKEN", "test-token")
    monkeypatch.setenv("APPLY_MODE", "off")
    app = create_app()
    return TestClient(app)


def test_health(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_stats_requires_token(client):
    assert client.get("/api/v1/stats").status_code == 401
    r = client.get("/api/v1/stats", headers={"Authorization": "Bearer test-token"})
    assert r.status_code == 200
    assert "total" in r.json()


def test_jobs_list(client):
    r = client.get("/api/v1/jobs?limit=1", headers={"Authorization": "Bearer test-token"})
    assert r.status_code == 200
    body = r.json()
    assert "items" in body
    assert "total" in body


def test_apply_mode_off(client):
    r = client.post(
        "/api/v1/apply/start",
        headers={"Authorization": "Bearer test-token"},
        json={"workers": 1},
    )
    assert r.status_code == 200
    assert r.json()["ok"] is False
