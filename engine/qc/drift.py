"""Drift across a clip: skin numbers on sampled frames against frame 1.

Measured twice and both must hold: over the whole frame (lighting changes), and
inside the face box doubled in size (a face-only change is diluted by the background
in a whole-frame mean). The doubled box keeps a turning head inside it: on the Imani
clip it moved lum by 5.5 and R-B by 2.8; the whole frame moved lum 58.3..60.3.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from . import result
from .skin import Box, measure


def expand(box: Box, k: float = 1.0) -> list[float]:
    w, h = box[2] - box[0], box[3] - box[1]
    return [max(0.0, box[0] - w * k / 2), max(0.0, box[1] - h * k / 2), min(1.0, box[2] + w * k / 2),
            min(1.0, box[3] + h * k / 2)]


def _series(frames: Sequence[str | Path], box: Box | None) -> list[dict[str, Any]] | str:
    out = []
    for f in frames:
        m = measure(f, box)
        if m is None:
            return Path(f).name
        out.append({"frame": Path(f).name, **m})
    return out


def check(frames: Sequence[str | Path], max_lum: float, max_rb: float = 12.0,
          face_box: Box | None = None) -> dict[str, Any]:
    if len(frames) < 2:
        return result(False, {"frames": len(frames)}, "Sample at least two frames from the clip before the drift check.")
    regions = {"frame": None}
    if face_box:
        regions["face"] = expand(face_box, 1.0)
    measures: dict[str, Any] = {"limit_lum": max_lum, "limit_rb": max_rb}
    ok = True
    for name, box in regions.items():
        series = _series(frames, box)
        if isinstance(series, str):
            return result(False, {"frame": series, "region": name},
                          f"No measurable skin in {series} ({name} region); the subject left the frame.")
        base = series[0]
        dl = max(abs(x["lum"] - base["lum"]) for x in series)
        drb = max(abs(x["r_minus_b"] - base["r_minus_b"]) for x in series)
        worst = max(series, key=lambda x: abs(x["r_minus_b"] - base["r_minus_b"]) + abs(x["lum"] - base["lum"]))
        measures[name] = {"max_lum": round(dl, 1), "max_rb": round(drb, 1), "worst_frame": worst["frame"],
                          "box": box, "series": series}
        ok = ok and dl <= max_lum and drb <= max_rb
    measures["max_lum"] = max(measures[n]["max_lum"] for n in regions)
    measures["max_rb"] = max(measures[n]["max_rb"] for n in regions)
    measures["worst_frame"] = max((measures[n] for n in regions), key=lambda m: m["max_lum"] + m["max_rb"])["worst_frame"]
    return result(ok, measures,
                  "Skin tone and light change during the clip; add 'lighting is constant, the face and skin tone stay "
                  "identical throughout' and remove any action that turns the face toward a different light source.")
