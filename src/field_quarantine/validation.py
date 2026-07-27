"""Value conversion and schema validation primitives."""

from __future__ import annotations

import math
import re
from datetime import date, datetime
from typing import Any, List, Mapping, Tuple

from .models import FieldDefinition


class ConversionError(ValueError):
    """Raised when an explicitly requested conversion cannot be completed."""


def apply_value_mapping(value: Any, mapping: Mapping[str, Any]) -> Tuple[Any, bool]:
    key = str(value)
    if key in mapping:
        return mapping[key], True
    return value, False


def convert_value(value: Any, conversion: str) -> Any:
    """Apply a named, explicit conversion.

    The deliberately small conversion vocabulary avoids locale-dependent or
    domain-specific interpretation.
    """

    if conversion in ("identity", "preserve"):
        return value
    if value is None:
        return None
    try:
        if conversion == "string_to_integer":
            if not isinstance(value, str) or not re.fullmatch(r"[+-]?\d+", value.strip()):
                raise ConversionError("value is not a base-10 integer string")
            return int(value.strip(), 10)
        if conversion == "string_to_number":
            if not isinstance(value, str):
                raise ConversionError("value is not a number string")
            result = float(value.strip())
            if not math.isfinite(result):
                raise ConversionError("number must be finite")
            return result
        if conversion == "string_to_boolean":
            if not isinstance(value, str):
                raise ConversionError("value is not a boolean string")
            normalized = value.strip().lower()
            if normalized in ("true", "1", "yes"):
                return True
            if normalized in ("false", "0", "no"):
                return False
            raise ConversionError("boolean string must be true/false, 1/0, or yes/no")
        if conversion in ("integer_to_string", "number_to_string", "boolean_to_string"):
            if conversion == "integer_to_string" and (
                not isinstance(value, int) or isinstance(value, bool)
            ):
                raise ConversionError("value is not an integer")
            if conversion == "number_to_string" and (
                not isinstance(value, (int, float)) or isinstance(value, bool)
            ):
                raise ConversionError("value is not a number")
            if conversion == "boolean_to_string" and not isinstance(value, bool):
                raise ConversionError("value is not a boolean")
            if isinstance(value, bool):
                return "true" if value else "false"
            return str(value)
        if conversion == "integer_to_number":
            if not isinstance(value, int) or isinstance(value, bool):
                raise ConversionError("value is not an integer")
            return value
        if conversion == "date_to_datetime_utc":
            if not isinstance(value, str):
                raise ConversionError("value is not an ISO date string")
            date.fromisoformat(value)
            return value + "T00:00:00Z"
    except (TypeError, ValueError, OverflowError) as exc:
        if isinstance(exc, ConversionError):
            raise
        raise ConversionError(str(exc)) from exc
    raise ConversionError(f"unsupported conversion: {conversion}")


def validate_value(field: FieldDefinition, value: Any) -> Tuple[str, ...]:
    """Return stable validation error codes for a field value."""

    errors: List[str] = []
    if value is None:
        if field.required:
            errors.append("required")
        return tuple(errors)

    field_type = field.field_type
    correct_type = True
    if field_type in ("string", "enum", "date", "datetime"):
        correct_type = isinstance(value, str)
    elif field_type == "integer":
        correct_type = isinstance(value, int) and not isinstance(value, bool)
    elif field_type == "number":
        correct_type = (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and (not isinstance(value, float) or math.isfinite(value))
        )
    elif field_type == "boolean":
        correct_type = isinstance(value, bool)
    elif field_type == "object":
        correct_type = isinstance(value, dict)
    elif field_type == "array":
        correct_type = isinstance(value, list)

    if not correct_type:
        return ("type",)

    if field_type == "date":
        try:
            date.fromisoformat(value)
        except ValueError:
            errors.append("date_format")
    elif field_type == "datetime":
        try:
            normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
            datetime.fromisoformat(normalized)
        except ValueError:
            errors.append("datetime_format")

    constraints = field.constraints
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if constraints.minimum is not None and value < constraints.minimum:
            errors.append("minimum")
        if constraints.maximum is not None and value > constraints.maximum:
            errors.append("maximum")
    if isinstance(value, (str, list, dict)):
        if constraints.min_length is not None and len(value) < constraints.min_length:
            errors.append("min_length")
        if constraints.max_length is not None and len(value) > constraints.max_length:
            errors.append("max_length")
    if constraints.pattern is not None and isinstance(value, str):
        try:
            if re.fullmatch(constraints.pattern, value) is None:
                errors.append("pattern")
        except re.error:
            errors.append("invalid_schema_pattern")
    if constraints.enum and value not in constraints.enum:
        errors.append("enum")
    return tuple(errors)
