"""Duration against the spec, measured with ffprobe."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from . import result


def probe(path: str | Path) -> dict[str, Any]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True, check=True).stdout
    data = json.loads(out)
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    return {
        "duration": round(float(data["format"]["duration"]), 2),
        "width": video.get("width"), "height": video.get("height"),
        "has_audio": any(s.get("codec_type") == "audio" for s in data.get("streams", [])),
    }


def check(path: str | Path, expected: float | None = None, tol: float = 0.3,
          max_s: float | None = None, min_s: float | None = None) -> dict[str, Any]:
    p = probe(path)
    d = p["duration"]
    fails = []
    if expected is not None and abs(d - expected) > tol:
        fails.append(f"duration {d}s is not {expected}s ±{tol}")
    if max_s is not None and d > max_s + tol:
        fails.append(f"duration {d}s exceeds {max_s}s")
    if min_s is not None and d < min_s - tol:
        fails.append(f"duration {d}s is under {min_s}s")
    return result(not fails, {**p, "expected": expected, "max": max_s, "min": min_s, "failed": fails},
                  "Duration: " + "; ".join(fails) + ".")
