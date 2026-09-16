"""`foundry build`: hand an approved piece to a headless Claude session that runs the loop.

Mirrors gstack-loops' driver: a mode maps to a permission mode, the prompt encodes the
pipeline and the never-ship-red rule, and the session is spawned in the workspace. The
session may only run `foundry`, upload bytes with curl, read files, and call the video
MCP server named in foundry.json providers.video.mcp_server.
"""
from __future__ import annotations

import shutil
import subprocess
from typing import Any

from .piece import Piece
from .util import FoundryError
from .workspace import Workspace

MODES = {
    "interactive": {"permission_mode": "default", "headless": False},
    "bypass": {"permission_mode": "acceptEdits", "headless": True},
    "autonomous": {"permission_mode": "bypassPermissions", "headless": True},
}


def prompt(ws: Workspace, piece: Piece, cycles: int) -> str:
    video = ws.config["providers"]["video"]
    ref = piece.ref
    return "\n".join([
        f"You are building the Foundry piece {ref} in this workspace. Its spec is approved; do not re-scope it.",
        f"Read {piece.path.relative_to(ws.root)}/SPEC.md first. Every step below is a `foundry` command that prints JSON; act on it.",
        f"Retry budget: {cycles} regeneration(s) per stage. `foundry qc` enforces it and marks the piece BLOCKED when it runs out.",
        "",
        "STAGE FRAMES",
        f"1. Open {piece.path.relative_to(ws.root)}/frames/approved.png. Record the face box: `foundry region {ref} frames/approved.png --face x0,y0,x1,y1` (fractions).",
        f"2. Look at the hands. Record `foundry verdict {ref} --check hands --stage frames --pass` or `--fail --note \"what is wrong\"`.",
        f"3. `foundry qc {ref} --stage frames`. If red and not blocked: `foundry regen-frame {ref}`, then repeat 1-3.",
        "",
        "STAGE CLIP",
        f"4. `foundry prompt {ref} --kind motion` prints the motion prompt and the generate_video params.",
        f"5. Reserve before spending: `foundry reserve {ref} --unit video_credits --amount <cost>` after a get_cost preflight.",
        f"   If reserve prints BLOCKED, stop. Upload frames/approved.png with the video MCP (media_upload, curl PUT, media_confirm),",
        f"   call generate_video with model {video['model']}, the approved frame as the start image, aspect {video['aspect']},",
        "   no audio. If the preflight returns a preset recommendation instead of a cost, re-send with declined_preset_id.",
        "   Wait with jobs_wait, download the mp4 with curl, then `foundry settle` the reservation with --ok and --ref <job id>.",
        f"6. `foundry ingest-clip {ref} <mp4> --job <job id>`. Look at the sampled frames in clips/shot01/frames/.",
        f"   Record the hands verdict for stage clip. Run `foundry qc {ref} --stage clip`.",
        "   If red and not blocked: append the printed guidance to the motion prompt (`foundry prompt --kind motion --guidance-from clip`) and repeat 5-6.",
        "",
        "STAGE CUT",
        f"7. `foundry cut {ref}` then `foundry qc {ref} --stage cut`. If red, fix what the guidance names and re-run 7.",
        "",
        "RULES",
        "- NEVER ship red. Never edit qc/*.json, status.json or invoice.json by hand. Never run `foundry ship` or post anything.",
        "- Any command printing BLOCKED ends the run: print `BLOCKED <gate>: <evidence>` and stop, keeping every file.",
        "- On green (`foundry qc --stage cut` reports state green): print `DONE` with `foundry ls --json` output for this piece.",
    ])


def build(ws: Workspace, piece: Piece, mode: str, cycles: int | None = None, dry_run: bool = False) -> dict[str, Any]:
    if mode not in MODES:
        raise FoundryError(f"mode must be one of {', '.join(MODES)}")
    if piece.state not in ("approved", "building"):
        raise FoundryError(f"{piece.ref} is '{piece.state}'; build needs an approved sheet (foundry approve)")
    if mode == "autonomous":
        raise FoundryError("autonomous mode would post without a human; posting is not implemented in v1. Use --mode bypass.")
    cycles = int(cycles if cycles is not None else ws.defaults["fix_cycles"])
    st = piece.status
    st["fix_cycles"] = cycles
    piece.save_status(st)
    text = prompt(ws, piece, cycles)
    if mode == "interactive":
        return {"piece": piece.ref, "mode": mode, "prompt": text,
                "next": f"run /foundry-build {piece.ref} in a Claude session in this workspace"}
    server = ws.config["providers"]["video"].get("mcp_server")
    allowed = ["Bash(foundry:*)", "Bash(curl:*)", "Read"] + ([f"mcp__{server}"] if server else [])
    argv = ["claude", "-p", text, "--permission-mode", MODES[mode]["permission_mode"], "--allowedTools", " ".join(allowed)]
    out = {"piece": piece.ref, "mode": mode, "fix_cycles": cycles, "argv": argv[:1] + ["-p", "<prompt>"] + argv[3:],
           "prompt": text}
    if not server:
        out["warning"] = ("providers.video.mcp_server is not set in foundry.json, so the headless session cannot call "
                          "the video tools without a permission prompt. Set it to the MCP server name.")
    if dry_run:
        return out
    if not server:
        raise FoundryError(out["warning"])
    if not shutil.which("claude"):
        raise FoundryError("claude CLI not on PATH")
    code = subprocess.run(argv, cwd=ws.root).returncode
    out["exit_code"] = code
    out["state"] = piece.status["state"]
    return out
