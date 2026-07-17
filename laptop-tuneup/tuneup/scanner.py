"""System inventory scanner.

Each sub-scan is a (PowerShell script, pure parser) pair. `scan_system()` runs
them all and returns one inventory dict; parsers are importable and tested
against recorded fixtures without Windows.
"""

from __future__ import annotations

import datetime as _dt
import re
from typing import Any, Dict, List, Optional

from . import runner
from .runner import as_list

# --------------------------------------------------------------------------- #
# PowerShell snippets (JSON out)
# --------------------------------------------------------------------------- #

PS_SYSTEM = r"""
$os = Get-CimInstance Win32_OperatingSystem
$cs = Get-CimInstance Win32_ComputerSystem
[PSCustomObject]@{
  os_caption = $os.Caption; os_version = $os.Version
  os_build = $os.BuildNumber
  last_boot = $os.LastBootUpTime.ToString('o')
  manufacturer = $cs.Manufacturer; model = $cs.Model
  total_ram_bytes = $cs.TotalPhysicalMemory
} | ConvertTo-Json
"""

PS_CPU = r"""
Get-CimInstance Win32_Processor | Select-Object Name, NumberOfCores,
  NumberOfLogicalProcessors, MaxClockSpeed | ConvertTo-Json
"""

PS_RAM = r"""
[PSCustomObject]@{
  modules = @(Get-CimInstance Win32_PhysicalMemory |
    Select-Object Capacity, Speed, Manufacturer, DeviceLocator)
  slots = (Get-CimInstance Win32_PhysicalMemoryArray).MemoryDevices
} | ConvertTo-Json -Depth 4
"""

PS_DISKS = r"""
@(Get-PhysicalDisk | Select-Object FriendlyName, MediaType, BusType,
  @{n='SizeGB';e={[math]::Round($_.Size/1GB,1)}}, HealthStatus) |
  ConvertTo-Json
"""

PS_VOLUMES = r"""
@(Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" |
  Select-Object DeviceID,
  @{n='SizeGB';e={[math]::Round($_.Size/1GB,1)}},
  @{n='FreeGB';e={[math]::Round($_.FreeSpace/1GB,1)}}) | ConvertTo-Json
"""

PS_GPU = r"""
@(Get-CimInstance Win32_VideoController | Select-Object Name, DriverVersion,
  @{n='DriverDate';e={$_.DriverDate.ToString('yyyy-MM-dd')}}) | ConvertTo-Json
"""

PS_BATTERY = r"""
$b = Get-CimInstance Win32_Battery
if ($b) {
  $full = (Get-CimInstance -Namespace root/wmi -ClassName BatteryFullChargedCapacity -ErrorAction SilentlyContinue).FullChargedCapacity
  $design = (Get-CimInstance -Namespace root/wmi -ClassName BatteryStaticData -ErrorAction SilentlyContinue).DesignedCapacity
  [PSCustomObject]@{
    percent = $b.EstimatedChargeRemaining
    status_code = $b.BatteryStatus
    full_charge_capacity = $full
    design_capacity = $design
  } | ConvertTo-Json
}
"""

PS_DRIVERS = r"""
@(Get-CimInstance Win32_PnPSignedDriver |
  Where-Object { $_.DeviceName -and $_.DriverDate } |
  Select-Object DeviceName, DriverVersion, Manufacturer,
  @{n='DriverDate';e={$_.DriverDate.ToString('yyyy-MM-dd')}} |
  Sort-Object DriverDate | Select-Object -First 40) | ConvertTo-Json
"""

PS_STARTUP = r"""
@(Get-CimInstance Win32_StartupCommand |
  Select-Object Name, Command, Location) | ConvertTo-Json
"""

PS_POWER_PLAN = r"""
powercfg /getactivescheme
"""


# --------------------------------------------------------------------------- #
# Pure parsers (unit-tested with fixtures)
# --------------------------------------------------------------------------- #

def parse_battery(data: Optional[dict]) -> Optional[dict]:
    if not data:
        return None
    out = dict(data)
    full = data.get("full_charge_capacity")
    design = data.get("design_capacity")
    wear = None
    if full and design and design > 0 and full <= design * 1.2:
        wear = round((1.0 - full / design) * 100.0, 1)
        wear = max(wear, 0.0)
    out["wear_percent"] = wear
    # Win32_Battery BatteryStatus: 2 = on AC, 1 = discharging
    out["on_ac"] = data.get("status_code") == 2
    return out


def parse_power_plan(text: str) -> Optional[str]:
    m = re.search(r"\(([^)]+)\)\s*$", (text or "").strip())
    return m.group(1) if m else None


def parse_driver_ages(drivers: List[dict],
                      today: Optional[_dt.date] = None) -> List[dict]:
    """Annotate drivers with age_years; skip unparseable dates."""
    today = today or _dt.date.today()
    out = []
    for d in drivers:
        raw = str(d.get("DriverDate") or "")[:10]
        try:
            date = _dt.date.fromisoformat(raw)
        except ValueError:
            continue
        item = dict(d)
        item["age_years"] = round((today - date).days / 365.25, 1)
        out.append(item)
    return out


def parse_winget_upgrades(text: Optional[str]) -> List[dict]:
    """Parse `winget upgrade` table output into rows.

    Format: Name  Id  Version  Available  Source (fixed columns per run).
    Heuristic: find the header row, use column offsets of Id/Version/Available.
    """
    if not text:
        return []
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    header_i = None
    for i, ln in enumerate(lines):
        if "Id" in ln and "Version" in ln and "Available" in ln:
            header_i = i
            break
    if header_i is None:
        return []
    header = lines[header_i]
    cols = {name: header.index(name)
            for name in ("Id", "Version", "Available")}
    rows = []
    for ln in lines[header_i + 1:]:
        if set(ln.strip()) <= {"-"}:
            continue
        if ln.strip().endswith("upgrades available.") or ln.startswith("   "):
            continue
        name = ln[:cols["Id"]].strip()
        ident = ln[cols["Id"]:cols["Version"]].strip()
        current = ln[cols["Version"]:cols["Available"]].strip()
        available = ln[cols["Available"]:].split()
        if not name or not ident or not available:
            continue
        rows.append({"name": name, "id": ident, "current": current,
                     "available": available[0]})
    return rows


# --------------------------------------------------------------------------- #
# Orchestration (Windows only)
# --------------------------------------------------------------------------- #

def scan_system(progress=print) -> Dict[str, Any]:
    """Run the full scan. Returns the inventory dict."""
    inv: Dict[str, Any] = {"scanned_at": _dt.datetime.now().isoformat()}

    steps = [
        ("system", lambda: runner.run_powershell_json(PS_SYSTEM)),
        ("cpu", lambda: runner.run_powershell_json(PS_CPU)),
        ("ram", lambda: runner.run_powershell_json(PS_RAM)),
        ("disks", lambda: as_list(runner.run_powershell_json(PS_DISKS))),
        ("volumes", lambda: as_list(runner.run_powershell_json(PS_VOLUMES))),
        ("gpu", lambda: as_list(runner.run_powershell_json(PS_GPU))),
        ("battery", lambda: parse_battery(runner.run_powershell_json(PS_BATTERY))),
        ("drivers", lambda: parse_driver_ages(
            as_list(runner.run_powershell_json(PS_DRIVERS, timeout=180)))),
        ("startup", lambda: as_list(runner.run_powershell_json(PS_STARTUP))),
        ("power_plan", lambda: parse_power_plan(
            runner.run_powershell(PS_POWER_PLAN))),
        ("winget_upgrades", lambda: parse_winget_upgrades(
            runner.run_command(["winget", "upgrade",
                                "--accept-source-agreements"]))),
    ]
    for name, fn in steps:
        progress(f"  scanning {name}...")
        try:
            inv[name] = fn()
        except Exception as exc:  # a failed sub-scan shouldn't kill the run
            inv[name] = None
            inv.setdefault("errors", {})[name] = str(exc)[:300]
    return inv
