"""Vendor charge-threshold support.

The embedded controller owns charging. Some vendors expose firmware charge
thresholds; where they do, use the vendor mechanism — it survives reboots and
works with the lid closed. This module detects the manufacturer and gives the
exact, honest path for each. It does not pretend to flip EC registers itself:
poking undocumented EC addresses can brick firmware, so we only automate
mechanisms the vendor documents.
"""

from __future__ import annotations

from typing import Dict, Optional

VENDOR_GUIDES: Dict[str, str] = {
    "lenovo": (
        "Lenovo: supported on most ThinkPads/IdeaPads.\n"
        "  - Lenovo Vantage app -> Device -> Power -> Battery Charge Threshold\n"
        "  - Or 'Conservation Mode' (caps ~60%) via Vantage/Legion Toolkit.\n"
        "  Once set in firmware, it works without any software running."
    ),
    "asus": (
        "ASUS: MyASUS app -> Customization -> Power & Performance -> "
        "Battery Health Charging (60% / 80% / 100% caps). Stored in firmware."
    ),
    "dell": (
        "Dell: Dell Power Manager (or BIOS -> Power Management) -> "
        "Battery Settings -> Custom charge start/stop thresholds. Also "
        "scriptable via Dell Command | Configure:\n"
        "  cctk --PrimaryBattChargeCfg=Custom:40-80"
    ),
    "hp": (
        "HP: no user-settable threshold on most consumer models. Some "
        "business models have BIOS 'Battery Health Manager' (Maximize My "
        "Battery Health caps at 80%). Otherwise use the smart-plug mode."
    ),
    "msi": (
        "MSI: MSI Center/Dragon Center -> Battery Master (Best for Battery "
        "caps ~60%, Balanced ~80%)."
    ),
    "acer": (
        "Acer: Acer Care Center -> Battery Charge Limit (80%) on supported "
        "models. Otherwise use the smart-plug mode."
    ),
    "samsung": ("Samsung: Samsung Settings -> Battery Life Extender (85% cap)."),
    "microsoft": (
        "Microsoft Surface: UEFI -> Boot configuration -> Enable Battery "
        "Limit (80%) on many models."
    ),
}


def detect_vendor(manufacturer: Optional[str]) -> Optional[str]:
    if not manufacturer:
        return None
    m = manufacturer.lower()
    for key in VENDOR_GUIDES:
        if key in m:
            return key
    return None


def guidance(manufacturer: Optional[str]) -> str:
    key = detect_vendor(manufacturer)
    if key:
        return VENDOR_GUIDES[key]
    return (
        f"No documented firmware charge threshold known for "
        f"'{manufacturer or 'unknown manufacturer'}'.\n"
        "Use the universal option instead: a smart plug + `tuneup bms run` "
        "physically stops charging at your threshold (see README)."
    )
