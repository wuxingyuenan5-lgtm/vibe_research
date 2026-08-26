"""Read the single validated market-monitor publication from GitHub."""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import threading

import requests


DEFAULT_REPOSITORY = "wuxingyuenan5-lgtm/vibe_research"
DEFAULT_REF = "main"
DEFAULT_PATH = "market-monitor/data/published/latest_market_monitor.json"

_LAST_GOOD: dict | None = None
_LOCK = threading.Lock()


def repository_config() -> tuple[str, str, str]:
    return (
        os.environ.get("VR_MARKET_DATA_REPO", DEFAULT_REPOSITORY).strip(),
        os.environ.get("VR_MARKET_DATA_REF", DEFAULT_REF).strip(),
        os.environ.get("VR_MARKET_DATA_PATH", DEFAULT_PATH).strip(),
    )


def validate_bundle(bundle: object) -> dict:
    if not isinstance(bundle, dict):
        raise RuntimeError("published market bundle is not a JSON object")
    if bundle.get("status") != "published":
        raise RuntimeError(f"published market bundle has invalid status: {bundle.get('status')}")
    report = bundle.get("report")
    if not isinstance(report, dict):
        raise RuntimeError("published market bundle has no report")
    data_date = str(bundle.get("data_date") or "")
    meta = report.get("meta") or {}
    market = report.get("market_history") or []
    latest_market = str((market[-1] if market else {}).get("date") or "")
    if not data_date or str(meta.get("report_date") or "") != data_date:
        raise RuntimeError("published market bundle report date mismatch")
    if str(meta.get("latest_market_date") or latest_market) != data_date or latest_market != data_date:
        raise RuntimeError("published market bundle latest market date mismatch")
    if meta.get("status") == "FAIL":
        raise RuntimeError("published market bundle contains a failed report")
    validation = bundle.get("validation") or {}
    if any(validation.get(key) == "FAIL" for key in ("canonical", "html", "report")):
        raise RuntimeError("published market bundle contains failed validation")
    expected_hash = str(bundle.get("report_sha256") or "")
    actual_hash = hashlib.sha256(
        json.dumps(report, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    if not expected_hash or expected_hash != actual_hash:
        raise RuntimeError("published market bundle report checksum mismatch")
    return bundle


def bundle_data_date(bundle: dict | None) -> str:
    if not isinstance(bundle, dict):
        return ""
    return str(bundle.get("data_date") or "")


def newer_bundle(*bundles: dict | None) -> dict | None:
    valid = [bundle for bundle in bundles if isinstance(bundle, dict)]
    if not valid:
        return None
    return max(valid, key=bundle_data_date)


def fetch_remote_bundle() -> dict:
    repository, ref, path = repository_config()
    url = f"https://api.github.com/repos/{repository}/contents/{path}"
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "Vibe-Research-market-reader",
    }
    token = os.environ.get("VR_GITHUB_TOKEN", "").strip() or os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = requests.get(url, params={"ref": ref}, headers=headers, timeout=(4, 12))
    response.raise_for_status()
    payload = response.json()
    if isinstance(payload, dict) and payload.get("content"):
        raw = base64.b64decode(str(payload["content"]).replace("\n", ""))
        bundle = json.loads(raw.decode("utf-8"))
    else:
        bundle = payload
    bundle = validate_bundle(bundle)
    remember(bundle)
    return bundle


def remember(bundle: dict) -> None:
    global _LAST_GOOD
    with _LOCK:
        _LAST_GOOD = bundle


def last_good() -> dict | None:
    with _LOCK:
        return _LAST_GOOD


def load_bundled_fallback(project_root: Path) -> dict | None:
    path = project_root / "market-monitor" / "data" / "published" / "latest_market_monitor.json"
    if not path.exists():
        return None
    try:
        bundle = validate_bundle(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return None
    remember(bundle)
    return bundle
