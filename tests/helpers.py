from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional, Sequence

from field_quarantine.models import (
    Answer,
    AttachmentMetadata,
    EvidenceRequirement,
    FieldDefinition,
    FormSchema,
    MigrationPlan,
    PendingSubmission,
    ValidationConstraints,
)


def make_field(
    field_id: str,
    field_type: str = "string",
    required: bool = False,
    *,
    enum: Sequence[Any] = (),
    minimum: Optional[float] = None,
    maximum: Optional[float] = None,
    min_length: Optional[int] = None,
    max_length: Optional[int] = None,
    pattern: Optional[str] = None,
    evidence_required: bool = False,
    evidence_count: int = 0,
    media_types: Sequence[str] = (),
    aliases: Sequence[str] = (),
) -> FieldDefinition:
    return FieldDefinition(
        field_id=field_id,
        label=field_id.replace("_", " ").title(),
        field_type=field_type,
        required=required,
        constraints=ValidationConstraints(
            minimum=minimum,
            maximum=maximum,
            min_length=min_length,
            max_length=max_length,
            pattern=pattern,
            enum=tuple(enum),
        ),
        evidence=EvidenceRequirement(
            required=evidence_required,
            min_count=evidence_count,
            media_types=tuple(media_types),
        ),
        aliases=tuple(aliases),
    )


def make_schema(
    version: str,
    fields: Sequence[FieldDefinition],
    *,
    schema_id: str = "form",
    obligation_hash: Optional[str] = None,
    source_hash: Optional[str] = None,
) -> FormSchema:
    return FormSchema(
        schema_id=schema_id,
        version=version,
        fields=tuple(fields),
        obligation_hash=obligation_hash or f"obl-{version}",
        source_hash=source_hash or f"src-{version}",
        title="Test form",
    )


def make_answer(field_id: str, value: Any) -> Answer:
    return Answer(
        field_id=field_id,
        value=value,
        captured_at="2025-01-01T00:00:00Z",
        provenance={"device_id": "dev-1"},
    )


def make_attachment(
    field_id: str,
    *,
    attachment_id: str = "att-1",
    media_type: str = "image/jpeg",
    status: str = "local",
    digest: str = "a" * 64,
) -> AttachmentMetadata:
    return AttachmentMetadata(
        attachment_id=attachment_id,
        field_id=field_id,
        file_name="evidence.bin",
        media_type=media_type,
        size_bytes=12,
        sha256=digest,
        captured_at="2025-01-01T00:00:01Z",
        status=status,
        provenance={"device_id": "dev-1"},
    )


def make_submission(
    schema: FormSchema,
    answers: Sequence[Answer],
    *,
    attachments: Sequence[AttachmentMetadata] = (),
    auth_expires_at: Optional[str] = "2025-02-01T00:00:00Z",
    delivery_id: Optional[str] = "delivery-1",
    sync_state: str = "local_only",
) -> PendingSubmission:
    return PendingSubmission(
        submission_id="sub-1",
        schema_id=schema.schema_id,
        schema_version=schema.version,
        answers=tuple(answers),
        obligation_hash=schema.obligation_hash,
        source_hash=schema.source_hash,
        created_at="2025-01-01T00:00:00Z",
        updated_at="2025-01-01T00:01:00Z",
        auth_expires_at=auth_expires_at,
        delivery_id=delivery_id,
        sync_state=sync_state,
        attachments=tuple(attachments),
        metadata={"test": True},
    )


def make_plan(old: FormSchema, new: FormSchema, **overrides: Any) -> MigrationPlan:
    data = {
        "schema_id": old.schema_id,
        "from_version": old.version,
        "to_version": new.version,
    }
    data.update(overrides)
    return MigrationPlan.from_dict(data)
