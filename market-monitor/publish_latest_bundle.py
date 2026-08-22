#!/usr/bin/env python3
"""Publish one immutable, frontend-ready market-monitor bundle.

The daily workflow calls this only after Canonical and HTML validation.  The
output is a single JSON file so readers never have to combine a new pointer
with an old payload (or vice versa).
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo


def _read_json(path: Path) -> dict:
    if not path.exists():
        raise RuntimeError(f"missing publication input: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"publication input is not an object: {path}")
    return value


def build_bundle(root: Path, target_date: str) -> dict[str, object]:
    output_dir = root / "output" / target_date
    report = _read_json(output_dir / "report_data.json")
    canonical = _read_json(output_dir / "canonical_validation.json")
    html = _read_json(output_dir / "html_validation.json")

    if canonical.get("status") == "FAIL" or canonical.get("failures"):
        raise RuntimeError(f"canonical validation failed: {canonical.get('failures')}")
    if html.get("status") == "FAIL" or html.get("failures"):
        raise RuntimeError(f"HTML validation failed: {html.get('failures')}")
    meta = report.get("meta") or {}
    if meta.get("status") == "FAIL":
        raise RuntimeError("report_data status is FAIL")
    if str(meta.get("report_date") or "") != target_date:
        raise RuntimeError(f"report date mismatch: {meta.get('report_date')} != {target_date}")
    if str(meta.get("latest_market_date") or "") != target_date:
        raise RuntimeError(
            f"latest market date mismatch: {meta.get('latest_market_date')} != {target_date}"
        )

    report_bytes = json.dumps(report, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return {
        "schema_version": "1.0",
        "status": "published",
        "data_date": target_date,
        "published_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds"),
        "producer": "github-actions" if os.environ.get("GITHUB_ACTIONS") == "true" else "local-verification",
        "repository": os.environ.get("GITHUB_REPOSITORY", ""),
        "run_id": os.environ.get("GITHUB_RUN_ID", "local-verification"),
        "commit_sha": os.environ.get("GITHUB_SHA", ""),
        "report_sha256": hashlib.sha256(report_bytes).hexdigest(),
        "validation": {
            "canonical": canonical.get("status"),
            "html": html.get("status"),
            "report": meta.get("status"),
        },
        "report": report,
    }


def publish(root: Path, target_date: str, output: Path) -> dict[str, object]:
    bundle = build_bundle(root, target_date)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    temporary.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, output)
    return bundle


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish the latest validated market-monitor bundle")
    parser.add_argument("--target-date", required=True)
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", default="data/published/latest_market_monitor.json")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    output = Path(args.output)
    if not output.is_absolute():
        output = root / output
    bundle = publish(root, args.target_date, output)
    print(
        f"published_bundle={output} data_date={bundle['data_date']} "
        f"sha256={bundle['report_sha256']}"
    )


if __name__ == "__main__":
    main()
