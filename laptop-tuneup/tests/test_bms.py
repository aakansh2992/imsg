"""BMS engine tests: hysteresis, smart plug, full loop with fakes."""

import pytest

from tuneup.bms import BMSConfig, BMSController, SmartPlug, run_bms
from tuneup.vendor import detect_vendor, guidance


def test_config_validation():
    with pytest.raises(ValueError):
        BMSConfig(stop_percent=40, resume_percent=80)
    with pytest.raises(ValueError):
        BMSConfig(stop_percent=101, resume_percent=40)


def test_hysteresis_no_flapping():
    c = BMSController(BMSConfig(stop_percent=80, resume_percent=40))
    assert c.decide(79) is None          # charging toward stop
    assert c.decide(80) == "stop"        # hit threshold once
    assert c.decide(81) is None          # no repeat commands
    assert c.decide(60) is None          # discharging, above resume
    assert c.decide(41) is None
    assert c.decide(40) == "resume"      # hit resume once
    assert c.decide(39) is None          # no repeat
    assert c.decide(80) == "stop"        # next cycle works


def test_none_percent_is_ignored():
    c = BMSController(BMSConfig())
    assert c.decide(None) is None


class _FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_smart_plug_calls_correct_urls():
    calls = []

    def opener(url):
        calls.append(url)
        return _FakeResponse()

    plug = SmartPlug("http://p/on", "http://p/off", opener=opener)
    assert plug.set_power(False) is True
    assert plug.set_power(True) is True
    assert calls == ["http://p/off", "http://p/on"]


def test_smart_plug_failure_returns_false():
    def opener(url):
        raise OSError("unreachable")

    plug = SmartPlug("http://p/on", "http://p/off", opener=opener)
    assert plug.set_power(True) is False


class _Recorder:
    def __init__(self):
        self.messages = []

    def notify(self, message):
        self.messages.append(message)


def test_run_bms_full_cycle_with_plug():
    # Battery climbs to 80 (cut), drains to 40 (restore).
    levels = iter([70, 80, 60, 40, 50])
    plug_calls = []

    def opener(url):
        plug_calls.append(url)
        return _FakeResponse()

    run_bms(
        BMSConfig(stop_percent=80, resume_percent=40, poll_seconds=0),
        plug=SmartPlug("http://p/on", "http://p/off", opener=opener),
        notifier=_Recorder(),
        reader=lambda: {"percent": next(levels), "on_ac": True},
        sleep=lambda s: None,
        max_cycles=5,
    )
    assert plug_calls == ["http://p/off", "http://p/on"]


def test_run_bms_alert_mode_messages():
    levels = iter([80, 40])
    rec = _Recorder()
    run_bms(
        BMSConfig(stop_percent=80, resume_percent=40, poll_seconds=0),
        plug=None, notifier=rec,
        reader=lambda: {"percent": next(levels), "on_ac": True},
        sleep=lambda s: None, max_cycles=2,
    )
    joined = " | ".join(rec.messages)
    assert "unplug" in joined
    assert "plug the charger back in" in joined


def test_vendor_detection_and_guidance():
    assert detect_vendor("LENOVO") == "lenovo"
    assert detect_vendor("ASUSTeK COMPUTER INC.") == "asus"
    assert detect_vendor("Weird Brand Co") is None
    assert "Vantage" in guidance("LENOVO")
    assert "smart plug" in guidance("Weird Brand Co").lower()
