"""Core data models for Field Quarantine.

The models deliberately use only the Python standard library.  Every model has a
stable JSON representation so records can be audited and exchanged between an
offline client and a reconciliation service.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


CLASSIFICATIONS: Tuple[str, ...] = (
    "compatible",
    "auto_migratable",
    "review_required",
    "invalidated",
)
FIELD_TYPES: Tuple[str, ...] = (
    "string",
    "integer",
    "number",
    "boolean",
    "date",
    "datetime",
    "enum",
    "object",
    "array",
)
SYNC_STATES: Tuple[str, ...] = ("local_only", "pending", "partial", "delivered")


class ModelError(ValueError):
    """Raised when an input record is structurally invalid."""


def _tuple_strings(value: Optional[Iterable[Any]], name: str) -> Tuple[str, ...]:
    if value is None:
        return ()
    result = tuple(str(item) for item in value)
    if any(not item for item in result):
        raise ModelError(f"{name} may not contain empty values")
    return result


def _dict(value: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    return dict(value or {})


@dataclass(frozen=True)
class ValidationConstraints:
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    min_length: Optional[int] = None
    max_length: Optional[int] = None
    pattern: Optional[str] = None
    enum: Tuple[Any, ...] = ()

    def __post_init__(self) -> None:
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ModelError("minimum must not exceed maximum")
        if self.min_length is not None and self.min_length < 0:
            raise ModelError("min_length must be non-negative")
        if self.max_length is not None and self.max_length < 0:
            raise ModelError("max_length must be non-negative")
        if (
            self.min_length is not None
            and self.max_length is not None
            and self.min_length > self.max_length
        ):
            raise ModelError("min_length must not exceed max_length")
        if len({repr(item) for item in self.enum}) != len(self.enum):
            raise ModelError("enum values must be unique")

    @classmethod
    def from_dict(cls, data: Optional[Mapping[str, Any]]) -> "ValidationConstraints":
        data = data or {}
        return cls(
            minimum=data.get("minimum"),
            maximum=data.get("maximum"),
            min_length=data.get("min_length"),
            max_length=data.get("max_length"),
            pattern=data.get("pattern"),
            enum=tuple(data.get("enum", ())),
        )

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for name in ("minimum", "maximum", "min_length", "max_length", "pattern"):
            value = getattr(self, name)
            if value is not None:
                result[name] = value
        if self.enum:
            result["enum"] = list(self.enum)
        return result


@dataclass(frozen=True)
class EvidenceRequirement:
    required: bool = False
    min_count: int = 0
    media_types: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.min_count < 0:
            raise ModelError("evidence min_count must be non-negative")
        if self.required and self.min_count < 1:
            object.__setattr__(self, "min_count", 1)

    @classmethod
    def from_dict(cls, data: Optional[Mapping[str, Any]]) -> "EvidenceRequirement":
        data = data or {}
        return cls(
            required=bool(data.get("required", False)),
            min_count=int(data.get("min_count", 0)),
            media_types=_tuple_strings(data.get("media_types"), "media_types"),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "required": self.required,
            "min_count": self.min_count,
            "media_types": list(self.media_types),
        }


@dataclass(frozen=True)
class FieldDefinition:
    field_id: str
    label: str
    field_type: str
    required: bool = False
    constraints: ValidationConstraints = field(default_factory=ValidationConstraints)
    evidence: EvidenceRequirement = field(default_factory=EvidenceRequirement)
    aliases: Tuple[str, ...] = ()
    description: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.field_id:
            raise ModelError("field_id is required")
        if not self.label:
            raise ModelError(f"label is required for field {self.field_id}")
        if self.field_type not in FIELD_TYPES:
            raise ModelError(f"unsupported field type: {self.field_type}")
        if self.field_type == "enum" and not self.constraints.enum:
            raise ModelError(f"enum field {self.field_id} requires enum constraints")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FieldDefinition":
        return cls(
            field_id=str(data["field_id"]),
            label=str(data.get("label", data["field_id"])),
            field_type=str(data.get("type", data.get("field_type", "string"))),
            required=bool(data.get("required", False)),
            constraints=ValidationConstraints.from_dict(data.get("constraints")),
            evidence=EvidenceRequirement.from_dict(data.get("evidence")),
            aliases=_tuple_strings(data.get("aliases"), "aliases"),
            description=data.get("description"),
        )

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "field_id": self.field_id,
            "label": self.label,
            "type": self.field_type,
            "required": self.required,
            "constraints": self.constraints.to_dict(),
            "evidence": self.evidence.to_dict(),
            "aliases": list(self.aliases),
        }
        if self.description is not None:
            result["description"] = self.description
        return result


@dataclass(frozen=True)
class FormSchema:
    schema_id: str
    version: str
    fields: Tuple[FieldDefinition, ...]
    obligation_hash: str
    source_hash: str
    title: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.schema_id or not self.version:
            raise ModelError("schema_id and version are required")
        ids = [item.field_id for item in self.fields]
        if len(ids) != len(set(ids)):
            raise ModelError("field_id values must be unique")
        aliases: List[str] = []
        for item in self.fields:
            aliases.extend(item.aliases)
        if set(ids).intersection(aliases):
            raise ModelError("field aliases may not shadow field ids")
        if not self.obligation_hash or not self.source_hash:
            raise ModelError("obligation_hash and source_hash are required")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FormSchema":
        return cls(
            schema_id=str(data["schema_id"]),
            version=str(data["version"]),
            fields=tuple(FieldDefinition.from_dict(item) for item in data.get("fields", ())),
            obligation_hash=str(data["obligation_hash"]),
            source_hash=str(data["source_hash"]),
            title=str(data.get("title", "")),
            metadata=_dict(data.get("metadata")),
        )

    def field_map(self) -> Dict[str, FieldDefinition]:
        return {item.field_id: item for item in self.fields}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_id": self.schema_id,
            "version": self.version,
            "title": self.title,
            "obligation_hash": self.obligation_hash,
            "source_hash": self.source_hash,
            "fields": [item.to_dict() for item in self.fields],
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class Answer:
    field_id: str
    value: Any
    captured_at: str
    provenance: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Answer":
        return cls(
            field_id=str(data["field_id"]),
            value=data.get("value"),
            captured_at=str(data.get("captured_at", "")),
            provenance=_dict(data.get("provenance")),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "field_id": self.field_id,
            "value": self.value,
            "captured_at": self.captured_at,
            "provenance": dict(self.provenance),
        }


@dataclass(frozen=True)
class AttachmentMetadata:
    attachment_id: str
    field_id: str
    file_name: str
    media_type: str
    size_bytes: int
    sha256: str
    captured_at: str
    status: str = "local"
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.attachment_id or not self.field_id:
            raise ModelError("attachment_id and field_id are required")
        if self.size_bytes < 0:
            raise ModelError("attachment size_bytes must be non-negative")
        if self.status not in ("local", "queued", "uploaded", "failed"):
            raise ModelError(f"unsupported attachment status: {self.status}")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AttachmentMetadata":
        return cls(
            attachment_id=str(data["attachment_id"]),
            field_id=str(data["field_id"]),
            file_name=str(data.get("file_name", "")),
            media_type=str(data.get("media_type", "application/octet-stream")),
            size_bytes=int(data.get("size_bytes", 0)),
            sha256=str(data.get("sha256", "")),
            captured_at=str(data.get("captured_at", "")),
            status=str(data.get("status", "local")),
            provenance=_dict(data.get("provenance")),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "attachment_id": self.attachment_id,
            "field_id": self.field_id,
            "file_name": self.file_name,
            "media_type": self.media_type,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "captured_at": self.captured_at,
            "status": self.status,
            "provenance": dict(self.provenance),
        }


@dataclass(frozen=True)
class PendingSubmission:
    submission_id: str
    schema_id: str
    schema_version: str
    answers: Tuple[Answer, ...]
    obligation_hash: str
    source_hash: str
    created_at: str
    updated_at: str
    auth_expires_at: Optional[str] = None
    delivery_id: Optional[str] = None
    sync_state: str = "local_only"
    attachments: Tuple[AttachmentMetadata, ...] = ()
    original_answers: Tuple[Answer, ...] = ()
    migration_history: Tuple[Mapping[str, Any], ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.submission_id or not self.schema_id or not self.schema_version:
            raise ModelError("submission_id, schema_id, and schema_version are required")
        ids = [answer.field_id for answer in self.answers]
        if len(ids) != len(set(ids)):
            raise ModelError("a submission may contain only one answer per field")
        attachment_ids = [item.attachment_id for item in self.attachments]
        if len(attachment_ids) != len(set(attachment_ids)):
            raise ModelError("attachment_id values must be unique")
        if self.sync_state not in SYNC_STATES:
            raise ModelError(f"unsupported sync_state: {self.sync_state}")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PendingSubmission":
        return cls(
            submission_id=str(data["submission_id"]),
            schema_id=str(data["schema_id"]),
            schema_version=str(data["schema_version"]),
            answers=tuple(Answer.from_dict(item) for item in data.get("answers", ())),
            obligation_hash=str(data["obligation_hash"]),
            source_hash=str(data["source_hash"]),
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
            auth_expires_at=data.get("auth_expires_at"),
            delivery_id=data.get("delivery_id"),
            sync_state=str(data.get("sync_state", "local_only")),
            attachments=tuple(
                AttachmentMetadata.from_dict(item) for item in data.get("attachments", ())
            ),
            original_answers=tuple(
                Answer.from_dict(item) for item in data.get("original_answers", ())
            ),
            migration_history=tuple(dict(item) for item in data.get("migration_history", ())),
            metadata=_dict(data.get("metadata")),
        )

    def answer_map(self) -> Dict[str, Answer]:
        return {item.field_id: item for item in self.answers}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "submission_id": self.submission_id,
            "schema_id": self.schema_id,
            "schema_version": self.schema_version,
            "answers": [item.to_dict() for item in self.answers],
            "obligation_hash": self.obligation_hash,
            "source_hash": self.source_hash,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "auth_expires_at": self.auth_expires_at,
            "delivery_id": self.delivery_id,
            "sync_state": self.sync_state,
            "attachments": [item.to_dict() for item in self.attachments],
            "original_answers": [item.to_dict() for item in self.original_answers],
            "migration_history": [dict(item) for item in self.migration_history],
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class MigrationPlan:
    schema_id: str
    from_version: str
    to_version: str
    field_mappings: Mapping[str, str] = field(default_factory=dict)
    value_mappings: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    defaults: Mapping[str, Any] = field(default_factory=dict)
    conversions: Mapping[str, str] = field(default_factory=dict)
    acknowledge_obligation_change: bool = False
    acknowledge_source_change: bool = False
    reviewed_by: Optional[str] = None
    note: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Optional[Mapping[str, Any]]) -> "MigrationPlan":
        data = data or {}
        return cls(
            schema_id=str(data.get("schema_id", "")),
            from_version=str(data.get("from_version", "")),
            to_version=str(data.get("to_version", "")),
            field_mappings={str(k): str(v) for k, v in data.get("field_mappings", {}).items()},
            value_mappings={
                str(field_id): {str(k): v for k, v in mapping.items()}
                for field_id, mapping in data.get("value_mappings", {}).items()
            },
            defaults=dict(data.get("defaults", {})),
            conversions={str(k): str(v) for k, v in data.get("conversions", {}).items()},
            acknowledge_obligation_change=bool(
                data.get("acknowledge_obligation_change", False)
            ),
            acknowledge_source_change=bool(data.get("acknowledge_source_change", False)),
            reviewed_by=data.get("reviewed_by"),
            note=data.get("note"),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_id": self.schema_id,
            "from_version": self.from_version,
            "to_version": self.to_version,
            "field_mappings": dict(self.field_mappings),
            "value_mappings": {
                key: dict(value) for key, value in self.value_mappings.items()
            },
            "defaults": dict(self.defaults),
            "conversions": dict(self.conversions),
            "acknowledge_obligation_change": self.acknowledge_obligation_change,
            "acknowledge_source_change": self.acknowledge_source_change,
            "reviewed_by": self.reviewed_by,
            "note": self.note,
        }


@dataclass(frozen=True)
class SchemaChange:
    code: str
    classification: str
    message: str
    field_id: Optional[str] = None
    target_field_id: Optional[str] = None
    before: Any = None
    after: Any = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "classification": self.classification,
            "message": self.message,
            "field_id": self.field_id,
            "target_field_id": self.target_field_id,
            "before": self.before,
            "after": self.after,
        }


@dataclass(frozen=True)
class QuarantineReason:
    code: str
    message: str
    field_id: Optional[str] = None
    details: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "field_id": self.field_id,
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class ReconciliationTask:
    task_id: str
    action: str
    message: str
    submission_id: str
    field_id: Optional[str] = None
    status: str = "open"
    details: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "action": self.action,
            "message": self.message,
            "submission_id": self.submission_id,
            "field_id": self.field_id,
            "status": self.status,
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class AuditEvent:
    event_id: str
    timestamp: str
    event_type: str
    actor: str
    submission_id: str
    details: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "actor": self.actor,
            "submission_id": self.submission_id,
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class DiffResult:
    schema_id: str
    from_version: str
    to_version: str
    classification: str
    changes: Tuple[SchemaChange, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_id": self.schema_id,
            "from_version": self.from_version,
            "to_version": self.to_version,
            "classification": self.classification,
            "changes": [item.to_dict() for item in self.changes],
        }


@dataclass(frozen=True)
class ClassificationResult:
    submission_id: str
    classification: str
    reasons: Tuple[QuarantineReason, ...]
    changes: Tuple[SchemaChange, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "submission_id": self.submission_id,
            "classification": self.classification,
            "reasons": [item.to_dict() for item in self.reasons],
            "changes": [item.to_dict() for item in self.changes],
        }


@dataclass(frozen=True)
class MigrationResult:
    submission_id: str
    status: str
    classification: str
    submission: Optional[PendingSubmission]
    quarantine_reasons: Tuple[QuarantineReason, ...]
    tasks: Tuple[ReconciliationTask, ...]
    audit_events: Tuple[AuditEvent, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "submission_id": self.submission_id,
            "status": self.status,
            "classification": self.classification,
            "submission": self.submission.to_dict() if self.submission else None,
            "quarantine_reasons": [item.to_dict() for item in self.quarantine_reasons],
            "tasks": [item.to_dict() for item in self.tasks],
            "audit_events": [item.to_dict() for item in self.audit_events],
        }


@dataclass(frozen=True)
class ReconciliationContext:
    now: str
    received_delivery_ids: Tuple[str, ...] = ()
    remote_applied_fields: Mapping[str, Any] = field(default_factory=dict)
    uploaded_attachment_ids: Tuple[str, ...] = ()
    actor: str = "reconciler"

    @classmethod
    def from_dict(cls, data: Optional[Mapping[str, Any]]) -> "ReconciliationContext":
        data = data or {}
        return cls(
            now=str(data.get("now", "")),
            received_delivery_ids=_tuple_strings(
                data.get("received_delivery_ids"), "received_delivery_ids"
            ),
            remote_applied_fields=_dict(data.get("remote_applied_fields")),
            uploaded_attachment_ids=_tuple_strings(
                data.get("uploaded_attachment_ids"), "uploaded_attachment_ids"
            ),
            actor=str(data.get("actor", "reconciler")),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "now": self.now,
            "received_delivery_ids": list(self.received_delivery_ids),
            "remote_applied_fields": dict(self.remote_applied_fields),
            "uploaded_attachment_ids": list(self.uploaded_attachment_ids),
            "actor": self.actor,
        }


@dataclass(frozen=True)
class ReconciliationResult:
    submission_id: str
    decision: str
    classification: str
    duplicate_delivery: bool
    tasks: Tuple[ReconciliationTask, ...]
    quarantine_reasons: Tuple[QuarantineReason, ...]
    audit_events: Tuple[AuditEvent, ...]
    migrated_submission: Optional[PendingSubmission] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "submission_id": self.submission_id,
            "decision": self.decision,
            "classification": self.classification,
            "duplicate_delivery": self.duplicate_delivery,
            "tasks": [item.to_dict() for item in self.tasks],
            "quarantine_reasons": [item.to_dict() for item in self.quarantine_reasons],
            "audit_events": [item.to_dict() for item in self.audit_events],
            "migrated_submission": (
                self.migrated_submission.to_dict() if self.migrated_submission else None
            ),
        }


def classification_max(values: Sequence[str]) -> str:
    """Return the most restrictive classification in *values*."""

    rank = {name: index for index, name in enumerate(CLASSIFICATIONS)}
    if not values:
        return "compatible"
    unknown = [value for value in values if value not in rank]
    if unknown:
        raise ModelError(f"unknown classification: {unknown[0]}")
    return max(values, key=lambda item: rank[item])
