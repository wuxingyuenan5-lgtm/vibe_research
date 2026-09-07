from __future__ import annotations

from fastapi.testclient import TestClient

import app as app_module
from data_platform import workspace_repository


client = TestClient(app_module.app)


def test_notes_crud_routes(monkeypatch):
    note = {"id": "n1", "kind": "复盘", "title": "标题", "content": "正文", "ts": 1}
    monkeypatch.setattr(workspace_repository, "list_notes", lambda: [note])
    monkeypatch.setattr(workspace_repository, "add_note", lambda *args: note)
    monkeypatch.setattr(workspace_repository, "delete_note", lambda note_id: note_id == "n1")
    monkeypatch.setattr(workspace_repository, "clear_notes", lambda: 1)

    assert client.get("/api/notes").json()["data"] == [note]
    assert client.post("/api/notes", json={"kind": "复盘", "title": "标题", "content": "正文"}).json()["data"] == note
    assert client.delete("/api/notes/n1").json()["data"]["ok"] is True
    assert client.delete("/api/notes").json()["data"]["deleted"] == 1


def test_note_requires_title_and_content():
    response = client.post("/api/notes", json={"kind": "复盘", "title": "", "content": ""})
    assert response.status_code == 400
