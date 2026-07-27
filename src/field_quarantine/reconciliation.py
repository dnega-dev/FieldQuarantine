"""Reconnect-time reconciliation for pending and partially synchronized records."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .codec import stable_id
from .migration import migrate_submission
from .models import (
    AuditEvent,
    FormSchema,
    MigrationPlan,
    PendingSubmission,
    QuarantineReason,
    ReconciliationContext,
    ReconciliationResult,
    ReconciliationTask,
)


def _task(
    submission: PendingSubmission,
    action: str,
    message: str,
    field_id: Optional[str] = None,
    **details: Any,
) -> ReconciliationTask:
    identity = {
        "submission_id": submission.submission_id,
        "action": action,
        "field_id": field_id,
        "details": details,
    }
    return ReconciliationTask(
        task_id=stable_id("task", identity),
        action=action,
        message=message,
        submission_id=submission.submission_id,
        field_id=field_id,
        details=details,
    )


def _audit(
    submission: PendingSubmission,
    timestamp: str,
    actor: str,
    event_type: str,
    details: Dict[str, Any],
) -> AuditEvent:
    identity = {
        "submission_id": submission.submission_id,
        "timestamp": timestamp,
        "event_type": event_type,
        "details": details,
    }
    return AuditEvent(
        event_id=stable_id("audit", identity),
        timestamp=timestamp,
        event_type=event_type,
        actor=actor,
        submission_id=submission.submission_id,
        details=details,
    )


def reconcile_submission(
    submission: PendingSubmission,
    old: FormSchema,
    new: FormSchema,
    plan: Optional[MigrationPlan],
    context: ReconciliationContext,
) -> ReconciliationResult:
    """Reconcile a pending record after connectivity returns.

    Duplicate delivery identifiers are suppressed before migration so retries are
    idempotent.  Partial remote state is compared, never overwritten silently.
    """

    timestamp = context.now or submission.updated_at or submission.created_at
    if submission.delivery_id and submission.delivery_id in context.received_delivery_ids:
        event = _audit(
            submission,
            timestamp,
            context.actor,
            "duplicate_delivery_suppressed",
            {"delivery_id": submission.delivery_id},
        )
        return ReconciliationResult(
            submission_id=submission.submission_id,
            decision="already_delivered",
            classification="compatible",
            duplicate_delivery=True,
            tasks=(),
            quarantine_reasons=(),
            audit_events=(event,),
            migrated_submission=None,
        )

    migration = migrate_submission(
        submission,
        old,
        new,
        plan,
        migrated_at=timestamp,
        actor=context.actor,
        now=timestamp,
    )
    if migration.submission is None:
        event = _audit(
            submission,
            timestamp,
            context.actor,
            "reconciliation_quarantined",
            {
                "classification": migration.classification,
                "reason_codes": [item.code for item in migration.quarantine_reasons],
            },
        )
        return ReconciliationResult(
            submission_id=submission.submission_id,
            decision="quarantined",
            classification=migration.classification,
            duplicate_delivery=False,
            tasks=migration.tasks,
            quarantine_reasons=migration.quarantine_reasons,
            audit_events=migration.audit_events + (event,),
            migrated_submission=None,
        )

    migrated = migration.submission
    answer_map = {item.field_id: item.value for item in migrated.answers}
    tasks: List[ReconciliationTask] = []
    reasons: List[QuarantineReason] = []

    for field_id in sorted(context.remote_applied_fields):
        remote_value = context.remote_applied_fields[field_id]
        if field_id not in answer_map or answer_map[field_id] != remote_value:
            details = {
                "remote_value": remote_value,
                "local_value": answer_map.get(field_id),
                "local_field_present": field_id in answer_map,
            }
            reasons.append(
                QuarantineReason(
                    code="PARTIAL_SYNC_CONFLICT",
                    message="Remote partial state conflicts with the preserved local answer.",
                    field_id=field_id,
                    details=details,
                )
            )
            tasks.append(
                _task(
                    submission,
                    "resolve_partial_sync_conflict",
                    "Compare remote and local values; do not overwrite either automatically.",
                    field_id,
                    **details,
                )
            )

    uploaded_ids = set(context.uploaded_attachment_ids)
    for attachment in migrated.attachments:
        if attachment.status != "uploaded" and attachment.attachment_id not in uploaded_ids:
            tasks.append(
                _task(
                    submission,
                    "upload_attachment",
                    "Upload the preserved attachment bytes and verify the recorded SHA-256 digest.",
                    attachment.field_id,
                    attachment_id=attachment.attachment_id,
                    sha256=attachment.sha256,
                    size_bytes=attachment.size_bytes,
                )
            )

    if not submission.delivery_id:
        tasks.append(
            _task(
                submission,
                "assign_delivery_id",
                "Assign and persist an idempotency key before delivery.",
            )
        )

    if submission.sync_state == "partial" and not reasons:
        remote_fields = sorted(context.remote_applied_fields)
        tasks.append(
            _task(
                submission,
                "resume_partial_delivery",
                "Resume delivery for fields and attachments not already acknowledged remotely.",
                remote_applied_fields=remote_fields,
            )
        )

    tasks.sort(key=lambda item: (item.field_id or "", item.action, item.task_id))
    reasons.sort(key=lambda item: (item.field_id or "", item.code))
    if reasons:
        decision = "quarantined"
        classification = "review_required"
        event_type = "partial_sync_conflict_detected"
    elif tasks:
        decision = "tasks_pending"
        classification = migration.classification
        event_type = "reconciliation_tasks_created"
    else:
        decision = "ready_to_deliver"
        classification = migration.classification
        event_type = "reconciliation_ready"

    event = _audit(
        submission,
        timestamp,
        context.actor,
        event_type,
        {
            "decision": decision,
            "task_ids": [item.task_id for item in tasks],
            "reason_codes": [item.code for item in reasons],
        },
    )
    return ReconciliationResult(
        submission_id=submission.submission_id,
        decision=decision,
        classification=classification,
        duplicate_delivery=False,
        tasks=tuple(tasks),
        quarantine_reasons=tuple(reasons),
        audit_events=migration.audit_events + (event,),
        migrated_submission=migrated,
    )
