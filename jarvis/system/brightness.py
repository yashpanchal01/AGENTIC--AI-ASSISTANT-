"""Screen brightness control via WMI ``WmiMonitorBrightnessMethods``.

Implementation choice — PowerShell CIM over ctypes COM
------------------------------------------------------
WMI brightness lives in the ``root\\wmi`` namespace and is only reachable through
COM. The repo prefers stdlib/ctypes over heavy deps (see
:mod:`jarvis.windows.win32api`, hand-rolled with ``ctypes``, and the Google slice
on stdlib ``urllib`` — no ``pywin32``). Hand-rolling the full COM/IWbem plumbing
through ``ctypes`` for one setter is fragile and verbose, and ``pywin32``/``wmi``
are exactly the heavy deps the project avoids. So the real calls shell out to
Windows PowerShell's CIM cmdlets (``Get-CimInstance`` / ``Invoke-CimMethod``) via
stdlib :mod:`subprocess` — dependency-free, robust, and the same "call the OS,
don't reimplement it" spirit as the rest of the codebase.

The real calls are isolated behind :func:`default_get_brightness` and
:func:`default_set_brightness` so tests can fake BOTH the success path and the
unsupported-panel error path (they raise :class:`BrightnessError`, never crash).
"""

from __future__ import annotations

import subprocess
import sys

# Speakable line for panels/externals with no WMI brightness support.
UNSUPPORTED_MESSAGE = "I can't change the screen brightness on this display."

# Windows: run PowerShell without popping a console window.
_CREATE_NO_WINDOW = 0x08000000


class BrightnessError(RuntimeError):
    """Speakable failure from the brightness layer (WMI unsupported / failed)."""


# WMI CurrentBrightness may be an array on multi-monitor rigs — take the first.
_GET_SCRIPT = (
    "$ErrorActionPreference='Stop';"
    "try {"
    " $v = (Get-CimInstance -Namespace root/wmi -ClassName WmiMonitorBrightness)"
    ".CurrentBrightness;"
    " if ($null -eq $v) { throw 'no brightness data' };"
    " Write-Output ([int]@($v)[0])"
    "} catch { Write-Error $_.Exception.Message; exit 1 }"
)

# __LEVEL__ is substituted with the integer percent (plain str.replace, so the
# PowerShell braces below need no format-escaping).
_SET_SCRIPT_TEMPLATE = (
    "$ErrorActionPreference='Stop';"
    "try {"
    " $m = Get-CimInstance -Namespace root/wmi -ClassName WmiMonitorBrightnessMethods;"
    " $null = Invoke-CimMethod -InputObject $m -MethodName WmiSetBrightness"
    " -Arguments @{Timeout=0; Brightness=__LEVEL__};"
    " Write-Output 'OK'"
    "} catch { Write-Error $_.Exception.Message; exit 1 }"
)


def _run_ps(script: str, *, timeout: float = 10.0) -> str:
    """Run *script* under Windows PowerShell; raise BrightnessError on failure."""
    if sys.platform != "win32":
        raise BrightnessError("Screen brightness control is only available on Windows.")
    try:
        proc = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=_CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise BrightnessError(UNSUPPORTED_MESSAGE) from exc
    if proc.returncode != 0:
        # Non-terminating WMI "Not supported" surfaces here via -ErrorAction Stop.
        raise BrightnessError(UNSUPPORTED_MESSAGE)
    return (proc.stdout or "").strip()


def clamp(level: int) -> int:
    """Clamp a brightness value into the valid 0..100 percent range."""
    return max(0, min(100, int(level)))


def default_get_brightness() -> int:
    """Current panel brightness (0..100). Raises BrightnessError if unsupported."""
    out = _run_ps(_GET_SCRIPT)
    try:
        return clamp(int(out.split()[0]))
    except (ValueError, IndexError) as exc:
        raise BrightnessError(UNSUPPORTED_MESSAGE) from exc


def default_set_brightness(level: int) -> None:
    """Set panel brightness to *level* percent. Raises BrightnessError if unsupported."""
    _run_ps(_SET_SCRIPT_TEMPLATE.replace("__LEVEL__", str(clamp(level))))
