from __future__ import annotations

import unittest

from field_quarantine.schema_diff import diff_schemas

from helpers import make_field, make_plan, make_schema


def schema(version, fields, obligation="obl", source="src"):
    return make_schema(
        version,
        fields,
        obligation_hash=obligation,
        source_hash=source,
    )


class SchemaDiffTests(unittest.TestCase):
    def test_unchanged_fields_are_compatible(self) -> None:
        field = make_field("name")
        old = schema("1", [field])
        new = schema("2", [field])
        result = diff_schemas(old, new, make_plan(old, new))
        self.assertEqual(result.classification, "compatible")
        self.assertEqual(result.changes, ())

    def test_optional_field_addition_is_compatible(self) -> None:
        old = schema("1", [])
        new = schema("2", [make_field("notes")])
        result = diff_schemas(old, new, make_plan(old, new))
        self.assertEqual(result.classification, "compatible")
        self.assertEqual(result.changes[0].code, "optional_field_added")

    def test_required_field_addition_without_default_is_invalidated(self) -> None:
        old = schema("1", [])
        new = schema("2", [make_field("name", required=True)])
        result = diff_schemas(old, new, make_plan(old, new))
        self.assertEqual(result.classification, "invalidated")
        self.assertEqual(result.changes[0].code, "required_field_added")

    def test_required_field_addition_with_default_is_auto_migratable(self) -> None:
        old = schema("1", [])
        new = schema("2", [make_field("name", required=True)])
        plan = make_plan(old, new, defaults={"name": "unknown"})
        result = diff_schemas(old, new, plan)
        self.assertEqual(result.classification, "auto_migratable")

    def test_explicit_rename_is_auto_migratable(self) -> None:
        old = schema("1", [make_field("old_name")])
        new = schema("2", [make_field("new_name", aliases=("old_name",))])
        plan = make_plan(old, new, field_mappings={"old_name": "new_name"})
        result = diff_schemas(old, new, plan)
        self.assertEqual(result.classification, "auto_migratable")
        self.assertIn("field_renamed", [item.code for item in result.changes])

    def test_alias_without_explicit_mapping_requires_review(self) -> None:
        old = schema("1", [make_field("old_name")])
        new = schema("2", [make_field("new_name", aliases=("old_name",))])
        result = diff_schemas(old, new, make_plan(old, new))
        self.assertEqual(result.classification, "review_required")
        deleted = next(item for item in result.changes if item.code == "field_deleted_unmapped")
        self.assertIn("Alias candidates", deleted.message)

    def test_missing_mapping_target_invalidates_plan(self) -> None:
        old = schema("1", [make_field("old")])
        new = schema("2", [make_field("new")])
        plan = make_plan(old, new, field_mappings={"old": "absent"})
        result = diff_schemas(old, new, plan)
        self.assertEqual(result.classification, "invalidated")
        self.assertIn("mapping_target_missing", [item.code for item in result.changes])

    def test_mapping_collision_invalidates_plan(self) -> None:
        old = schema("1", [make_field("a"), make_field("b")])
        new = schema("2", [make_field("c")])
        plan = make_plan(old, new, field_mappings={"a": "c", "b": "c"})
        result = diff_schemas(old, new, plan)
        self.assertEqual(result.classification, "invalidated")
        self.assertIn("mapping_target_ambiguous", [item.code for item in result.changes])

    def test_explicit_mapping_cannot_collide_with_identity_mapping(self) -> None:
        old = schema("1", [make_field("a"), make_field("b")])
        new = schema("2", [make_field("a"), make_field("b")])
        plan = make_plan(old, new, field_mappings={"a": "b"})
        result = diff_schemas(old, new, plan)
        self.assertEqual(result.classification, "invalidated")
        self.assertIn("mapping_target_ambiguous", [item.code for item in result.changes])

    def test_enum_expansion_is_compatible(self) -> None:
        old = schema("1", [make_field("state", "enum", enum=("a",))])
        new = schema("2", [make_field("state", "enum", enum=("a", "b"))])
        result = diff_schemas(old, new, make_plan(old, new))
        self.assertEqual(result.classification, "compatible")
        self.assertEqual(result.changes[0].code, "enum_values_added")

    def test_enum_removal_requires_review(self) -> None:
        old = schema("1", [make_field("state", "enum", enum=("a", "b"))])
        new = schema("2", [make_field("state", "enum", enum=("a",))])
        result = diff_schemas(old, new, make_plan(old, new))
        self.assertEqual(result.classification, "review_required")
        self.assertEqual(result.changes[0].code, "enum_values_removed")

    def test_range_tightening_requires_review(self) -> None:
        old = schema("1", [make_field("score", "number", minimum=0, maximum=10)])
        new = schema("2", [make_field("score", "number", minimum=2, maximum=8)])
        result = diff_schemas(old, new, make_plan(old, new))
        self.assertEqual(result.classification, "review_required")
        codes = [item.code for item in result.changes]
        self.assertIn("validation_minimum_tightened", codes)
        self.assertIn("validation_maximum_tightened", codes)

    def test_range_relaxation_is_compatible(self) -> None:
        old = schema("1", [make_field("score", "number", minimum=2, maximum=8)])
        new = schema("2", [make_field("score", "number", minimum=0, maximum=10)])
        result = diff_schemas(old, new, make_plan(old, new))
        self.assertEqual(result.classification, "compatible")

    def test_evidence_tightening_requires_review(self) -> None:
        old = schema("1", [make_field("photo")])
        new = schema(
            "2",
            [
                make_field(
                    "photo",
                    evidence_required=True,
                    evidence_count=1,
                    media_types=("image/jpeg",),
                )
            ],
        )
        result = diff_schemas(old, new, make_plan(old, new))
        self.assertEqual(result.classification, "review_required")
        self.assertEqual(result.changes[0].code, "evidence_requirement_tightened")

    def test_obligation_hash_change_needs_reviewed_acknowledgement(self) -> None:
        old = schema("1", [], obligation="a")
        new = schema("2", [], obligation="b")
        unreviewed = make_plan(old, new, acknowledge_obligation_change=True)
        reviewed = make_plan(
            old,
            new,
            acknowledge_obligation_change=True,
            reviewed_by="reviewer",
        )
        self.assertEqual(diff_schemas(old, new, unreviewed).classification, "review_required")
        self.assertEqual(diff_schemas(old, new, reviewed).classification, "auto_migratable")

    def test_explicit_type_conversion_is_auto_migratable(self) -> None:
        old = schema("1", [make_field("count", "string")])
        new = schema("2", [make_field("count", "integer")])
        plan = make_plan(old, new, conversions={"count": "string_to_integer"})
        self.assertEqual(diff_schemas(old, new, plan).classification, "auto_migratable")

    def test_integer_to_number_is_compatible(self) -> None:
        old = schema("1", [make_field("count", "integer")])
        new = schema("2", [make_field("count", "number")])
        self.assertEqual(diff_schemas(old, new, make_plan(old, new)).classification, "compatible")


if __name__ == "__main__":
    unittest.main()
