"""Drift across a clip: skin numbers on sampled frames against frame 1.

Relative, so the whole-frame region is valid: background pixels are identical
between frames of a locked-off shot and cancel. Imani's clip moved lum 58.3..60.3
and R-B 6.5..8.0 across 121 frames.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from . import result
from .skin import measure


def check(frames: Sequence[str | Path], max_lum: float, max_rb: float = 12.0) -> dict[str, Any]:
    if len(frames) < 2:
        return result(False, {"frames": len(frames)}, "Sample at least two frames from the clip before the drift check.")
    series = []
    for f in frames:
        m = measure(f)
        if m is None:
            return result(False, {"frame": Path(f).name}, f"No measurable skin in {Path(f).name}; the subject left the frame.")
        series.append({"frame": Path(f).name, **m})
    base = series[0]
    dl = max(abs(s["lum"] - base["lum"]) for s in series)
    drb = max(abs(s["r_minus_b"] - base["r_minus_b"]) for s in series)
    worst = max(series, key=lambda s: abs(s["r_minus_b"] - base["r_minus_b"]) + abs(s["lum"] - base["lum"]))
    ok = dl <= max_lum and drb <= max_rb
    return result(ok, {"max_lum": round(dl, 1), "max_rb": round(drb, 1), "limit_lum": max_lum,
                       "limit_rb": max_rb, "worst_frame": worst["frame"], "series": series},
                  "Skin tone and light change during the clip; add 'lighting is constant, the face and skin tone stay "
                  "identical throughout' and remove any action that turns the face toward a different light source.")
