"""The build loop's moving parts: QC runs, the retry budget, regeneration, clip ingest.

The loop itself is driven by an agent (SPEC.md D6): it calls these commands in order,
reads the JSON they print, and acts on `guidance`. All policy lives here, so an agent
cannot go green by skipping a check, reusing a stale result, or retrying past the budget.

    stage     inputs                                    checks
    frames    frames/approved.png                        skin (recorded face box), hands verdict
    clip      clips/shotNN.mp4 + sampled frames           frame0, drift, skin, duration, hands verdict
    cut       cut/final.mp4 + cut/caption.json            duration, size, caption_band, loudness, text_lint

Invariants:
- Thresholds and the retry budget come from approved.lock.json, never from spec.json.
- Replacing an input deletes every QC result downstream of it.
- A regeneration is refused unless the stage's last QC is red and budget remains.
"""
from __future__ import annotations

import shutil
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Sequence

from engine.providers import get_image_provider
from engine.providers.openai_images import ImageRefused
from engine.qc import caption_band, drift, duration, frame0, hands, loudness, safety_lint, skin, text_lint

from . import cast, media
from .imaging import capture_treatment, save_png
from .piece import APPROVED, STAGES, Piece
from .spec import first_frame_prompt
from .util import SHOT_RE, FoundryError, check_name, inside, now, read_json, write_json
from .workspace import Workspace

MAX_DOWNLOAD = 500 * 1024 * 1024


# ---------------------------------------------------------------- recorded observations
def regions(piece: Piece) -> dict[str, Any]:
    return read_json(piece.rel("qc", "regions.json"), {})


def record_region(piece: Piece, image: str, face: Sequence[float]) -> dict[str, Any]:
    p = inside(piece.path, image, "image")
    if not p.exists():
        raise FoundryError(f"no image {image} in {piece.ref}")
    x0, y0, x1, y1 = (float(v) for v in face)
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        raise FoundryError("face box must be x0,y0,x1,y1 fractions with x0<x1 and y0<y1")
    key = str(p.relative_to(piece.path))
    r = regions(piece)
    r[key] = {"face": [x0, y0, x1, y1], "at": now()}
    write_json(piece.rel("qc", "regions.json"), r)
    return r[key]


def face_box(piece: Piece, image: str) -> tuple[list[float] | None, str]:
    """Recorded box for this image; clip and cut checks may fall back to the approved frame's box
    (the provider stretches the start frame to the clip size, so fractions carry over)."""
    r = regions(piece)
    if image in r:
        return r[image]["face"], "regions.json"
    if image != APPROVED and APPROVED in r:
        return r[APPROVED]["face"], "regions.json (approved frame)"
    return None, "none"


def record_verdict(piece: Piece, check: str, stage: str, ok: bool, note: str = "") -> dict[str, Any]:
    if check != "hands":
        raise FoundryError("only the hands check takes a recorded verdict")
    if stage not in ("frames", "clip"):
        raise FoundryError("hands verdicts are recorded for frames or clip")
    v = read_json(piece.rel("qc", "verdicts.json"), {})
    v.setdefault(check, {})[stage] = {"pass": ok, "note": note, "at": now()}
    write_json(piece.rel("qc", "verdicts.json"), v)
    return v[check][stage]


def invalidate(piece: Piece, stages: Sequence[str], images: Sequence[str] = ()) -> None:
    """A new input makes every downstream result stale: QC reports, observations, the cut."""
    for s in stages:
        piece.rel("qc", f"{s}.json").unlink(missing_ok=True)
    r = regions(piece)
    for im in images:
        r.pop(im, None)
    write_json(piece.rel("qc", "regions.json"), r)
    v = read_json(piece.rel("qc", "verdicts.json"), {})
    for s in stages:
        (v.get("hands") or {}).pop(s, None)
    write_json(piece.rel("qc", "verdicts.json"), v)
    if "cut" in stages and piece.rel("cut").exists():
        shutil.rmtree(piece.rel("cut"))


# ---------------------------------------------------------------- QC
def run_qc(ws: Workspace, piece: Piece, stage: str) -> dict[str, Any]:
    if stage not in STAGES:
        raise FoundryError(f"stage must be one of {', '.join(STAGES)}")
    piece.require("approved", "building", "green")
    lock = piece.lock
    if piece.state == "approved":
        piece.set_state("building")
    spec = piece.spec
    q = lock["qc_targets"]
    verdicts = piece.rel("qc", "verdicts.json")
    checks: dict[str, Any] = {}

    if stage == "frames":
        box, src = face_box(piece, APPROVED)
        checks["skin"] = skin.check(piece.rel(APPROVED), q["skin"], box, src)
        checks["hands"] = hands.check(verdicts, "frames")

    elif stage == "clip":
        piece.require_pass("frames")
        multi = len(spec["shots"]) > 1
        for sh in spec["shots"]:
            key = (lambda name, sid=sh["id"]: f"{sid}.{name}") if multi else (lambda name: name)
            clip = piece.rel("clips", f"{sh['id']}.mp4")
            if not clip.exists():
                raise FoundryError(f"no clip {clip.name}; generate it and run foundry fetch or ingest-clip")
            frames = sorted(piece.rel("clips", sh["id"], "frames").glob("f_*.png"))
            first = f"clips/{sh['id']}/frames/f_0001.png"
            checks[key("frame0")] = frame0.check(piece.rel(APPROVED), piece.rel(first), q["frame0_max_diff"])
            checks[key("drift")] = drift.check(frames, q["drift_max_lum"], q.get("drift_max_rb", 12))
            box, src = face_box(piece, first)
            checks[key("skin")] = skin.check(piece.rel(first), q["skin"], box, src)
            checks[key("duration")] = duration.check(clip, expected=sh["duration_s"], tol=0.5)
        checks["hands"] = hands.check(verdicts, "clip")

    else:
        piece.require_pass("clip")
        final = piece.rel("cut", "final.mp4")
        if not final.exists():
            raise FoundryError("no cut/final.mp4; run foundry cut first")
        lo, hi = q.get("cut_duration_s", [0, ws.defaults["max_duration_s"]])
        checks["duration"] = duration.check(final, min_s=lo, max_s=min(hi, ws.defaults["max_duration_s"]))
        p = checks["duration"]["measures"]
        size_ok = (p["width"], p["height"]) == media.OUTPUT_SIZE
        checks["size"] = {"pass": size_ok, "measures": {"width": p["width"], "height": p["height"]},
                          "guidance": "" if size_ok else f"Render the cut at {media.OUTPUT_SIZE[0]}x{media.OUTPUT_SIZE[1]}."}
        cap = read_json(piece.rel("cut", "caption.json"))
        box, _ = face_box(piece, f"clips/{spec['shots'][0]['id']}/frames/f_0001.png")
        cs = q.get("caption_safe", {})
        checks["caption_band"] = caption_band.check(cap["box"], box, cs.get("top_pct", 11), cs.get("bottom_pct", 71))
        checks["loudness"] = loudness.check(final, spec["audio"]["kind"])
        charter = read_json(ws.dir("accounts") / spec["account"] / "charter.json")
        checks["text_lint"] = text_lint.lint(spec["captions"]["text"], charter)

    failed = [k for k, v in checks.items() if not v["pass"]]
    st = piece.status
    budget = int(lock["fix_cycles"])
    report = {"stage": stage, "pass": not failed, "failed": failed, "checks": checks,
              "guidance": " ".join(checks[k]["guidance"] for k in failed if checks[k]["guidance"]),
              "cycle": st["cycles"][stage], "fix_cycles": budget, "at": now()}
    write_json(piece.rel("qc", f"{stage}.json"), report)

    if failed:
        if st["cycles"][stage] >= budget:
            raise piece.block(f"{stage}.{failed[0]}",
                              f"{stage} QC still red after {st['cycles'][stage]} regeneration(s): {report['guidance']}")
        report["next"] = f"regenerate {stage} with the guidance ({st['cycles'][stage]} of {budget} regenerations used)"
    elif stage == "cut" and all((read_json(piece.rel("qc", f"{s}.json")) or {}).get("pass") for s in STAGES):
        piece.set_state("green", green_at=now())
        report["next"] = "green: hand off to the human for foundry ship"
    return report


def begin_regeneration(piece: Piece, stage: str) -> dict[str, Any]:
    """Refuse unless the stage's last QC is red; block if the budget is spent. Returns that red report."""
    r = read_json(piece.rel("qc", f"{stage}.json"))
    if not r:
        raise FoundryError(f"run foundry qc --stage {stage} before regenerating")
    if r["pass"]:
        raise FoundryError(f"{stage} QC is green; nothing to regenerate")
    budget = int(piece.lock["fix_cycles"])
    used = piece.status["cycles"][stage]
    if used >= budget:
        raise piece.block(f"{stage}.{r['failed'][0]}", f"retry budget spent ({used} of {budget}): {r['guidance']}")
    return r


# ---------------------------------------------------------------- regeneration
def regen_frame(ws: Workspace, piece: Piece, provider=None) -> dict[str, Any]:
    piece.require("building")
    r = begin_regeneration(piece, "frames")
    spec = piece.spec
    pdir = cast.pdir(ws, spec["creator"])
    prompt = safety_lint.lint(first_frame_prompt(ws, spec, guidance=r["guidance"]))["rewritten"]
    eid = piece.reserve("image_call", 1.0, "frames regeneration")
    provider = provider or get_image_provider(ws.image)
    try:
        data = provider.edit(prompt, [pdir / "master.png", pdir / "sheet.png"], n=1, size="1024x1536")[0]
    except ImageRefused as e:
        piece.settle(eid, ok=False)
        raise piece.block("frames.safety_refused", str(e))
    except Exception:
        piece.settle(eid, ok=False)
        raise
    piece.settle(eid, ok=True)
    cycle = piece.bump_cycle("frames")
    hist = piece.rel("frames", "history")
    hist.mkdir(exist_ok=True)
    shutil.copyfile(piece.rel(APPROVED), hist / f"approved-{cycle - 1}.png")
    (hist / f"prompt-{cycle}.txt").write_text(prompt)
    raw = save_png(data, hist / f"raw-{cycle}.png")
    capture_treatment(raw, piece.rel(APPROVED), seed=100 + cycle)
    invalidate(piece, ["frames", "clip", "cut"], [APPROVED])
    return {"piece": piece.ref, "stage": "frames", "cycle": cycle, "image": APPROVED,
            "next": "record the face box and hands verdict for the new frame, then foundry qc --stage frames"}


def ingest_clip(ws: Workspace, piece: Piece, mp4: Path, job: str, shot: str = "shot01") -> dict[str, Any]:
    piece.require("building")
    piece.require_pass("frames")
    check_name(shot, SHOT_RE, "shot id")
    spec = piece.spec
    if shot not in {s["id"] for s in spec["shots"]}:
        raise FoundryError(f"unknown shot {shot}")
    src = Path(mp4).resolve()
    if not src.exists():
        raise FoundryError(f"no file {mp4}")
    if piece.rel("clips").resolve() in src.parents:
        raise FoundryError("download the clip outside clips/ (use foundry fetch); clips/ is managed by ingest")
    info = duration.probe(src)
    if not info.get("width"):
        raise FoundryError(f"{mp4} has no video stream")
    dst = piece.rel("clips", f"{shot}.mp4")
    regeneration = dst.exists()
    if regeneration:
        begin_regeneration(piece, "clip")
    piece.consume("video_credits", job)
    cycle = piece.bump_cycle("clip") if regeneration else piece.status["cycles"]["clip"]
    if regeneration:
        hist = piece.rel("clips", "history")
        hist.mkdir(parents=True, exist_ok=True)
        shutil.move(str(dst), hist / f"{shot}-{cycle - 1}.mp4")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    frames = media.sample_frames(dst, piece.rel("clips", shot, "frames"), every=10)
    invalidate(piece, ["clip", "cut"], [f"clips/{shot}/frames/f_0001.png"])
    write_json(piece.rel("clips", f"{shot}.json"), {"source": str(src), "job": job, "cycle": cycle, "at": now(),
                                                   "frames": [f.name for f in frames], "probe": info})
    return {"piece": piece.ref, "shot": shot, "cycle": cycle, "frames": len(frames),
            "next": "look at the sampled frames, record the hands verdict, then foundry qc --stage clip"}


# ---------------------------------------------------------------- provider transfer (no raw curl for the agent)
def _https(url: str) -> str:
    u = urllib.parse.urlparse(url)
    if u.scheme != "https" or not u.hostname:
        raise FoundryError("only https URLs are accepted")
    return url


def upload_approved(piece: Piece, url: str) -> dict[str, Any]:
    """PUT frames/approved.png to a presigned upload URL. Nothing else in the workspace can be sent."""
    piece.require("building")
    piece.require_pass("frames")
    data = piece.rel(APPROVED).read_bytes()
    req = urllib.request.Request(_https(url), data=data, method="PUT", headers={"Content-Type": "image/png"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return {"piece": piece.ref, "uploaded": APPROVED, "bytes": len(data), "http": r.status}


def fetch_clip(ws: Workspace, piece: Piece, url: str, job: str, shot: str = "shot01") -> dict[str, Any]:
    piece.require("building")
    check_name(shot, SHOT_RE, "shot id")
    incoming = piece.rel("incoming")
    incoming.mkdir(exist_ok=True)
    safe_job = "".join(ch for ch in job if ch.isalnum() or ch in "-_")[:64] or "job"
    dst = incoming / f"{shot}-{safe_job}.mp4"
    with urllib.request.urlopen(urllib.request.Request(_https(url)), timeout=300) as r, open(dst, "wb") as f:
        total = 0
        while chunk := r.read(1 << 20):
            total += len(chunk)
            if total > MAX_DOWNLOAD:
                raise FoundryError("download exceeds 500 MB")
            f.write(chunk)
    return ingest_clip(ws, piece, dst, job=job, shot=shot)
