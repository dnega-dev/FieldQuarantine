from __future__ import annotations

import json
import unittest
from pathlib import Path

from field_quarantine import (
    FormSchema,
    MigrationPlan,
    PendingSubmission,
    ReconciliationContext,
    classify_submission,
    diff_schemas,
    reconcile_submission,
)


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def load(name: str):
    with (EXAMPLES / name).open("r", encoding="utf-8") as handle:
        return json.load(handle)


class OfflineLifecycleTests(unittest.TestCase):
    def test_disconnect_schema_change_reconnect(self) -> None:
        # Disconnect: revision 1 is captured locally with answer and attachment
        # provenance while the network is unavailable.
        old = FormSchema.from_dict(load("schema-v1.json"))
        pending = PendingSubmission.from_dict(load("pending-submission.json"))
        captured_snapshot = pending.to_dict()
        self.assertEqual(pending.sync_state, "local_only")

        # Schema change: the server publishes revision 2 and a reviewed,
        # explicit plan. The broad schema diff requires review because it cannot
        # know which old values exist, while this submission is safely migratable.
        new = FormSchema.from_dict(load("schema-v2.json"))
        plan = MigrationPlan.from_dict(load("migration-plan.json"))
        change = diff_schemas(old, new, plan)
        classified = classify_submission(
            pending, old, new, plan, now="2025-01-03T12:00:00Z"
        )
        self.assertEqual(change.classification, "review_required")
        self.assertEqual(classified.classification, "auto_migratable")

        # Reconnect: attachment transfer is acknowledged, safe migration runs,
        # and the record is ready for idempotent delivery.
        context = ReconciliationContext.from_dict(load("reconnect-context.json"))
        reconciled = reconcile_submission(pending, old, new, plan, context)
        self.assertEqual(reconciled.decision, "ready_to_deliver")
        self.assertFalse(reconciled.duplicate_delivery)
        self.assertEqual(reconciled.tasks, ())
        self.assertIsNotNone(reconciled.migrated_submission)
        migrated = reconciled.migrated_submission
        assert migrated is not None

        self.assertEqual(migrated.schema_version, "2")
        self.assertEqual(migrated.answer_map()["asset_condition"].value, "needs_attention")
        self.assertEqual(migrated.answer_map()["temperature"].value, 42)
        self.assertEqual(migrated.answer_map()["visit_complete"].value, True)
        self.assertEqual(migrated.attachments[0].field_id, "asset_condition")
        self.assertEqual(migrated.original_answers, pending.answers)
        self.assertEqual(pending.to_dict(), captured_snapshot)
        self.assertEqual(
            [event.event_type for event in reconciled.audit_events],
            ["submission_migrated", "reconciliation_ready"],
        )


if __name__ == "__main__":
    unittest.main()
