from __future__ import annotations

from fastapi.testclient import TestClient

import app as app_module


def test_operations_endpoint_is_safe_when_database_is_disabled(monkeypatch):
    monkeypatch.delenv("VR_DATABASE_URL", raising=False)
    response = TestClient(app_module.app).get("/api/operations/data-platform")
    assert response.status_code == 200
    assert response.json() == {
        "status": "disabled",
        "recent_events": [],
        "quality_checks": [],
    }
