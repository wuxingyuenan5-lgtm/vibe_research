from __future__ import annotations

import json

from data_platform.workspace_import import load_workspace


def test_load_workspace_preserves_personal_files(tmp_path):
    (tmp_path / "portfolio.json").write_text(json.dumps({
        "holdings": [{"code": "600519", "shares": 10, "cost": 100}],
        "closed": [{"code": "000001", "pnl": 5}],
    }), encoding="utf-8")
    reports = tmp_path / "myreports"
    reports.mkdir()
    (reports / "index.json").write_text(json.dumps([{"id": "r1", "name": "报告.pdf", "ext": ".pdf"}]), encoding="utf-8")
    loaded = load_workspace(tmp_path)
    assert loaded.holdings[0]["code"] == "600519"
    assert loaded.closed[0]["pnl"] == 5
    assert loaded.reports[0]["id"] == "r1"
