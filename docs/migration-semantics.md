# Migration semantics

This document defines the safety contract implemented by Field Quarantine 0.1.
It is normative for classification behavior; the README is introductory.

## 1. Invariants

1. **Capture identity is immutable.** A pending submission declares the schema
   id/version and obligation/source hashes used at capture. A mismatch with the
   supplied source schema invalidates the operation.
2. **No silent reinterpretation.** A value is copied by identity unless a plan
   names a field mapping, value mapping, conversion, or target default.
3. **No silent loss.** An answered field or attachment association that has no
   target field invalidates that submission. Optional deleted fields with no
   captured material do not invalidate the submission.
4. **First evidence is retained.** On first migration, `original_answers` is an
   exact immutable copy of the captured answer records. Later migrations retain
   it. Current answers receive an append-only `migration_chain` in provenance.
5. **Most restrictive outcome wins.** The order is `compatible` <
   `auto_migratable` < `review_required` < `invalidated`.
6. **Time is input.** Authorization and event timestamps are evaluated from an
   explicit caller value, never the process clock.
7. **Retries are idempotent.** A known delivery id produces `already_delivered`
   before any migration or remote write is proposed.

## 2. Schema-level diff

`diff_schemas` emits every material change and a conservative overall class.
`classify_submission` then evaluates captured values and may determine that a
conservative change is harmless or fatal for that particular record.

### Field identity

- Same field id: identity is retained.
- Different id with `field_mappings[source] = target`: `auto_migratable`.
- Deleted source without mapping: `review_required` at schema diff time; an
  answer or attachment on that source is `invalidated` for the submission.
- Aliases are hints in a diff message only. They never act as mappings.
- Two sources mapping to one target: `invalidated` because provenance and value
  precedence would be ambiguous.
- Mapping source/target absent from its schema: `invalidated`.

### Added fields and requiredness

- Added optional field: `compatible`; no answer is invented.
- Added required field with a valid explicit default: `auto_migratable`.
- Added required field without a default: schema diff and any old submission are
  `invalidated`.
- Optional → required: conservative `review_required` in a schema diff. A
  submission already carrying a target-valid value remains compatible for that
  change. A missing value without a default is invalidated.
- Required → optional: `compatible`.

Defaults are explicit target answers. Their provenance says
`origin=migration_default`; they are never represented as captured evidence.

### Type changes

Integer → number is compatible because the Python integer value is copied
without a representation change and the target validator accepts it. Every
other type change requires a named conversion to be automatically migrated.
Without one it is `review_required` even when the raw JSON happens to satisfy the
target type; this prevents semantic reinterpretation.

A failed or unsupported explicit conversion is `invalidated`. Conversions are
pure, locale-independent operations. `null` remains `null` and is still subject
to target requiredness.

### Enum changes

- Added values: `compatible` for old records.
- Removed values: conservative `review_required` in a diff.
- Captured value still in target enum: compatible for that value.
- Removed captured value with an explicit source-field value map to an accepted
  value: `auto_migratable`.
- Removed captured value with no accepted mapping: `invalidated`.

The original value remains in `original_answers`; current provenance records
that a value map was applied.

### Validation changes

Adding or tightening `minimum`, `maximum`, `min_length`, `max_length`, or
`pattern` is conservative `review_required` in a diff. Relaxing or removing a
constraint is compatible. Classification validates the actual post-mapping,
post-conversion value against the complete target field:

- value passes: compatible for that constraint;
- value fails: invalidated;
- invalid target regular expression: invalidated with
  `invalid_schema_pattern`.

Target validation never mutates or normalizes values.

### Evidence changes

Evidence gets stricter when it becomes required, its minimum count increases, or
its allowed media set rejects a formerly allowed type. Tightening is
`review_required` at schema diff time. For each submission:

- too few target-associated attachments: `invalidated`;
- a captured media type outside the target set: `invalidated`;
- malformed SHA-256 metadata: `invalidated`;
- a mapped field moves its attachment association and extends provenance:
  `auto_migratable`;
- evidence relaxation: compatible.

Only metadata is modeled. A delivery implementation is responsible for keeping
bytes, checking byte length and SHA-256, and uploading them.

### Obligation and source hashes

A schema hash change is `review_required` by default. It becomes
`auto_migratable` only when the migration plan has both the corresponding
acknowledgement flag and a non-empty `reviewed_by` identity. This records human
or policy approval; it does not assert that the library understands domain
obligations.

A pending submission whose captured hashes do not match its declared source
schema is invalidated as an internal provenance inconsistency.

## 3. Migration

Migration runs only for `compatible` or `auto_migratable` results. For
`review_required` or `invalidated`, it returns:

- `status=quarantined`;
- no migrated submission;
- structured reasons;
- deterministic reconciliation tasks; and
- a `migration_quarantined` audit event.

A successful migration:

1. maps each answer and attachment to its explicit target;
2. applies a source-field value map, if present;
3. applies a named source-field conversion, if present;
4. creates missing defaults;
5. sorts current answers by target field id;
6. updates schema version and target hashes;
7. retains creation time, authorization expiry, delivery id, and metadata;
8. records the plan and source/target hashes in migration history; and
9. emits `submission_migrated`.

The operation creates a new frozen dataclass and does not mutate source objects.

## 4. Reconciliation

Reconciliation context contains a deterministic evaluation time, known received
delivery ids, remote partial field values, uploaded attachment ids, and actor.

Processing order matters:

1. **Duplicate suppression.** If the pending delivery id is already received,
   return `already_delivered`; do not migrate or propose delivery.
2. **Classification/migration.** Authorization expiry participates here.
   Expired authorization produces `review_required` and a
   `renew_authorization` task; it does not destroy the record.
3. **Partial state comparison.** Remote fields are compared with the safely
   migrated local values. An unequal or remote-only field creates
   `PARTIAL_SYNC_CONFLICT`; neither side wins automatically.
4. **Attachment work.** Local attachments not listed as uploaded produce an
   `upload_attachment` task with digest and size metadata.
5. **Delivery identity.** A missing delivery id creates `assign_delivery_id`.
6. **Resume work.** A non-conflicting submission marked `partial` receives
   `resume_partial_delivery`, including the already applied field list.

Possible decisions are:

- `already_delivered`: duplicate retry suppressed;
- `quarantined`: schema, authorization, validation, evidence, or partial-state
  review is required;
- `tasks_pending`: safe migration succeeded but delivery work remains;
- `ready_to_deliver`: migration succeeded and no known task blocks delivery.

## 5. Deterministic representation

`to_dict()` methods use explicit keys. CLI JSON uses UTF-8, sorted object keys,
two-space indentation, and one trailing newline. Arrays use semantic stable
ordering. IDs for tasks and audit events are a prefix plus the first 16 hex
characters of SHA-256 over compact canonical JSON of their identity content.

Identifiers are correlation aids, not authorization secrets or content
signatures.

## 6. Out of scope

- Domain-specific obligation interpretation or proprietary mining rules.
- Network transport, databases, authentication refresh, and attachment bytes.
- Cryptographic signing or encryption.
- Automatic guessing of renames, enum equivalence, units, locale, or timezone.
- Conflict resolution policy for partial sync.

Callers implement these concerns and feed explicit decisions back through a
migration plan or a subsequent reviewed submission.
