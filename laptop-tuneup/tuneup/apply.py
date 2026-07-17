"""Apply engine: execute the safe subset of recommendations.

Autonomy with a seatbelt: only recommendations that carry an
`auto_apply_script` are executable at all (cleanups, power plan, winget
updates). Driver installs, BIOS changes, and hardware work are never
automated. Default is confirm-each; `--yes` applies the safe set unattended.
"""

from __future__ import annotations

from typing import List

from . import runner
from .analyzer import Recommendation


def applicable(recs: List[Recommendation]) -> List[Recommendation]:
    return [r for r in recs if r.auto_apply_script]


def apply_recommendations(recs: List[Recommendation],
                          assume_yes: bool = False,
                          dry_run: bool = False,
                          ask=input, out=print) -> int:
    todo = applicable(recs)
    if not todo:
        out("Nothing auto-applicable. Everything else needs manual action "
            "(see the report).")
        return 0
    applied = 0
    for r in todo:
        out(f"\n-> {r.title}")
        out(f"   script: {r.auto_apply_script}")
        if dry_run:
            out("   [dry-run] skipped")
            continue
        if not assume_yes:
            answer = ask("   apply? [y/N] ").strip().lower()
            if answer not in ("y", "yes"):
                out("   skipped")
                continue
        try:
            runner.run_powershell(r.auto_apply_script, timeout=1800)
            out("   done")
            applied += 1
        except Exception as exc:
            out(f"   FAILED: {exc}")
    out(f"\nApplied {applied}/{len(todo)} auto-applicable fixes.")
    return applied
