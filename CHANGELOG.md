# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
semantic versioning.

## [Unreleased]

## [0.1.0] - 2025-01-01

### Added

- Standard-library-only Python 3.9+ model layer for schemas, submissions,
  attachments, migration plans, quarantine reasons, reconciliation tasks, and
  audit events.
- Submission-aware schema diff and four-level classification.
- Explicit field, value, default, and type conversion migration controls.
- Immutable migration preserving original answer records and provenance.
- Reconnect reconciliation for authorization expiry, duplicate delivery,
  partial synchronization, and attachment work.
- Deterministic JSON output and text reports for `diff`, `classify`, `migrate`,
  and `reconcile` CLI commands.
- End-to-end offline simulation and comprehensive `unittest` coverage.
