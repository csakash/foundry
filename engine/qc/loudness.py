"""Integrated loudness via ffmpeg ebur128.

silent: no audio stream, or integrated <= -69 LUFS (ebur128 floors digital silence
at -70). Anything else: -14 LUFS ± 2.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from . import result
from .duration import probe


def integrated(path: str | Path) -> float | None:
    if not probe(path)["has_audio"]:
        return None
    err = subprocess.run(["ffmpeg", "-nostats", "-hide_banner", "-i", str(path), "-map", "0:a:0",
                          "-af", "ebur128", "-f", "null", "-"], capture_output=True, text=True).stderr
    found = re.findall(r"I:\s+(-?[\d.]+|-inf)\s+LUFS", err)
    if not found:
        return None
    v = found[-1]
    return float("-inf") if v == "-inf" else float(v)


def check(path: str | Path, kind: str, target: float = -14.0, tol: float = 2.0) -> dict[str, Any]:
    i = integrated(path)
    if kind == "silent":
        ok = i is None or i <= -69.0
        return result(ok, {"integrated_lufs": i, "kind": kind},
                      f"The spec says silent but the cut has audio at {i} LUFS; strip or mute the audio.")
    ok = i is not None and abs(i - target) <= tol
    return result(ok, {"integrated_lufs": i, "kind": kind, "target": target, "tol": tol},
                  f"Loudness {i} LUFS is outside {target}±{tol}; normalise the mix.")
