"""Ship: re-check the cut, write the publish handoff, save the piece as a recipe.

Bypass (the v1 acceptance mode) stops here: nothing is posted. The human posts the
file and records it with `foundry posted`, which is what `foundry reap` waits for.
"""
from __future__ import annotations

from typing import Any

from .loop import run_qc
from .piece import Piece
from .util import SLUG_RE, FoundryError, check_name, human_only, now, read_json, write_json
from .workspace import Workspace

RECIPE_PARAMETERS = [
    {"slot": "hook.line", "description": "the on-screen hook line", "stages": ["sheet", "frames", "clip", "cut"]},
    {"slot": "assets.0.path", "description": "the product clip that follows the reaction", "stages": ["sheet", "cut"]},
]


def ship(ws: Workspace, piece: Piece, recipe_name: str | None = None) -> dict[str, Any]:
    human_only("ship")
    piece.require("green")
    spec = piece.spec
    name = check_name(recipe_name or spec["slug"], SLUG_RE, "recipe name")
    existing = read_json(ws.dir("pipelines") / f"{name}.json")
    if existing and existing.get("made_from") != piece.ref:
        raise FoundryError(f"pipelines/{name}.json was made from {existing.get('made_from')}; pass --recipe <new name>")
    for s in ("frames", "clip"):
        piece.require_pass(s)
    report = run_qc(ws, piece, "cut")
    if not report["pass"]:
        piece.set_state("building")
        raise FoundryError("cut QC went red on the ship re-check: " + report["guidance"])
    final = piece.rel("cut", "final.mp4")
    channel = ws.config["publish"]["channels"].get(spec["account"])
    publish = {"account": spec["account"], "kind": ws.config["publish"]["kind"], "channel_id": channel,
               "video": str(final), "on_screen_text": spec["captions"]["text"], "posted_at": None, "post_url": None,
               "prepared_at": now(),
               "instructions": [f"Upload {final} to {spec['account']} as a Reel (no extra caption burn needed).",
                                f"Then record it: foundry posted {piece.ref} --url <post url>"]}
    write_json(piece.rel("publish.json"), publish)

    inv = piece.invoice
    recipe = {
        "id": name, "name": name, "made_from": piece.ref, "saved_at": now(), "post_type": "video", "format": spec["format"],
        "spec": {k: v for k, v in spec.items() if k not in ("account", "slug", "created_at", "resolved_from", "recipe")},
        "parameters": RECIPE_PARAMETERS,
        "stage_map": {p["slot"]: p["stages"] for p in RECIPE_PARAMETERS},
        "cost_per_run": {u: piece.spent(u) for u in ("image_call", "video_credits")},
        "touches": piece.status.get("touches", 0),
        "cycles": piece.status["cycles"],
        "invoice_ceilings": inv.get("ceilings"),
        "qc_targets_approved": piece.lock["qc_targets"],
    }
    write_json(ws.dir("pipelines") / f"{name}.json", recipe)
    piece.set_state("shipped", shipped_at=now(), recipe=name)
    return {"piece": piece.ref, "video": str(final), "recipe": f"pipelines/{name}.json",
            "publish": str(piece.rel("publish.json")), "posted": False, "instructions": publish["instructions"],
            "cost": recipe["cost_per_run"], "touches": recipe["touches"]}


def posted(ws: Workspace, piece: Piece, url: str | None) -> dict[str, Any]:
    human_only("posted")
    piece.require("shipped")
    pub = read_json(piece.rel("publish.json"))
    pub.update(posted_at=now(), post_url=url)
    write_json(piece.rel("publish.json"), pub)
    return {"piece": piece.ref, "posted_at": pub["posted_at"], "post_url": url}
