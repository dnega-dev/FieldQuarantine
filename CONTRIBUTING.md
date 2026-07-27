# Contributing

Field Quarantine is intentionally small, deterministic, and free of runtime
dependencies.

## Development setup

Python 3.9 or newer is required. A virtual environment is optional because the
test suite uses only the standard library.

```sh
PYTHONPATH=src python -m unittest discover -s tests -v
sh ci/check.sh
```

An editable installation may be used when build tooling is available:

```sh
python -m pip install -e .
field-quarantine --help
```

## Design rules

1. Never discard or silently reinterpret a captured answer.
2. Require explicit field mappings, value mappings, or named conversions when
   identity preservation is not enough.
3. Keep JSON and text output deterministic; never read the wall clock inside a
   classification or migration operation.
4. Preserve initial answer records and provenance across every migration.
5. Use only the Python standard library at runtime.
6. Keep examples synthetic and domain-neutral. Do not add proprietary mining,
   extraction, or regulatory decision logic.
7. Add tests for every semantic branch and regression.

## Changes

- Update `CHANGELOG.md` for user-visible behavior.
- Run `sh ci/check.sh` before proposing a change.
- Keep commits focused and explain any classification change in
  `docs/migration-semantics.md`.
- New named conversions must be deterministic, locale-independent, and
  explicitly invoked by a migration plan.

By contributing, you agree that your contribution is licensed under Apache-2.0.
