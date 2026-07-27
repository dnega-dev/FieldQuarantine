"""Schema comparison and change classification."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from .models import (
    DiffResult,
    FieldDefinition,
    FormSchema,
    MigrationPlan,
    SchemaChange,
    ValidationConstraints,
    classification_max,
)


def _change(
    code: str,
    classification: str,
    message: str,
    field_id: Optional[str] = None,
    target_field_id: Optional[str] = None,
    before: Any = None,
    after: Any = None,
) -> SchemaChange:
    return SchemaChange(
        code=code,
        classification=classification,
        message=message,
        field_id=field_id,
        target_field_id=target_field_id,
        before=before,
        after=after,
    )


def _constraint_changes(
    old: FieldDefinition, new: FieldDefinition
) -> Iterable[SchemaChange]:
    before = old.constraints
    after = new.constraints
    field_id = old.field_id
    target = new.field_id

    for attribute, lower_is_tighter in (("minimum", True), ("maximum", False)):
        old_value = getattr(before, attribute)
        new_value = getattr(after, attribute)
        if old_value == new_value:
            continue
        if old_value is None:
            tightened = new_value is not None
        elif new_value is None:
            tightened = False
        elif lower_is_tighter:
            tightened = new_value > old_value
        else:
            tightened = new_value < old_value
        yield _change(
            f"validation_{attribute}_{'tightened' if tightened else 'relaxed'}",
            "review_required" if tightened else "compatible",
            f"Validation {attribute} changed from {old_value!r} to {new_value!r}.",
            field_id,
            target,
            old_value,
            new_value,
        )

    for attribute, larger_is_tighter in (("min_length", True), ("max_length", False)):
        old_value = getattr(before, attribute)
        new_value = getattr(after, attribute)
        if old_value == new_value:
            continue
        if old_value is None:
            tightened = new_value is not None
        elif new_value is None:
            tightened = False
        elif larger_is_tighter:
            tightened = new_value > old_value
        else:
            tightened = new_value < old_value
        yield _change(
            f"validation_{attribute}_{'tightened' if tightened else 'relaxed'}",
            "review_required" if tightened else "compatible",
            f"Validation {attribute} changed from {old_value!r} to {new_value!r}.",
            field_id,
            target,
            old_value,
            new_value,
        )

    if before.pattern != after.pattern:
        if before.pattern is None and after.pattern is not None:
            classification = "review_required"
            direction = "added"
        elif before.pattern is not None and after.pattern is None:
            classification = "compatible"
            direction = "removed"
        else:
            classification = "review_required"
            direction = "changed"
        yield _change(
            f"validation_pattern_{direction}",
            classification,
            f"Validation pattern {direction}.",
            field_id,
            target,
            before.pattern,
            after.pattern,
        )


def _enum_changes(old: FieldDefinition, new: FieldDefinition) -> Iterable[SchemaChange]:
    old_values = tuple(old.constraints.enum)
    new_values = tuple(new.constraints.enum)
    if old_values == new_values:
        return ()
    old_set = {repr(item): item for item in old_values}
    new_set = {repr(item): item for item in new_values}
    removed = [old_set[key] for key in old_set.keys() - new_set.keys()]
    added = [new_set[key] for key in new_set.keys() - old_set.keys()]
    result: List[SchemaChange] = []
    if removed:
        result.append(
            _change(
                "enum_values_removed",
                "review_required",
                "One or more enum values were removed.",
                old.field_id,
                new.field_id,
                removed,
                None,
            )
        )
    if added:
        result.append(
            _change(
                "enum_values_added",
                "compatible",
                "One or more enum values were added.",
                old.field_id,
                new.field_id,
                None,
                added,
            )
        )
    return result


def _field_changes(
    old: FieldDefinition,
    new: FieldDefinition,
    plan: MigrationPlan,
) -> Iterable[SchemaChange]:
    changes: List[SchemaChange] = []
    source_id = old.field_id
    target_id = new.field_id

    if source_id != target_id:
        changes.append(
            _change(
                "field_renamed",
                "auto_migratable",
                f"Field {source_id!r} is explicitly mapped to {target_id!r}.",
                source_id,
                target_id,
                source_id,
                target_id,
            )
        )

    if old.label != new.label:
        changes.append(
            _change(
                "field_label_changed",
                "compatible",
                "Field label changed; stored answers remain associated by field id.",
                source_id,
                target_id,
                old.label,
                new.label,
            )
        )

    if old.field_type != new.field_type:
        conversion = plan.conversions.get(source_id)
        if old.field_type == "integer" and new.field_type == "number":
            classification = "compatible"
            message = "Integer values are accepted unchanged by the number field."
        elif conversion:
            classification = "auto_migratable"
            message = f"Type change uses explicit conversion {conversion!r}."
        else:
            classification = "review_required"
            message = "Type changed without an explicit conversion."
        changes.append(
            _change(
                "field_type_changed",
                classification,
                message,
                source_id,
                target_id,
                old.field_type,
                new.field_type,
            )
        )

    if old.required != new.required:
        tightened = not old.required and new.required
        changes.append(
            _change(
                "requiredness_increased" if tightened else "requiredness_decreased",
                "review_required" if tightened else "compatible",
                "Field became required." if tightened else "Field is no longer required.",
                source_id,
                target_id,
                old.required,
                new.required,
            )
        )

    changes.extend(_constraint_changes(old, new))
    if old.field_type == "enum" or new.field_type == "enum":
        changes.extend(_enum_changes(old, new))

    old_evidence = old.evidence
    new_evidence = new.evidence
    if old_evidence != new_evidence:
        old_types = set(old_evidence.media_types)
        new_types = set(new_evidence.media_types)
        tightened = (
            (not old_evidence.required and new_evidence.required)
            or new_evidence.min_count > old_evidence.min_count
            or (bool(new_types) and (not old_types or not new_types.issuperset(old_types)))
        )
        changes.append(
            _change(
                "evidence_requirement_tightened" if tightened else "evidence_requirement_relaxed",
                "review_required" if tightened else "compatible",
                "Evidence requirements became stricter."
                if tightened
                else "Evidence requirements were relaxed.",
                source_id,
                target_id,
                old_evidence.to_dict(),
                new_evidence.to_dict(),
            )
        )
    return changes


def validate_plan(old: FormSchema, new: FormSchema, plan: MigrationPlan) -> Tuple[SchemaChange, ...]:
    changes: List[SchemaChange] = []
    if plan.schema_id and plan.schema_id != old.schema_id:
        changes.append(
            _change(
                "plan_schema_mismatch",
                "invalidated",
                "Migration plan schema_id does not match the source schema.",
                before=plan.schema_id,
                after=old.schema_id,
            )
        )
    if plan.from_version and plan.from_version != old.version:
        changes.append(
            _change(
                "plan_source_version_mismatch",
                "invalidated",
                "Migration plan from_version does not match the source schema.",
                before=plan.from_version,
                after=old.version,
            )
        )
    if plan.to_version and plan.to_version != new.version:
        changes.append(
            _change(
                "plan_target_version_mismatch",
                "invalidated",
                "Migration plan to_version does not match the target schema.",
                before=plan.to_version,
                after=new.version,
            )
        )
    old_ids = set(old.field_map())
    new_ids = set(new.field_map())
    for source, target in sorted(plan.field_mappings.items()):
        if source not in old_ids:
            changes.append(
                _change(
                    "mapping_source_missing",
                    "invalidated",
                    f"Mapping source {source!r} is not in the source schema.",
                    source,
                    target,
                )
            )
        if target not in new_ids:
            changes.append(
                _change(
                    "mapping_target_missing",
                    "invalidated",
                    f"Mapping target {target!r} is not in the target schema.",
                    source,
                    target,
                )
            )

    # Explicit mappings are authoritative. Include implicit identity mappings
    # when detecting collisions so ``a -> b`` cannot silently collide with an
    # unchanged source field named ``b``.
    seen_targets: Dict[str, str] = {}
    for source in sorted(old_ids):
        target = plan.field_mappings.get(source)
        if target is None and source in new_ids:
            target = source
        if not target or target not in new_ids:
            continue
        if target in seen_targets and seen_targets[target] != source:
            changes.append(
                _change(
                    "mapping_target_ambiguous",
                    "invalidated",
                    f"Multiple effective source fields map to target {target!r}.",
                    source,
                    target,
                    seen_targets[target],
                    source,
                )
            )
        else:
            seen_targets[target] = source
    for field_id in sorted(plan.defaults):
        if field_id not in new_ids:
            changes.append(
                _change(
                    "default_target_missing",
                    "invalidated",
                    f"Default target {field_id!r} is not in the target schema.",
                    target_field_id=field_id,
                )
            )
    for field_id in sorted(plan.conversions):
        if field_id not in old_ids:
            changes.append(
                _change(
                    "conversion_source_missing",
                    "invalidated",
                    f"Conversion source {field_id!r} is not in the source schema.",
                    field_id=field_id,
                )
            )
    return tuple(changes)


def diff_schemas(
    old: FormSchema,
    new: FormSchema,
    plan: Optional[MigrationPlan] = None,
) -> DiffResult:
    """Compare two schema versions using only explicit migration declarations."""

    plan = plan or MigrationPlan(
        schema_id=old.schema_id,
        from_version=old.version,
        to_version=new.version,
    )
    changes: List[SchemaChange] = list(validate_plan(old, new, plan))
    if old.schema_id != new.schema_id:
        changes.append(
            _change(
                "schema_id_changed",
                "invalidated",
                "Schema identity changed; cross-schema reinterpretation is forbidden.",
                before=old.schema_id,
                after=new.schema_id,
            )
        )

    old_fields = old.field_map()
    new_fields = new.field_map()
    mapped_targets: Set[str] = set()

    for source_id in sorted(old_fields):
        old_field = old_fields[source_id]
        if source_id in plan.field_mappings:
            target_id = plan.field_mappings[source_id]
        elif source_id in new_fields:
            target_id = source_id
        else:
            target_id = ""
        if not target_id or target_id not in new_fields:
            aliases = sorted(
                field.field_id for field in new.fields if source_id in field.aliases
            )
            changes.append(
                _change(
                    "field_deleted_unmapped",
                    "review_required",
                    "Source field was deleted without an explicit mapping."
                    + (f" Alias candidates: {', '.join(aliases)}." if aliases else ""),
                    source_id,
                    before=old_field.to_dict(),
                )
            )
            continue
        mapped_targets.add(target_id)
        changes.extend(_field_changes(old_field, new_fields[target_id], plan))

    for target_id in sorted(new_fields):
        if target_id in mapped_targets:
            continue
        new_field = new_fields[target_id]
        if new_field.required:
            if target_id in plan.defaults:
                classification = "auto_migratable"
                code = "required_field_added_with_default"
                message = "Required field was added with an explicit migration default."
            else:
                classification = "invalidated"
                code = "required_field_added"
                message = "Required field was added without a migration default."
        else:
            classification = "compatible"
            code = "optional_field_added"
            message = "Optional field was added."
        changes.append(
            _change(
                code,
                classification,
                message,
                target_field_id=target_id,
                after=new_field.to_dict(),
            )
        )

    if old.obligation_hash != new.obligation_hash:
        authorized = plan.acknowledge_obligation_change and bool(plan.reviewed_by)
        changes.append(
            _change(
                "obligation_hash_changed",
                "auto_migratable" if authorized else "review_required",
                "Obligation mapping changed and was explicitly reviewed."
                if authorized
                else "Obligation mapping changed; explicit reviewed acknowledgement is required.",
                before=old.obligation_hash,
                after=new.obligation_hash,
            )
        )
    if old.source_hash != new.source_hash:
        authorized = plan.acknowledge_source_change and bool(plan.reviewed_by)
        changes.append(
            _change(
                "source_hash_changed",
                "auto_migratable" if authorized else "review_required",
                "Source material changed and was explicitly reviewed."
                if authorized
                else "Source material changed; explicit reviewed acknowledgement is required.",
                before=old.source_hash,
                after=new.source_hash,
            )
        )

    changes.sort(key=lambda item: (item.field_id or "", item.target_field_id or "", item.code))
    classification = classification_max([item.classification for item in changes])
    return DiffResult(
        schema_id=old.schema_id,
        from_version=old.version,
        to_version=new.version,
        classification=classification,
        changes=tuple(changes),
    )
