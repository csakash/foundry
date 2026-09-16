"""Machine QC for the Foundry build loop.

Every module is a set of pure functions over files. Each check returns the same
shape so the loop can act on it without reading prose:

    {"pass": bool, "measures": {...}, "guidance": "one sentence for the next prompt"}

`guidance` is empty on a pass. On a fail it is written for the generator, not a
human: it is appended to the next regeneration prompt verbatim.
"""
from __future__ import annotations

from typing import Any


def result(ok: bool, measures: dict[str, Any], guidance: str = "") -> dict[str, Any]:
    return {"pass": bool(ok), "measures": measures, "guidance": "" if ok else guidance}
