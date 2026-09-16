"""On-screen words: no-ai-slop rules plus the account charter's never-list.

Charter never-lists are prose, so banned phrases are the quoted fragments inside
them ('buy X', "don't miss", 'guaranteed returns / get rich / risk-free'), split on
' / '. An explicit charter["compliance"]["banned_phrases"] list is honoured too.
"""
from __future__ import annotations

import re
from typing import Any

from . import result

SLOP_WORDS = ["delve", "crucial", "robust", "comprehensive", "nuanced", "multifaceted", "furthermore",
              "moreover", "additionally", "pivotal", "landscape", "tapestry", "underscore", "foster",
              "showcase", "intricate", "vibrant", "game-changer", "unlock", "elevate", "seamless",
              "leverage", "revolutionize", "in today's"]
# A quote opens after a non-letter and closes before a non-letter, so apostrophes
# inside a phrase ("don't miss") do not end it.
QUOTED = re.compile(r"(?<![A-Za-z])['\u2018\u201c\"](.{3,60}?)['\u2019\u201d\"](?![A-Za-z])")


def charter_phrases(charter: dict[str, Any] | None) -> list[str]:
    if not charter:
        return []
    out: list[str] = []
    for line in charter.get("never_list") or []:
        for frag in QUOTED.findall(str(line)):
            out += [p.strip() for p in frag.split(" / ") if len(p.strip()) >= 3]
    out += list(((charter.get("compliance") or {}).get("banned_phrases")) or [])
    seen, uniq = set(), []
    for p in out:
        k = p.lower()
        if k not in seen:
            seen.add(k)
            uniq.append(p)
    return uniq


def lint(text: str, charter: dict[str, Any] | None = None, max_chars: int = 140) -> dict[str, Any]:
    fails: list[str] = []
    if "\u2014" in text or "\u2013" in text:
        fails.append("uses an em or en dash")
    low = text.lower()
    for w in SLOP_WORDS:
        if re.search(r"\b" + re.escape(w) + r"\b", low):
            fails.append(f"AI-sounding word '{w}'")
    for p in charter_phrases(charter):
        # An uppercase X in a never-list phrase is a placeholder: 'buy X' bans "buy TSLA".
        pat = r"\s+".join(r"\w+" if tok == "X" else re.escape(tok.lower()) for tok in p.split())
        if re.search(r"(?<!\w)" + pat + r"(?!\w)", low):
            fails.append(f"charter never-list phrase '{p}'")
    if len(text) > max_chars:
        fails.append(f"{len(text)} characters, over {max_chars}")
    return result(not fails, {"text": text, "failed": fails},
                  "Caption text: " + "; ".join(fails) + ". Rewrite the line in plain phone-typed words.")
