"""Frame-0 conformance: does the clip start on the frame the human approved?

Mean absolute pixel difference (0..255, averaged over RGB) between the clip's first
frame and approved.png resized to the clip's size. Higgsfield seedance_2_5 with a
start image landed at 20.3 on the Imani clip (720x1280), so the default gate is 30.

The approved frame (2:3) is stretched to the clip's size rather than cover-cropped:
on the Imani clip stretch measured 20.3, cover-crop 21.7 and letterbox 26.7, so the
provider fills the frame. Face-box fractions therefore carry over unchanged.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from . import result


def diff(approved: str | Path, frame1: str | Path) -> float:
    f = Image.open(frame1).convert("RGB")
    a = Image.open(approved).convert("RGB").resize(f.size, Image.BILINEAR)
    return round(float(np.abs(np.asarray(a, np.float32) - np.asarray(f, np.float32)).mean()), 1)


def check(approved: str | Path, frame1: str | Path, max_diff: float) -> dict[str, Any]:
    d = diff(approved, frame1)
    return result(d <= max_diff, {"diff": d, "max": max_diff},
                  "The clip does not start on the approved frame; pass approved.png as the start image, "
                  "not as a loose reference, and keep the framing and pose identical at 0 s.")
