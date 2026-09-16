"""Assemble cut/final.mp4: persona shot(s) with the caption burned in, hard-cut to the product clip."""
from __future__ import annotations

import shutil
from typing import Any

from . import media
from .caption import render as render_caption
from .loop import _require_pass
from .piece import Piece
from .util import FoundryError, now, read_json, write_json
from .workspace import Workspace


def build(ws: Workspace, piece: Piece) -> dict[str, Any]:
    piece.require("building", "green")
    _require_pass(piece, "frames")
    _require_pass(piece, "clip")
    spec = piece.spec
    cd = piece.rel("cut")
    prev = read_json(piece.rel("qc", "cut.json"))
    cycle = piece.status["cycles"]["cut"]
    if (cd / "final.mp4").exists() and prev and not prev["pass"]:
        cycle = piece.bump_cycle("cut")
    if cd.exists():
        shutil.rmtree(cd)
    (cd / "parts").mkdir(parents=True)

    kind = spec["audio"]["kind"]
    cap = render_caption(spec["captions"], cd / "caption.png")
    parts = []
    for i, sh in enumerate(spec["shots"]):
        raw = media.normalise(piece.rel("clips", f"{sh['id']}.mp4"), cd / "parts" / f"{i:02d}-{sh['id']}-raw.mp4",
                              0.0, float(sh["duration_s"]))
        if spec["captions"].get("during") in (sh["id"], "all"):
            parts.append(media.burn_overlay(raw, cd / "caption.png", cd / "parts" / f"{i:02d}-{sh['id']}.mp4"))
        else:
            parts.append(raw)
    for j, a in enumerate(spec["assets"]):
        src = ws.root / a["path"]
        if not src.exists():
            raise FoundryError(f"product clip {a['path']} is missing")
        keep = kind == "clip" and media.has_audio(src)
        t0, t1 = float(a["trim_s"][0]), float(a["trim_s"][1])
        parts.append(media.normalise(src, cd / "parts" / f"{len(parts):02d}-asset{j}.mp4", t0, t1 - t0, keep_audio=keep))
    final = media.concat(parts, cd / "final.mp4")
    if kind == "trending":
        track = spec["audio"].get("path")
        if not track or not (ws.root / track).exists():
            raise FoundryError("audio.kind is trending but audio.path is missing")
        tmp = cd / "final-music.mp4"
        media.run(["ffmpeg", "-y", "-v", "error", "-i", str(final), "-i", str(ws.root / track), "-map", "0:v",
                   "-map", "1:a", "-c:v", "copy", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-c:a", "aac", "-shortest", str(tmp)])
        tmp.replace(final)
    manifest = {"parts": [p.name for p in parts], "caption": cap, "audio": kind, "cycle": cycle, "at": now()}
    write_json(cd / "cut.json", manifest)
    return {"piece": piece.ref, "final": str(final), "cycle": cycle, "font_used": cap["font_used"],
            "font_substituted": cap["font_substituted"], "next": "foundry qc --stage cut"}
