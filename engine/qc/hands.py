"""Hands: five fingers per visible hand, no fused or extra digits.

There is no numeric hand check that works on generated video, so this gate reads a
verdict recorded by an agent that looked at the frames (the build loop runs inside a
multimodal Claude session; D6 in SPEC.md). The verdict lives in qc/verdicts.json:

    {"hands": {"frames": {"pass": true, "note": "..."}, "clip": {"pass": false, "note": "..."}}}

A missing verdict fails the gate, so the loop cannot go green without someone looking.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import result


def check(verdicts_path: str | Path, stage: str) -> dict[str, Any]:
    p = Path(verdicts_path)
    data = json.loads(p.read_text()) if p.exists() else {}
    v = (data.get("hands") or {}).get(stage)
    if not v:
        return result(False, {"verdict": None},
                      f"Look at the {stage} images and record a hands verdict (foundry verdict --check hands).")
    ok = bool(v.get("pass"))
    return result(ok, {"verdict": v},
                  "Hands are malformed: " + str(v.get("note") or "fix finger count") +
                  ". Ask for anatomically correct hands with five fingers, one hand relaxed and visible.")
