from __future__ import annotations

import unittest

from field_quarantine.models import ReconciliationContext
from field_quarantine.reconciliation import reconcile_submission

from helpers import (
    make_answer,
    make_attachment,
    make_field,
    make_plan,
    make_schema,
    make_submission,
)


def schema(version, fields):
    return make_schema(
        version,
        fields,
        obligation_hash="obl",
        source_hash="src",
    )


def context(**overrides):
    data = {
        "now": "2025-01-03T00:00:00Z",
        "received_delivery_ids": [],
        "remote_applied_fields": {},
        "uploaded_attachment_ids": [],
        "actor": "sync-worker",
    }
    data.update(overrides)
    return ReconciliationContext.from_dict(data)


class ReconciliationTests(unittest.TestCase):
    def test_duplicate_delivery_is_suppressed_before_migration(self) -> None:
        old = schema("1", [make_field("field")])
        new = schema("2", [])
        submission = make_submission(old, [make_answer("field", "would invalidate")])
        result = reconcile_submission(
            submission,
            old,
            new,
            make_plan(old, new),
            context(received_delivery_ids=["delivery-1"]),
        )
        self.assertEqual(result.decision, "already_delivered")
        self.assertTrue(result.duplicate_delivery)
        self.assertEqual(result.audit_events[0].event_type, "duplicate_delivery_suppressed")

    def test_expired_authorization_is_quarantined_with_renewal_task(self) -> None:
        field = make_field("field")
        old = schema("1", [field])
        new = schema("2", [field])
        submission = make_submission(
            old,
            [make_answer("field", "value")],
            auth_expires_at="2025-01-02T00:00:00Z",
        )
        result = reconcile_submission(
            submission, old, new, make_plan(old, new), context()
        )
        self.assertEqual(result.decision, "quarantined")
        self.assertIn("renew_authorization", [item.action for item in result.tasks])

    def test_partial_sync_conflict_is_never_overwritten(self) -> None:
        field = make_field("field")
        old = schema("1", [field])
        new = schema("2", [field])
        submission = make_submission(
            old,
            [make_answer("field", "local")],
            sync_state="partial",
        )
        result = reconcile_submission(
            submission,
            old,
            new,
            make_plan(old, new),
            context(remote_applied_fields={"field": "remote"}),
        )
        self.assertEqual(result.decision, "quarantined")
        self.assertEqual(result.classification, "review_required")
        self.assertIn("PARTIAL_SYNC_CONFLICT", [item.code for item in result.quarantine_reasons])
        self.assertEqual(result.migrated_submission.answer_map()["field"].value, "local")

    def test_matching_partial_sync_creates_resume_task(self) -> None:
        field = make_field("field")
        old = schema("1", [field])
        new = schema("2", [field])
        submission = make_submission(
            old,
            [make_answer("field", "same")],
            sync_state="partial",
        )
        result = reconcile_submission(
            submission,
            old,
            new,
            make_plan(old, new),
            context(remote_applied_fields={"field": "same"}),
        )
        self.assertEqual(result.decision, "tasks_pending")
        self.assertIn("resume_partial_delivery", [item.action for item in result.tasks])

    def test_local_attachment_creates_upload_task(self) -> None:
        field = make_field(
            "field",
            evidence_required=True,
            evidence_count=1,
            media_types=("image/jpeg",),
        )
        old = schema("1", [field])
        new = schema("2", [field])
        submission = make_submission(
            old,
            [make_answer("field", "value")],
            attachments=[make_attachment("field")],
        )
        result = reconcile_submission(
            submission, old, new, make_plan(old, new), context()
        )
        self.assertEqual(result.decision, "tasks_pending")
        self.assertIn("upload_attachment", [item.action for item in result.tasks])

    def test_confirmed_uploaded_attachment_allows_delivery(self) -> None:
        field = make_field(
            "field",
            evidence_required=True,
            evidence_count=1,
            media_types=("image/jpeg",),
        )
        old = schema("1", [field])
        new = schema("2", [field])
        submission = make_submission(
            old,
            [make_answer("field", "value")],
            attachments=[make_attachment("field")],
        )
        result = reconcile_submission(
            submission,
            old,
            new,
            make_plan(old, new),
            context(uploaded_attachment_ids=["att-1"]),
        )
        self.assertEqual(result.decision, "ready_to_deliver")
        self.assertEqual(result.tasks, ())

    def test_missing_delivery_id_creates_idempotency_task(self) -> None:
        field = make_field("field")
        old = schema("1", [field])
        new = schema("2", [field])
        submission = make_submission(
            old,
            [make_answer("field", "value")],
            delivery_id=None,
        )
        result = reconcile_submission(
            submission, old, new, make_plan(old, new), context()
        )
        self.assertEqual(result.decision, "tasks_pending")
        self.assertIn("assign_delivery_id", [item.action for item in result.tasks])

    def test_safe_submission_is_ready_to_deliver(self) -> None:
        field = make_field("field")
        old = schema("1", [field])
        new = schema("2", [field])
        submission = make_submission(old, [make_answer("field", "value")])
        result = reconcile_submission(
            submission, old, new, make_plan(old, new), context()
        )
        self.assertEqual(result.decision, "ready_to_deliver")
        self.assertIsNotNone(result.migrated_submission)
        self.assertEqual(result.audit_events[-1].event_type, "reconciliation_ready")

    def test_reconciliation_is_deterministic(self) -> None:
        field = make_field("field")
        old = schema("1", [field])
        new = schema("2", [field])
        submission = make_submission(old, [make_answer("field", "value")], delivery_id=None)
        first = reconcile_submission(
            submission, old, new, make_plan(old, new), context()
        )
        second = reconcile_submission(
            submission, old, new, make_plan(old, new), context()
        )
        self.assertEqual(first.to_dict(), second.to_dict())


if __name__ == "__main__":
    unittest.main()
