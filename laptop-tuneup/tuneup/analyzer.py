"""Rules engine: turn an inventory into concrete recommendations.

Each recommendation says what was found, why it matters, what to do, and —
when a fix is safe enough to automate — carries a PowerShell apply script.
Risky actions (driver installs, BIOS, hardware) are never auto-applied; they
come with exact instructions instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

SEV = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


@dataclass
class Recommendation:
    id: str
    severity: str          # critical | high | medium | low | info
    category: str          # hardware | software | drivers | settings | battery
    title: str
    why: str
    action: str
    auto_apply_script: Optional[str] = None  # PowerShell; None = manual only
    details: Dict[str, Any] = field(default_factory=dict)


def analyze(inv: Dict[str, Any]) -> List[Recommendation]:
    recs: List[Recommendation] = []
    for rule in (_rule_hdd, _rule_low_ram, _rule_disk_full, _rule_battery_wear,
                 _rule_startup_bloat, _rule_old_drivers, _rule_software_updates,
                 _rule_power_plan, _rule_disk_health, _rule_upgrade_paths):
        try:
            recs.extend(rule(inv) or [])
        except Exception:
            continue  # one broken rule must not sink the report
    recs.sort(key=lambda r: SEV.get(r.severity, 9))
    return recs


# --------------------------------------------------------------------------- #
# Rules
# --------------------------------------------------------------------------- #

def _rule_hdd(inv):
    disks = inv.get("disks") or []
    hdds = [d for d in disks if str(d.get("MediaType", "")).upper() == "HDD"]
    if not hdds:
        return []
    return [Recommendation(
        id="hdd_to_ssd", severity="high", category="hardware",
        title="Mechanical hard drive detected — an SSD is the single biggest speedup",
        why=(f"{hdds[0].get('FriendlyName', 'A disk')} is a spinning HDD. "
             "Replacing the boot HDD with a SATA or NVMe SSD typically cuts "
             "boot and app-load times by 3-10x on an older laptop."),
        action=("Clone the drive to an SSD (Macrium Reflect Free / Clonezilla) "
                "and swap it. Check the service manual for whether the bay is "
                "2.5\" SATA or M.2."),
        details={"disks": hdds},
    )]


def _rule_low_ram(inv):
    sysinfo = inv.get("system") or {}
    ram = inv.get("ram") or {}
    total = sysinfo.get("total_ram_bytes") or 0
    gb = total / (1024 ** 3)
    if gb == 0 or gb >= 8:
        return []
    modules = (ram.get("modules") or [])
    slots = ram.get("slots") or 0
    free_slots = max(0, slots - len(modules)) if slots else None
    slot_note = (f"You have {slots} slots with {len(modules)} in use — "
                 f"{free_slots} free." if slots else
                 "Slot count unknown; check the service manual (RAM may be soldered).")
    return [Recommendation(
        id="low_ram", severity="high", category="hardware",
        title=f"Only {gb:.1f} GB RAM — upgrade to 8-16 GB",
        why=("Below 8 GB, Windows swaps to disk constantly, which is the "
             "classic 'everything is slow' symptom on old laptops."),
        action=f"Add or replace RAM modules. {slot_note}",
        details={"total_gb": round(gb, 1), "slots": slots,
                 "modules": len(modules)},
    )]


def _rule_disk_full(inv):
    out = []
    for v in inv.get("volumes") or []:
        size, free = v.get("SizeGB") or 0, v.get("FreeGB") or 0
        if size <= 0:
            continue
        used_pct = (1 - free / size) * 100
        if used_pct >= 90:
            out.append(Recommendation(
                id=f"disk_full_{v.get('DeviceID', '?')}".replace(":", ""),
                severity="high" if used_pct >= 95 else "medium",
                category="software",
                title=f"Drive {v.get('DeviceID')} is {used_pct:.0f}% full",
                why=("Windows and SSDs slow down badly with <10% free space "
                     "(no room for pagefile, updates, SSD wear-leveling)."),
                action="Run Disk Cleanup / Storage Sense; move large files off the drive.",
                auto_apply_script=(
                    "Start-Process cleanmgr -ArgumentList '/sagerun:1' -Wait; "
                    "Remove-Item -Path \"$env:TEMP\\*\" -Recurse -Force "
                    "-ErrorAction SilentlyContinue"),
                details=v,
            ))
    return out


def _rule_battery_wear(inv):
    b = inv.get("battery")
    if not b or b.get("wear_percent") is None:
        return []
    wear = b["wear_percent"]
    if wear < 25:
        return []
    return [Recommendation(
        id="battery_worn", severity="medium", category="battery",
        title=f"Battery has lost ~{wear:.0f}% of its design capacity",
        why=("Worn batteries can also trigger CPU throttling on some laptops "
             "when they can't deliver peak current."),
        action=("Consider a replacement battery (OEM part if possible). "
                "Meanwhile, use `tuneup bms run` to charge-limit and slow "
                "further wear."),
        details=b,
    )]


def _rule_startup_bloat(inv):
    startup = inv.get("startup") or []
    if len(startup) < 8:
        return []
    names = [s.get("Name", "?") for s in startup]
    return [Recommendation(
        id="startup_bloat", severity="medium", category="software",
        title=f"{len(startup)} programs launch at startup",
        why="Each adds boot time and background RAM/CPU on an old machine.",
        action=("Open Task Manager > Startup apps and disable what you don't "
                f"need at boot. Found: {', '.join(names[:10])}"
                f"{'...' if len(names) > 10 else ''}"),
        details={"count": len(startup), "names": names},
    )]


def _rule_old_drivers(inv):
    drivers = inv.get("drivers") or []
    old = [d for d in drivers if d.get("age_years", 0) >= 4]
    gpus = inv.get("gpu") or []
    out = []
    if old:
        worst = old[0]
        out.append(Recommendation(
            id="old_drivers", severity="medium", category="drivers",
            title=f"{len(old)} drivers are 4+ years old",
            why=("Old chipset/storage/graphics drivers cost performance and "
                 "stability; vendors fixed real bugs since."),
            action=("Get drivers from the laptop maker's support page for your "
                    f"model ({(inv.get('system') or {}).get('model', 'see System Info')}) — "
                    "not from driver-updater apps, which are mostly scamware. "
                    f"Oldest: {worst.get('DeviceName')} ({worst.get('DriverDate')})."),
            details={"old_count": len(old),
                     "oldest": old[:5]},
        ))
    for g in gpus:
        # GPU driver age matters most for perceived speed.
        raw = str(g.get("DriverDate") or "")
        if raw and raw < "2023":
            out.append(Recommendation(
                id="gpu_driver", severity="medium", category="drivers",
                title=f"GPU driver from {raw} ({g.get('Name', 'GPU')})",
                why="Graphics drivers affect UI smoothness, video decode, and browsers.",
                action=("Update from Intel/NVIDIA/AMD directly "
                        "(or the laptop vendor for older iGPUs)."),
                details=g,
            ))
    return out


def _rule_software_updates(inv):
    ups = inv.get("winget_upgrades") or []
    if not ups:
        return []
    return [Recommendation(
        id="software_updates", severity="medium", category="software",
        title=f"{len(ups)} apps have updates available",
        why="Outdated apps are slower and the top malware entry point.",
        action="Review and run: winget upgrade --all  (or apply below).",
        auto_apply_script=("winget upgrade --all --silent "
                           "--accept-package-agreements --accept-source-agreements"),
        details={"updates": ups[:20]},
    )]


def _rule_power_plan(inv):
    plan = inv.get("power_plan")
    if not plan or "high" in plan.lower() or "performance" in plan.lower():
        return []
    return [Recommendation(
        id="power_plan", severity="low", category="settings",
        title=f"Power plan is '{plan}'",
        why=("On AC power, the High Performance plan removes CPU parking/"
             "frequency caps that make old laptops feel sluggish."),
        action="Switch to High performance when plugged in.",
        auto_apply_script=(
            "powercfg /setactive 8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"),
        details={"current": plan},
    )]


def _rule_disk_health(inv):
    bad = [d for d in inv.get("disks") or []
           if str(d.get("HealthStatus", "")).lower() not in ("healthy", "", "none")]
    if not bad:
        return []
    return [Recommendation(
        id="disk_health", severity="critical", category="hardware",
        title=f"Disk reports health status: {bad[0].get('HealthStatus')}",
        why="A failing disk can lose your data at any moment.",
        action="Back up NOW, then replace the drive before anything else.",
        details={"disks": bad},
    )]


def _rule_upgrade_paths(inv):
    """The 'anything else, including reballing & soldering' honest report."""
    sysinfo = inv.get("system") or {}
    model = sysinfo.get("model", "your laptop")
    return [Recommendation(
        id="upgrade_paths", severity="info", category="hardware",
        title="Full upgrade map (including solder-level work)",
        why="Ordered by value for money on an old laptop.",
        action=(
            "1) SSD swap and RAM to 8-16 GB - biggest wins, screwdriver-level.\n"
            "2) New battery + fresh thermal paste and fan clean - stops "
            "thermal/power throttling; paste on a 5+ year machine is dust.\n"
            "3) Wi-Fi card swap (M.2/mPCIe) to AX-class if the slot allows.\n"
            "4) Solder-level (hot air/reball) - honest take: replacing "
            "soldered RAM or upgrading a BGA CPU/GPU is technically possible "
            "but needs donor chips, a rework station, and BIOS support; it "
            "usually costs more than the laptop is worth and has a real "
            "brick risk. Worth it only as a hobby project or for a rare "
            "machine. GPU 'reballing' specifically is a repair for dead "
            "solder joints, not an upgrade - if graphics are artifacting on "
            f"{model}, reflow/reball can revive it, temporarily more often "
            "than permanently.\n"
            "5) If the CPU is socketed (some old 15-17 inch models), a "
            "top-tier CPU of the same socket/TDP is a cheap real upgrade - "
            "check the service manual."),
    )]


def render_report(recs: List[Recommendation]) -> str:
    if not recs:
        return "No issues found - the machine looks healthy.\n"
    lines = []
    for r in recs:
        lines.append(f"[{r.severity.upper():8}] {r.title}")
        lines.append(f"    why:    {r.why}")
        for ln in r.action.splitlines():
            lines.append(f"    action: {ln}" if ln is r.action.splitlines()[0]
                         else f"            {ln}")
        if r.auto_apply_script:
            lines.append("    auto:   can be applied by `tuneup apply`")
        lines.append("")
    return "\n".join(lines)
