from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import PromptError, build, families, load


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="engine.prompts",
                                 description="Versioned, linted prompt library.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="list prompt families")

    sh = sub.add_parser("show", help="print a family's full craft guidance")
    sh.add_argument("family")

    b = sub.add_parser("build", help="render a prompt from slots")
    b.add_argument("family")
    b.add_argument("--slots", help="path to a JSON file of slots")
    b.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    b.add_argument("--lenient", action="store_true",
                   help="warn instead of failing (never use for a paid render)")
    b.add_argument("--json", action="store_true", help="emit the full result object")

    a = ap.parse_args(argv)

    if a.cmd == "list":
        for f in families():
            spec = load(f)
            req = [n for n, r in (spec.get("slots") or {}).items()
                   if isinstance(r, dict) and r.get("required")]
            print(f"{f:20} v{spec.get('version')}  {spec.get('purpose','')}")
            print(f"{'':20} required: {', '.join(req)}\n")
        return 0

    if a.cmd == "show":
        spec = load(a.family)
        print(spec["body"])
        return 0

    slots: dict = {}
    if a.slots:
        slots.update(json.loads(Path(a.slots).read_text()))
    for pair in a.set:
        if "=" not in pair:
            print(f"--set expects KEY=VALUE, got {pair!r}", file=sys.stderr)
            return 2
        k, v = pair.split("=", 1)
        slots[k] = v

    try:
        result = build(a.family, slots, strict=not a.lenient)
    except PromptError as e:
        print(f"prompt rejected: {e}", file=sys.stderr)
        return 1

    if a.json:
        print(json.dumps(result, indent=2))
    else:
        print(result["prompt"])
        if result["warnings"]:
            print("\n-- warnings --", file=sys.stderr)
            for w in result["warnings"]:
                print(f"   {w}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
