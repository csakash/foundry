"""The build loop's moving parts: QC runs, the retry budget, regeneration, clip ingest.

The loop itself is driven by an agent (SPEC.md D6): it calls these commands in order,
reads the JSON they print, and acts on `guidance`. All policy lives here, so an agent
cannot go green by skipping a check or retry past the budget.

    stage     inputs                                    checks
    frames    frames/approved.png                        skin (face box), hands verdict
    clip      clips/shotNN.mp4 + sampled frames           frame0, drift, skin, duration, hands verdict
    cut       cut/final.mp4 + cut/caption.json            duration, size, caption_band, loudness, text_lint
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Sequence

from engine.providers import get_image_provider
from engine.providers.openai_images import ImageRefused
from engine.qc import caption_band, drift, duration, frame0, hands, loudness, safety_lint, skin, text_lint

from . import cast, hook_reel, media
from .imaging import capture_treatment, save_png
from .piece import STAGES, Piece
from .spec import first_frame_prompt
from .util import FoundryError, now, read_json, write_json
from .workspace import Workspace

APPROVED = "frames/approved.png"


# ---------------------------------------------------------------- recorded observations
def regions(piece: Piece) -> dict[str, Any]:
    return read_json(piece.rel("qc", "regions.json"), {})


def record_region(piece: Piece, image: str, face: Sequence[float]) -> dict[str, Any]:
    if not piece.rel(image).exists():
        raise FoundryError(f"no image {image} in {piece.ref}")
    x0, y0, x1, y1 = (float(v) for v in face)
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        raise FoundryError("face box must be x0,y0,x1,y1 fractions with x0<x1 and y0<y1")
    r = regions(piece)
    r[image] = {"face": [x0, y0, x1, y1], "at": now()}
    write_json(piece.rel("qc", "regions.json"), r)
    return r[image]


def face_box(piece: Piece, image: str, spec: dict[str, Any]) -> tuple[list[float], str]:
    r = regions(piece).get(image)
    if r:
        return r["face"], "regions.json"
    if image != APPROVED and regions(piece).get(APPROVED):
        return regions(piece)[APPROVED]["face"], "regions.json (approved frame)"
    return hook_reel.scene(spec["shots"][0]["scene"])["face_region_hint"], "scene_hint"


def record_verdict(piece: Piece, check: str, stage: str, ok: bool, note: str = "") -> dict[str, Any]:
    if check != "hands":
        raise FoundryError("only the hands check takes a recorded verdict")
    if stage not in ("frames", "clip"):
        raise FoundryError("hands verdicts are recorded for frames or clip")
    v = read_json(piece.rel("qc", "verdicts.json"), {})
    v.setdefault(check, {})[stage] = {"pass": ok, "note": note, "at": now()}
    write_json(piece.rel("qc", "verdicts.json"), v)
    return v[check][stage]


def _clear_observations(piece: Piece, stage: str, images: list[str]) -> None:
    r = regions(piece)
    for im in images:
        r.pop(im, None)
    write_json(piece.rel("qc", "regions.json"), r)
    v = read_json(piece.rel("qc", "verdicts.json"), {})
    (v.get("hands") or {}).pop(stage, None)
    write_json(piece.rel("qc", "verdicts.json"), v)


# ---------------------------------------------------------------- QC
def fix_cycles(ws: Workspace, piece: Piece) -> int:
    return int(piece.status.get("fix_cycles", ws.defaults["fix_cycles"]))


def run_qc(ws: Workspace, piece: Piece, stage: str) -> dict[str, Any]:
    if stage not in STAGES:
        raise FoundryError(f"stage must be one of {', '.join(STAGES)}")
    piece.require("approved", "building", "green")
    if piece.state == "approved":
        piece.set_state("building")
    spec = piece.spec
    q = spec["qc_targets"]
    verdicts = piece.rel("qc", "verdicts.json")
    checks: dict[str, Any] = {}

    if stage == "frames":
        box, src = face_box(piece, APPROVED, spec)
        checks["skin"] = skin.check(piece.rel(APPROVED), q["skin"], box, src)
        if src == "scene_hint":
            checks["skin"]["measures"]["note"] = "face box from the scene hint; record the real box with foundry region"
        checks["hands"] = hands.check(verdicts, "frames")

    elif stage == "clip":
        _require_pass(piece, "frames")
        for i, sh in enumerate(spec["shots"]):
            clip = piece.rel("clips", f"{sh['id']}.mp4")
            if not clip.exists():
                raise FoundryError(f"no clip {clip.name}; generate it and run foundry ingest-clip")
            frames = sorted(piece.rel("clips", sh["id"], "frames").glob("f_*.png"))
            first = f"clips/{sh['id']}/frames/f_0001.png"
            key = lambda name: f"{sh['id']}.{name}" if len(spec["shots"]) > 1 else name
            checks[key("frame0")] = frame0.check(piece.rel(APPROVED), piece.rel(first), q["frame0_max_diff"])
            checks[key("drift")] = drift.check(frames, q["drift_max_lum"], q.get("drift_max_rb", 12))
            box, src = face_box(piece, first, spec)
            checks[key("skin")] = skin.check(piece.rel(first), q["skin"], box, src)
            checks[key("duration")] = duration.check(clip, expected=sh["duration_s"], tol=0.5)
        checks["hands"] = hands.check(verdicts, "clip")

    else:
        _require_pass(piece, "clip")
        final = piece.rel("cut", "final.mp4")
        if not final.exists():
            raise FoundryError("no cut/final.mp4; run foundry cut first")
        lo, hi = q.get("cut_duration_s", [0, ws.defaults["max_duration_s"]])
        checks["duration"] = duration.check(final, min_s=lo, max_s=min(hi, ws.defaults["max_duration_s"]))
        p = checks["duration"]["measures"]
        size_ok = (p["width"], p["height"]) == (1080, 1920)
        checks["size"] = {"pass": size_ok, "measures": {"width": p["width"], "height": p["height"]},
                          "guidance": "" if size_ok else "Render the cut at 1080x1920."}
        cap = read_json(piece.rel("cut", "caption.json"))
        box, _ = face_box(piece, f"clips/{spec['shots'][0]['id']}/frames/f_0001.png", spec)
        cs = q.get("caption_safe", {})
        checks["caption_band"] = caption_band.check(cap["box"], box, cs.get("top_pct", 11), cs.get("bottom_pct", 71))
        checks["loudness"] = loudness.check(final, spec["audio"]["kind"])
        charter = read_json(ws.dir("accounts") / spec["account"] / "charter.json")
        checks["text_lint"] = text_lint.lint(spec["captions"]["text"], charter)

    failed = [k for k, v in checks.items() if not v["pass"]]
    st = piece.status
    report = {"stage": stage, "pass": not failed, "failed": failed, "checks": checks,
              "guidance": " ".join(checks[k]["guidance"] for k in failed if checks[k]["guidance"]),
              "cycle": st["cycles"][stage], "fix_cycles": fix_cycles(ws, piece), "at": now()}
    write_json(piece.rel("qc", f"{stage}.json"), report)

    if failed:
        if st["cycles"][stage] >= fix_cycles(ws, piece):
            raise piece.block(f"{stage}.{failed[0]}",
                              f"{stage} QC still red after {st['cycles'][stage]} regeneration(s): {report['guidance']}")
        report["next"] = f"regenerate {stage} with the guidance ({st['cycles'][stage]} of {fix_cycles(ws, piece)} regenerations used)"
    elif stage == "cut" and all((read_json(piece.rel("qc", f"{s}.json")) or {}).get("pass") for s in STAGES):
        piece.set_state("green", green_at=now())
        report["next"] = "green: run foundry ship"
    return report


def _require_pass(piece: Piece, stage: str) -> None:
    r = read_json(piece.rel("qc", f"{stage}.json"))
    if not r or not r["pass"]:
        raise FoundryError(f"{stage} QC is not green yet; run foundry qc --stage {stage} first")


# ---------------------------------------------------------------- regeneration
def _last_failed(piece: Piece, stage: str) -> dict[str, Any]:
    r = read_json(piece.rel("qc", f"{stage}.json"))
    if not r:
        raise FoundryError(f"run foundry qc --stage {stage} before regenerating")
    if r["pass"]:
        raise FoundryError(f"{stage} QC is green; nothing to regenerate")
    return r


def regen_frame(ws: Workspace, piece: Piece, provider=None) -> dict[str, Any]:
    piece.require("building")
    r = _last_failed(piece, "frames")
    spec = piece.spec
    cycle = piece.bump_cycle("frames")
    hist = piece.rel("frames", "history")
    hist.mkdir(exist_ok=True)
    shutil.copyfile(piece.rel(APPROVED), hist / f"approved-{cycle - 1}.png")
    pdir = cast.pdir(ws, spec["creator"])
    prompt = safety_lint.lint(first_frame_prompt(ws, spec, guidance=r["guidance"]))["rewritten"]
    (hist / f"prompt-{cycle}.txt").write_text(prompt)
    eid = piece.reserve("image_call", 1.0, f"frames regeneration {cycle}")
    provider = provider or get_image_provider(ws.image)
    try:
        data = provider.edit(prompt, [pdir / "master.png", pdir / "sheet.png"], n=1, size="1024x1536")[0]
    except ImageRefused as e:
        piece.settle(eid, ok=False)
        raise piece.block("frames.safety_refused", str(e))
    piece.settle(eid, ok=True)
    raw = save_png(data, hist / f"raw-{cycle}.png")
    capture_treatment(raw, piece.rel(APPROVED), seed=100 + cycle)
    _clear_observations(piece, "frames", [APPROVED])
    (piece.rel("qc", "clip.json")).unlink(missing_ok=True)  # a new start frame invalidates any clip
    return {"piece": piece.ref, "stage": "frames", "cycle": cycle, "image": APPROVED,
            "next": "record the face box and hands verdict for the new frame, then foundry qc --stage frames"}


def ingest_clip(ws: Workspace, piece: Piece, mp4: Path, shot: str = "shot01", job: str | None = None) -> dict[str, Any]:
    piece.require("building")
    _require_pass(piece, "frames")
    spec = piece.spec
    if shot not in {s["id"] for s in spec["shots"]}:
        raise FoundryError(f"unknown shot {shot}")
    if not Path(mp4).exists():
        raise FoundryError(f"no file {mp4}")
    dst = piece.rel("clips", f"{shot}.mp4")
    cycle = piece.status["cycles"]["clip"]
    if dst.exists():
        cycle = piece.bump_cycle("clip")
        hist = piece.rel("clips", "history")
        hist.mkdir(parents=True, exist_ok=True)
        shutil.move(str(dst), hist / f"{shot}-{cycle - 1}.mp4")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(mp4, dst)
    frames = media.sample_frames(dst, piece.rel("clips", shot, "frames"), every=10)
    _clear_observations(piece, "clip", [f"clips/{shot}/frames/f_0001.png"])
    write_json(piece.rel("clips", f"{shot}.json"), {"source": str(mp4), "job": job, "cycle": cycle, "at": now(),
                                                   "frames": [f.name for f in frames]})
    return {"piece": piece.ref, "shot": shot, "cycle": cycle, "frames": len(frames),
            "next": "look at the sampled frames, record the hands verdict, then foundry qc --stage clip"}
