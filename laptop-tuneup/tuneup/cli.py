"""TuneUp CLI.

    python -m tuneup scan  --out inventory.json
    python -m tuneup analyze [--input inventory.json] [--ai]
    python -m tuneup apply   [--input inventory.json] [--yes] [--dry-run]
    python -m tuneup auto    [--ai] [--yes]      # scan -> analyze -> apply
    python -m tuneup bms run [--stop 80] [--resume 40]
                             [--plug-on-url URL --plug-off-url URL]
    python -m tuneup bms vendor                  # firmware-threshold guidance
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from typing import List

from . import analyzer, apply as apply_mod, bms, scanner, vendor
from .analyzer import Recommendation


def _load_or_scan(args) -> dict:
    if getattr(args, "input", None):
        with open(args.input) as fh:
            return json.load(fh)
    print("Scanning system (this can take a minute)...")
    return scanner.scan_system()


def _analyze(inv) -> List[Recommendation]:
    return analyzer.analyze(inv)


def cmd_scan(args) -> int:
    inv = scanner.scan_system()
    out = args.out or "inventory.json"
    with open(out, "w") as fh:
        json.dump(inv, fh, indent=1, default=str)
    print(f"Inventory saved to {out}")
    if inv.get("errors"):
        print(f"(some sub-scans failed: {', '.join(inv['errors'])})")
    return 0


def cmd_analyze(args) -> int:
    inv = _load_or_scan(args)
    recs = _analyze(inv)
    print()
    print(analyzer.render_report(recs))
    if args.ai:
        from . import ai
        print("=" * 60)
        print("AI ANALYSIS (Claude)")
        print("=" * 60)
        findings = [dataclasses.asdict(r) for r in recs]
        print(ai.ai_analyze(inv, findings))
    if args.out:
        payload = {"inventory": inv,
                   "recommendations": [dataclasses.asdict(r) for r in recs]}
        with open(args.out, "w") as fh:
            json.dump(payload, fh, indent=1, default=str)
        print(f"Report saved to {args.out}")
    return 0


def cmd_apply(args) -> int:
    inv = _load_or_scan(args)
    recs = _analyze(inv)
    apply_mod.apply_recommendations(recs, assume_yes=args.yes,
                                    dry_run=args.dry_run)
    return 0


def cmd_auto(args) -> int:
    """The 'perform all tasks on its own' mode: scan -> analyze -> apply."""
    inv = scanner.scan_system()
    recs = _analyze(inv)
    print()
    print(analyzer.render_report(recs))
    if args.ai:
        from . import ai
        findings = [dataclasses.asdict(r) for r in recs]
        print("=" * 60)
        print("AI ANALYSIS (Claude)")
        print("=" * 60)
        print(ai.ai_analyze(inv, findings))
    apply_mod.apply_recommendations(recs, assume_yes=args.yes)
    return 0


def cmd_bms_run(args) -> int:
    plug = None
    if args.plug_on_url and args.plug_off_url:
        plug = bms.SmartPlug(args.plug_on_url, args.plug_off_url)
    elif args.plug_on_url or args.plug_off_url:
        print("error: provide BOTH --plug-on-url and --plug-off-url",
              file=sys.stderr)
        return 1
    cfg = bms.BMSConfig(stop_percent=args.stop, resume_percent=args.resume,
                        poll_seconds=args.poll)
    try:
        bms.run_bms(cfg, plug=plug)
    except KeyboardInterrupt:
        print("\nBMS stopped.")
    return 0


def cmd_bms_vendor(args) -> int:
    manufacturer = args.manufacturer
    if not manufacturer:
        try:
            inv = scanner.scan_system(progress=lambda *_: None)
            manufacturer = (inv.get("system") or {}).get("manufacturer")
        except Exception:
            manufacturer = None
    print(vendor.guidance(manufacturer))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tuneup", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)

    sc = sub.add_parser("scan", help="Scan hardware/software/drivers to JSON")
    sc.add_argument("--out", default="inventory.json")
    sc.set_defaults(func=cmd_scan)

    an = sub.add_parser("analyze", help="Recommendations from a scan")
    an.add_argument("--input", help="Use a saved inventory.json instead of scanning")
    an.add_argument("--ai", action="store_true",
                    help="Add Claude AI analysis (needs anthropic SDK + API key)")
    an.add_argument("--out", help="Save full JSON report")
    an.set_defaults(func=cmd_analyze)

    ap = sub.add_parser("apply", help="Apply the safe auto-fixes")
    ap.add_argument("--input")
    ap.add_argument("--yes", action="store_true",
                    help="Apply the safe set without per-item confirmation")
    ap.add_argument("--dry-run", action="store_true")
    ap.set_defaults(func=cmd_apply)

    au = sub.add_parser("auto", help="Scan + analyze + apply in one run")
    au.add_argument("--ai", action="store_true")
    au.add_argument("--yes", action="store_true")
    au.set_defaults(func=cmd_auto)

    bm = sub.add_parser("bms", help="Battery management engine")
    bsub = bm.add_subparsers(dest="bms_command", required=True)
    br = bsub.add_parser("run", help="Run the charge-limit loop")
    br.add_argument("--stop", type=int, default=80,
                    help="Stop charging at this %% (default 80)")
    br.add_argument("--resume", type=int, default=40,
                    help="Resume charging at this %% (default 40)")
    br.add_argument("--poll", type=float, default=60.0,
                    help="Seconds between battery checks")
    br.add_argument("--plug-on-url",
                    help="Smart plug HTTP URL that turns power ON")
    br.add_argument("--plug-off-url",
                    help="Smart plug HTTP URL that turns power OFF")
    br.set_defaults(func=cmd_bms_run)
    bv = bsub.add_parser("vendor",
                         help="Firmware charge-threshold options for your brand")
    bv.add_argument("--manufacturer")
    bv.set_defaults(func=cmd_bms_vendor)
    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
