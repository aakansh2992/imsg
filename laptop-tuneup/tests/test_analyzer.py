"""Rules-engine tests on synthetic inventories."""

from tuneup.analyzer import analyze, render_report


def _base_inventory(**overrides):
    inv = {
        "system": {"manufacturer": "LENOVO", "model": "ThinkPad T480",
                   "total_ram_bytes": 16 * 1024 ** 3},
        "cpu": {"Name": "Intel i5-8250U", "NumberOfCores": 4},
        "ram": {"modules": [{"Capacity": 8}, {"Capacity": 8}], "slots": 2},
        "disks": [{"FriendlyName": "Samsung SSD", "MediaType": "SSD",
                   "SizeGB": 512.0, "HealthStatus": "Healthy"}],
        "volumes": [{"DeviceID": "C:", "SizeGB": 500.0, "FreeGB": 200.0}],
        "gpu": [{"Name": "Intel UHD 620", "DriverVersion": "31.0",
                 "DriverDate": "2024-06-01"}],
        "battery": {"percent": 90, "wear_percent": 10.0, "on_ac": True},
        "drivers": [{"DeviceName": "NIC", "DriverDate": "2024-01-01",
                     "age_years": 2.5}],
        "startup": [{"Name": f"app{i}"} for i in range(3)],
        "power_plan": "High performance",
        "winget_upgrades": [],
    }
    inv.update(overrides)
    return inv


def _ids(recs):
    return {r.id for r in recs}


def test_healthy_machine_only_gets_upgrade_map():
    recs = analyze(_base_inventory())
    assert _ids(recs) == {"upgrade_paths"}
    assert "reball" in recs[0].action.lower() or "solder" in recs[0].action.lower()


def test_hdd_triggers_ssd_recommendation():
    inv = _base_inventory(disks=[{"FriendlyName": "WD Blue",
                                  "MediaType": "HDD", "SizeGB": 1000.0,
                                  "HealthStatus": "Healthy"}])
    recs = analyze(inv)
    assert "hdd_to_ssd" in _ids(recs)


def test_low_ram_reports_free_slots():
    inv = _base_inventory(
        system={"manufacturer": "Dell", "model": "Latitude",
                "total_ram_bytes": 4 * 1024 ** 3},
        ram={"modules": [{"Capacity": 4}], "slots": 2})
    recs = analyze(inv)
    rec = next(r for r in recs if r.id == "low_ram")
    assert "1 free" in rec.action


def test_full_disk_is_auto_applicable():
    inv = _base_inventory(volumes=[{"DeviceID": "C:", "SizeGB": 500.0,
                                    "FreeGB": 10.0}])
    recs = analyze(inv)
    rec = next(r for r in recs if r.id.startswith("disk_full"))
    assert rec.severity == "high"
    assert rec.auto_apply_script


def test_battery_wear_triggers_bms_suggestion():
    inv = _base_inventory(battery={"percent": 80, "wear_percent": 35.0,
                                   "on_ac": True})
    recs = analyze(inv)
    rec = next(r for r in recs if r.id == "battery_worn")
    assert "bms" in rec.action.lower()


def test_unhealthy_disk_is_critical_and_first():
    inv = _base_inventory(disks=[{"FriendlyName": "Dying HDD",
                                  "MediaType": "HDD", "SizeGB": 500.0,
                                  "HealthStatus": "Warning"}])
    recs = analyze(inv)
    assert recs[0].id == "disk_health"
    assert recs[0].severity == "critical"


def test_winget_updates_rule_and_report_renders():
    inv = _base_inventory(winget_upgrades=[
        {"name": "Firefox", "id": "Mozilla.Firefox", "current": "1",
         "available": "2"}])
    recs = analyze(inv)
    assert "software_updates" in _ids(recs)
    text = render_report(recs)
    assert "apps have updates" in text
    assert "tuneup apply" in text
