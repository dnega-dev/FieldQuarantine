"""Deterministic JSON and identifier helpers."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, IO, Mapping, Union


JsonSource = Union[str, Path, IO[str]]


def canonical_json(value: Any) -> str:
    """Serialize *value* in a stable, compact JSON form."""

    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def pretty_json(value: Any) -> str:
    """Serialize *value* in stable human-readable JSON, terminated by a newline."""

    return json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def stable_id(prefix: str, value: Any, length: int = 16) -> str:
    digest = hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()[:length]
    return f"{prefix}_{digest}"


def load_json(source: JsonSource) -> Any:
    if hasattr(source, "read"):
        return json.load(source)  # type: ignore[arg-type]
    path = Path(source)
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def dump_json(value: Any, destination: Union[str, Path, IO[str]]) -> None:
    text = pretty_json(value)
    if hasattr(destination, "write"):
        destination.write(text)  # type: ignore[union-attr]
        return
    path = Path(destination)
    path.write_text(text, encoding="utf-8")


def parse_timestamp(value: str) -> datetime:
    """Parse an ISO-8601 timestamp and normalize it to an aware datetime."""

    if not value:
        raise ValueError("timestamp is required")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def is_expired(expires_at: str, now: str) -> bool:
    return parse_timestamp(expires_at) <= parse_timestamp(now)


def normalize_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return a plain recursively JSON-compatible mapping for audit snapshots."""

    return json.loads(canonical_json(value))
