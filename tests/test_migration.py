from __future__ import annotations

import unittest

from field_quarantine.migration import migrate_submission

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


class MigrationTests(unittest.TestCase):
    def test_success_updates_schema_and_hashes_without_mutating_source(self) -> None:
        field = make_field("name", required=True)
        old = schema("1", [field], obligation="o1", source="s1")
        new = schema("2", [field], obligation="o2", source="s2")
        submission = make_submission(old, [make_answer("name", "Ada")])
        before = submission.to_dict()
        plan = make_plan(
            old,
            new,
            acknowledge_obligation_change=True,
            acknowledge_source_change=True,
            reviewed_by="reviewer",
        )
        result = migrate_submission(
            submission,
            old,
            new,
            plan,
            migrated_at="2025-01-03T00:00:00Z",
        )
        self.assertEqual(result.status, "migrated")
        self.assertIsNotNone(result.submission)
        migrated = result.submission
        assert migrated is not None
        self.assertEqual(migrated.schema_version, "2")
        self.assertEqual(migrated.obligation_hash, "o2")
        self.assertEqual(migrated.source_hash, "s2")
        self.assertEqual(submission.to_dict(), before)

    def test_original_answers_are_exactly_preserved(self) -> None:
        old = schema("1", [make_field("old")])
        new = schema("2", [make_field("new")])
        answer = make_answer("old", "value")
        submission = make_submission(old, [answer])
        plan = make_plan(old, new, field_mappings={"old": "new"})
        result = migrate_submission(submission, old, new, plan)
        assert result.submission is not None
        self.assertEqual(result.submission.original_answers, (answer,))
        self.assertEqual(result.submission.original_answers[0].field_id, "old")
        self.assertEqual(result.submission.original_answers[0].provenance, answer.provenance)

    def test_explicit_mapping_is_authoritative_when_old_id_still_exists(self) -> None:
        old = schema("1", [make_field("source")])
        new = schema("2", [make_field("source"), make_field("destination")])
        submission = make_submission(old, [make_answer("source", "value")])
        plan = make_plan(old, new, field_mappings={"source": "destination"})
        result = migrate_submission(submission, old, new, plan)
        assert result.submission is not None
        self.assertEqual([item.field_id for item in result.submission.answers], ["destination"])

    def test_mapping_and_value_mapping_are_recorded_in_provenance(self) -> None:
        old = schema("1", [make_field("old", "enum", enum=("bad",))])
        new = schema("2", [make_field("new", "enum", enum=("review",))])
        submission = make_submission(old, [make_answer("old", "bad")])
        plan = make_plan(
            old,
            new,
            field_mappings={"old": "new"},
            value_mappings={"old": {"bad": "review"}},
        )
        result = migrate_submission(
            submission, old, new, plan, migrated_at="2025-01-03T00:00:00Z"
        )
        assert result.submission is not None
        current = result.submission.answers[0]
        self.assertEqual(current.field_id, "new")
        self.assertEqual(current.value, "review")
        chain = current.provenance["migration_chain"]
        self.assertTrue(chain[-1]["value_mapping_applied"])
        self.assertEqual(chain[-1]["source_field_id"], "old")
        self.assertEqual(chain[-1]["target_field_id"], "new")

    def test_explicit_default_has_non_capture_provenance(self) -> None:
        old = schema("1", [])
        new = schema("2", [make_field("confirmed", "boolean", required=True)])
        submission = make_submission(old, [])
        plan = make_plan(old, new, defaults={"confirmed": True})
        result = migrate_submission(
            submission, old, new, plan, migrated_at="2025-01-03T00:00:00Z"
        )
        assert result.submission is not None
        default = result.submission.answers[0]
        self.assertEqual(default.value, True)
        self.assertEqual(default.provenance["origin"], "migration_default")
        self.assertEqual(default.captured_at, "2025-01-03T00:00:00Z")

    def test_attachment_field_and_provenance_are_migrated(self) -> None:
        old_field = make_field(
            "old",
            evidence_required=True,
            evidence_count=1,
            media_types=("image/jpeg",),
        )
        new_field = make_field(
            "new",
            evidence_required=True,
            evidence_count=1,
            media_types=("image/jpeg",),
        )
        old = schema("1", [old_field])
        new = schema("2", [new_field])
        submission = make_submission(
            old,
            [make_answer("old", "yes")],
            attachments=[make_attachment("old")],
        )
        result = migrate_submission(
            submission,
            old,
            new,
            make_plan(old, new, field_mappings={"old": "new"}),
        )
        assert result.submission is not None
        attachment = result.submission.attachments[0]
        self.assertEqual(attachment.field_id, "new")
        self.assertEqual(attachment.provenance["original_field_id"], "old")

    def test_unsafe_migration_is_quarantined_with_task_and_audit(self) -> None:
        old = schema("1", [make_field("old")])
        new = schema("2", [])
        submission = make_submission(old, [make_answer("old", "keep me")])
        result = migrate_submission(submission, old, new, make_plan(old, new))
        self.assertEqual(result.status, "quarantined")
        self.assertIsNone(result.submission)
        self.assertTrue(result.tasks)
        self.assertEqual(result.audit_events[0].event_type, "migration_quarantined")

    def test_migration_output_identifiers_are_deterministic(self) -> None:
        old = schema("1", [make_field("old")])
        new = schema("2", [])
        submission = make_submission(old, [make_answer("old", "keep me")])
        plan = make_plan(old, new)
        first = migrate_submission(submission, old, new, plan)
        second = migrate_submission(submission, old, new, plan)
        self.assertEqual(first.to_dict(), second.to_dict())

    def test_second_migration_retains_first_capture_and_extends_history(self) -> None:
        first_schema = schema("1", [make_field("a")])
        second_schema = schema("2", [make_field("b")])
        third_schema = schema("3", [make_field("c")])
        original = make_submission(first_schema, [make_answer("a", "value")])
        first = migrate_submission(
            original,
            first_schema,
            second_schema,
            make_plan(first_schema, second_schema, field_mappings={"a": "b"}),
            migrated_at="2025-01-02T00:00:00Z",
        )
        assert first.submission is not None
        second = migrate_submission(
            first.submission,
            second_schema,
            third_schema,
            make_plan(second_schema, third_schema, field_mappings={"b": "c"}),
            migrated_at="2025-01-03T00:00:00Z",
        )
        assert second.submission is not None
        self.assertEqual(second.submission.original_answers, original.answers)
        self.assertEqual(len(second.submission.migration_history), 2)
        chain = second.submission.answers[0].provenance["migration_chain"]
        self.assertEqual(len(chain), 2)

    def test_migrated_answers_are_sorted_by_target_field_id(self) -> None:
        old = schema("1", [make_field("z"), make_field("a")])
        new = schema("2", [make_field("z"), make_field("a")])
        submission = make_submission(old, [make_answer("z", "one"), make_answer("a", "two")])
        result = migrate_submission(submission, old, new, make_plan(old, new))
        assert result.submission is not None
        self.assertEqual([item.field_id for item in result.submission.answers], ["a", "z"])


if __name__ == "__main__":
    unittest.main()
