"""Assemble cut/final.mp4: persona shot(s) with the caption burned in, hard-cut to the product clip."""
from __future__ import annotations

from typing import Any

from engine.qc import duration as qc_duration
from engine.qc.loudness import TARGET_LUFS

from . import media
from .caption import render as render_caption
from .loop import invalidate, begin_regeneration
from .piece import Piece
from .util import FoundryError, inside, now, read_json, write_json
from .workspace import Workspace


def build(ws: Workspace, piece: Piece) -> dict[str, Any]:
    piece.require("building")
    piece.require_pass("frames")
    piece.require_pass("clip")
    piece.lock  # refuses if the spec changed after approval
    spec = piece.spec
    cd = piece.rel("cut")
    rebuild = (cd / "cut.json").exists()  # a final.mp4 without its manifest is an interrupted build, not a cut
    if rebuild:
        if read_json(piece.rel("qc", "cut.json")) is None:
            raise FoundryError("a cut exists and has not been checked; run foundry qc --stage cut first")
        begin_regeneration(piece, "cut")
        cycle = piece.bump_cycle("cut")
    else:
        cycle = piece.status["cycles"]["cut"]
    invalidate(piece, ["cut"])
    (cd / "parts").mkdir(parents=True)

    kind = spec["audio"]["kind"]
    cap = render_caption(spec["captions"], cd / "caption.png")
    parts = []
    for i, sh in enumerate(spec["shots"]):
        overlay = cd / "caption.png" if spec["captions"].get("during") in (sh["id"], "all") else None
        parts.append(media.normalise(piece.rel("clips", f"{sh['id']}.mp4"), cd / "parts" / f"{i:02d}-{sh['id']}.mp4",
                                     0.0, float(sh["duration_s"]), overlay=overlay))
    for j, a in enumerate(spec["assets"]):
        src = inside(ws.root, a["path"], "product clip")
        if not src.exists():
            raise FoundryError(f"product clip {a['path']} is missing")
        t0, t1 = float(a["trim_s"][0]), float(a["trim_s"][1])
        keep = kind == "clip" and qc_duration.probe(src)["has_audio"]
        parts.append(media.normalise(src, cd / "parts" / f"{len(parts):02d}-asset{j}.mp4", t0, t1 - t0, keep_audio=keep))
    joined = media.concat(parts, cd / ("joined.mp4" if kind != "silent" else "final.mp4"))
    if kind == "clip":
        media.loudnorm(joined, cd / "final.mp4", TARGET_LUFS)
    elif kind == "trending":
        track = spec["audio"].get("path")
        if not track:
            raise FoundryError("audio.kind is trending but audio.path is missing")
        media.loudnorm(joined, cd / "final.mp4", TARGET_LUFS, audio=inside(ws.root, track, "audio track"))
    if kind != "silent":
        joined.unlink(missing_ok=True)
    write_json(cd / "cut.json", {"parts": [p.name for p in parts], "caption": cap, "audio": kind,
                                 "cycle": cycle, "at": now()})
    return {"piece": piece.ref, "final": str(cd / "final.mp4"), "cycle": cycle, "font_used": cap["font_used"],
            "font_substituted": cap["font_substituted"], "next": "foundry qc --stage cut"}
