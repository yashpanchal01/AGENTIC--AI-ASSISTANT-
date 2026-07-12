"""Append-only audit log of every action JARVIS takes (issue 11 / US-53).

Default path: ``%USERPROFILE%\\.jarvis\\audit.log`` (JSON-lines, one event per line).
Human-reviewable after the fact; never required for the happy path to succeed.
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from jarvis.paths import default_audit_log_path


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


@runtime_checkable
class Auditor(Protocol):
    def log(self, event: str, **details: Any) -> None: ...


@dataclass
class AuditLog:
    """Thread-safe JSON-lines audit log writer."""

    path: Path = field(default_factory=default_audit_log_path)
    # When True, never raise from log() (production). Tests may set False.
    swallow_errors: bool = True
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def log(self, event: str, **details: Any) -> None:
        record: dict[str, Any] = {
            "ts": _utc_now_iso(),
            "event": event,
        }
        for key, value in details.items():
            record[key] = _jsonable(value)
        line = json.dumps(record, ensure_ascii=False, default=str) + "\n"
        try:
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as fh:
                    fh.write(line)
        except OSError:
            if not self.swallow_errors:
                raise

    def read_events(self) -> list[dict[str, Any]]:
        """Parse all events (tests / review helpers). Missing file → []."""
        if not self.path.is_file():
            return []
        events: list[dict[str, Any]] = []
        text = self.path.read_text(encoding="utf-8")
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                events.append(obj)
        return events


class NullAuditLog:
    """No-op auditor for tests that do not care about history."""

    def log(self, event: str, **details: Any) -> None:  # noqa: ARG002
        return None


class MemoryAuditLog:
    """In-memory auditor for unit tests."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def log(self, event: str, **details: Any) -> None:
        record = {
            "ts": _utc_now_iso(),
            "event": event,
            **{k: _jsonable(v) for k, v in details.items()},
        }
        with self._lock:
            self.events.append(record)


class BusAuditor:
    """Auditor-shaped publisher: ``log()`` rides the event bus (issue 12).

    Drop-in for AuditLog at every call site; the real writer subscribes via
    :func:`attach_audit` and produces byte-identical records.
    """

    def __init__(self, bus: Any) -> None:
        self._bus = bus

    def log(self, event: str, **details: Any) -> None:
        from jarvis.events import AuditRecord

        self._bus.publish(AuditRecord(name=event, details=details))


class AuditSubscriber:
    """Maps ``AuditRecord`` events back onto an Auditor (the real writer)."""

    def __init__(self, auditor: Auditor) -> None:
        self._auditor = auditor

    def __call__(self, event: object) -> None:
        from jarvis.events import AuditRecord

        if isinstance(event, AuditRecord):
            self._auditor.log(event.name, **event.details)


def attach_audit(bus: Any, auditor: Auditor) -> Any:
    """Subscribe the real audit writer to *bus*. Returns the unsubscribe."""
    return bus.subscribe(AuditSubscriber(auditor))


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if is_dataclass(value) and not isinstance(value, type):
        return {k: _jsonable(v) for k, v in asdict(value).items()}
    # Action-like objects
    name = getattr(value, "name", None)
    detail = getattr(value, "detail", None)
    if name is not None:
        out: dict[str, Any] = {"name": name}
        if detail is not None:
            out["detail"] = detail
        return out
    return str(value)


def default_audit_log() -> AuditLog:
    return AuditLog()
