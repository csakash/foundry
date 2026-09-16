"""foundry: cast / spec / build / ship for a local short-form content factory.

Exit codes: 0 ok or green · 1 QC red, BLOCKED, or a build that did not reach green · 2 refused
(precondition not met) · 3 unexpected error.
Every command prints JSON with --json; the build agent always uses --json.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import __version__, build as build_mod, cast, cut as cut_mod, loop, ops, sheet, ship as ship_mod, spec as spec_mod
from . import workspace
from .piece import Piece
from .util import Blocked, FoundryError, human_only, read_json


def _floats(s: str) -> list[float]:
    try:
        v = [float(x) for x in s.split(",")]
    except ValueError:
        raise argparse.ArgumentTypeError("expected x0,y0,x1,y1")
    if len(v) != 4:
        raise argparse.ArgumentTypeError("expected four numbers x0,y0,x1,y1")
    return v


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="foundry", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"foundry {__version__}")
    ap.add_argument("--json", action="store_true", help="print JSON")
    ap.add_argument("-C", dest="cwd", help="run as if in this directory")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="write foundry.json and the workspace dirs here")
    d = sub.add_parser("doctor", help="check tools, keys, models, skills")
    d.add_argument("--offline", action="store_true", help="skip network checks")

    c = sub.add_parser("cast", help="cast a creator: --brief, then --pick cN, then --approve")
    c.add_argument("name")
    g = c.add_mutually_exclusive_group(required=True)
    g.add_argument("--brief", help="who they are and how they look")
    g.add_argument("--pick", metavar="cN", help="choose the master candidate (human touch 1)")
    g.add_argument("--approve", action="store_true", help="lock the pack after a green sheet (human touch 2)")
    c.add_argument("--n", type=int, default=3)
    c.add_argument("--face", type=_floats, help="face box on the master, x0,y0,x1,y1 fractions")
    c.add_argument("--story", help="one-paragraph story for the pack")
    c.add_argument("--wardrobe", help="default wardrobe line")

    n = sub.add_parser("new", help="create a piece: work/<@account>/<slug>")
    n.add_argument("account")
    n.add_argument("slug")
    n.add_argument("--recipe")

    r = sub.add_parser("resolve", help="fill the spec; print the questions still open (max 5)")
    r.add_argument("piece")
    s = sub.add_parser("set", help="set spec slots: slot=value ...")
    s.add_argument("piece")
    s.add_argument("pairs", nargs="+")
    s.add_argument("--touch", action="store_true", help="count this as the human's answer round")

    sh = sub.add_parser("sheet", help="render the approval sheet")
    sh.add_argument("piece")
    sh.add_argument("--n", type=int)
    a = sub.add_parser("approve", help="approve a sheet candidate (freezes the invoice)")
    a.add_argument("piece")
    a.add_argument("--candidate", required=True)

    b = sub.add_parser("build", help="run the build loop")
    b.add_argument("piece")
    b.add_argument("--mode", default=None, choices=build_mod.MODES)
    b.add_argument("--fix-cycles", type=int)
    b.add_argument("--dry-run", action="store_true")

    q = sub.add_parser("qc", help="run a stage's QC")
    q.add_argument("piece")
    q.add_argument("--stage", required=True, choices=["frames", "clip", "cut"])

    rg = sub.add_parser("region", help="record the face box for an image in the piece")
    rg.add_argument("piece")
    rg.add_argument("image", help="path inside the piece, e.g. frames/approved.png")
    rg.add_argument("--face", type=_floats, required=True)
    v = sub.add_parser("verdict", help="record a looked-at verdict (hands)")
    v.add_argument("piece")
    v.add_argument("--check", default="hands")
    v.add_argument("--stage", required=True, choices=["frames", "clip"])
    vg = v.add_mutually_exclusive_group(required=True)
    vg.add_argument("--pass", dest="ok", action="store_true")
    vg.add_argument("--fail", dest="ok", action="store_false")
    v.add_argument("--note", default="")

    p = sub.add_parser("prompt", help="print the frame or motion prompt (and video params)")
    p.add_argument("piece")
    p.add_argument("--kind", required=True, choices=["frame", "motion"])
    p.add_argument("--guidance-from", choices=["frames", "clip"])

    rs = sub.add_parser("reserve", help="record spend before a provider call")
    rs.add_argument("piece")
    rs.add_argument("--unit", required=True, choices=["video_credits", "image_call"])
    rs.add_argument("--amount", type=float, required=True)
    rs.add_argument("--note", default="")
    se = sub.add_parser("settle", help="close a reservation")
    se.add_argument("piece")
    se.add_argument("entry")
    sg = se.add_mutually_exclusive_group(required=True)
    sg.add_argument("--ok", dest="ok", action="store_true")
    sg.add_argument("--failed", dest="ok", action="store_false")
    se.add_argument("--actual", type=float)
    se.add_argument("--ref")

    sub.add_parser("regen-frame", help="regenerate the start frame with QC guidance").add_argument("piece")
    ic = sub.add_parser("ingest-clip", help="bring a local clip into the piece (needs its settled reservation)")
    ic.add_argument("piece")
    ic.add_argument("mp4")
    ic.add_argument("--job", required=True, help="the job id the reservation was settled with")
    ic.add_argument("--shot", default="shot01")
    up = sub.add_parser("upload", help="PUT frames/approved.png to a presigned https upload URL")
    up.add_argument("piece")
    up.add_argument("--url", required=True)
    fe = sub.add_parser("fetch", help="download a generated clip over https and ingest it")
    fe.add_argument("piece")
    fe.add_argument("--url", required=True)
    fe.add_argument("--job", required=True)
    fe.add_argument("--shot", default="shot01")

    sub.add_parser("cut", help="assemble cut/final.mp4").add_argument("piece")
    sp = sub.add_parser("ship", help="publish handoff + save recipe (does not post)")
    sp.add_argument("piece")
    sp.add_argument("--recipe")
    po = sub.add_parser("posted", help="record that the human posted it")
    po.add_argument("piece")
    po.add_argument("--url")
    sub.add_parser("status", help="print a piece's status.json").add_argument("piece")
    sub.add_parser("ls", help="every piece: state, cycles, credits, blocked gate")
    rp = sub.add_parser("reap", help="clear media from shipped, posted pieces")
    rp.add_argument("--dry-run", action="store_true")
    return ap


def dispatch(a: argparse.Namespace) -> tuple[Any, int]:
    start = Path(a.cwd).resolve() if a.cwd else None
    if a.cmd == "init":
        human_only("init")
        ws, created = workspace.init(start)
        return {"workspace": str(ws.root), "created": created}, 0
    if a.cmd == "doctor":
        try:
            ws = workspace.load(start, check_version=False)
        except FoundryError:
            ws = None
        res = ops.doctor(ws, offline=a.offline)
        return res, 1 if res["status"] == "fail" else 0

    ws = workspace.load(start)
    if a.cmd == "cast":
        if a.brief:
            return cast.bootstrap(ws, a.name, a.brief, n=a.n), 0
        if a.pick:
            return cast.pick(ws, a.name, a.pick, face=a.face), 0
        return cast.approve(ws, a.name, story=a.story, wardrobe=a.wardrobe), 0
    if a.cmd == "new":
        p = spec_mod.new(ws, a.account, a.slug, recipe=a.recipe)
        return spec_mod.resolve(ws, p), 0
    if a.cmd == "ls":
        return ops.ls(ws), 0
    if a.cmd == "reap":
        return ops.reap(ws, dry_run=a.dry_run), 0

    piece = Piece.open(ws, a.piece)
    if a.cmd == "build":  # not under the piece lock: the session it spawns runs foundry commands on this piece
        res = build_mod.build(ws, piece, a.mode or ws.defaults["mode"], a.fix_cycles, a.dry_run)
        headless_run = "exit_code" in res
        return res, (0 if res.get("state") == "green" else 1) if headless_run else 0
    with piece.exclusive():
        return _piece_command(a, ws, piece)


def _piece_command(a: argparse.Namespace, ws, piece: Piece) -> tuple[Any, int]:
    if a.cmd == "resolve":
        return spec_mod.resolve(ws, piece), 0
    if a.cmd == "set":
        return spec_mod.set_values(ws, piece, a.pairs, touch=a.touch), 0
    if a.cmd == "sheet":
        return sheet.render(ws, piece, n=a.n), 0
    if a.cmd == "approve":
        return sheet.approve(ws, piece, a.candidate), 0
    if a.cmd == "qc":
        rep = loop.run_qc(ws, piece, a.stage)
        return rep, 0 if rep["pass"] else 1
    if a.cmd == "region":
        return loop.record_region(piece, a.image, a.face), 0
    if a.cmd == "verdict":
        return loop.record_verdict(piece, a.check, a.stage, a.ok, a.note), 0
    if a.cmd == "prompt":
        spec = piece.spec
        guidance = ""
        if a.guidance_from:
            guidance = ((read_json(piece.rel("qc", f"{a.guidance_from}.json")) or {}).get("guidance")) or ""
        if a.kind == "frame":
            return {"prompt": spec_mod.first_frame_prompt(ws, spec, guidance)}, 0
        video = ws.config["providers"]["video"]
        text = spec_mod.motion_prompt(ws, spec, 0, guidance)
        return {"prompt": text, "start_image": str(piece.rel(loop.APPROVED)),
                "params": {"model": video["model"], "prompt": text, "duration": spec["shots"][0]["duration_s"],
                           "aspect_ratio": video["aspect"], "get_cost": True,
                           "medias": [{"role": "<start image role from models_explore>", "value": "<media_id>"}]}}, 0
    if a.cmd == "reserve":
        return {"entry": piece.reserve(a.unit, a.amount, a.note or a.unit), "spent": piece.spent(a.unit),
                "ceiling": piece.invoice["ceilings"].get(a.unit)}, 0
    if a.cmd == "settle":
        return piece.settle(a.entry, a.ok, a.actual, a.ref), 0
    if a.cmd == "regen-frame":
        return loop.regen_frame(ws, piece), 0
    if a.cmd == "ingest-clip":
        return loop.ingest_clip(ws, piece, Path(a.mp4), job=a.job, shot=a.shot), 0
    if a.cmd == "upload":
        return loop.upload_approved(ws, piece, a.url), 0
    if a.cmd == "fetch":
        return loop.fetch_clip(ws, piece, a.url, job=a.job, shot=a.shot), 0
    if a.cmd == "cut":
        return cut_mod.build(ws, piece), 0
    if a.cmd == "ship":
        return ship_mod.ship(ws, piece, a.recipe), 0
    if a.cmd == "posted":
        return ship_mod.posted(ws, piece, a.url), 0
    if a.cmd == "status":
        return piece.status, 0
    raise FoundryError(f"unknown command {a.cmd}")


def _print(res: Any, as_json: bool) -> None:
    if as_json or not isinstance(res, (dict, list)):
        print(json.dumps(res, indent=2, default=str) if not isinstance(res, str) else res)
        return
    if isinstance(res, list):
        for row in res:
            print("  ".join(f"{k}={v}" for k, v in row.items()))
        if not res:
            print("(none)")
        return
    for k, v in res.items():
        if k == "checks" and isinstance(v, dict):
            for name, chk in v.items():
                print(f"  {'PASS' if chk['pass'] else 'FAIL'}  {name}  {chk.get('guidance', '')}")
        elif k == "checks" and isinstance(v, list):
            for chk in v:
                print(f"  {chk['status']:4}  {chk['check']}  {chk['detail']}")
        elif k == "prompt" and isinstance(v, str):
            print(v)
        else:
            print(f"{k}: {json.dumps(v, default=str) if isinstance(v, (dict, list)) else v}")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in argv  # accepted anywhere, not just before the subcommand
    argv = [x for x in argv if x != "--json"]
    a = parser().parse_args(argv)
    a.json = a.json or as_json
    try:
        res, code = dispatch(a)
    except Blocked as e:
        out = {"status": "BLOCKED", "gate": e.gate, "evidence": e.evidence}
        print(json.dumps(out, indent=2) if a.json else str(e), file=sys.stdout)
        return e.code
    except FoundryError as e:
        out = {"status": "REFUSED", "error": str(e)}
        if a.json:  # agents parse stdout; a refusal is a result, not a crash
            print(json.dumps(out, indent=2))
        else:
            print(f"refused: {e}", file=sys.stderr)
        return e.code
    except Exception as e:  # a crash is neither red QC (1) nor a refusal (2): exit 3, still parseable
        out = {"status": "ERROR", "error": f"{type(e).__name__}: {e}"}
        if a.json:
            print(json.dumps(out, indent=2))
        else:
            print(f"error: {out['error']}", file=sys.stderr)
        return 3
    _print(res, a.json)
    return code
