"""Parser tests against recorded Windows outputs — run anywhere, no Windows."""

import datetime as dt

from tuneup.scanner import (
    parse_battery,
    parse_driver_ages,
    parse_power_plan,
    parse_winget_upgrades,
)


def test_battery_wear_computed():
    b = parse_battery({"percent": 77, "status_code": 2,
                       "full_charge_capacity": 32000,
                       "design_capacity": 41000})
    assert b["on_ac"] is True
    assert abs(b["wear_percent"] - 22.0) < 0.1


def test_battery_wear_none_when_capacities_missing():
    b = parse_battery({"percent": 50, "status_code": 1,
                       "full_charge_capacity": None,
                       "design_capacity": None})
    assert b["wear_percent"] is None
    assert b["on_ac"] is False


def test_battery_none_passthrough():
    assert parse_battery(None) is None


def test_power_plan_extracts_name():
    text = ("Power Scheme GUID: 381b4222-f694-41f0-9685-ff5bb260df2e  "
            "(Balanced)\n")
    assert parse_power_plan(text) == "Balanced"
    assert parse_power_plan("") is None


def test_driver_ages_annotated_and_bad_dates_skipped():
    drivers = [
        {"DeviceName": "Old NIC", "DriverDate": "2018-06-01"},
        {"DeviceName": "Broken", "DriverDate": "not-a-date"},
        {"DeviceName": "New GPU", "DriverDate": "2025-01-15"},
    ]
    out = parse_driver_ages(drivers, today=dt.date(2026, 7, 17))
    assert len(out) == 2
    assert out[0]["age_years"] > 8
    assert out[1]["age_years"] < 2


WINGET_FIXTURE = """\
Name                 Id                    Version    Available  Source
------------------------------------------------------------------------
Mozilla Firefox      Mozilla.Firefox       120.0      128.0.2    winget
7-Zip                7zip.7zip             22.01      24.08      winget
2 upgrades available.
"""


def test_winget_parse_rows():
    rows = parse_winget_upgrades(WINGET_FIXTURE)
    assert len(rows) == 2
    assert rows[0]["id"] == "Mozilla.Firefox"
    assert rows[0]["available"] == "128.0.2"
    assert rows[1]["name"] == "7-Zip"


def test_winget_parse_empty_and_garbage():
    assert parse_winget_upgrades(None) == []
    assert parse_winget_upgrades("No installed package found.") == []
