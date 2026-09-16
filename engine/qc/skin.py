"""Skin tone numbers: mean luminance, R minus B, and saturation.

Colour alone cannot find a face: under cool screen light a near-black complexion
is closer to neutral than the warm wall behind it (measured on the Imani frames,
2026-09-16). So an ABSOLUTE check needs a face box, and the box is recorded by
whoever can see the frame (the build agent, or the cast skill) in qc/regions.json.
Without a box, `measure` falls back to the whole frame, which is only valid for
RELATIVE checks (drift against frame 1) and is labelled as such.

Inside the region, pixels count as skin-candidate when luminance is 18..190 (drops
eye whites, highlights on jewellery, and crushed hair shadow), saturation <= 0.60,
saturation >= `smin`, and R >= B. `smin` 0.07 removes neutral grey studio backdrops
(Imani master background: sat 3.2 %, R-B -1.4).

Calibration on Imani (face boxes): master 58.7 / 10.0 / 16.9, approved first frame
59.3 / 7.3 / 17.9, clip frames 54.9..60.2; a warmed copy of the master reads
R-B 42.9 / sat 51.0 and fails.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

import numpy as np
from PIL import Image

from . import result

Box = Sequence[float]  # x0, y0, x1, y1 as fractions of width/height


def load_rgb(path: str | Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGB")).astype(np.float32)


def crop(a: np.ndarray, box: Box | None) -> np.ndarray:
    if not box:
        return a
    h, w = a.shape[:2]
    x0, y0, x1, y1 = (max(0.0, min(1.0, float(v))) for v in box)
    if x1 <= x0 or y1 <= y0:
        raise ValueError(f"empty box {tuple(box)}")
    return a[int(y0 * h):max(int(y1 * h), int(y0 * h) + 1), int(x0 * w):max(int(x1 * w), int(x0 * w) + 1)]


def measure_array(a: np.ndarray, smin: float = 0.07) -> dict[str, float] | None:
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    mx, mn = a.max(-1), a.min(-1)
    sat = (mx - mn) / np.maximum(mx, 1.0)
    m = (lum >= 18) & (lum <= 190) & (sat <= 0.60) & (sat >= smin) & ((r - b) >= 0)
    if int(m.sum()) < 50:
        return None
    return {
        "lum": round(float(lum[m].mean()), 1),
        "r_minus_b": round(float((r - b)[m].mean()), 1),
        "sat_pct": round(float(sat[m].mean() * 100), 1),
        "coverage": round(float(m.mean()), 3),
    }


def measure(path: str | Path, box: Box | None = None, smin: float = 0.07) -> dict[str, float] | None:
    return measure_array(crop(load_rgb(path), box), smin=smin)


def check(path: str | Path, targets: dict[str, Any], box: Box | None,
          region_source: str = "regions.json") -> dict[str, Any]:
    """Absolute check against a creator pack's measured skin numbers.

    targets = {"lum", "r_minus_b", "sat_pct", "tol": {"lum", "r_minus_b", "sat_pct"}}
    """
    if not box:
        return result(False, {"region_source": "none"},
                      "Record the face box for this frame (foundry region) before the skin check can run.")
    m = measure(path, box)
    if m is None:
        return result(False, {"region_source": region_source, "box": list(box)},
                      "No skin pixels inside the face box: the face is covered, out of frame, or the box is wrong.")
    tol = targets.get("tol", {})
    deltas = {k: round(m[k] - float(targets[k]), 1) for k in ("lum", "r_minus_b", "sat_pct") if k in targets}
    fails = [k for k, d in deltas.items() if abs(d) > float(tol.get(k, 0))]
    guidance = []
    if "r_minus_b" in fails and deltas["r_minus_b"] > 0:
        guidance.append("her skin has drifted warm; restate the cool, neutral, desaturated skin spec and keep warm light in the background only")
    if "r_minus_b" in fails and deltas["r_minus_b"] < 0:
        guidance.append("her skin reads too blue; use neutral-white key light")
    if "sat_pct" in fails and deltas["sat_pct"] > 0:
        guidance.append("skin is oversaturated; ask for natural, desaturated skin with real texture")
    if "lum" in fails:
        guidance.append("skin is rendered too " + ("light" if deltas["lum"] > 0 else "dark") + " against her pack; match the master's tone")
    return result(not fails, {**m, "deltas": deltas, "failed": fails,
                              "region_source": region_source, "box": list(box)},
                  ("Skin QC: " + "; ".join(guidance) + ".") if guidance else "")
