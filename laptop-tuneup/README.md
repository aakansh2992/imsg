# TuneUp

An honest laptop scan / optimize / battery-care toolkit for Windows.
Pure-Python core (standard library only), AI analysis via Claude as an
optional add-on.

What it does:

1. **Scans** hardware, software, and drivers — CPU, RAM (incl. free slots),
   disks (HDD/SSD + health), GPU, battery wear %, driver ages, startup
   programs, power plan, and pending app updates (winget).
2. **Recommends** updates and optimized settings via a rules engine, with an
   optional **Claude AI analysis** tailored to your exact model.
3. **Applies** the safe fixes itself (`auto` mode) — cleanups, power plan,
   `winget upgrade --all` — with confirmation by default, unattended with
   `--yes`. Driver installs and hardware work are never automated: it gives
   exact instructions instead, because auto-installing drivers is how systems
   get bricked.
4. **BMS engine**: stops charging at a threshold and resumes at a lower one.
5. **Upgrade report** for old laptops — from SSD/RAM up to solder-level work,
   with honest cost/risk on each.

## Quick start (on your Windows laptop)

```bat
cd laptop-tuneup

:: Scan + report + apply safe fixes, one shot:
python -m tuneup auto

:: Or step by step:
python -m tuneup scan --out inventory.json
python -m tuneup analyze --input inventory.json
python -m tuneup apply   --input inventory.json --dry-run

:: Fully unattended (safe subset only):
python -m tuneup auto --yes
```

Run from an **administrator** prompt for the most complete scan and for
applying fixes. Python 3.9+; no packages required for the core.

## AI analysis (optional)

```bat
pip install anthropic
set ANTHROPIC_API_KEY=sk-ant-...
python -m tuneup analyze --ai
```

Sends your inventory + findings to Claude (`claude-opus-4-8`) and returns a
plan tailored to your exact model — what to buy, what to skip, and what it
would honestly not bother with. Nothing is sent anywhere unless you pass
`--ai`.

## The BMS engine — and the honest part

**Software cannot directly stop your battery charging on most laptops.** The
embedded controller (firmware) owns charging. Anyone who tells you a generic
app can flip it off is guessing or lying. What actually works — and what this
tool implements — is:

| Mechanism | Command | Works on |
|---|---|---|
| **Vendor firmware threshold** (best) | `python -m tuneup bms vendor` | Lenovo, ASUS, Dell, MSI, Samsung, Surface, some HP/Acer — set once in firmware, works forever |
| **Smart plug** (universal) | `bms run` with plug URLs | Any laptop + any HTTP-controllable plug: physically cuts AC at the stop %, restores at the resume % |
| **Alerts** (fallback) | `bms run` with no plug | Any laptop — tells you when to unplug/replug |

```bat
:: Alert mode: notify at 80%, remind at 40%
python -m tuneup bms run --stop 80 --resume 40

:: Smart plug mode (Tasmota example) — actually stops/starts charging:
python -m tuneup bms run --stop 80 --resume 40 ^
  --plug-on-url  "http://192.168.1.50/cm?cmnd=Power%%20On" ^
  --plug-off-url "http://192.168.1.50/cm?cmnd=Power%%20Off"

:: Shelly plug:  http://IP/relay/0?turn=on   /   turn=off
```

The 80/40 defaults follow the common guidance that lithium cells age fastest
held at 100% and hot; cycling in the middle band extends lifespan. Note: in
smart-plug mode the laptop runs from battery between cycles — that's the
point.

Run it at login via Task Scheduler:

```bat
schtasks /create /tn "TuneUp BMS" /sc onlogon /tr "cmd /c cd /d C:\path\to\laptop-tuneup && python -m tuneup bms run --stop 80 --resume 40"
```

## What "make it faster" honestly looks like

For an old laptop, in order of real impact:

1. **HDD → SSD** — the single biggest upgrade, by far.
2. **RAM to 8–16 GB** — if slots allow (the scan tells you).
3. **Thermal paste + fan cleaning** — old paste causes throttling.
4. **Fresh battery** — worn packs can trigger CPU power-limit throttling.
5. Software: trim startup apps, update drivers from the *vendor's* site,
   High Performance power plan on AC, keep 10%+ disk free.
6. **Solder-level (reballing/BGA) — the honest take:** replacing soldered RAM
   or a BGA CPU/GPU is technically possible with a rework station, donor
   chips, and BIOS support, but it usually costs more than the laptop is
   worth and carries real brick risk. GPU *reballing* is a repair for cracked
   solder joints (artifacting/no display), not an upgrade — and reflowed
   joints often fail again. Do it as a hobby or for a rare machine; otherwise
   put the money toward items 1–4.

The scanner + `analyze` produce this list tailored to your actual hardware;
`--ai` refines it further for your exact model.

## Tests

```bash
pip install pytest
PYTHONPATH=. python -m pytest -q     # 25 tests; run on any OS
```

Parsers, rules, the BMS hysteresis state machine, and the apply gates are all
tested with recorded fixtures — no Windows needed for the test suite.

## Safety notes

- `apply` runs only the whitelisted safe scripts, shows each one first, and
  never touches drivers/BIOS/firmware.
- The BMS never writes to the embedded controller; vendor thresholds are set
  through official vendor tools only.
- The scan is read-only.
