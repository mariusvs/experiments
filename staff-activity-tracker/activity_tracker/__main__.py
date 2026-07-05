"""Command-line entry point.

    python -m activity_tracker run [--config PATH] [--yes]
    python -m activity_tracker report [--config PATH] [--days N] [--json]
    python -m activity_tracker efficiency [--config PATH] [--categories PATH] [--days N] [--json]
    python -m activity_tracker notice [--config PATH]
    python -m activity_tracker init-config PATH
"""

from __future__ import annotations

import argparse
import json
import sys

from .config import Config
from . import consent


def cmd_run(args) -> int:
    from .agent import Agent
    config = Config.load(args.config)
    agent = Agent(config)
    return agent.run(assume_yes=args.yes)


def cmd_report(args) -> int:
    from .storage import Storage
    from . import report as report_mod
    config = Config.load(args.config)
    storage = Storage(config.db_path)
    try:
        since = report_mod.default_since(args.days) if args.days else None
        rep = report_mod.build_report(storage, since=since)
    finally:
        storage.close()
    if args.json:
        print(json.dumps(rep, indent=2))
    else:
        print(report_mod.render_text(rep))
    return 0


def cmd_efficiency(args) -> int:
    from .storage import Storage
    from . import efficiency as eff_mod
    from . import report as report_mod
    config = Config.load(args.config)
    categories = args.categories or config.categories_file or None
    storage = Storage(config.db_path)
    try:
        since = report_mod.default_since(args.days) if args.days else None
        rep = eff_mod.build_efficiency(storage, categories_path=categories, since=since)
    finally:
        storage.close()
    if args.json:
        print(json.dumps(rep, indent=2))
    else:
        print(eff_mod.render_text(rep))
    return 0


def cmd_notice(args) -> int:
    config = Config.load(args.config)
    print(consent.notice_text(config.upload_url))
    return 0


def cmd_init_config(args) -> int:
    config = Config()
    config.save(args.path)
    print(f"Wrote default config to {args.path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="activity_tracker",
        description="Transparent, consent-based staff activity tracker.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("run", help="Start monitoring on this device")
    r.add_argument("--config", help="Path to JSON config file")
    r.add_argument("--yes", action="store_true",
                   help="Skip interactive consent prompt (consent handled by policy)")
    r.set_defaults(func=cmd_run)

    rep = sub.add_parser("report", help="Print an activity report from local data")
    rep.add_argument("--config", help="Path to JSON config file")
    rep.add_argument("--days", type=int, default=1, help="Look back this many days")
    rep.add_argument("--json", action="store_true", help="Emit JSON instead of text")
    rep.set_defaults(func=cmd_report)

    e = sub.add_parser("efficiency", help="Print a per-user efficiency report")
    e.add_argument("--config", help="Path to JSON config file")
    e.add_argument("--categories", help="Path to categories JSON (overrides config)")
    e.add_argument("--days", type=int, default=1, help="Look back this many days")
    e.add_argument("--json", action="store_true", help="Emit JSON instead of text")
    e.set_defaults(func=cmd_efficiency)

    n = sub.add_parser("notice", help="Print the monitoring notice text")
    n.add_argument("--config", help="Path to JSON config file")
    n.set_defaults(func=cmd_notice)

    ic = sub.add_parser("init-config", help="Write a default config file")
    ic.add_argument("path", help="Where to write the config JSON")
    ic.set_defaults(func=cmd_init_config)

    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
