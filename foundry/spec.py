"""spec.json: the one file a piece is built from, and the resolver that fills it.

Resolution order per slot: value already set -> recipe -> creator pack -> format
defaults -> the account's last shipped piece -> unresolved. Only unresolved slots
become questions, and there are never more than five of them, asked in one round.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from engine.qc import caption_band, duration as qc_duration, text_lint

from . import REPO, caption, cast, hook_reel
from .piece import Piece
from .util import (NAME_RE, SHOT_RE, FoundryError, check_name, get_path, human_only, inside, now, parse_value,
                   read_json, set_path)
from .workspace import Workspace

MAX_QUESTIONS = 5
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm"}


def new(ws: Workspace, account: str, slug: str, recipe: str | None = None) -> Piece:
    human_only("new")
    p = Piece.create(ws, account, slug)
    spec = hook_reel.defaults()
    spec.update(account=account, slug=slug, creator=None, resolved_from={}, created_at=now())
    if recipe:
        r = read_json(ws.dir("pipelines") / f"{recipe}.json")
        if not r:
            raise FoundryError(f"no recipe pipelines/{recipe}.json")
        locked = copy.deepcopy(r["spec"])
        for param in r.get("parameters", []):
            set_path(locked, param["slot"], None)
        locked.update(account=account, slug=slug, created_at=now())
        locked["recipe"] = recipe
        locked["resolved_from"] = {k: "recipe" for k in ("format", "creator", "audio", "captions", "shots")}
        spec = locked
    p.save_spec(spec)
    return p


def _packs(ws: Workspace) -> list[str]:
    return sorted(d.parent.name for d in ws.dir("personas").glob("*/pack.json"))


def _last_shipped(ws: Workspace, account: str) -> dict[str, Any] | None:
    best = None
    for p in Piece.all(ws):
        st = p.status
        if st["account"] == account and st["state"] == "shipped":
            if best is None or st["history"][-1]["at"] > best[0]:
                best = (st["history"][-1]["at"], p.spec)
    return best[1] if best else None


def resolve(ws: Workspace, piece: Piece) -> dict[str, Any]:
    if piece.state == "sheet_pending":
        raise FoundryError(f"{piece.ref} has a rendered sheet; change it with foundry set (which re-opens the spec)")
    if piece.state not in ("created", "specced"):
        raise FoundryError(f"{piece.ref} is '{piece.state}'; the spec is frozen after approval")
    spec = piece.spec
    rf = spec.setdefault("resolved_from", {})
    questions: list[dict[str, Any]] = []
    last = _last_shipped(ws, spec["account"])

    # 1. format: one video format exists in v1
    if spec.get("format") != hook_reel.FORMAT:
        spec["format"] = hook_reel.FORMAT
        rf["format"] = "only_option"
    rf.setdefault("format", "format_default")

    # 2. creator
    packs = _packs(ws)
    if not spec.get("creator"):
        if last and last.get("creator") in packs:
            spec["creator"], rf["creator"] = last["creator"], "last_shipped"
        elif len(packs) == 1:
            spec["creator"], rf["creator"] = packs[0], "only_option"
    if not packs:
        raise FoundryError("no locked creators in personas/; run `foundry cast <name>` first")
    if not spec.get("creator"):
        questions.append({"id": "creator", "slot": "creator", "question": "Which creator is in the reaction shot?",
                          "options": packs, "recommended": packs[0]})
    elif spec["creator"] not in packs:
        raise FoundryError(f"creator {spec['creator']!r} has no pack.json (have: {', '.join(packs)})")

    # 3. hook line: always the human's words
    if not get_path(spec, "hook.line"):
        questions.append({"id": "hook", "slot": "hook.line",
                          "question": "What is the on-screen hook line (the text the viewer reads over the reaction)?",
                          "options": [], "recommended": None,
                          "note": "The face answers the line: this scene reads as shock or surprise."})
    else:
        rf.setdefault("hook", "user")
        spec["captions"]["text"] = spec["hook"]["line"]

    # 4. product asset
    asset = get_path(spec, "assets.0.path")
    if not asset and last and get_path(last, "assets.0.path"):
        spec["assets"][0]["path"], rf["assets"] = last["assets"][0]["path"], "last_shipped"
        asset = spec["assets"][0]["path"]
    if not asset:
        questions.append({"id": "assets", "slot": "assets.0.path",
                          "question": "Which product clip follows the reaction? (path inside the workspace)",
                          "options": sorted(str(p.relative_to(ws.root)) for p in ws.root.glob("assets/**/*")
                                            if p.suffix.lower() in VIDEO_EXT)[:4], "recommended": None})
    else:
        rf.setdefault("assets", "user")

    # 5. audio
    if not get_path(spec, "audio.kind"):
        questions.append({"id": "audio", "slot": "audio.kind", "question": "Sound?",
                          "options": ["silent", "clip", "trending"], "recommended": "silent"})
    else:
        rf.setdefault("audio", "format_default")

    # creator pack fills skin targets, wardrobe and the invoice plan
    problems: list[str] = []
    warnings: list[str] = []
    if spec.get("creator") in packs:
        pack = cast.load_pack(ws, spec["creator"])
        spec["qc_targets"]["skin"] = pack["qc_targets"]["skin"]
        for sh in spec["shots"]:
            sh["wardrobe"] = sh.get("wardrobe") or pack.get("wardrobe_default")
        rf["qc_targets.skin"] = "pack"
    if asset:
        try:
            ap = inside(ws.root, asset, "product clip")
        except FoundryError as e:
            problems.append(str(e))
            ap = None
        if ap is None:
            pass
        elif not ap.exists():
            problems.append(f"product clip {asset} does not exist")
        elif ap.suffix.lower() not in VIDEO_EXT:
            problems.append(f"product clip {asset} is not a video ({ap.suffix})")
        else:
            info = qc_duration.probe(ap)
            end = float(spec["assets"][0]["trim_s"][1])
            if info["duration"] + 0.05 < end:
                problems.append(f"product clip {asset} is {info['duration']}s but the cut trims to {end:g}s; "
                                f"set assets.0.trim_s to fit")
            if get_path(spec, "audio.kind") == "clip" and not info["has_audio"]:
                problems.append(f"audio is 'clip' but {asset} has no audio track")
    for sh in spec["shots"]:
        try:
            check_name(sh["id"], SHOT_RE, "shot id")
            check_name(sh["scene"], NAME_RE, "scene id")
            hook_reel.scene(sh["scene"])
        except (FoundryError, FileNotFoundError) as e:
            problems.append(str(e))
    if get_path(spec, "hook.line"):
        # the cut gates on these, so they are problems now, before a credit is spent
        charter = read_json(ws.dir("accounts") / piece.status["account"] / "charter.json")
        lint = text_lint.lint(spec["hook"]["line"], charter)
        problems += [f"hook line: {f}" for f in lint["measures"]["failed"]]
        cap = caption.render({**spec["captions"], "text": spec["hook"]["line"]}, piece.rel(".caption-check.png"))
        piece.rel(".caption-check.png").unlink(missing_ok=True)
        piece.rel(".caption-check.json").unlink(missing_ok=True)
        cs = spec["qc_targets"].get("caption_safe", {})
        band = caption_band.check(cap["box"], None, cs.get("top_pct", 11), cs.get("bottom_pct", 71))
        problems += [f"caption: {f}" for f in band["measures"]["failed"]]
        if cap["font_substituted"]:
            warnings.append(f"caption font {cap['font_wanted']} is not installed; rendering with {cap['font_used']}")
    spec["structure"] = hook_reel.structure(spec)
    lo, hi = spec["qc_targets"].get("cut_duration_s", [0, ws.defaults["max_duration_s"]])
    total = max(seg["t"][1] for seg in spec["structure"])
    if not lo <= total <= min(hi, ws.defaults["max_duration_s"]):
        problems.append(f"the cut would run {total:g}s, outside {lo}-{min(hi, ws.defaults['max_duration_s'])}s; "
                        f"adjust assets.0.trim_s")
    n = int(ws.defaults.get("sheet_candidates", 3))
    planned = hook_reel.plan(spec, n)
    spec["budget"] = {"unit_credits": hook_reel.UNIT_CREDITS, "planned": planned,
                      "ceiling": {k: v * ws.defaults["credit_ceiling_multiplier"] for k, v in planned.items()}}

    if len(questions) > MAX_QUESTIONS:  # structurally impossible with five slots; guard the invariant anyway
        raise AssertionError(f"resolver produced {len(questions)} questions")
    piece.save_spec(spec)
    complete = not questions and not problems
    if complete and piece.state == "created":
        piece.set_state("specced")
    return {"piece": piece.ref, "complete": complete, "questions": questions, "problems": problems,
            "warnings": warnings, "resolved_from": rf}


def set_values(ws: Workspace, piece: Piece, pairs: list[str], touch: bool = False) -> dict[str, Any]:
    human_only("set")
    if piece.state not in ("created", "specced", "sheet_pending"):
        raise FoundryError(f"{piece.ref} is '{piece.state}'; the spec is frozen after approval")
    spec = piece.spec
    for pair in pairs:
        if "=" not in pair:
            raise FoundryError(f"expected slot=value, got {pair!r}")
        k, v = pair.split("=", 1)
        set_path(spec, k.strip(), parse_value(v))
        spec.setdefault("resolved_from", {})[k.split(".")[0]] = "user"
    piece.save_spec(spec)
    if piece.state in ("specced", "sheet_pending"):
        piece.set_state("created", sheet_spec_sha256=None)  # any edit re-opens resolution and voids a rendered sheet
    if touch:
        piece.touch("spec answers")
    return resolve(ws, piece)


# ---------------------------------------------------------------- prompts
def _fill(template: Path, **kw: Any) -> str:
    return template.read_text().format(**kw).strip() + "\n"


def first_frame_prompt(ws: Workspace, spec: dict[str, Any], guidance: str = "") -> str:
    pack = cast.load_pack(ws, spec["creator"])
    sh = spec["shots"][0]
    sc = hook_reel.scene(sh["scene"])
    return _fill(REPO / "engine/prompts/frame/first-frame.txt", name=spec["creator"].title(),
                 skin_rule=pack["skin_rule"], action=sc["first_frame_action"], camera=sc["camera_text"],
                 caption_space=sc["caption_space"], setting=sc["setting"], light=sc["light"],
                 wardrobe=sh.get("wardrobe") or pack["wardrobe_default"],
                 guidance=f"\nCORRECTIONS FROM QC: {guidance}" if guidance else "")


def motion_prompt(ws: Workspace, spec: dict[str, Any], shot: int = 0, guidance: str = "") -> str:
    sh = spec["shots"][shot]
    sc = hook_reel.scene(sh["scene"])
    beats = "\n".join(f"{b['t'][0]:.1f}-{b['t'][1]:.1f} s: {spec['creator'].title()} {b['action']}." for b in sh["beats"])
    return _fill(REPO / "engine/prompts/motion/seedance-beats.txt", camera=sc["camera_text"],
                 name=spec["creator"].title(), setting_short=sc["setting"].split(". ")[0].lower() + ".",
                 beats=beats, motion_rules=sc["motion_rules"], light=sc["light"], negative=sc["motion_negative"],
                 guidance=f"\nCORRECTIONS FROM QC: {guidance}" if guidance else "")


def layout_prompt(spec: dict[str, Any]) -> str:
    panels = []
    for i, seg in enumerate(spec["structure"], 1):
        label = "reaction: facepalm, then wide eyes into the lens" if "persona" in seg["beat"] else "product walkthrough"
        panels.append(f"{i}. {seg['t'][0]:.0f}-{seg['t'][1]:.0f} s, {label}")
    return _fill(REPO / "foundry/templates/sheet_layout.txt", title=spec["slug"].replace("-", " ").upper(),
                 name=spec["creator"].title(), panels="\n".join(panels), caption=spec["hook"]["line"])


# ---------------------------------------------------------------- SPEC.md
def render_md(spec: dict[str, Any], piece: Piece | None = None) -> str:
    rf = spec.get("resolved_from", {})
    L = [f"# {spec.get('account')}/{spec.get('slug')}: {spec.get('format')}", ""]
    if piece is not None and (piece.path / "status.json").exists():
        st = piece.status
        L += [f"State: **{st['state']}** · touches {st.get('touches', 0)} · cycles "
              + ", ".join(f"{k} {v}" for k, v in st["cycles"].items()), ""]
    L += ["| Slot | Value | From |", "|---|---|---|"]
    rows = [("creator", spec.get("creator"), rf.get("creator"), True),
            ("hook", (spec.get("hook") or {}).get("line"), rf.get("hook"), True),
            ("mechanism", (spec.get("hook") or {}).get("mechanism"), "", False),
            ("product clip", get_path(spec, "assets.0.path"), rf.get("assets"), True),
            ("audio", get_path(spec, "audio.kind"), rf.get("audio"), True),
            ("recipe", spec.get("recipe"), "", False)]
    for k, v, f, required in rows:
        shown = v if v not in (None, "") else ("**unresolved**" if required else "none")
        L.append(f"| {k} | {shown} | {f or ''} |")
    if spec.get("structure"):
        L += ["", "## Structure", ""] + [f"- {s['t'][0]:.0f}-{s['t'][1]:.0f} s: {s['beat']}" for s in spec["structure"]]
    for sh in spec.get("shots", []):
        L += ["", f"## {sh['id']} ({sh['scene']}, {sh['camera']}, {sh['duration_s']} s)", ""]
        L += [f"- {b['t'][0]:.1f}-{b['t'][1]:.1f} s: {b['action']}" for b in sh["beats"]]
    c = spec.get("captions") or {}
    L += ["", "## Caption", "", f"\"{c.get('text')}\" · {c.get('font')} {c.get('size_pct_w')}% width · "
          f"{c.get('band')} band from {c.get('band_start_pct_h')}% · stroke {c.get('stroke_pct')}%"]
    q = spec.get("qc_targets") or {}
    L += ["", "## QC targets", "", "```json", json.dumps(q, indent=2), "```"]
    if spec.get("budget"):
        L += ["", "## Budget", "", "```json", json.dumps(spec["budget"], indent=2), "```"]
    return "\n".join(L) + "\n"
