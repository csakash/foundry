"""The carousel input contract — one seed in, a six-slot fill out.

A carousel in this stack is not "some slides about a topic". It is a fixed
six-role ladder (see .claude/skills/foundry-carousel/SKILL.md):

    provocation -> proof -> mechanism -> example -> widen -> open loop

which means the input question has an exact answer: an input is valid **iff it
can fill those six slots**. Everything the user hands over is a *seed*; the six
slots are the *fill*; the foundry resolves fill from seed and asks the human
only about what it could not resolve. A seed that cannot reach four resolved
slots is not a carousel — it is a single-image post or a reel, and this module
says which.

    python3 -m engine.carousel_intake scaffold work/@handle/slug \
        --seed-type url --seed https://... --ask "why did K-markets fall"
    python3 -m engine.carousel_intake check work/@handle/slug

`check` is the Gate-1 lint for carousels: it resolves evidence ids against the
ledger, lints the provocation and the open loop, enforces the two transfer rules
(paint the reader's row, convert foreign numbers), and prints the routing
verdict plus exactly what is still owed.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from . import evidence

ROOT = evidence.ROOT

# The ladder, locked. Order is the swipe order; `expands` marks the roles that
# may take more than one slide when the story needs it (7-10 slides total).
SLOTS: list[dict[str, Any]] = [
    {"key": "provocation", "required": True,  "expands": False,
     "asks": "What flat statement about this shouldn't be true?"},
    # `raises` is not a seventh slide — it is the provocation's own proof of work.
    {"key": "proof",       "required": True,  "expands": False,
     "asks": "Which single sourced number makes it real — and what jargon inside it needs a gloss?"},
    {"key": "mechanism",   "required": True,  "expands": True,
     "asks": "How does it actually work, in two or three causal steps?"},
    {"key": "example",     "required": True,  "expands": True,
     "asks": "Which real, nameable entity is this happening to?"},
    {"key": "widen",       "required": False, "expands": True,
     "asks": "Where else has this happened — another country, another scale, a precedent?"},
    {"key": "open_loop",   "required": False, "expands": False,
     "asks": "What question about this would you actually read the answers to?"},
]
SLOT_KEYS = [s["key"] for s in SLOTS]

SEED_TYPES = ("url", "claim", "figure", "question", "document", "reference_post", "topic")

# A provocation that says "you" is an ad; one with a number has spent slide 2's
# ammunition on the cover; one over eight words is not a cover line.
PROVOCATION_MAX_WORDS = 8
SECOND_PERSON = re.compile(r"\b(you|your|you're|yours)\b", re.I)
HAS_DIGIT = re.compile(r"\d")
DEAD_LOOPS = ("what do you think", "let us know", "comment below", "drop your thoughts",
               "thoughts?", "share your views", "tell us in the comments")

# The "so what" gate. A cover line earns the swipe only if it opens a gap the
# reader wants closed. The check is not a vibe: name the question the reader asks
# in their head after reading it. If that question is a shrug, the line failed —
# no rewrite of the wording will save a line that raises nothing.
SHRUGS = ("so what", "who cares", "why should i care", "and", "ok", "okay",
          "interesting", "tell me more", "cool", "nice", "sure", "right")
ASKING = ("which", "what", "why", "how", "who", "where", "when", "wait", "since when",
          "how much", "how many")
FOREIGN = re.compile(r"(\$|US\$|USD|€|EUR|£|GBP|¥|JPY|KRW|₩|\bbn\b|\bbillion dollars\b)", re.I)


def blank_fill() -> dict[str, Any]:
    fill: dict[str, Any] = {}
    for s in SLOTS:
        fill[s["key"]] = {"status": "missing", "value": None, "source": None}
    fill["proof"].update({"figure": None, "evidence_id": None, "gloss": None,
                          "table": None, "highlight_row": None})
    fill["provocation"].update({"raises": None, "answered_on": 2})
    fill["example"].update({"name": None})
    fill["local_anchor"] = {"status": "n/a", "value": None,
                            "note": "required when any figure is denominated in a foreign currency"}
    return fill


def scaffold(work_dir: Path, seed_type: str, seed: str, ask: str | None) -> Path:
    if seed_type not in SEED_TYPES:
        raise SystemExit(f"seed type must be one of: {', '.join(SEED_TYPES)}")
    work_dir.mkdir(parents=True, exist_ok=True)
    path = work_dir / "00-intake.json"
    doc = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {
        "spec_version": "intake/1.0",
        "slug": work_dir.name,
        "account": work_dir.parent.name if work_dir.parent.name.startswith("@") else None,
        "created": date.today().isoformat(),
        "user_ask": ask or "",
        "inputs": [],
    }
    doc.setdefault("inputs", []).append({"type": seed_type, "value": seed, "role": "carousel seed"})
    doc["post_type"] = "carousel"
    doc["carousel"] = {
        "contract": "six-slot ladder — see .claude/skills/foundry-carousel/SKILL.md",
        "seed": {"type": seed_type, "value": seed, "ask": ask},
        "fill": doc.get("carousel", {}).get("fill") or blank_fill(),
        "locks": {"slide_count": None, "sell": False, "account_voice": None},
    }
    path.write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")
    return path


# ------------------------------------------------------------------ checking

def _resolved(slot: dict[str, Any]) -> bool:
    return slot.get("status") == "resolved" and bool(slot.get("value"))


def check(work_dir: Path) -> tuple[list[str], list[str], str]:
    """Returns (failures, owed, routing verdict)."""
    path = work_dir / "00-intake.json"
    if not path.exists():
        raise SystemExit(f"no 00-intake.json in {work_dir}")
    doc = json.loads(path.read_text(encoding="utf-8"))
    car = doc.get("carousel")
    if not car:
        raise SystemExit(f"{path} has no carousel block — run `scaffold` first")
    fill = car.get("fill") or {}
    fails: list[str] = []
    owed: list[str] = []

    for s in SLOTS:
        slot = fill.get(s["key"]) or {}
        if _resolved(slot):
            continue
        (owed if s["required"] else owed).append(f"{s['key']}: {s['asks']}")

    prov = (fill.get("provocation") or {}).get("value") or ""
    if prov:
        if len(prov.split()) > PROVOCATION_MAX_WORDS:
            fails.append(f"provocation is {len(prov.split())} words — the cover line is "
                         f"{PROVOCATION_MAX_WORDS} or fewer")
        if SECOND_PERSON.search(prov):
            fails.append("provocation says 'you' — the cover states a fact, it doesn't address the reader")
        if HAS_DIGIT.search(prov):
            fails.append("provocation carries a number — that number belongs on slide 2, not the cover")
        seed_val = str((car.get("seed") or {}).get("value") or "")
        if prov.strip().lower() and prov.strip().lower() in seed_val.lower():
            fails.append("provocation is the source headline verbatim — the cover is the layer underneath it")

        # the so-what gate
        raises = ((fill.get("provocation") or {}).get("raises") or "").strip()
        if not raises:
            owed.append("provocation: write the question the reader asks after reading it. "
                        "If you cannot, the line raises nothing and there is no reason to swipe.")
        else:
            low = raises.lower().rstrip("?").strip()
            if low in SHRUGS:
                fails.append(f"the cover raises '{raises}' — that is a shrug, not curiosity. "
                             f"The line states something and closes it. Open a gap instead: a "
                             f"contradiction, a number that is off, or a withheld referent.")
            elif not (low.startswith(ASKING) or raises.endswith("?")):
                fails.append(f"the cover's `raises` is not a question ('{raises}') — name what the "
                             f"reader actually wants to know next")
            elif len(raises.split()) > 12:
                fails.append(f"the cover raises a {len(raises.split())}-word question — a real one is "
                             f"short, because it is the first thing that occurs to someone")

    proof = fill.get("proof") or {}
    if _resolved(proof):
        eid = proof.get("evidence_id")
        if not eid:
            fails.append("proof has no evidence_id — every figure on a slide needs a ledger row "
                         "(engine.evidence.put_figure)")
        else:
            man = evidence.MANIFEST
            entries = (json.loads(man.read_text(encoding="utf-8")).get("entries", {})
                       if man.exists() else {})
            if eid not in entries:
                fails.append(f"proof cites evidence id '{eid}' which is not in the ledger")
        if not proof.get("gloss"):
            owed.append("proof: gloss the jargon inside the number (the bottom-right slot)")
        if proof.get("table") and not proof.get("highlight_row"):
            fails.append("proof renders a table with no highlight_row — paint the row the reader "
                         "stands in (their index, their year)")

    ex = fill.get("example") or {}
    if _resolved(ex) and not ex.get("name"):
        fails.append("example has no name — 'a company' is not an example")

    loop = (fill.get("open_loop") or {}).get("value") or ""
    if loop and any(d in loop.lower() for d in DEAD_LOOPS):
        fails.append(f"open loop is a dead prompt ('{loop.strip()}') — ask something the account "
                     f"would actually read the answers to")

    blob = json.dumps(fill, ensure_ascii=False)
    anchor = fill.get("local_anchor") or {}
    if FOREIGN.search(blob) and anchor.get("status") != "resolved":
        fails.append("a foreign-denominated figure is in the fill with no local_anchor — convert it "
                     "into a number the reader can feel (a quarter's profit in local-giant years)")

    n_res = sum(1 for s in SLOTS if _resolved(fill.get(s["key"]) or {}))
    req_res = sum(1 for s in SLOTS if s["required"] and _resolved(fill.get(s["key"]) or {}))
    if req_res == 4:
        verdict = f"CAROUSEL — all four required slots resolved ({n_res}/6 total)"
    elif _resolved(proof) and req_res <= 2:
        verdict = ("SINGLE IMAGE — there is a sourced number but no mechanism/example under it. "
                   "One chart, one claim, one caption is the honest post here.")
    elif req_res == 0:
        verdict = "NOT BUILDABLE — the seed has not resolved into anything yet"
    else:
        verdict = (f"NOT YET — {req_res}/4 required slots resolved. Resolve the rest, or drop to a "
                   f"single image post.")
    return fails, owed, verdict


def cmd_check(work_dir: Path) -> int:
    fails, owed, verdict = check(work_dir)
    print(verdict)
    if fails:
        print("\nfails:")
        for f in fails:
            print(f"  x {f}")
    if owed:
        print("\nstill owed (ask the human only about these):")
        for o in owed:
            print(f"  ? {o}")
    if not fails and not owed:
        print("\nfill is complete and clean — write 02-script.json and rebuild the review page.")
    return 1 if fails or owed else 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scaffold", help="start a carousel intake from one seed")
    s.add_argument("work_dir")
    s.add_argument("--seed-type", required=True, choices=SEED_TYPES)
    s.add_argument("--seed", required=True)
    s.add_argument("--ask", default=None, help="the user's own words, verbatim")
    c = sub.add_parser("check", help="lint the fill and route the post")
    c.add_argument("work_dir")
    a = ap.parse_args()
    if a.cmd == "scaffold":
        print(f"-> {scaffold(Path(a.work_dir), a.seed_type, a.seed, a.ask)}")
        print("   fill the six slots from the seed; ask the human only about what won't resolve.")
    else:
        raise SystemExit(cmd_check(Path(a.work_dir)))


if __name__ == "__main__":
    main()
