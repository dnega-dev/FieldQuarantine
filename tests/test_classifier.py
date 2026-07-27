from __future__ import annotations

import unittest
from dataclasses import replace

from field_quarantine.classifier import classify_submission

from helpers import (
    make_answer,
    make_attachment,
    make_field,
    make_plan,
    make_schema,
    make_submission,
)


def schema(version, fields, obligation="obl", source="src"):
    return make_schema(
        version,
        fields,
        obligation_hash=obligation,
        source_hash=source,
    )


class ClassificationTests(unittest.TestCase):
    def test_tightened_range_passes_for_actual_value(self) -> None:
        old = schema("1", [make_field("score", "number", maximum=10)])
        new = schema("2", [make_field("score", "number", maximum=8)])
        submission = make_submission(old, [make_answer("score", 7)])
        result = classify_submission(submission, old, new, make_plan(old, new))
        self.assertEqual(result.classification, "compatible")

    def test_tightened_range_invalidates_out_of_range_value(self) -> None:
        old = schema("1", [make_field("score", "number", maximum=10)])
        new = schema("2", [make_field("score", "number", maximum=8)])
        submission = make_submission(old, [make_answer("score", 9)])
        result = classify_submission(submission, old, new, make_plan(old, new))
        self.assertEqual(result.classification, "invalidated")
        self.assertIn("TARGET_VALIDATION_FAILED", [item.code for item in result.reasons])

    def test_enum_removal_does_not_harm_retained_value(self) -> None:
        old = schema("1", [make_field("state", "enum", enum=("a", "b"))])
        new = schema("2", [make_field("state", "enum", enum=("a",))])
        submission = make_submission(old, [make_answer("state", "a")])
        result = classify_submission(submission, old, new, make_plan(old, new))
        self.assertEqual(result.classification, "compatible")

    def test_removed_enum_value_is_invalidated_without_mapping(self) -> None:
        old = schema("1", [make_field("state", "enum", enum=("a", "b"))])
        new = schema("2", [make_field("state", "enum", enum=("a",))])
        submission = make_submission(old, [make_answer("state", "b")])
        result = classify_submission(submission, old, new, make_plan(old, new))
        self.assertEqual(result.classification, "invalidated")

    def test_removed_enum_value_with_mapping_is_auto_migratable(self) -> None:
        old = schema("1", [make_field("state", "enum", enum=("a", "b"))])
        new = schema("2", [make_field("state", "enum", enum=("a", "c"))])
        submission = make_submission(old, [make_answer("state", "b")])
        plan = make_plan(old, new, value_mappings={"state": {"b": "c"}})
        result = classify_submission(submission, old, new, plan)
        self.assertEqual(result.classification, "auto_migratable")
        self.assertIn("EXPLICIT_VALUE_MAPPING", [item.code for item in result.reasons])

    def test_answered_rename_requires_explicit_mapping(self) -> None:
        old = schema("1", [make_field("old")])
        new = schema("2", [make_field("new", aliases=("old",))])
        submission = make_submission(old, [make_answer("old", "value")])
        no_plan = classify_submission(submission, old, new, make_plan(old, new))
        plan = make_plan(old, new, field_mappings={"old": "new"})
        mapped = classify_submission(submission, old, new, plan)
        self.assertEqual(no_plan.classification, "invalidated")
        self.assertEqual(mapped.classification, "auto_migratable")

    def test_unanswered_deleted_optional_field_is_compatible(self) -> None:
        old = schema("1", [make_field("old")])
        new = schema("2", [])
        submission = make_submission(old, [])
        result = classify_submission(submission, old, new, make_plan(old, new))
        self.assertEqual(result.classification, "compatible")

    def test_required_target_default_is_auto_migratable(self) -> None:
        old = schema("1", [])
        new = schema("2", [make_field("confirmed", "boolean", required=True)])
        submission = make_submission(old, [])
        plan = make_plan(old, new, defaults={"confirmed": True})
        result = classify_submission(submission, old, new, plan)
        self.assertEqual(result.classification, "auto_migratable")

    def test_invalid_target_default_invalidates(self) -> None:
        old = schema("1", [])
        new = schema("2", [make_field("count", "integer", required=True, minimum=1)])
        submission = make_submission(old, [])
        plan = make_plan(old, new, defaults={"count": 0})
        result = classify_submission(submission, old, new, plan)
        self.assertEqual(result.classification, "invalidated")
        self.assertIn("INVALID_MIGRATION_DEFAULT", [item.code for item in result.reasons])

    def test_requiredness_increase_is_compatible_when_value_exists(self) -> None:
        old = schema("1", [make_field("name")])
        new = schema("2", [make_field("name", required=True)])
        submission = make_submission(old, [make_answer("name", "Ada")])
        result = classify_submission(submission, old, new, make_plan(old, new))
        self.assertEqual(result.classification, "compatible")

    def test_missing_required_evidence_invalidates(self) -> None:
        old = schema("1", [make_field("condition")])
        new = schema(
            "2",
            [
                make_field(
                    "condition",
                    evidence_required=True,
                    evidence_count=1,
                    media_types=("image/jpeg",),
                )
            ],
        )
        submission = make_submission(old, [make_answer("condition", "ok")])
        result = classify_submission(submission, old, new, make_plan(old, new))
        self.assertEqual(result.classification, "invalidated")
        self.assertIn("MISSING_REQUIRED_EVIDENCE", [item.code for item in result.reasons])

    def test_attachment_follows_explicit_field_mapping(self) -> None:
        old = schema(
            "1",
            [
                make_field(
                    "photo_old",
                    evidence_required=True,
                    evidence_count=1,
                    media_types=("image/jpeg",),
                )
            ],
        )
        new = schema(
            "2",
            [
                make_field(
                    "photo_new",
                    evidence_required=True,
                    evidence_count=1,
                    media_types=("image/jpeg",),
                )
            ],
        )
        submission = make_submission(
            old,
            [make_answer("photo_old", "present")],
            attachments=[make_attachment("photo_old")],
        )
        plan = make_plan(old, new, field_mappings={"photo_old": "photo_new"})
        result = classify_submission(submission, old, new, plan)
        self.assertEqual(result.classification, "auto_migratable")
        self.assertIn("EXPLICIT_ATTACHMENT_MAPPING", [item.code for item in result.reasons])

    def test_rejected_attachment_media_type_invalidates(self) -> None:
        field = make_field(
            "photo",
            evidence_required=True,
            evidence_count=1,
            media_types=("image/jpeg",),
        )
        old = schema("1", [field])
        new = schema("2", [field])
        submission = make_submission(
            old,
            [make_answer("photo", "present")],
            attachments=[make_attachment("photo", media_type="image/png")],
        )
        result = classify_submission(submission, old, new, make_plan(old, new))
        self.assertEqual(result.classification, "invalidated")
        self.assertIn("EVIDENCE_MEDIA_TYPE_REJECTED", [item.code for item in result.reasons])

    def test_malformed_attachment_hash_invalidates(self) -> None:
        field = make_field("photo")
        old = schema("1", [field])
        new = schema("2", [field])
        submission = make_submission(
            old,
            [],
            attachments=[make_attachment("photo", digest="bad")],
        )
        result = classify_submission(submission, old, new, make_plan(old, new))
        self.assertEqual(result.classification, "invalidated")
        self.assertIn("INVALID_ATTACHMENT_DIGEST", [item.code for item in result.reasons])

    def test_obligation_change_requires_review_or_reviewed_ack(self) -> None:
        old = schema("1", [], obligation="old")
        new = schema("2", [], obligation="new")
        submission = make_submission(old, [])
        plain = classify_submission(submission, old, new, make_plan(old, new))
        acknowledged = classify_submission(
            submission,
            old,
            new,
            make_plan(
                old,
                new,
                acknowledge_obligation_change=True,
                reviewed_by="reviewer",
            ),
        )
        self.assertEqual(plain.classification, "review_required")
        self.assertEqual(acknowledged.classification, "auto_migratable")

    def test_expired_authorization_requires_review(self) -> None:
        field = make_field("name")
        old = schema("1", [field])
        new = schema("2", [field])
        submission = make_submission(
            old,
            [make_answer("name", "Ada")],
            auth_expires_at="2025-01-02T00:00:00Z",
        )
        result = classify_submission(
            submission,
            old,
            new,
            make_plan(old, new),
            now="2025-01-03T00:00:00Z",
        )
        self.assertEqual(result.classification, "review_required")
        self.assertIn("AUTH_EXPIRED", [item.code for item in result.reasons])

    def test_type_change_without_conversion_requires_review(self) -> None:
        old = schema("1", [make_field("count", "string")])
        new = schema("2", [make_field("count", "integer")])
        submission = make_submission(old, [make_answer("count", "12")])
        result = classify_submission(submission, old, new, make_plan(old, new))
        self.assertEqual(result.classification, "invalidated")
        codes = [item.code for item in result.reasons]
        self.assertIn("TYPE_CHANGE_WITHOUT_CONVERSION", codes)
        self.assertIn("TARGET_VALIDATION_FAILED", codes)

    def test_failed_explicit_conversion_invalidates(self) -> None:
        old = schema("1", [make_field("count", "string")])
        new = schema("2", [make_field("count", "integer")])
        submission = make_submission(old, [make_answer("count", "not-number")])
        plan = make_plan(old, new, conversions={"count": "string_to_integer"})
        result = classify_submission(submission, old, new, plan)
        self.assertEqual(result.classification, "invalidated")
        self.assertIn("CONVERSION_FAILED", [item.code for item in result.reasons])

    def test_capture_hash_mismatch_invalidates(self) -> None:
        old = schema("1", [])
        new = schema("2", [])
        submission = replace(make_submission(old, []), obligation_hash="wrong")
        result = classify_submission(submission, old, new, make_plan(old, new))
        self.assertEqual(result.classification, "invalidated")
        self.assertIn("CAPTURE_OBLIGATION_HASH_MISMATCH", [item.code for item in result.reasons])


if __name__ == "__main__":
    unittest.main()
