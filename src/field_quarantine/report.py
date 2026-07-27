"""Deterministic plain-text reports for CLI and audit review."""

from __future__ import annotations

from typing import Iterable, List

from .models import (
    ClassificationResult,
    DiffResult,
    MigrationResult,
    ReconciliationResult,
)


def _value(value: object) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def diff_report(result: DiffResult) -> str:
    lines = [
        "Field Quarantine schema diff",
        f"Schema: {result.schema_id}",
        f"Versions: {result.from_version} -> {result.to_version}",
        f"Classification: {result.classification}",
        f"Changes: {len(result.changes)}",
    ]
    for item in result.changes:
        location = item.field_id or item.target_field_id or "schema"
        if item.field_id and item.target_field_id and item.field_id != item.target_field_id:
            location = f"{item.field_id} -> {item.target_field_id}"
        lines.append(
            f"- [{item.classification}] {item.code} ({location}): {item.message}"
        )
    return "\n".join(lines) + "\n"


def classification_report(result: ClassificationResult) -> str:
    lines = [
        "Field Quarantine submission classification",
        f"Submission: {result.submission_id}",
        f"Classification: {result.classification}",
        f"Reasons: {len(result.reasons)}",
    ]
    for item in result.reasons:
        location = f" ({item.field_id})" if item.field_id else ""
        lines.append(f"- {item.code}{location}: {item.message}")
    return "\n".join(lines) + "\n"


def migration_report(result: MigrationResult) -> str:
    lines = [
        "Field Quarantine migration",
        f"Submission: {result.submission_id}",
        f"Status: {result.status}",
        f"Classification: {result.classification}",
        f"Quarantine reasons: {len(result.quarantine_reasons)}",
        f"Reconciliation tasks: {len(result.tasks)}",
        f"Audit events: {len(result.audit_events)}",
    ]
    if result.submission:
        lines.extend(
            [
                f"Target schema version: {result.submission.schema_version}",
                f"Answers: {len(result.submission.answers)}",
                f"Attachments: {len(result.submission.attachments)}",
                f"Original answers preserved: {len(result.submission.original_answers)}",
            ]
        )
    for reason in result.quarantine_reasons:
        location = f" ({reason.field_id})" if reason.field_id else ""
        lines.append(f"- {reason.code}{location}: {reason.message}")
    return "\n".join(lines) + "\n"


def reconciliation_report(result: ReconciliationResult) -> str:
    lines = [
        "Field Quarantine reconciliation",
        f"Submission: {result.submission_id}",
        f"Decision: {result.decision}",
        f"Classification: {result.classification}",
        f"Duplicate delivery: {_value(result.duplicate_delivery)}",
        f"Tasks: {len(result.tasks)}",
        f"Quarantine reasons: {len(result.quarantine_reasons)}",
        f"Audit events: {len(result.audit_events)}",
    ]
    for item in result.tasks:
        location = f" ({item.field_id})" if item.field_id else ""
        lines.append(f"- {item.action}{location}: {item.message}")
    for item in result.quarantine_reasons:
        location = f" ({item.field_id})" if item.field_id else ""
        lines.append(f"- {item.code}{location}: {item.message}")
    return "\n".join(lines) + "\n"
