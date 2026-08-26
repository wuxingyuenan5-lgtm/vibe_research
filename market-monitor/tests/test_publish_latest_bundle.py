from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from publish_latest_bundle import publish


class PublishLatestBundleTests(unittest.TestCase):
    def _fixture(
        self,
        root: Path,
        *,
        canonical_status: str = "PASS",
        report_date: str | None = None,
        latest_market_date: str | None = None,
        publication: dict[str, object] | None = None,
    ) -> tuple[str, Path]:
        target = "2026-08-21"
        output_dir = root / "output" / target
        output_dir.mkdir(parents=True)
        report_date = report_date or target
        latest_market_date = latest_market_date or report_date
        report = {
            "meta": {
                "report_date": report_date,
                "latest_market_date": latest_market_date,
                "status": "PASS",
            },
            "market_history": [{"date": latest_market_date}],
            "quality": {
                "publication": publication or {
                    "target_date": target,
                    "can_publish_target_date": report_date == target and latest_market_date == target,
                    "blocking_reasons": [],
                }
            },
        }
        (output_dir / "report_data.json").write_text(json.dumps(report), encoding="utf-8")
        (output_dir / "canonical_validation.json").write_text(
            json.dumps({"status": canonical_status, "failures": []}), encoding="utf-8"
        )
        (output_dir / "html_validation.json").write_text(
            json.dumps({"status": "PASS", "failures": []}), encoding="utf-8"
        )
        return target, root / "data/published/latest_market_monitor.json"

    def test_publish_writes_one_validated_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target, output = self._fixture(root)
            bundle = publish(root, target, output)
            saved = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(saved["status"], "published")
            self.assertEqual(saved["data_date"], target)
            self.assertEqual(saved["report"], bundle["report"])

    def test_failed_validation_does_not_replace_last_good(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target, output = self._fixture(root, canonical_status="FAIL")
            output.parent.mkdir(parents=True)
            output.write_text('{"last":"good"}', encoding="utf-8")
            with self.assertRaises(RuntimeError):
                publish(root, target, output)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), {"last": "good"})

    def test_publish_rejects_previous_report_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target, output = self._fixture(
                root,
                report_date="2026-08-20",
                latest_market_date="2026-08-20",
                publication={
                    "target_date": "2026-08-21",
                    "can_publish_target_date": False,
                    "blocking_reasons": [{"module": "market_history", "detail": "missing 2026-08-21"}],
                },
            )
            with self.assertRaises(RuntimeError):
                publish(root, target, output)


if __name__ == "__main__":
    unittest.main()
