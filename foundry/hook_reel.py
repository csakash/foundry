"""The hook_reel format: one persona reaction shot hard-cut into a product clip.

Defaults here are the format's; the resolver layers recipe -> creator pack ->
these defaults -> the account's last shipped piece on top of an empty spec.
"""
from __future__ import annotations

import copy
import math
from typing import Any

from . import REPO
from .util import read_json

FORMAT = "hook_reel"
DEFAULT_SCENE = "reaction-facepalm-reveal"
UNIT_CREDITS = {"image_call": 1, "video_5s": 32.5}


def scene(scene_id: str) -> dict[str, Any]:
    from .util import NAME_RE, check_name
    s = read_json(REPO / "catalog/scenes" / f"{check_name(scene_id, NAME_RE, 'scene id')}.json")
    if not s:
        raise FileNotFoundError(f"no scene catalog/scenes/{scene_id}.json")
    return s


def defaults() -> dict[str, Any]:
    sc = scene(DEFAULT_SCENE)
    return {
        "format": FORMAT,
        "goal": None,
        "hook": {"line": None, "mechanism": None},
        "shots": [{"id": "shot01", "scene": sc["id"], "camera": sc["camera"], "duration_s": sc["duration_s"],
                   "beats": copy.deepcopy(sc["beats"]), "wardrobe": None, "light": sc["light"],
                   "on_screen_text": None}],
        "assets": [{"path": None, "enter_at_s": sc["duration_s"], "trim_s": [0, 20], "reframe": "9:16"}],
        "audio": {"kind": "silent"},
        "captions": {"font": "TikTok Sans Bold", "size_pct_w": 6.6, "band": "top", "band_start_pct_h": 11,
                     "stroke_pct": 12.5, "text": None, "during": "shot01"},
        "qc_targets": {"skin": None, "frame0_max_diff": 30, "drift_max_lum": 12, "drift_max_rb": 12,
                       "caption_safe": {"top_pct": 11, "bottom_pct": 71}, "cut_duration_s": [20, 30]},
    }


def structure(spec: dict[str, Any]) -> list[dict[str, Any]]:
    t, out = 0.0, []
    for sh in spec["shots"]:
        out.append({"t": [t, t + sh["duration_s"]], "beat": f"{sh['id']}: persona reaction"})
        t += sh["duration_s"]
    for a in spec["assets"]:
        dur = a["trim_s"][1] - a["trim_s"][0]
        out.append({"t": [a["enter_at_s"], a["enter_at_s"] + dur], "beat": "product cut"})
    return out


def plan(spec: dict[str, Any], candidates: int) -> dict[str, float]:
    video = sum(math.ceil(sh["duration_s"] / 5) * UNIT_CREDITS["video_5s"] for sh in spec["shots"])
    return {"image_call": float(1 + candidates), "video_credits": float(video)}
