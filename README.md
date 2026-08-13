# Field Quarantine

[![CI](https://github.com/dnega-dev/FieldQuarantine/actions/workflows/ci.yml/badge.svg)](https://github.com/dnega-dev/FieldQuarantine/actions/workflows/ci.yml)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-3776AB)](https://www.python.org/)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

Field Quarantine is a zero-runtime-dependency Python 3.9+ library and CLI for
classifying and safely migrating form or inspection submissions captured while a
client is offline. It is designed for the awkward reconnect window in which the
form schema, validation rules, evidence requirements, or obligation/source
mappings may have changed.

The core rule is simple:

> A captured answer is evidence. Never discard it or reinterpret it silently.

Field Quarantine therefore preserves the initial answer records, carries
provenance through every migration, requires explicit mappings for renamed or
deleted fields, and emits deterministic quarantine reasons, reconciliation
tasks, and audit events when automatic handling would be unsafe.

This project contains no proprietary mining or extraction logic. Its models and
semantics are domain-neutral.

## Capabilities

- Versioned form schemas with typed fields, requiredness, validation constraints,
  enum values, and evidence requirements.
- Captured obligation and source hashes on schemas and pending submissions.
- Submission-aware schema diff with four outcomes:
  `compatible`, `auto_migratable`, `review_required`, and `invalidated`.
- Explicit field rename mappings, enum/value mappings, migration defaults, and a
  small deterministic type-conversion vocabulary.
- Immutable migration that preserves exact original answers and extends answer
  and attachment provenance.
- Reconnect reconciliation for expired authorization, duplicate deliveries,
  partial synchronization conflicts, missing idempotency keys, and pending
  attachment uploads.
- Stable JSON serialization, stable task/event identifiers, and plain-text
  reports without timestamps read from the wall clock.
- Standard-library `unittest` suite and an end-to-end disconnect → schema change
  → reconnect example.

## Install and run

No third-party package is needed at runtime.

```sh
python -m pip install .
field-quarantine --help
```

For a source checkout without installation:

```sh
PYTHONPATH=src python -m field_quarantine --help
PYTHONPATH=src python -m unittest discover -s tests -v
```

## CLI

All commands default to deterministic, sorted, indented JSON. Add
`--format text` for an operator report and `-o PATH` to write a file.

```text
field-quarantine diff OLD_SCHEMA NEW_SCHEMA [--plan PLAN]
field-quarantine classify SUBMISSION OLD_SCHEMA NEW_SCHEMA [--plan PLAN] [--at TIME]
field-quarantine migrate SUBMISSION OLD_SCHEMA NEW_SCHEMA [--plan PLAN] [--at TIME]
field-quarantine reconcile SUBMISSION OLD_SCHEMA NEW_SCHEMA --context CONTEXT [--plan PLAN]
```

Examples:

```sh
PYTHONPATH=src python -m field_quarantine diff \
  examples/schema-v1.json examples/schema-v2.json \
  --plan examples/migration-plan.json --format text

PYTHONPATH=src python -m field_quarantine classify \
  examples/pending-submission.json examples/schema-v1.json examples/schema-v2.json \
  --plan examples/migration-plan.json --at 2025-01-03T12:00:00Z

PYTHONPATH=src python -m field_quarantine migrate \
  examples/pending-submission.json examples/schema-v1.json examples/schema-v2.json \
  --plan examples/migration-plan.json --at 2025-01-03T12:00:00Z

PYTHONPATH=src python -m field_quarantine reconcile \
  examples/pending-submission.json examples/schema-v1.json examples/schema-v2.json \
  --plan examples/migration-plan.json --context examples/reconnect-context.json \
  --format text
```

`migrate` and `reconcile` return exit status 2 when a record is quarantined,
status 1 for malformed input or I/O errors, and status 0 otherwise. Classification
itself always returns status 0 when its input is valid; inspect its result.

A positional input may be `-` to read JSON from standard input. Because stdin is
a single stream, use `-` for at most one input in a command.

## Classification semantics

The most restrictive applicable result wins:

| Result | Meaning |
| --- | --- |
| `compatible` | The captured values retain their identity and satisfy the target schema without transformation. |
| `auto_migratable` | Every non-identity step is explicitly declared and deterministic. Examples: a field mapping, reviewed hash acknowledgement, value map, or default. |
| `review_required` | The record is intact, but policy or operator input is required before delivery. Examples: an unacknowledged obligation change, expired authorization, or an unconverted semantic type change. |
| `invalidated` | The record cannot satisfy the target contract without losing, inventing, or ambiguously changing evidence. Examples: an answered deleted field without mapping, missing newly required evidence, invalid default, mapping collision, or target validation failure. |

Classification is submission-aware. A tightened numeric maximum only invalidates
answers exceeding it. An enum removal only invalidates a submission carrying a
removed value unless an explicit value map supplies an accepted target value.

See [docs/migration-semantics.md](docs/migration-semantics.md) for the complete
rules.

## Input records

### Schema

```json
{
  "schema_id": "inspection",
  "version": "1",
  "title": "Offline inspection",
  "obligation_hash": "obl-v1",
  "source_hash": "src-v1",
  "fields": [
    {
      "field_id": "condition",
      "label": "Condition",
      "type": "enum",
      "required": true,
      "constraints": {"enum": ["good", "repair"]},
      "evidence": {
        "required": true,
        "min_count": 1,
        "media_types": ["image/jpeg"]
      },
      "aliases": []
    }
  ],
  "metadata": {}
}
```

Supported field types are `string`, `integer`, `number`, `boolean`, `date`,
`datetime`, `enum`, `object`, and `array`. Constraints are `minimum`, `maximum`,
`min_length`, `max_length`, `pattern`, and `enum`.

### Pending submission

```json
{
  "submission_id": "sub-001",
  "schema_id": "inspection",
  "schema_version": "1",
  "obligation_hash": "obl-v1",
  "source_hash": "src-v1",
  "created_at": "2025-01-01T09:00:00Z",
  "updated_at": "2025-01-01T09:05:00Z",
  "auth_expires_at": "2025-01-04T00:00:00Z",
  "delivery_id": "delivery-sub-001",
  "sync_state": "local_only",
  "answers": [
    {
      "field_id": "condition",
      "value": "repair",
      "captured_at": "2025-01-01T09:03:00Z",
      "provenance": {"device_id": "device-demo"}
    }
  ],
  "attachments": [
    {
      "attachment_id": "att-001",
      "field_id": "condition",
      "file_name": "evidence.jpg",
      "media_type": "image/jpeg",
      "size_bytes": 128,
      "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "captured_at": "2025-01-01T09:04:00Z",
      "status": "local",
      "provenance": {"device_id": "device-demo"}
    }
  ],
  "original_answers": [],
  "migration_history": [],
  "metadata": {}
}
```

Attachment bytes are deliberately out of scope. The model retains file name,
media type, byte size, SHA-256 digest, capture time, upload status, and
provenance. The reconciliation task instructs the delivery layer to verify the
digest before upload.

### Migration plan

```json
{
  "schema_id": "inspection",
  "from_version": "1",
  "to_version": "2",
  "field_mappings": {"condition": "asset_condition"},
  "value_mappings": {"condition": {"repair": "needs_attention"}},
  "defaults": {"visit_complete": true},
  "conversions": {},
  "acknowledge_obligation_change": true,
  "acknowledge_source_change": false,
  "reviewed_by": "reviewer@example.invalid",
  "note": "Synthetic example"
}
```

Mappings are keyed by source field id. Defaults are keyed by target field id.
A hash acknowledgement only authorizes automatic migration when `reviewed_by`
is present.

Named conversions are intentionally limited and locale-independent:

- `identity` / `preserve`
- `string_to_integer`
- `string_to_number`
- `string_to_boolean`
- `integer_to_string`
- `number_to_string`
- `boolean_to_string`
- `integer_to_number`
- `date_to_datetime_utc`

### Reconciliation context

```json
{
  "now": "2025-01-03T12:00:00Z",
  "received_delivery_ids": [],
  "remote_applied_fields": {},
  "uploaded_attachment_ids": [],
  "actor": "sync-worker"
}
```

The caller supplies `now`; the library never makes a wall-clock decision. A
delivery id already present in `received_delivery_ids` is suppressed before
migration. Remote partial values are compared with migrated local values and a
conflict is quarantined instead of overwriting either side.

## Library API

```python
from field_quarantine import (
    FormSchema,
    MigrationPlan,
    PendingSubmission,
    classify_submission,
    diff_schemas,
    migrate_submission,
)

old = FormSchema.from_dict(old_data)
new = FormSchema.from_dict(new_data)
submission = PendingSubmission.from_dict(submission_data)
plan = MigrationPlan.from_dict(plan_data)

schema_diff = diff_schemas(old, new, plan)
classification = classify_submission(
    submission, old, new, plan, now="2025-01-03T12:00:00Z"
)
result = migrate_submission(
    submission,
    old,
    new,
    plan,
    migrated_at="2025-01-03T12:00:00Z",
)
```

Models are frozen dataclasses. Operations return new records and do not mutate
caller objects.

## Determinism and auditability

- JSON keys are sorted and output ends with exactly one newline.
- Changes, reasons, tasks, answers, and attachments are stably ordered.
- Task and audit identifiers are SHA-256-derived from canonical event content.
- Callers provide decision timestamps; migration otherwise reuses the
  submission's `updated_at`.
- `original_answers` captures the exact initial answer objects on first
  migration and remains unchanged across later migrations.
- Migration provenance records source/target field ids, source/target schema
  versions, explicit conversion or value-map use, and the caller-supplied time.

## Development checks

```sh
sh ci/check.sh
```

The script runs all unit tests, the end-to-end simulation, and `compileall`.

## Assurance toolkit

This repository is part of a set of small, deterministic tools for testing AI-agent and retrieval-system failure boundaries:

- [SourceAdapter-Fuzz](https://github.com/dnega-dev/SourceAdapter-Fuzz) — fault injection for public-data acquisition strategies.
- [SourceContract](https://github.com/dnega-dev/SourceContract) — conformance testing for official-source ingestion adapters.
- [ClaimSpec](https://github.com/dnega-dev/ClaimSpec) — executable grounding contracts for research-agent traces.
- [CitationChaos](https://github.com/dnega-dev/CitationChaos) — citation mutation testing for grounded-answer pipelines.
- [AsOfGuard](https://github.com/dnega-dev/AsOfGuard) — temporal-contamination detection for RAG and agent memory.
- [Legal-MCP-Assurance](https://github.com/dnega-dev/Legal-MCP-Assurance) — black-box assurance for legal and retrieval tool servers.
- [JurisdictionLeakBench](https://github.com/dnega-dev/JurisdictionLeakBench) — retrieval-scope isolation security benchmark.
- [MemoryLitmus](https://github.com/dnega-dev/MemoryLitmus) — conformance testing for agent-memory semantics.
- [FailureKata](https://github.com/dnega-dev/FailureKata) — executable practice from coding-agent transcript failures.
- [FieldQuarantine](https://github.com/dnega-dev/FieldQuarantine) — safe migration of offline submissions across schema changes.

Each project is independently installable and reports deterministic outcomes suitable for local development and CI.

## License

Apache License 2.0. See [LICENSE](LICENSE).
