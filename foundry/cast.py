"""Cast a creator: bootstrap masters, pick one, generate the mandatory sheet, measure, lock a pack.

    foundry cast nova --brief "..."          -> personas/nova/candidates/c1..cN.png + contact.png
    foundry cast nova --pick c2 [--face ..]  -> master.png, sheet.png, measure.json  (touch 1)
                                                fails closed: BLOCKED sheet_drift, no pack
    foundry cast nova --approve              -> pack.json                            (touch 2)

No creator can be used in a spec without pack.json, and pack.json only exists when the
sheet's measured skin matched the master's.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Sequence

from engine.providers import get_image_provider
from engine.qc import safety_lint, skin

from . import REPO
from .imaging import contact, save_png
from .util import CANDIDATE_RE, NAME_RE, Blocked, FoundryError, check_name, human_only, now, read_json, write_json
from .workspace import Workspace

DEFAULT_FACE = (0.33, 0.22, 0.67, 0.55)
SHEET_TOP_ROW = (0.0, 0.02, 1.0, 0.33)
SKIN_TOL = {"lum": 12, "r_minus_b": 16, "sat_pct": 11}
CAMERA_RULE = ("Every shot needs a nameable camera position the creator set up themselves: selfie, propped, "
               "POV, object/detail, or handed-over. In a selfie one hand is the camera.")


SHEET_PANELS = 7  # the sheet template asks for seven heads across the top row


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
    provider = provider or get_image_provider(ws.image)
    st["calls"].append({"op": "generate", "n": n, "at": now(), "safety_hits": lint["measures"]["hits"]})
    _save(ws, name, st)
    outs = provider.generate(prompt, n=n, size="1024x1536")
    paths = [save_png(b, d / "candidates" / f"c{i + 1}.png") for i, b in enumerate(outs)]
    contact(paths, d / "candidates/contact.png", [p.stem for p in paths], cols=len(paths),
            title=f"{name}: pick a master (foundry cast {name} --pick cN)")
    st.update(state="candidates", brief=brief.strip(), candidates=[p.stem for p in paths])
    _save(ws, name, st)
    return st


def measure_sheet(sheet_path: Path) -> dict[str, Any]:
    a = skin.crop(skin.load_rgb(sheet_path), SHEET_TOP_ROW)
    w = a.shape[1]
    panels = [skin.measure_array(a[:, int(i * w / SHEET_PANELS):int((i + 1) * w / SHEET_PANELS)])
              for i in range(SHEET_PANELS)]
    lums = [p["lum"] for p in panels if p]
    return {"row": skin.measure_array(a), "panels": panels, "measured_panels": len(lums),
            "panel_spread": round(max(lums) - min(lums), 1) if lums else None}


def pick(ws: Workspace, name: str, candidate: str, face: Sequence[float] | None = None, provider=None) -> dict[str, Any]:
    human_only("cast --pick")
    check_name(candidate, CANDIDATE_RE, "candidate")
    st = state(ws, name)
    if st["state"] not in ("candidates", "blocked", "sheet_measured"):
        raise FoundryError(f"personas/{name} is '{st['state']}'; run `foundry cast {name} --brief ...` first")
    d = pdir(ws, name)
    src = d / "candidates" / f"{candidate}.png"
    if not src.exists():
        raise FoundryError(f"no candidate {candidate} in personas/{name}/candidates")
    st["touches"] = st.get("touches", 0) + (0 if st["state"] == "blocked" and st.get("master_from") == candidate else 1)
    shutil.copyfile(src, d / "master.png")
    face = list(face or DEFAULT_FACE)
    master_m = skin.measure(d / "master.png", face)
    if master_m is None:
        raise FoundryError(f"no measurable skin inside the face box {face}; pass --face x0,y0,x1,y1")
    rule = skin_rule(master_m)
    prompt = safety_lint.lint((REPO / "foundry/templates/cast_sheet.txt").read_text().format(skin_rule=rule))["rewritten"]
    (d / "prompts/sheet.txt").write_text(prompt)
    provider = provider or get_image_provider(ws.image)
    st["calls"].append({"op": "edit", "n": 1, "refs": ["master.png"], "at": now()})
    st.update(master_from=candidate, face_box=face)
    _save(ws, name, st)
    save_png(provider.edit(prompt, [d / "master.png"], n=1, size="1536x1024")[0], d / "sheet.png")

    sheet_m = measure_sheet(d / "sheet.png")
    cfg = ws.config["cast"]
    fails = []
    if sheet_m["row"] is None or sheet_m["measured_panels"] < 4:
        fails.append(f"only {sheet_m['measured_panels']} of {SHEET_PANELS} top-row panels have measurable skin")
    else:
        delta = round(sheet_m["row"]["lum"] - master_m["lum"], 1)
        if abs(delta) > cfg["max_sheet_lum_delta"]:
            fails.append(f"sheet skin lum {sheet_m['row']['lum']} vs master {master_m['lum']} (delta {delta}, max {cfg['max_sheet_lum_delta']})")
        if sheet_m["panel_spread"] > cfg["max_panel_spread"]:
            fails.append(f"panel spread {sheet_m['panel_spread']} > {cfg['max_panel_spread']}")
    write_json(d / "measure.json", {"method": "engine.qc.skin face-box v1", "master": master_m, "face_box": face,
                                    "sheet": sheet_m, "failed": fails, "at": now()})
    if fails:
        (d / "pack.json").unlink(missing_ok=True)
        st.update(state="blocked", blocked_gate="sheet_drift")
        _save(ws, name, st)
        raise Blocked("sheet_drift", "; ".join(fails) + f". Re-run `foundry cast {name} --pick {candidate}` to regenerate the sheet.")
    st.update(state="sheet_measured", blocked_gate=None)
    _save(ws, name, st)
    return st


def approve(ws: Workspace, name: str, story: str | None = None, wardrobe: str | None = None) -> dict[str, Any]:
    human_only("cast --approve")
    st = state(ws, name)
    if st["state"] != "sheet_measured":
        raise FoundryError(f"personas/{name} is '{st['state']}'; the sheet must be measured green before approval")
    d = pdir(ws, name)
    m = read_json(d / "measure.json")
    st["touches"] = st.get("touches", 0) + 1
    pack = {
        "name": name, "version": 1, "locked_at": now(),
        "files": {"master": "master.png", "sheet": "sheet.png", "prompts": "prompts/"},
        "look": st.get("brief", ""),
        "face_box": m["face_box"],
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


def load_pack(ws: Workspace, name: str) -> dict[str, Any]:
    pack = read_json(pdir(ws, name) / "pack.json")
    if not pack:
        raise FoundryError(f"personas/{name} has no pack.json; cast it first (foundry cast {name})")
    return pack
