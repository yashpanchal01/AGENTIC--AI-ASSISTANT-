"""Windows autostart registration for the resident daemon (issue 11 / US-51).

Registers ``python -m jarvis --daemon`` under the current user's Run key so
JARVIS starts with Windows without a manual launch.

Override the registry backend in tests to avoid touching a real hive.
"""

from __future__ import annotations

import sys
from typing import Protocol


# HKCU\Software\Microsoft\Windows\CurrentVersion\Run
RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "JARVIS"


class RegistryBackend(Protocol):
    def set_value(self, name: str, value: str) -> None: ...
    def delete_value(self, name: str) -> bool: ...
    def get_value(self, name: str) -> str | None: ...


class MemoryRegistry:
    """In-memory registry fake for unit tests."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def set_value(self, name: str, value: str) -> None:
        self.values[name] = value

    def delete_value(self, name: str) -> bool:
        return self.values.pop(name, None) is not None

    def get_value(self, name: str) -> str | None:
        return self.values.get(name)


class WinRegBackend:
    """Real HKCU Run key via the stdlib ``winreg`` module."""

    def set_value(self, name: str, value: str) -> None:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            RUN_KEY_PATH,
            0,
            winreg.KEY_SET_VALUE,
        )
        try:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
        finally:
            winreg.CloseKey(key)

    def delete_value(self, name: str) -> bool:
        import winreg

        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                RUN_KEY_PATH,
                0,
                winreg.KEY_SET_VALUE,
            )
        except OSError:
            return False
        try:
            try:
                winreg.DeleteValue(key, name)
                return True
            except FileNotFoundError:
                return False
            except OSError:
                return False
        finally:
            winreg.CloseKey(key)

    def get_value(self, name: str) -> str | None:
        import winreg

        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                RUN_KEY_PATH,
                0,
                winreg.KEY_READ,
            )
        except OSError:
            return None
        try:
            try:
                val, _ = winreg.QueryValueEx(key, name)
            except FileNotFoundError:
                return None
            except OSError:
                return None
            return str(val) if val is not None else None
        finally:
            winreg.CloseKey(key)


def _prefer_pythonw(python_exe: str) -> str:
    """Prefer pythonw.exe on Windows so logon does not flash a console.

    Falls back to *python_exe* when pythonw is missing (e.g. embeddable
    installs or non-Windows).
    """
    from pathlib import Path

    p = Path(python_exe)
    name = p.name.lower()
    if name == "python.exe":
        candidate = p.with_name("pythonw.exe")
        if candidate.is_file():
            return str(candidate)
    if name == "python":
        # POSIX-style name on Windows store stubs — try sibling pythonw.exe.
        candidate = p.with_name("pythonw.exe")
        if candidate.is_file():
            return str(candidate)
    return python_exe


def default_daemon_command(
    *,
    python_exe: str | None = None,
    prefer_pythonw: bool = True,
) -> str:
    """Command string written to the Run key.

    Uses the current interpreter so autostart matches the install that
    registered it (``sys.executable -m jarvis --daemon``). On Windows,
    prefers ``pythonw.exe`` when present so login does not open a console
    window (pass ``prefer_pythonw=False`` for debug consoles).
    """
    exe = python_exe or sys.executable
    if prefer_pythonw:
        exe = _prefer_pythonw(exe)
    # Quote the executable for paths with spaces (typical on Windows).
    if " " in exe and not exe.startswith('"'):
        exe = f'"{exe}"'
    return f"{exe} -m jarvis --daemon"


def install_autostart(
    *,
    backend: RegistryBackend | None = None,
    command: str | None = None,
    value_name: str = VALUE_NAME,
) -> str:
    """Register JARVIS to start with Windows. Returns the command registered."""
    reg = backend if backend is not None else WinRegBackend()
    cmd = command if command is not None else default_daemon_command()
    reg.set_value(value_name, cmd)
    return cmd


def uninstall_autostart(
    *,
    backend: RegistryBackend | None = None,
    value_name: str = VALUE_NAME,
) -> bool:
    """Remove the Run key entry. Returns True if a value was deleted."""
    reg = backend if backend is not None else WinRegBackend()
    return reg.delete_value(value_name)


def is_autostart_installed(
    *,
    backend: RegistryBackend | None = None,
    value_name: str = VALUE_NAME,
) -> bool:
    reg = backend if backend is not None else WinRegBackend()
    return reg.get_value(value_name) is not None


def autostart_command(
    *,
    backend: RegistryBackend | None = None,
    value_name: str = VALUE_NAME,
) -> str | None:
    reg = backend if backend is not None else WinRegBackend()
    return reg.get_value(value_name)
