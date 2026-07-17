"""PowerShell execution layer.

All Windows system queries go through here as PowerShell snippets that emit
JSON (ConvertTo-Json), parsed into Python structures. Parsing is kept separate
from execution so every parser is unit-testable on any OS with recorded
fixtures.
"""

from __future__ import annotations

import json
import platform
import subprocess
from typing import Any, Optional


class PowerShellUnavailable(RuntimeError):
    pass


def is_windows() -> bool:
    return platform.system() == "Windows"


def run_powershell(script: str, timeout: float = 60.0) -> str:
    """Run a PowerShell snippet and return stdout text. Raises off-Windows."""
    if not is_windows():
        raise PowerShellUnavailable(
            "This scan runs PowerShell and only works on Windows. "
            "On other systems, use recorded inventory JSON (tuneup analyze --input)."
        )
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
         "Bypass", "-Command", script],
        capture_output=True, text=True, timeout=timeout,
    )
    if proc.returncode != 0 and not proc.stdout.strip():
        raise RuntimeError(f"PowerShell failed: {proc.stderr.strip()[:400]}")
    return proc.stdout


def run_powershell_json(script: str, timeout: float = 60.0) -> Any:
    """Run a snippet whose output is ConvertTo-Json; returns parsed data.

    Returns None on empty output. A single object comes back as a dict —
    callers that expect lists should use `as_list`.
    """
    out = run_powershell(script, timeout=timeout).strip()
    if not out:
        return None
    return json.loads(out)


def as_list(data: Any) -> list:
    """ConvertTo-Json collapses single-element arrays; normalise to a list."""
    if data is None:
        return []
    if isinstance(data, list):
        return data
    return [data]


def run_command(argv: list[str], timeout: float = 120.0) -> Optional[str]:
    """Run a plain command (e.g. winget); None if the binary is missing."""
    try:
        proc = subprocess.run(argv, capture_output=True, text=True,
                              timeout=timeout)
    except FileNotFoundError:
        return None
    return proc.stdout
