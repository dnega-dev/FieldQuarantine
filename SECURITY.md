# Security Policy

## Supported versions

Until a 1.0 release, only the latest release on the main development line is
supported with security fixes.

## Reporting a vulnerability

Please report suspected vulnerabilities privately to the project maintainers.
Do not include sensitive submissions, attachment bytes, credentials, or real
obligation material in an issue or public reproduction. Include:

- affected version and Python version;
- a minimal synthetic input;
- expected and observed behavior;
- security impact; and
- any proposed mitigation.

Maintainers should acknowledge a report within 5 business days, coordinate a
fix and disclosure timeline, and credit reporters who want attribution.

## Operational guidance

Field Quarantine operates on metadata and JSON records; it does not encrypt
storage or transport. Deployments must provide those controls. Treat answer
records, provenance, hashes, attachment metadata, and audit events as sensitive.
Use least-privilege file permissions, authenticated transport, bounded input
sizes, and an idempotent delivery store. Never use `--output` to write into a
world-readable location. Validate attachment bytes against the recorded SHA-256
digest before upload; this library intentionally stores metadata, not bytes.

The library does not execute values from schemas or submissions. Regular
expression constraints are evaluated with Python's `re` engine, so operators
accepting untrusted schemas should review patterns and impose resource limits.
