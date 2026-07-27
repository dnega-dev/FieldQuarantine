#!/usr/bin/env python3
"""Deterministic disconnect -> schema change -> reconnect simulation."""

from __future__ import annotations

import json
from pathlib import Path

from field_quarantine import (
    FormSchema,
    MigrationPlan,
    PendingSubmission,
    ReconciliationContext,
    classify_submission,
    diff_schemas,
    reconcile_submission,
)
from field_quarantine.codec import pretty_json


HERE = Path(__file__).resolve().parent


def load(name: str):
    with (HERE / name).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def main() -> None:
    # 1. The record already exists locally: it was captured during disconnection.
    pending = PendingSubmission.from_dict(load("pending-submission.json"))
    old = FormSchema.from_dict(load("schema-v1.json"))

    # 2. While the device is offline, the service publishes revision 2 plus an
    # explicitly reviewed migration plan.
    new = FormSchema.from_dict(load("schema-v2.json"))
    plan = MigrationPlan.from_dict(load("migration-plan.json"))
    schema_change = diff_schemas(old, new, plan)
    classification = classify_submission(
        pending, old, new, plan, now="2025-01-03T12:00:00Z"
    )

    # 3. Connectivity returns. The attachment transfer layer confirms the one
    # attachment is uploaded, then reconciliation prepares safe delivery.
    context = ReconciliationContext.from_dict(load("reconnect-context.json"))
    reconciliation = reconcile_submission(pending, old, new, plan, context)

    assert classification.classification == "auto_migratable"
    assert reconciliation.decision == "ready_to_deliver"
    assert reconciliation.migrated_submission is not None
    migrated = reconciliation.migrated_submission
    assert migrated.original_answers == pending.answers
    assert migrated.answer_map()["asset_condition"].value == "needs_attention"

    result = {
        "disconnect": {
            "submission_id": pending.submission_id,
            "captured_schema_version": pending.schema_version,
            "sync_state": pending.sync_state,
        },
        "schema_change": schema_change.to_dict(),
        "submission_classification": classification.to_dict(),
        "reconnect": reconciliation.to_dict(),
    }
    print(pretty_json(result), end="")


if __name__ == "__main__":
    main()
