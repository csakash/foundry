"""Cast a creator: bootstrap masters, pick one, generate the mandatory sheet, measure, lock a pack.

    foundry cast nova --brief "..."          -> personas/nova/candidates/c1..cN.png + contact.png
    foundry cast nova --pick c2 [--face ..]  -> master.png, sheet.png, measure.json  (touch 1)
                                                fails closed: BLOCKED sheet_drift, no pack
    foundry cast nova --approve              -> pack.json                            (touch 2)
    foundry cast nova --remeasure [--face ..]-> measure.json again on the same images   (no image calls)

No creator can be used in a spec without pack.json, and pack.json only exists when the
sheet's measured skin matched the master's.

How the sheet is measured (v2, after Michelle's false sheet_drift on 2026-09-16):
the master's face is FOUND in each top-row panel (engine.qc.facefind), and skin is read
from the centre of the match, exactly as it is read from the centre of the master's face
box. Panels where the face is not found confidently (profiles, odd framing) are left out.
Hair is never measured as skin, and no assumption is made about where a sheet puts faces.
If fewer than two panels can be matched the result is `sheet_unmeasurable`, not drift: a
human looks at the sheet and may approve it with --visual-check.

Face finding locates *a* face, it does not prove identity: a different person with similar
skin can match. The gate compares skin brightness, warmth and saturation; identity is the
human's call at --pick and --approve.

Guards: a sheet that has ever measured as drift for these exact master and sheet images can
never be approved by eye (re-measuring with a different face box cannot launder it), a
measurement is tied to the image hashes it read, and a locked creator cannot be re-measured
while any piece built on it is approved, building or green.
"""
from __future__ import annotations

import shutil
import statistics
from pathlib import Path
from typing import Any, Sequence

import numpy as np
from PIL import Image

from engine.providers import get_image_provider
from engine.qc import facefind, safety_lint, skin

from . import REPO, media
from .imaging import contact, save_png
from .util import (CANDIDATE_RE, NAME_RE, Blocked, FoundryError, check_face_box, check_name, human_only, now,
                   read_json, sha256_file, write_json)
from .workspace import Workspace

DEFAULT_FACE = (0.33, 0.22, 0.67, 0.55)
SHEET_TOP_ROW = (0.0, 0.02, 1.0, 0.33)
SHEET_PANELS = 7  # the sheet template asks for seven heads across the top row
MIN_MATCHED_PANELS = 2
METHOD = "engine.qc.skin face-centre + facefind v2"
SKIN_TOL = {"lum": 12, "r_minus_b": 16, "sat_pct": 11}  # frame/clip QC tolerances written into every pack
ACTIVE_PIECE_STATES = ("approved", "building", "green")
CAMERA_RULE = ("Every shot needs a nameable camera position the creator set up themselves: selfie, propped, "
               "POV, object/detail, or handed-over. In a selfie one hand is the camera.")


def pdir(ws: Workspace, name: str) -> Path:
    return ws.dir("personas") / check_name(name, NAME_RE, "persona name")


def state(ws: Workspace, name: str) -> dict[str, Any]:
    return read_json(pdir(ws, name) / "cast.json", {"name": name, "state": "new", "touches": 0, "calls": []})


def _save(ws: Workspace, name: str, st: dict[str, Any]) -> None:
    write_json(pdir(ws, name) / "cast.json", st)


def skin_rule(m: dict[str, float]) -> str:
    if m["r_minus_b"] < 15 and m["sat_pct"] < 25:
        return ("Skin is cool, neutral and desaturated. Restate this in every prompt and keep warm light off the "
                "skin: warm light alone pushes the tone brown or bronze.")
    return "Restate the exact skin tone and undertone in every prompt and light the face with neutral white light."


def bootstrap(ws: Workspace, name: str, brief: str, n: int = 3, provider=None) -> dict[str, Any]:
    human_only("cast")
    st = state(ws, name)
    if (pdir(ws, name) / "pack.json").exists():
        raise FoundryError(f"personas/{name} is already locked (pack.json exists)")
    d = pdir(ws, name)
    (d / "prompts").mkdir(parents=True, exist_ok=True)
    prompt = (REPO / "foundry/templates/cast_bootstrap.txt").read_text().format(brief=brief.strip())
    lint = safety_lint.lint(prompt)
    prompt = lint["rewritten"]
    (d / "brief.txt").write_text(brief.strip() + "\n")
    (d / "prompts/bootstrap.txt").write_text(prompt)
    provider = provider or get_image_provider(ws.image, str(ws.root / ".foundry"))
    st["calls"].append({"op": "generate", "n": n, "at": now(), "safety_hits": lint["measures"]["hits"]})
    _save(ws, name, st)
    outs = provider.generate(prompt, n=n, size=media.FRAME_IMAGE_SIZE)
    paths = [save_png(b, d / "candidates" / f"c{i + 1}.png") for i, b in enumerate(outs)]
    contact(paths, d / "candidates/contact.png", [p.stem for p in paths], cols=len(paths),
            title=f"{name}: pick a master (foundry cast {name} --pick cN)")
    st.update(state="candidates", brief=brief.strip(), candidates=[p.stem for p in paths])
    _save(ws, name, st)
    return st


def measure_sheet(sheet_path: Path, master_path: Path, face: Sequence[float]) -> dict[str, Any]:
    """Locate the master's face in each top-row panel and read skin from the centre of each confident match."""
    sheet = Image.open(sheet_path).convert("RGB")
    master = Image.open(master_path).convert("RGB")
    W, H = sheet.size
    y0, y1 = int(SHEET_TOP_ROW[1] * H), int(SHEET_TOP_ROW[3] * H)
    panels = []
    for i in range(SHEET_PANELS):
        x0, x1 = int(i * W / SHEET_PANELS), int((i + 1) * W / SHEET_PANELS)
        panel = sheet.crop((x0, y0, x1, y1))
        match = facefind.locate(panel, master, face)
        m = None
        if match["confident"]:
            m = skin.measure_array(skin.crop(np.asarray(panel, np.float32), skin.skin_box(match["box"])))
        panels.append({"panel": i, "match": match, "skin": m})
    used = [p["skin"] for p in panels if p["skin"]]
    row = None
    if used:
        row = {k: round(statistics.median(u[k] for u in used), 1) for k in ("lum", "r_minus_b", "sat_pct")}
    lums = [u["lum"] for u in used]
    return {"panels": panels, "matched_panels": [p["panel"] for p in panels if p["skin"]],
            "row": row, "panel_spread": round(max(lums) - min(lums), 1) if len(lums) > 1 else 0.0}


def _gate(ws: Workspace, name: str, st: dict[str, Any], face: Sequence[float]) -> dict[str, Any]:
    """Measure master.png against sheet.png as they stand and set the cast state. No image calls."""
    face = check_face_box(face)
    d = pdir(ws, name)
    master_m = skin.measure_face(d / "master.png", face)
    if master_m is None:
        raise FoundryError(f"no measurable skin in the centre of the face box {list(face)}; pass --face x0,y0,x1,y1 "
                           f"(forehead to chin, ear to ear, as fractions of the master)")
    sheet_m = measure_sheet(d / "sheet.png", d / "master.png", face)
    cfg = ws.config["cast"]
    fails, gate = [], "sheet_drift"
    if len(sheet_m["matched_panels"]) < MIN_MATCHED_PANELS:
        gate = "sheet_unmeasurable"
        fails.append(f"the master's face was found confidently in only {len(sheet_m['matched_panels'])} of "
                     f"{SHEET_PANELS} top-row panels, so the sheet cannot be compared by numbers")
    else:
        row = sheet_m["row"]
        delta = round(row["lum"] - master_m["lum"], 1)
        if abs(delta) > cfg["max_sheet_lum_delta"]:
            fails.append(f"sheet skin brightness {row['lum']} vs master {master_m['lum']} "
                         f"(delta {delta:+}, max {cfg['max_sheet_lum_delta']})")
        drb = round(row["r_minus_b"] - master_m["r_minus_b"], 1)
        if abs(drb) > cfg["max_sheet_rb_delta"]:
            fails.append(f"sheet skin warmth R-B {row['r_minus_b']} vs master {master_m['r_minus_b']} "
                         f"(delta {drb:+}, max {cfg['max_sheet_rb_delta']})")
        dsat = round(row["sat_pct"] - master_m["sat_pct"], 1)
        if abs(dsat) > cfg["max_sheet_sat_delta"]:
            fails.append(f"sheet skin saturation {row['sat_pct']}% vs master {master_m['sat_pct']}% "
                         f"(delta {dsat:+}, max {cfg['max_sheet_sat_delta']})")
        if sheet_m["panel_spread"] > cfg["max_panel_spread"]:
            fails.append(f"matched panels disagree by {sheet_m['panel_spread']} > {cfg['max_panel_spread']}")
    images = {"master_sha256": sha256_file(d / "master.png"), "sheet_sha256": sha256_file(d / "sheet.png")}
    write_json(d / "measure.json", {"method": METHOD, "master": master_m, "face_box": list(face),
                                    "skin_box": skin.skin_box(face), "sheet": sheet_m, "failed": fails,
                                    "gate": gate if fails else None, "images": images, "at": now()})
    if gate == "sheet_drift" and fails:  # remembered for these images, whatever face box is used later
        st.setdefault("drift_seen", []).append({**images, "face_box": list(face), "at": now()})
    if fails:  # an existing pack stays: its approved numbers are still what pieces were built against
        st.update(state="blocked", blocked_gate=gate)
        _save(ws, name, st)
        if gate == "sheet_unmeasurable":
            hint = (f" Look at personas/{name}/sheet.png. If it is the same person with the same skin, approve it with "
                    f"`foundry cast {name} --approve --visual-check \"what you checked\"`; otherwise re-run "
                    f"`foundry cast {name} --pick {st.get('master_from')}`.")
        else:
            hint = (f" Check personas/{name}/measure.json. Re-run `foundry cast {name} --pick {st.get('master_from')}` "
                    f"to regenerate the sheet.")
        raise Blocked(gate, "; ".join(fails) + "." + hint)
    st.update(state="sheet_measured", blocked_gate=None)
    _save(ws, name, st)
    return st


def remeasure(ws: Workspace, name: str, face: Sequence[float] | None = None) -> dict[str, Any]:
    """Run the sheet gate again on the existing master.png and sheet.png: no image calls, no new sheet."""
    human_only("cast --remeasure")
    st = state(ws, name)
    if st["state"] not in ("blocked", "sheet_measured", "locked"):
        raise FoundryError(f"personas/{name} is '{st['state']}'; nothing to re-measure")
    d = pdir(ws, name)
    if not (d / "master.png").exists() or not (d / "sheet.png").exists():
        raise FoundryError(f"personas/{name} has no master.png and sheet.png; run --pick first")
    face = check_face_box(face or st.get("face_box") or DEFAULT_FACE)
    st["face_box"] = face
    _refuse_if_in_use(ws, name, "--remeasure")  # pack.json stays until a new --approve replaces it
    return _gate(ws, name, st, face)


def pieces_using(ws: Workspace, name: str) -> list[str]:
    from .piece import Piece  # local import: piece imports workspace only, cast is imported by spec
    out = []
    for p in Piece.all(ws):
        try:
            st = p.status
            spec = read_json(p.rel("spec.json")) or {}
        except (ValueError, OSError):  # an unreadable piece might be built on this creator: be conservative
            out.append(f"{p.path.relative_to(ws.root)} (unreadable; fix or remove it)")
            continue
        if spec.get("creator") == name and st.get("state") in ACTIVE_PIECE_STATES:
            out.append(f"{st.get('account')}/{st.get('slug')}")
    return out


def _refuse_if_in_use(ws: Workspace, name: str, step: str) -> None:
    """A creator whose pack pieces are approved against must not change under them."""
    if (pdir(ws, name) / "pack.json").exists():
        active = pieces_using(ws, name)
        if active:
            raise FoundryError(f"personas/{name} is used by pieces that are approved or building ({', '.join(active)}); "
                               f"ship or drop them before `foundry cast {name} {step}`")


def pick(ws: Workspace, name: str, candidate: str, face: Sequence[float] | None = None, provider=None) -> dict[str, Any]:
    human_only("cast --pick")
    check_name(candidate, CANDIDATE_RE, "candidate")
    _refuse_if_in_use(ws, name, "--pick")
    st = state(ws, name)
    if st["state"] not in ("candidates", "blocked", "sheet_measured", "picking"):
        raise FoundryError(f"personas/{name} is '{st['state']}'; run `foundry cast {name} --brief ...` first")
    d = pdir(ws, name)
    src = d / "candidates" / f"{candidate}.png"
    if not src.exists():
        raise FoundryError(f"no candidate {candidate} in personas/{name}/candidates")
    st["touches"] = st.get("touches", 0) + (0 if st["state"] == "blocked" and st.get("master_from") == candidate else 1)
    shutil.copyfile(src, d / "master.png")
    face = check_face_box(face or DEFAULT_FACE)
    master_m = skin.measure_face(d / "master.png", face)
    if master_m is None:
        raise FoundryError(f"no measurable skin in the centre of the face box {face}; pass --face x0,y0,x1,y1")
    rule = skin_rule(master_m)
    prompt = safety_lint.lint((REPO / "foundry/templates/cast_sheet.txt").read_text().format(skin_rule=rule))["rewritten"]
    (d / "prompts/sheet.txt").write_text(prompt)
    provider = provider or get_image_provider(ws.image, str(ws.root / ".foundry"))
    st["calls"].append({"op": "edit", "n": 1, "refs": ["master.png"], "at": now()})
    st.update(master_from=candidate, face_box=face, state="picking", blocked_gate=None)
    (d / "measure.json").unlink(missing_ok=True)  # a failed sheet call must not leave an old measurement to approve
    (d / "sheet.png").unlink(missing_ok=True)
    _save(ws, name, st)
    tmp = save_png(provider.edit(prompt, [d / "master.png"], n=1, size=media.SHEET_IMAGE_SIZE)[0], d / ".sheet.tmp.png")
    tmp.replace(d / "sheet.png")

    return _gate(ws, name, st, face)


def approve(ws: Workspace, name: str, story: str | None = None, wardrobe: str | None = None,
            visual_check: str | None = None) -> dict[str, Any]:
    human_only("cast --approve")
    _refuse_if_in_use(ws, name, "--approve")
    st = state(ws, name)
    d = pdir(ws, name)
    m = read_json(d / "measure.json")
    if not m or not (d / "master.png").exists() or not (d / "sheet.png").exists():
        raise FoundryError(f"personas/{name} has no measured sheet; run --pick (or --remeasure) first")
    current = {"master_sha256": sha256_file(d / "master.png"), "sheet_sha256": sha256_file(d / "sheet.png")}
    if m.get("images") != current:
        raise FoundryError(f"personas/{name}: master.png or sheet.png changed since they were measured; run "
                           f"`foundry cast {name} --remeasure` first")
    override = None
    if st["state"] == "blocked" and st.get("blocked_gate") == "sheet_unmeasurable" and m and m.get("gate") == "sheet_unmeasurable":
        if not (visual_check or "").strip():
            raise FoundryError(f"the sheet could not be measured; look at personas/{name}/sheet.png and approve with "
                               f"--visual-check \"what you checked\"")
        if any(x.get("master_sha256") == current["master_sha256"] and x.get("sheet_sha256") == current["sheet_sha256"]
               for x in st.get("drift_seen", [])):
            raise FoundryError("this master and sheet already measured as drift; a different face box cannot turn "
                               "that into a visual approval. Regenerate the sheet with --pick")
        override = {"gate": "sheet_unmeasurable", "note": visual_check.strip(), "at": now()}
    elif visual_check:
        raise FoundryError("--visual-check only applies to a sheet that could not be measured; a measured drift "
                           "cannot be approved by eye")
    elif st["state"] != "sheet_measured" or m.get("failed"):
        raise FoundryError(f"personas/{name} is '{st['state']}'; the sheet must be measured green before approval")
    st["touches"] = st.get("touches", 0) + 1
    pack = {
        "name": name, "version": 1, "locked_at": now(),
        "files": {"master": "master.png", "sheet": "sheet.png", "prompts": "prompts/"},
        "look": st.get("brief", ""),
        "face_box": m["face_box"],
        "skin_box": m.get("skin_box"),
        "images": m["images"],
        "sheet_check": override or {"gate": "measured", "matched_panels": m["sheet"].get("matched_panels")},
        "skin_rule": skin_rule(m["master"]),
        "camera_rule": CAMERA_RULE,
        "wardrobe_default": wardrobe or "opaque everyday cotton top in a solid colour",
        "known_defects": [],
        "story": {"summary": story or ""},
        "qc_targets": {"skin": {"lum": m["master"]["lum"], "r_minus_b": m["master"]["r_minus_b"],
                                "sat_pct": m["master"]["sat_pct"], "tol": dict(SKIN_TOL)},
                       "method": m["method"]},
        "measurements": {"master": m["master"], "sheet_row": m["sheet"]["row"],
                         "panel_spread": m["sheet"]["panel_spread"]},
        "cast_touches": st["touches"],
    }
    write_json(d / "pack.json", pack)
    st.update(state="locked")
    _save(ws, name, st)
    return pack


def pack_problem(ws: Workspace, name: str) -> str | None:
    """Why this creator's pack must not be used right now, or None when it is usable.

    A pack is usable only while the creator is locked AND master.png/sheet.png are still the images the pack
    was approved with: during a re-cast (picking, blocked, or measured but not yet approved) the old pack
    describes a face that is no longer on disk."""
    d = pdir(ws, name)
    pack = read_json(d / "pack.json")
    if not pack:
        return f"personas/{name} has no pack.json; cast it first (foundry cast {name})"
    st = state(ws, name)
    if st.get("state") != "locked":
        return f"personas/{name} is being re-cast ({st.get('state')}); approve it again before using it"
    images = pack.get("images")
    if images:
        for key, file in (("master_sha256", "master.png"), ("sheet_sha256", "sheet.png")):
            if not (d / file).exists() or sha256_file(d / file) != images.get(key):
                return f"personas/{name}/{file} changed since the pack was approved; re-cast it"
    return None


def load_pack(ws: Workspace, name: str) -> dict[str, Any]:
    problem = pack_problem(ws, name)
    if problem:
        raise FoundryError(problem)
    return read_json(pdir(ws, name) / "pack.json")
