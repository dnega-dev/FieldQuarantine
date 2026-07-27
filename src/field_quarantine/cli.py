"""Command-line interface for Field Quarantine."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, TextIO

from .classifier import classify_submission
from .codec import pretty_json
from .migration import migrate_submission
from .models import (
    FormSchema,
    MigrationPlan,
    PendingSubmission,
    ReconciliationContext,
)
from .reconciliation import reconcile_submission
from .report import (
    classification_report,
    diff_report,
    migration_report,
    reconciliation_report,
)
from .schema_diff import diff_schemas


def _load(path: str) -> Any:
    if path == "-":
        return json.load(sys.stdin)
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _plan(path: Optional[str]) -> Optional[MigrationPlan]:
    return MigrationPlan.from_dict(_load(path)) if path else None


def _write(text: str, path: Optional[str]) -> None:
    if path:
        Path(path).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)


def _render(value: Any, report: Callable[[Any], str], output_format: str) -> str:
    if output_format == "json":
        return pretty_json(value.to_dict())
    return report(value)


def _add_common(parser: argparse.ArgumentParser, include_submission: bool = False) -> None:
    if include_submission:
        parser.add_argument("submission", help="pending submission JSON file")
    parser.add_argument("old_schema", help="source schema JSON file")
    parser.add_argument("new_schema", help="target schema JSON file")
    parser.add_argument("--plan", help="explicit migration plan JSON file")
    parser.add_argument(
        "--format",
        choices=("json", "text"),
        default="json",
        help="output format (default: json)",
    )
    parser.add_argument("-o", "--output", help="write output to this file")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="field-quarantine",
        description="Classify and safely migrate offline form submissions.",
    )
    parser.add_argument("--version", action="version", version="%(prog)s 0.1.0")
    subparsers = parser.add_subparsers(dest="command", required=True)

    diff_parser = subparsers.add_parser("diff", help="diff two schema versions")
    _add_common(diff_parser)

    classify_parser = subparsers.add_parser(
        "classify", help="classify one pending submission"
    )
    _add_common(classify_parser, include_submission=True)
    classify_parser.add_argument(
        "--at", help="ISO-8601 evaluation time for authorization expiry"
    )

    migrate_parser = subparsers.add_parser(
        "migrate", help="migrate a compatible or auto-migratable submission"
    )
    _add_common(migrate_parser, include_submission=True)
    migrate_parser.add_argument(
        "--at",
        help="deterministic migration timestamp (defaults to submission updated_at)",
    )
    migrate_parser.add_argument("--actor", default="field-quarantine")

    reconcile_parser = subparsers.add_parser(
        "reconcile", help="reconcile a submission after connectivity returns"
    )
    _add_common(reconcile_parser, include_submission=True)
    reconcile_parser.add_argument(
        "--context",
        required=True,
        help="reconciliation context JSON (time, remote receipts, partial state)",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        old = FormSchema.from_dict(_load(args.old_schema))
        new = FormSchema.from_dict(_load(args.new_schema))
        plan = _plan(args.plan)

        if args.command == "diff":
            result = diff_schemas(old, new, plan)
            _write(_render(result, diff_report, args.format), args.output)
            return 0

        submission = PendingSubmission.from_dict(_load(args.submission))
        if args.command == "classify":
            result = classify_submission(submission, old, new, plan, now=args.at)
            _write(_render(result, classification_report, args.format), args.output)
            return 0
        if args.command == "migrate":
            result = migrate_submission(
                submission,
                old,
                new,
                plan,
                migrated_at=args.at,
                actor=args.actor,
                now=args.at,
            )
            _write(_render(result, migration_report, args.format), args.output)
            return 0 if result.status == "migrated" else 2
        if args.command == "reconcile":
            context = ReconciliationContext.from_dict(_load(args.context))
            result = reconcile_submission(submission, old, new, plan, context)
            _write(_render(result, reconciliation_report, args.format), args.output)
            return 2 if result.decision == "quarantined" else 0
    except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"field-quarantine: error: {exc}\n")
        return 1
    parser.error(f"unsupported command: {args.command}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
