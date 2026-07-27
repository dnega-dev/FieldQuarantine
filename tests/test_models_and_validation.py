from __future__ import annotations

import unittest

from field_quarantine.codec import canonical_json, pretty_json, stable_id
from field_quarantine.models import (
    EvidenceRequirement,
    FormSchema,
    ModelError,
    PendingSubmission,
    ValidationConstraints,
)
from field_quarantine.validation import ConversionError, convert_value, validate_value

from helpers import make_answer, make_field, make_schema, make_submission


class ModelTests(unittest.TestCase):
    def test_invalid_numeric_constraint_range_is_rejected(self) -> None:
        with self.assertRaises(ModelError):
            ValidationConstraints(minimum=5, maximum=4)

    def test_required_evidence_implies_minimum_one(self) -> None:
        requirement = EvidenceRequirement(required=True)
        self.assertEqual(requirement.min_count, 1)

    def test_enum_field_requires_values(self) -> None:
        with self.assertRaises(ModelError):
            make_field("state", "enum")

    def test_schema_rejects_duplicate_field_ids(self) -> None:
        field = make_field("same")
        with self.assertRaises(ModelError):
            make_schema("1", [field, field])

    def test_submission_rejects_duplicate_answer_fields(self) -> None:
        schema = make_schema("1", [make_field("name")])
        with self.assertRaises(ModelError):
            make_submission(schema, [make_answer("name", "a"), make_answer("name", "b")])

    def test_schema_round_trip(self) -> None:
        schema = make_schema(
            "1",
            [make_field("score", "number", required=True, minimum=0, maximum=10)],
        )
        self.assertEqual(FormSchema.from_dict(schema.to_dict()), schema)

    def test_submission_round_trip(self) -> None:
        schema = make_schema("1", [make_field("name")])
        submission = make_submission(schema, [make_answer("name", "Ada")])
        self.assertEqual(PendingSubmission.from_dict(submission.to_dict()), submission)

    def test_canonical_json_and_stable_ids_are_deterministic(self) -> None:
        first = {"b": 2, "a": 1}
        second = {"a": 1, "b": 2}
        self.assertEqual(canonical_json(first), canonical_json(second))
        self.assertEqual(stable_id("x", first), stable_id("x", second))
        self.assertTrue(pretty_json(first).endswith("\n"))


class ValidationTests(unittest.TestCase):
    def test_boolean_is_not_accepted_as_integer(self) -> None:
        self.assertEqual(validate_value(make_field("count", "integer"), True), ("type",))

    def test_number_constraints_are_enforced(self) -> None:
        field = make_field("score", "number", minimum=1, maximum=5)
        self.assertEqual(validate_value(field, 0), ("minimum",))
        self.assertEqual(validate_value(field, 6), ("maximum",))
        self.assertEqual(validate_value(field, 3), ())

    def test_string_constraints_and_pattern_are_enforced(self) -> None:
        field = make_field("code", min_length=3, max_length=4, pattern=r"[A-Z]+")
        self.assertIn("min_length", validate_value(field, "a"))
        self.assertIn("pattern", validate_value(field, "abc"))
        self.assertEqual(validate_value(field, "ABC"), ())

    def test_enum_constraint_is_enforced(self) -> None:
        field = make_field("state", "enum", enum=("open", "closed"))
        self.assertEqual(validate_value(field, "other"), ("enum",))

    def test_named_conversions(self) -> None:
        self.assertEqual(convert_value("42", "string_to_integer"), 42)
        self.assertEqual(convert_value("false", "string_to_boolean"), False)
        self.assertEqual(convert_value(7, "integer_to_string"), "7")
        self.assertEqual(convert_value("2025-01-01", "date_to_datetime_utc"), "2025-01-01T00:00:00Z")

    def test_bad_conversion_fails_closed(self) -> None:
        with self.assertRaises(ConversionError):
            convert_value("4.2", "string_to_integer")
        with self.assertRaises(ConversionError):
            convert_value("x", "unknown")


if __name__ == "__main__":
    unittest.main()
