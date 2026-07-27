"""Safe, auditable submission migration."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Dict, List, Optional, Tuple

from .classifier import classify_submission
from .codec import stable_id
from .models import (
    Answer,
    AttachmentMetadata,
    AuditEvent,
    FormSchema,
    MigrationPlan,
    MigrationResult,
    PendingSubmission,
    QuarantineReason,
    ReconciliationTask,
)
from .validation import apply_value_mapping, convert_value


def _action_for_reason(code: str) -> str:
    if code in ("AUTH_EXPIRED", "AUTH_EXPIRY_UNREADABLE"):
        return "renew_authorization"
    if "EVIDENCE" in code or "ATTACHMENT" in code:
        return "recapture_or_verify_evidence"
    if "OBLIGATION" in code or "SOURCE_HASH" in code:
        return "review_obligation_source_change"
    if "MAPPING" in code or "FIELD_DELETED" in code:
        return "define_or_correct_mapping"
    if "CONVERSION" in code or "TYPE_CHANGE" in code:
        return "define_or_correct_conversion"
    if "REQUIRED" in code or "VALIDATION" in code or "DEFAULT" in code:
        return "collect_or_review_answer"
    return "manual_review"


def tasks_for_reasons(
    submission_id: str, reasons: Tuple[QuarantineReason, ...]
) -> Tuple[ReconciliationTask, ...]:
    tasks: List[ReconciliationTask] = []
    for reason in reasons:
        action = _action_for_reason(reason.code)
        identity = {
            "submission_id": submission_id,
            "code": reason.code,
            "field_id": reason.field_id,
            "details": dict(reason.details),
        }
        tasks.append(
            ReconciliationTask(
                task_id=stable_id("task", identity),
                action=action,
                message=reason.message,
                submission_id=submission_id,
                field_id=reason.field_id,
                details={"reason_code": reason.code, **dict(reason.details)},
            )
        )
    tasks.sort(key=lambda item: (item.field_id or "", item.action, item.task_id))
    return tuple(tasks)


def _migrated_provenance(
    existing: Dict[str, Any],
    source_field_id: str,
    target_field_id: str,
    old: FormSchema,
    new: FormSchema,
    migrated_at: str,
    value_mapping_applied: bool,
    conversion: Optional[str],
) -> Dict[str, Any]:
    provenance = dict(existing)
    raw_chain = provenance.get("migration_chain", [])
    chain = list(raw_chain) if isinstance(raw_chain, list) else [{"legacy_value": raw_chain}]
    chain.append(
        {
            "from_schema_version": old.version,
            "to_schema_version": new.version,
            "source_field_id": source_field_id,
            "target_field_id": target_field_id,
            "value_mapping_applied": value_mapping_applied,
            "conversion": conversion,
            "migrated_at": migrated_at,
        }
    )
    provenance.setdefault("original_field_id", source_field_id)
    provenance.setdefault("original_schema_version", old.version)
    provenance["migration_chain"] = chain
    return provenance


def migrate_submission(
    submission: PendingSubmission,
    old: FormSchema,
    new: FormSchema,
    plan: Optional[MigrationPlan] = None,
    migrated_at: Optional[str] = None,
    actor: str = "field-quarantine",
    now: Optional[str] = None,
) -> MigrationResult:
    """Migrate a submission only when classification permits it.

    The source object is immutable.  ``original_answers`` is initialized from the
    exact captured answer records on the first migration and retained thereafter.
    """

    plan = plan or MigrationPlan(
        schema_id=old.schema_id,
        from_version=old.version,
        to_version=new.version,
    )
    migrated_at = migrated_at or submission.updated_at or submission.created_at
    classification = classify_submission(submission, old, new, plan, now=now)

    if classification.classification in ("review_required", "invalidated"):
        tasks = tasks_for_reasons(submission.submission_id, classification.reasons)
        details = {
            "classification": classification.classification,
            "reason_codes": [item.code for item in classification.reasons],
            "from_version": old.version,
            "to_version": new.version,
        }
        event = AuditEvent(
            event_id=stable_id(
                "audit",
                {
                    "event_type": "migration_quarantined",
                    "timestamp": migrated_at,
                    "submission_id": submission.submission_id,
                    "details": details,
                },
            ),
            timestamp=migrated_at,
            event_type="migration_quarantined",
            actor=actor,
            submission_id=submission.submission_id,
            details=details,
        )
        return MigrationResult(
            submission_id=submission.submission_id,
            status="quarantined",
            classification=classification.classification,
            submission=None,
            quarantine_reasons=classification.reasons,
            tasks=tasks,
            audit_events=(event,),
        )

    new_fields = new.field_map()
    answers: List[Answer] = []
    populated = set()
    for answer in sorted(submission.answers, key=lambda item: item.field_id):
        source_id = answer.field_id
        target_id = plan.field_mappings.get(source_id, source_id)
        value = answer.value
        value_mapping = plan.value_mappings.get(source_id, {})
        value, mapping_applied = apply_value_mapping(value, value_mapping)
        conversion = plan.conversions.get(source_id)
        if conversion:
            value = convert_value(value, conversion)
        provenance = _migrated_provenance(
            dict(answer.provenance),
            source_id,
            target_id,
            old,
            new,
            migrated_at,
            mapping_applied,
            conversion,
        )
        answers.append(
            Answer(
                field_id=target_id,
                value=value,
                captured_at=answer.captured_at,
                provenance=provenance,
            )
        )
        populated.add(target_id)

    for target_id in sorted(plan.defaults):
        if target_id in populated:
            continue
        answers.append(
            Answer(
                field_id=target_id,
                value=plan.defaults[target_id],
                captured_at=migrated_at,
                provenance={
                    "origin": "migration_default",
                    "original_field_id": None,
                    "original_schema_version": old.version,
                    "migration_chain": [
                        {
                            "from_schema_version": old.version,
                            "to_schema_version": new.version,
                            "source_field_id": None,
                            "target_field_id": target_id,
                            "value_mapping_applied": False,
                            "conversion": None,
                            "migrated_at": migrated_at,
                        }
                    ],
                },
            )
        )
    answers.sort(key=lambda item: item.field_id)

    attachments: List[AttachmentMetadata] = []
    for attachment in sorted(submission.attachments, key=lambda item: item.attachment_id):
        source_id = attachment.field_id
        target_id = plan.field_mappings.get(source_id, source_id)
        provenance = _migrated_provenance(
            dict(attachment.provenance),
            source_id,
            target_id,
            old,
            new,
            migrated_at,
            False,
            None,
        )
        attachments.append(replace(attachment, field_id=target_id, provenance=provenance))

    plan_snapshot = plan.to_dict()
    history_entry = {
        "from_version": old.version,
        "to_version": new.version,
        "from_obligation_hash": old.obligation_hash,
        "to_obligation_hash": new.obligation_hash,
        "from_source_hash": old.source_hash,
        "to_source_hash": new.source_hash,
        "migrated_at": migrated_at,
        "actor": actor,
        "plan": plan_snapshot,
        "classification": classification.classification,
    }
    migrated = PendingSubmission(
        submission_id=submission.submission_id,
        schema_id=new.schema_id,
        schema_version=new.version,
        answers=tuple(answers),
        obligation_hash=new.obligation_hash,
        source_hash=new.source_hash,
        created_at=submission.created_at,
        updated_at=migrated_at,
        auth_expires_at=submission.auth_expires_at,
        delivery_id=submission.delivery_id,
        sync_state="partial" if submission.sync_state == "partial" else "pending",
        attachments=tuple(attachments),
        original_answers=(
            submission.original_answers if submission.original_answers else submission.answers
        ),
        migration_history=submission.migration_history + (history_entry,),
        metadata=dict(submission.metadata),
    )

    details = {
        "classification": classification.classification,
        "from_version": old.version,
        "to_version": new.version,
        "answer_count": len(migrated.answers),
        "attachment_count": len(migrated.attachments),
        "plan_id": stable_id("plan", plan_snapshot),
    }
    event = AuditEvent(
        event_id=stable_id(
            "audit",
            {
                "event_type": "submission_migrated",
                "timestamp": migrated_at,
                "submission_id": submission.submission_id,
                "details": details,
            },
        ),
        timestamp=migrated_at,
        event_type="submission_migrated",
        actor=actor,
        submission_id=submission.submission_id,
        details=details,
    )
    return MigrationResult(
        submission_id=submission.submission_id,
        status="migrated",
        classification=classification.classification,
        submission=migrated,
        quarantine_reasons=(),
        tasks=(),
        audit_events=(event,),
    )
