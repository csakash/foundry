"""Find a creator's face inside another image by matching the master's own face.

Colour cannot tell dark hair from skin, and generated character sheets do not put the
face in the same place in every panel (Michelle's heads are centred and surrounded by
long dark hair; Imani's sit low in each panel). So the face is located by normalised
cross-correlation against the master's face crop, over a range of sizes, on small
greyscale copies. It needs no model and no extra dependency.

A match is only trusted when its score clears MATCH_MIN: profile views and misframed
panels score low and are left out rather than measured in the wrong place.
Calibrated 2026-09-16: Michelle's front, three-quarter, up and down panels scored
0.70-0.98 and landed on the face; Imani's front and three-quarter scored 0.88-0.94;
every wrong placement scored at most 0.58.
"""
from __future__ import annotations

from typing import Sequence

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from PIL import Image

MATCH_MIN = 0.68
MIN_WINDOW_STD = 4.0  # grey levels
WORK_WIDTH = 72
SIZE_FRACTIONS = np.linspace(0.25, 0.85, 13)  # face width as a share of the searched image's width


def _gray(img: Image.Image, width: int) -> np.ndarray:
    im = img.convert("L")
    h = max(1, round(im.height * width / im.width))
    return np.asarray(im.resize((width, h), Image.BILINEAR), np.float32)


def _window_stats(P: np.ndarray, th: int, tw: int) -> tuple[np.ndarray, np.ndarray]:
    """Mean and std of every th x tw window, from integral images (O(pixels), not O(pixels x window))."""
    def integral(a):
        return np.pad(np.cumsum(np.cumsum(a, 0, dtype=np.float64), 1), ((1, 0), (1, 0)))
    n = th * tw
    I, I2 = integral(P), integral(P.astype(np.float64) ** 2)
    s = I[th:, tw:] - I[:-th, tw:] - I[th:, :-tw] + I[:-th, :-tw]
    s2 = I2[th:, tw:] - I2[:-th, tw:] - I2[th:, :-tw] + I2[:-th, :-tw]
    mean = s / n
    return mean, np.sqrt(np.maximum(s2 / n - mean ** 2, 0.0))


def locate(image: Image.Image, master: Image.Image, face: Sequence[float]) -> dict:
    """Best match of master's face box inside image: {"score", "box", "confident"} with box as fractions of image."""
    P = _gray(image, WORK_WIDTH)
    mw, mh = master.size
    crop = master.crop((int(face[0] * mw), int(face[1] * mh), int(face[2] * mw), int(face[3] * mh))).convert("L")
    aspect = crop.height / max(1, crop.width)
    best = {"score": -1.0, "box": None}
    for frac in SIZE_FRACTIONS:
        tw = max(8, int(round(frac * WORK_WIDTH)))
        th = max(8, int(round(tw * aspect)))
        if th >= P.shape[0] or tw >= P.shape[1]:
            continue
        T = np.asarray(crop.resize((tw, th), Image.BILINEAR), np.float32)
        T = (T - T.mean()) / (T.std() + 1e-6)
        # T has zero mean, so sum((W - mean_W) * T) == sum(W * T): one tensor product over all windows
        corr = np.tensordot(sliding_window_view(P, (th, tw)), T, axes=([2, 3], [0, 1]))
        _, std = _window_stats(P, th, tw)
        flat = std < MIN_WINDOW_STD  # a window with no contrast cannot hold a face; never divide noise by ~0
        ncc = np.where(flat, -1.0, corr / (th * tw * np.maximum(std, MIN_WINDOW_STD)))
        y, x = np.unravel_index(int(np.argmax(ncc)), ncc.shape)
        if ncc[y, x] > best["score"]:
            best = {"score": round(float(ncc[y, x]), 3),
                    "box": [round(x / P.shape[1], 4), round(y / P.shape[0], 4),
                            round((x + tw) / P.shape[1], 4), round((y + th) / P.shape[0], 4)]}
    best["confident"] = best["score"] >= MATCH_MIN
    return best
