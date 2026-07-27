"""Submission-aware migration classification."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple

from .codec import is_expired
from .models import (
    ClassificationResult,
    FormSchema,
    MigrationPlan,
    PendingSubmission,
    QuarantineReason,
    classification_max,
)
from .schema_diff import diff_schemas, validate_plan
from .validation import ConversionError, apply_value_mapping, convert_value, validate_value


def _reason(
    code: str,
    message: str,
    field_id: Optional[str] = None,
    **details: Any,
) -> QuarantineReason:
    return QuarantineReason(code=code, message=message, field_id=field_id, details=details)


def _target_for(source_id: str, new: FormSchema, plan: MigrationPlan) -> Optional[str]:
    if source_id in plan.field_mappings:
        return plan.field_mappings[source_id]
    if source_id in new.field_map():
        return source_id
    return None


def _preview_value(source_id: str, value: Any, plan: MigrationPlan) -> Tuple[Any, bool, bool]:
    mapped = False
    converted = False
    value_mapping = plan.value_mappings.get(source_id, {})
    if value_mapping:
        value, mapped = apply_value_mapping(value, value_mapping)
    conversion = plan.conversions.get(source_id)
    if conversion:
        value = convert_value(value, conversion)
        converted = True
    return value, mapped, converted


def classify_submission(
    submission: PendingSubmission,
    old: FormSchema,
    new: FormSchema,
    plan: Optional[MigrationPlan] = None,
    now: Optional[str] = None,
) -> ClassificationResult:
    """Classify one pending submission against a schema transition.

    ``now`` is explicit rather than read from the system clock, keeping repeated
    classifications reproducible.
    """

    plan = plan or MigrationPlan(
        schema_id=old.schema_id,
        from_version=old.version,
        to_version=new.version,
    )
    diff = diff_schemas(old, new, plan)
    reasons: List[QuarantineReason] = []
    levels: List[str] = ["compatible"]

    def add(level: str, reason: QuarantineReason) -> None:
        levels.append(level)
        reasons.append(reason)

    for issue in validate_plan(old, new, plan):
        add(
            "invalidated",
            _reason(issue.code.upper(), issue.message, issue.field_id),
        )

    if submission.schema_id != old.schema_id:
        add(
            "invalidated",
            _reason(
                "SUBMISSION_SCHEMA_MISMATCH",
                "Submission schema_id does not match the source schema.",
                submission_schema_id=submission.schema_id,
                expected_schema_id=old.schema_id,
            ),
        )
    if submission.schema_version != old.version:
        add(
            "invalidated",
            _reason(
                "SUBMISSION_VERSION_MISMATCH",
                "Submission schema_version does not match the source schema.",
                submission_version=submission.schema_version,
                expected_version=old.version,
            ),
        )
    if submission.obligation_hash != old.obligation_hash:
        add(
            "invalidated",
            _reason(
                "CAPTURE_OBLIGATION_HASH_MISMATCH",
                "Captured obligation hash does not match its declared source schema.",
                captured=submission.obligation_hash,
                expected=old.obligation_hash,
            ),
        )
    if submission.source_hash != old.source_hash:
        add(
            "invalidated",
            _reason(
                "CAPTURE_SOURCE_HASH_MISMATCH",
                "Captured source hash does not match its declared source schema.",
                captured=submission.source_hash,
                expected=old.source_hash,
            ),
        )

    if old.schema_id != new.schema_id:
        add(
            "invalidated",
            _reason(
                "TARGET_SCHEMA_MISMATCH",
                "Cross-schema migration is forbidden.",
                source=old.schema_id,
                target=new.schema_id,
            ),
        )

    if old.obligation_hash != new.obligation_hash:
        if plan.acknowledge_obligation_change and plan.reviewed_by:
            add(
                "auto_migratable",
                _reason(
                    "OBLIGATION_CHANGE_ACKNOWLEDGED",
                    "Reviewed obligation change is recorded in the migration plan.",
                    reviewer=plan.reviewed_by,
                ),
            )
        else:
            add(
                "review_required",
                _reason(
                    "OBLIGATION_HASH_CHANGED",
                    "Obligation mapping changed and requires reviewed acknowledgement.",
                    before=old.obligation_hash,
                    after=new.obligation_hash,
                ),
            )
    if old.source_hash != new.source_hash:
        if plan.acknowledge_source_change and plan.reviewed_by:
            add(
                "auto_migratable",
                _reason(
                    "SOURCE_CHANGE_ACKNOWLEDGED",
                    "Reviewed source change is recorded in the migration plan.",
                    reviewer=plan.reviewed_by,
                ),
            )
        else:
            add(
                "review_required",
                _reason(
                    "SOURCE_HASH_CHANGED",
                    "Source material changed and requires reviewed acknowledgement.",
                    before=old.source_hash,
                    after=new.source_hash,
                ),
            )

    old_fields = old.field_map()
    new_fields = new.field_map()
    answer_targets: Dict[str, Any] = {}
    touched_targets: Set[str] = set()

    for answer in sorted(submission.answers, key=lambda item: item.field_id):
        source_id = answer.field_id
        old_field = old_fields.get(source_id)
        if old_field is None:
            add(
                "invalidated",
                _reason(
                    "UNKNOWN_SOURCE_FIELD",
                    "Submission contains an answer not declared by its source schema.",
                    source_id,
                ),
            )
            continue
        target_id = _target_for(source_id, new, plan)
        if not target_id or target_id not in new_fields:
            add(
                "invalidated",
                _reason(
                    "ANSWER_FIELD_DELETED_UNMAPPED",
                    "Answered field was deleted without an explicit mapping; dropping it is forbidden.",
                    source_id,
                ),
            )
            continue
        if target_id in touched_targets:
            add(
                "invalidated",
                _reason(
                    "ANSWER_MAPPING_COLLISION",
                    "Multiple answers would populate one target field.",
                    source_id,
                    target_field_id=target_id,
                ),
            )
            continue
        touched_targets.add(target_id)

        if target_id != source_id:
            add(
                "auto_migratable",
                _reason(
                    "EXPLICIT_FIELD_MAPPING",
                    "Answer can be moved using the explicit field mapping.",
                    source_id,
                    target_field_id=target_id,
                ),
            )

        try:
            value, mapped, converted = _preview_value(source_id, answer.value, plan)
        except ConversionError as exc:
            add(
                "invalidated",
                _reason(
                    "CONVERSION_FAILED",
                    f"Explicit conversion failed: {exc}",
                    source_id,
                    conversion=plan.conversions.get(source_id),
                ),
            )
            continue

        target_field = new_fields[target_id]
        if old_field.field_type != target_field.field_type:
            safe_widening = old_field.field_type == "integer" and target_field.field_type == "number"
            if converted:
                add(
                    "auto_migratable",
                    _reason(
                        "EXPLICIT_TYPE_CONVERSION",
                        "Type change uses the declared conversion.",
                        source_id,
                        target_field_id=target_id,
                        conversion=plan.conversions[source_id],
                    ),
                )
            elif not safe_widening:
                add(
                    "review_required",
                    _reason(
                        "TYPE_CHANGE_WITHOUT_CONVERSION",
                        "Type changed without an explicit conversion; the value will not be reinterpreted.",
                        source_id,
                        before=old_field.field_type,
                        after=target_field.field_type,
                    ),
                )
        if mapped:
            add(
                "auto_migratable",
                _reason(
                    "EXPLICIT_VALUE_MAPPING",
                    "Value can be changed using an explicit value mapping.",
                    source_id,
                    target_field_id=target_id,
                    original_value=answer.value,
                    mapped_value=value,
                ),
            )

        errors = validate_value(target_field, value)
        if errors:
            add(
                "invalidated",
                _reason(
                    "TARGET_VALIDATION_FAILED",
                    "Answer does not satisfy the target field constraints.",
                    source_id,
                    target_field_id=target_id,
                    errors=list(errors),
                    value=value,
                ),
            )
        answer_targets[target_id] = value

    for target_id in sorted(new_fields):
        target_field = new_fields[target_id]
        if target_id in answer_targets:
            continue
        if target_id in plan.defaults:
            default = plan.defaults[target_id]
            errors = validate_value(target_field, default)
            if errors:
                add(
                    "invalidated",
                    _reason(
                        "INVALID_MIGRATION_DEFAULT",
                        "Explicit default does not satisfy the target field.",
                        target_id,
                        errors=list(errors),
                        value=default,
                    ),
                )
            else:
                add(
                    "auto_migratable",
                    _reason(
                        "EXPLICIT_DEFAULT",
                        "Missing target answer can be populated from the declared default.",
                        target_id,
                        value=default,
                    ),
                )
                answer_targets[target_id] = default
        elif target_field.required:
            add(
                "invalidated",
                _reason(
                    "MISSING_REQUIRED_TARGET_FIELD",
                    "Target schema requires a value that was not captured and has no explicit default.",
                    target_id,
                ),
            )

    attachments_by_target: Dict[str, List[Any]] = {}
    attachment_ids: Set[str] = set()
    for attachment in sorted(submission.attachments, key=lambda item: item.attachment_id):
        if attachment.attachment_id in attachment_ids:
            add(
                "invalidated",
                _reason(
                    "DUPLICATE_ATTACHMENT_ID",
                    "Attachment identifiers must be unique.",
                    attachment.field_id,
                    attachment_id=attachment.attachment_id,
                ),
            )
        attachment_ids.add(attachment.attachment_id)
        if not re.fullmatch(r"[0-9a-fA-F]{64}", attachment.sha256):
            add(
                "invalidated",
                _reason(
                    "INVALID_ATTACHMENT_DIGEST",
                    "Attachment metadata must contain a 64-character SHA-256 digest.",
                    attachment.field_id,
                    attachment_id=attachment.attachment_id,
                ),
            )
        if attachment.field_id not in old_fields:
            add(
                "invalidated",
                _reason(
                    "UNKNOWN_ATTACHMENT_FIELD",
                    "Attachment references a field absent from the source schema.",
                    attachment.field_id,
                    attachment_id=attachment.attachment_id,
                ),
            )
            continue
        target_id = _target_for(attachment.field_id, new, plan)
        if not target_id or target_id not in new_fields:
            add(
                "invalidated",
                _reason(
                    "ATTACHMENT_FIELD_DELETED_UNMAPPED",
                    "Attachment field was deleted without an explicit mapping.",
                    attachment.field_id,
                    attachment_id=attachment.attachment_id,
                ),
            )
            continue
        attachments_by_target.setdefault(target_id, []).append(attachment)
        if target_id != attachment.field_id:
            add(
                "auto_migratable",
                _reason(
                    "EXPLICIT_ATTACHMENT_MAPPING",
                    "Attachment association can be moved with its explicitly mapped field.",
                    attachment.field_id,
                    attachment_id=attachment.attachment_id,
                    target_field_id=target_id,
                ),
            )

    for target_id in sorted(new_fields):
        requirement = new_fields[target_id].evidence
        attached = attachments_by_target.get(target_id, [])
        if requirement.min_count and len(attached) < requirement.min_count:
            add(
                "invalidated",
                _reason(
                    "MISSING_REQUIRED_EVIDENCE",
                    "Captured attachments do not meet the target evidence count.",
                    target_id,
                    required_count=requirement.min_count,
                    captured_count=len(attached),
                ),
            )
        if requirement.media_types:
            invalid_media = sorted(
                {
                    item.media_type
                    for item in attached
                    if item.media_type not in requirement.media_types
                }
            )
            if invalid_media:
                add(
                    "invalidated",
                    _reason(
                        "EVIDENCE_MEDIA_TYPE_REJECTED",
                        "One or more attachments use a media type rejected by the target schema.",
                        target_id,
                        rejected_media_types=invalid_media,
                    ),
                )

    if submission.auth_expires_at and now:
        try:
            expired = is_expired(submission.auth_expires_at, now)
        except ValueError:
            add(
                "review_required",
                _reason(
                    "AUTH_EXPIRY_UNREADABLE",
                    "Authorization expiry timestamp could not be parsed.",
                    value=submission.auth_expires_at,
                ),
            )
        else:
            if expired:
                add(
                    "review_required",
                    _reason(
                        "AUTH_EXPIRED",
                        "Authorization expired while the submission was offline; reauthorization is required.",
                        expired_at=submission.auth_expires_at,
                        evaluated_at=now,
                    ),
                )

    reasons.sort(key=lambda item: (item.field_id or "", item.code, repr(sorted(item.details.items()))))
    return ClassificationResult(
        submission_id=submission.submission_id,
        classification=classification_max(levels),
        reasons=tuple(reasons),
        changes=diff.changes,
    )
