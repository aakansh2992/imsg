"""Battery management (BMS) engine.

Reality check, stated plainly: on most laptops, software cannot directly stop
the embedded controller from charging. Three mechanisms actually work:

1. Vendor firmware hooks — Lenovo/ASUS/Dell/MSI expose charge thresholds via
   their own channels (see vendor.py). Where available, that's the cleanest.
2. A smart plug — physically cuts AC power at the wall. Universal and real:
   charging stops at the stop threshold, resumes at the resume threshold.
   Works with any laptop and any locally-controllable plug (Tasmota, Shelly,
   or anything with simple HTTP on/off URLs).
3. Alerts — if neither is available, the tool tells you to unplug/replug.

The threshold logic is a small hysteresis state machine, kept pure so it's
unit-testable; actuators are pluggable.
"""

from __future__ import annotations

import time
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional

from . import runner

# --------------------------------------------------------------------------- #
# Pure decision logic
# --------------------------------------------------------------------------- #


@dataclass
class BMSConfig:
    stop_percent: int = 80    # stop charging at/above this
    resume_percent: int = 40  # resume charging at/below this
    poll_seconds: float = 60.0

    def __post_init__(self):
        if not (0 < self.resume_percent < self.stop_percent <= 100):
            raise ValueError("need 0 < resume < stop <= 100")


class BMSController:
    """Hysteresis: charge up to stop%, discharge down to resume%, repeat."""

    def __init__(self, config: BMSConfig):
        self.cfg = config
        self.charging_enabled = True  # what we last commanded

    def decide(self, percent: Optional[int]) -> Optional[str]:
        """Returns 'stop' / 'resume' / None given the battery percent."""
        if percent is None:
            return None
        if self.charging_enabled and percent >= self.cfg.stop_percent:
            self.charging_enabled = False
            return "stop"
        if not self.charging_enabled and percent <= self.cfg.resume_percent:
            self.charging_enabled = True
            return "resume"
        return None


# --------------------------------------------------------------------------- #
# Actuators
# --------------------------------------------------------------------------- #

class SmartPlug:
    """HTTP-controllable plug. Give it the exact on/off URLs.

    Tasmota:  http://PLUG_IP/cm?cmnd=Power%20On   /  Power%20Off
    Shelly:   http://PLUG_IP/relay/0?turn=on      /  turn=off
    """

    def __init__(self, on_url: str, off_url: str, opener=None,
                 timeout: float = 10.0):
        self.on_url = on_url
        self.off_url = off_url
        self._open = opener or (lambda url: urllib.request.urlopen(
            url, timeout=timeout))
        self.timeout = timeout

    def set_power(self, on: bool) -> bool:
        url = self.on_url if on else self.off_url
        try:
            with self._open(url) as resp:  # noqa: F841
                return True
        except Exception:
            return False


class Notifier:
    """Console + best-effort Windows toast notification."""

    def notify(self, message: str) -> None:
        print(f"[BMS] {message}", flush=True)
        if runner.is_windows():
            script = (
                "[void][System.Reflection.Assembly]::LoadWithPartialName("
                "'System.Windows.Forms');"
                "$n = New-Object System.Windows.Forms.NotifyIcon;"
                "$n.Icon = [System.Drawing.SystemIcons]::Information;"
                "$n.Visible = $true;"
                f"$n.ShowBalloonTip(10000, 'TuneUp BMS', '{message}', "
                "[System.Windows.Forms.ToolTipIcon]::Info)")
            try:
                runner.run_powershell(script, timeout=15)
            except Exception:
                pass


# --------------------------------------------------------------------------- #
# Battery reading + main loop
# --------------------------------------------------------------------------- #

PS_BATTERY_QUICK = (
    "Get-CimInstance Win32_Battery | Select-Object EstimatedChargeRemaining, "
    "BatteryStatus | ConvertTo-Json"
)


def read_battery() -> Optional[dict]:
    data = runner.run_powershell_json(PS_BATTERY_QUICK, timeout=30)
    if not data:
        return None
    if isinstance(data, list):
        data = data[0]
    return {"percent": data.get("EstimatedChargeRemaining"),
            "on_ac": data.get("BatteryStatus") == 2}


def run_bms(config: BMSConfig,
            plug: Optional[SmartPlug] = None,
            notifier: Optional[Notifier] = None,
            reader: Callable[[], Optional[dict]] = read_battery,
            sleep: Callable[[float], None] = time.sleep,
            max_cycles: Optional[int] = None) -> None:
    """The BMS loop. Ctrl-C to stop.

    With a plug: physically cuts/restores AC at the thresholds.
    Without:     alerts you to unplug/replug at the thresholds.
    """
    ctrl = BMSController(config)
    notifier = notifier or Notifier()
    mode = "smart-plug" if plug else "alert-only"
    notifier.notify(
        f"BMS running ({mode}): stop at {config.stop_percent}%, "
        f"resume at {config.resume_percent}%")

    cycles = 0
    while max_cycles is None or cycles < max_cycles:
        cycles += 1
        try:
            state = reader()
        except Exception as exc:
            notifier.notify(f"battery read failed: {exc}")
            sleep(config.poll_seconds)
            continue
        pct = state.get("percent") if state else None
        action = ctrl.decide(pct)
        if action == "stop":
            if plug:
                ok = plug.set_power(False)
                notifier.notify(
                    f"{pct}% reached - AC power {'cut' if ok else 'CUT FAILED'} "
                    f"(will resume at {config.resume_percent}%)")
            else:
                notifier.notify(f"{pct}% reached - unplug the charger "
                                f"(will remind at {config.resume_percent}%)")
        elif action == "resume":
            if plug:
                ok = plug.set_power(True)
                notifier.notify(
                    f"{pct}% - AC power {'restored' if ok else 'RESTORE FAILED'} "
                    f"(will stop at {config.stop_percent}%)")
            else:
                notifier.notify(f"{pct}% - plug the charger back in")
        sleep(config.poll_seconds)
