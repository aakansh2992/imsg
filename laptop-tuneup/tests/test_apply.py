"""Apply-engine tests: only scripted recs run; confirmation gates respected."""

from tuneup.analyzer import Recommendation
from tuneup.apply import applicable, apply_recommendations


def _recs():
    return [
        Recommendation(id="manual", severity="high", category="hardware",
                       title="Swap to SSD", why="w", action="a"),
        Recommendation(id="scripted", severity="low", category="settings",
                       title="Set power plan", why="w", action="a",
                       auto_apply_script="echo hi"),
    ]


def test_applicable_filters_to_scripted():
    assert [r.id for r in applicable(_recs())] == ["scripted"]


def test_dry_run_applies_nothing(capsys):
    applied = apply_recommendations(_recs(), dry_run=True)
    assert applied == 0
    assert "[dry-run]" in capsys.readouterr().out


def test_declining_skips(capsys):
    applied = apply_recommendations(_recs(), ask=lambda _: "n")
    assert applied == 0
    assert "skipped" in capsys.readouterr().out
