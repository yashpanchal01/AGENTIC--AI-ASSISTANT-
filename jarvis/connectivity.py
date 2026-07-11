"""Network reachability for offline honesty (brain is cloud; rest is local).

The cloud brain needs the internet. Wake word, STT, and Piper do not.
Check reachability before calling the brain so offline is a spoken message,
not a hang.
"""

from __future__ import annotations

import socket
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@runtime_checkable
class Connectivity(Protocol):
    """True when the cloud brain is likely reachable."""

    def is_online(self) -> bool:
        ...


@dataclass
class FakeConnectivity:
    """Scriptable connectivity for tests."""

    online: bool = True
    checks: list[bool] = field(default_factory=list)

    def is_online(self) -> bool:
        self.checks.append(self.online)
        return self.online


@dataclass
class SocketConnectivity:
    """Best-effort TCP check to a public DNS IP (no HTTP, short timeout)."""

    host: str = "1.1.1.1"
    port: int = 443
    timeout_s: float = 1.5

    def is_online(self) -> bool:
        try:
            with socket.create_connection((self.host, self.port), self.timeout_s):
                return True
        except OSError:
            return False


def default_connectivity() -> SocketConnectivity:
    return SocketConnectivity()
