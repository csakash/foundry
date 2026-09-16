"""Pre-call prompt lint: phrases that trip image/video safety filters, with rewrites.

The table is data (catalog/safety_phrases.json) so a newly learned refusal is one
row, not a code change. `lint` never blocks on its own: the caller sends
`rewritten`, and records the hits so the invoice shows why a prompt changed.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from . import result

TABLE = Path(__file__).resolve().parents[2] / "catalog" / "safety_phrases.json"


def load_table(path: str | Path = TABLE) -> list[dict[str, str]]:
    return json.loads(Path(path).read_text())["phrases"]


def lint(text: str, table: list[dict[str, str]] | None = None) -> dict[str, Any]:
    table = load_table() if table is None else table
    hits, out = [], text
    for row in table:
        pat = re.compile(r"\b" + re.escape(row["phrase"]) + r"\b", re.I)
        if pat.search(out):
            hits.append({"phrase": row["phrase"], "rewrite": row["rewrite"], "why": row.get("why", "")})
            out = pat.sub(row["rewrite"], out)
    r = result(not hits, {"hits": hits},
               "Prompt used phrases that trip the safety filter: " + ", ".join(h["phrase"] for h in hits) + ".")
    r["rewritten"] = out
    return r
