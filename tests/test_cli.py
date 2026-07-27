from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from field_quarantine.cli import main


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"


class CliTests(unittest.TestCase):
    def run_cli(self, *args: str):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            status = main(list(args))
        return status, stdout.getvalue(), stderr.getvalue()

    def test_diff_json_is_valid_and_deterministic(self) -> None:
        args = (
            "diff",
            str(EXAMPLES / "schema-v1.json"),
            str(EXAMPLES / "schema-v2.json"),
            "--plan",
            str(EXAMPLES / "migration-plan.json"),
        )
        first = self.run_cli(*args)
        second = self.run_cli(*args)
        self.assertEqual(first, second)
        self.assertEqual(first[0], 0)
        payload = json.loads(first[1])
        self.assertEqual(payload["schema_id"], "offline-inspection")
        self.assertTrue(first[1].endswith("\n"))

    def test_diff_text_report(self) -> None:
        status, output, error = self.run_cli(
            "diff",
            str(EXAMPLES / "schema-v1.json"),
            str(EXAMPLES / "schema-v2.json"),
            "--plan",
            str(EXAMPLES / "migration-plan.json"),
            "--format",
            "text",
        )
        self.assertEqual(status, 0)
        self.assertIn("Field Quarantine schema diff", output)
        self.assertIn("Classification:", output)
        self.assertEqual(error, "")

    def test_classify_example_is_auto_migratable(self) -> None:
        status, output, _ = self.run_cli(
            "classify",
            str(EXAMPLES / "pending-submission.json"),
            str(EXAMPLES / "schema-v1.json"),
            str(EXAMPLES / "schema-v2.json"),
            "--plan",
            str(EXAMPLES / "migration-plan.json"),
            "--at",
            "2025-01-03T12:00:00Z",
        )
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(output)["classification"], "auto_migratable")

    def test_migrate_example_preserves_original_answers(self) -> None:
        status, output, _ = self.run_cli(
            "migrate",
            str(EXAMPLES / "pending-submission.json"),
            str(EXAMPLES / "schema-v1.json"),
            str(EXAMPLES / "schema-v2.json"),
            "--plan",
            str(EXAMPLES / "migration-plan.json"),
            "--at",
            "2025-01-03T12:00:00Z",
        )
        payload = json.loads(output)
        self.assertEqual(status, 0)
        self.assertEqual(payload["status"], "migrated")
        self.assertEqual(len(payload["submission"]["original_answers"]), 2)

    def test_unsafe_migrate_returns_status_two(self) -> None:
        status, output, _ = self.run_cli(
            "migrate",
            str(EXAMPLES / "pending-submission.json"),
            str(EXAMPLES / "schema-v1.json"),
            str(EXAMPLES / "schema-v2.json"),
            "--at",
            "2025-01-03T12:00:00Z",
        )
        self.assertEqual(status, 2)
        self.assertEqual(json.loads(output)["status"], "quarantined")

    def test_reconcile_example_is_ready(self) -> None:
        status, output, _ = self.run_cli(
            "reconcile",
            str(EXAMPLES / "pending-submission.json"),
            str(EXAMPLES / "schema-v1.json"),
            str(EXAMPLES / "schema-v2.json"),
            "--plan",
            str(EXAMPLES / "migration-plan.json"),
            "--context",
            str(EXAMPLES / "reconnect-context.json"),
        )
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(output)["decision"], "ready_to_deliver")

    def test_output_file_and_malformed_input_handling(self) -> None:
        with tempfile.TemporaryDirectory(dir=str(ROOT / "tests")) as directory:
            output_path = Path(directory) / "report.json"
            status, stdout, stderr = self.run_cli(
                "diff",
                str(EXAMPLES / "schema-v1.json"),
                str(EXAMPLES / "schema-v2.json"),
                "--plan",
                str(EXAMPLES / "migration-plan.json"),
                "-o",
                str(output_path),
            )
            self.assertEqual(status, 0)
            self.assertEqual(stdout, "")
            self.assertTrue(output_path.read_text(encoding="utf-8").endswith("\n"))

            malformed = Path(directory) / "bad.json"
            malformed.write_text("{not-json", encoding="utf-8")
            status, _, stderr = self.run_cli(
                "diff",
                str(malformed),
                str(EXAMPLES / "schema-v2.json"),
            )
            self.assertEqual(status, 1)
            self.assertIn("field-quarantine: error:", stderr)


if __name__ == "__main__":
    unittest.main()
