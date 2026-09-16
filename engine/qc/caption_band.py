"""Caption placement: inside the band, inside the middle 80 %, never over the face.

Band defaults follow the reel-style caption spec: a top caption starts at 11 % of
frame height and nothing sits below 71 % (the platform UI covers the bottom).
"""
from __future__ import annotations

from typing import Any, Sequence

from . import result

SAFE_DEFAULT = {"top_pct": 11, "bottom_pct": 71}


def _overlap(a: Sequence[float], b: Sequence[float]) -> float:
    w = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    h = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    area = max(1e-9, (a[2] - a[0]) * (a[3] - a[1]))
    return w * h / area


def check(caption_box: Sequence[float], face_box: Sequence[float] | None,
          top_pct: float = SAFE_DEFAULT["top_pct"], bottom_pct: float = SAFE_DEFAULT["bottom_pct"],
          side_margin: float = 0.10) -> dict[str, Any]:
    x0, y0, x1, y1 = caption_box
    fails = []
    if y0 < top_pct / 100 - 0.005:
        fails.append(f"caption starts at {y0:.3f}, above the {top_pct}% band start")
    if y1 > bottom_pct / 100 + 0.005:
        fails.append(f"caption ends at {y1:.3f}, below the {bottom_pct}% safe line")
    if x0 < side_margin - 0.005 or x1 > 1 - side_margin + 0.005:
        fails.append("caption is wider than the middle 80% of the frame")
    ov = _overlap(caption_box, face_box) if face_box else 0.0
    if ov > 0.02:
        fails.append(f"caption covers {ov:.0%} of its area over the face")
    return result(not fails, {"caption_box": [round(v, 3) for v in caption_box],
                              "face_box": list(face_box) if face_box else None,
                              "face_overlap": round(ov, 3), "failed": fails},
                  "Caption: " + "; ".join(fails) + ". Move the caption band or shorten the line.")
