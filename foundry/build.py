"""`foundry build`: hand an approved piece to a headless Claude session that runs the loop.

Mirrors gstack-loops' driver (a mode, a driving prompt, a spawned `claude -p`), with one
deliberate difference: the session gets NO file-editing tools and NO raw shell. It may
run `foundry` (minus the human steps), read files, and call the video MCP server. Every
QC limit lives in approved.lock.json and every transfer goes through `foundry upload` /
`foundry fetch`, so the agent cannot edit its way to green or send workspace files
anywhere. FOUNDRY_AGENT=1 marks the session; human steps refuse under it.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from typing import Any

from .piece import LOCK, Piece
from .util import AGENT_ENV, FoundryError, human_only, read_json
from .workspace import Workspace

PERMISSION_MODE = {"interactive": "default", "bypass": "dontAsk"}  # dontAsk: anything not allowlisted is denied
VIDEO_TOOLS = ["balance", "models_explore", "media_upload", "media_confirm", "generate_video", "jobs_wait"]
BUILD_TIMEOUT_S = 3 * 3600
MAX_FIX_CYCLES = 10
MODES = ["interactive", "bypass", "autonomous"]
SERVER_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
HUMAN_STEPS = ["init", "cast", "new", "set", "sheet", "approve", "build", "ship", "posted", "reap"]


def prompt(ws: Workspace, piece: Piece, cycles: int) -> str:
    video = ws.config["providers"]["video"]
    ref = piece.ref
    d = piece.path.relative_to(ws.root)
    shots = ", ".join(sh["id"] for sh in (read_json(piece.rel("spec.json")) or {}).get("shots", [])) or "shot01"
    return "\n".join([
        f"You are building the Foundry piece {ref} in this workspace. Its spec is approved; do not re-scope it.",
        f"Read {d}/SPEC.md first. Every step below is a `foundry` command; add --json and act on what it prints.",
        f"Retry budget: {cycles} regeneration(s) per stage, enforced by foundry. When it runs out the piece is BLOCKED.",
        "",
        "STAGE FRAMES",
        f"1. Open {d}/frames/approved.png. Record the face box: `foundry region {ref} frames/approved.png --face x0,y0,x1,y1` (fractions, forehead to chin, ear to ear).",
        f"2. Look at the hands. Record `foundry verdict {ref} --check hands --stage frames --pass` or `--fail --note \"what is wrong\"`.",
        f"3. `foundry qc {ref} --stage frames`. If red and not blocked: `foundry regen-frame {ref}`, then repeat 1-3.",
        "",
        "STAGE CLIP (repeat for each shot: " + shots + ")",
        f"4. `foundry prompt {ref} --kind motion` prints the motion prompt and the generate_video params.",
        "5. Use the video MCP: models_explore once for the start-image media role and durations; media_upload for approved.png;",
        f"   `foundry upload {ref} --url <upload_url>`; media_confirm; generate_video with get_cost true (model {video['model']},",
        f"   aspect {video['aspect']}, no audio). A preset recommendation instead of a cost: re-send with declined_preset_id.",
        f"6. `foundry reserve {ref} --unit video_credits --amount <cost>` (BLOCKED means stop). generate_video for real.",
        f"   jobs_wait until terminal. `foundry settle {ref} <entry> --ok --ref <job_id>` (or --failed if the job failed).",
        f"7. `foundry fetch {ref} --url <result url> --job <job_id> --shot <shot id>`. Look at clips/<shot id>/frames/.",
        f"   Record the hands verdict for stage clip. `foundry qc {ref} --stage clip`. If red and not blocked: repeat 4-7 with",
        "   `foundry prompt --kind motion --guidance-from clip`.",
        "   Never resubmit a generation whose outcome is unknown after a timeout; reuse the job id.",
        "",
        "STAGE CUT",
        f"8. `foundry cut {ref}` then `foundry qc {ref} --stage cut`. A red cut cannot be fixed by you: report the guidance.",
        "",
        "RULES",
        "- NEVER ship red. You cannot edit files; do not try. The human runs `foundry ship`.",
        "- Any command printing BLOCKED ends the run: print `BLOCKED <gate>: <evidence>` and stop.",
        "- On green (`foundry qc --stage cut` reports state green): print `DONE` and the `foundry ls --json` row for this piece.",
    ])


def argv(ws: Workspace, piece: Piece, mode: str, cycles: int) -> list[str]:
    server = ws.config["providers"]["video"].get("mcp_server")
    if not server:
        raise FoundryError("providers.video.mcp_server is not set in foundry.json; the headless session needs the "
                           "video MCP server's name to call its tools")
    if not SERVER_RE.match(server):
        raise FoundryError(f"providers.video.mcp_server {server!r} must match {SERVER_RE.pattern}")
    work = ws.config["dirs"]["work"]
    allowed = ["Bash(foundry:*)", f"Read(./{work}/**)"] + [f"mcp__{server}__{t}" for t in VIDEO_TOOLS]
    # dontAsk + the allowlist already confine reads to work/. Never deny a home-wide pattern: the
    # workspace itself usually lives under the home directory and deny rules beat allow rules.
    denied = (["Edit", "Write", "NotebookEdit", "WebFetch", "WebSearch", "Read(./.env)", "Read(~/.ssh/**)",
               "Read(~/.aws/**)", "Read(~/.config/**)"]
              + [f"Bash(foundry {s}:*)" for s in HUMAN_STEPS])
    return ["claude", "-p", prompt(ws, piece, cycles), "--permission-mode", PERMISSION_MODE[mode],
            "--allowedTools", *allowed, "--disallowedTools", *denied]


def build(ws: Workspace, piece: Piece, mode: str, cycles: int | None = None, dry_run: bool = False) -> dict[str, Any]:
    human_only("build")
    if mode not in MODES:
        raise FoundryError(f"mode must be one of {', '.join(MODES)}")
    if mode == "autonomous":
        raise FoundryError("autonomous mode would post without a human; posting is not implemented in v1. Use --mode bypass.")
    if piece.state not in ("approved", "building"):
        raise FoundryError(f"{piece.ref} is '{piece.state}'; build needs an approved sheet (foundry approve)")
    lock = read_json(piece.rel(LOCK)) or {}  # read, not verified: a dry run must never block
    if not lock:
        raise FoundryError(f"{piece.ref} has no approval lock; approve the sheet first")
    if cycles is not None and not 0 <= cycles <= MAX_FIX_CYCLES:
        raise FoundryError(f"--fix-cycles must be between 0 and {MAX_FIX_CYCLES}")
    if cycles is not None and cycles != lock["fix_cycles"]:
        if piece.state != "approved":
            raise FoundryError("the retry budget is fixed once the build has started")
        if not dry_run:
            piece.set_fix_cycles(cycles)
    budget = cycles if cycles is not None else lock["fix_cycles"]
    text = prompt(ws, piece, budget)
    if mode == "interactive":
        return {"piece": piece.ref, "mode": mode, "fix_cycles": budget, "prompt": text,
                "next": f"run /foundry-build {piece.ref} in a Claude session in this workspace"}
    args = argv(ws, piece, mode, budget)
    out = {"piece": piece.ref, "mode": mode, "fix_cycles": budget, "prompt": text,
           "argv": args[:2] + ["<prompt>"] + args[3:]}
    if dry_run:
        return out
    if not shutil.which("claude"):
        raise FoundryError("claude CLI not on PATH")
    pidfile = piece.rel(".build.pid")
    fd = _claim_pidfile(pidfile, piece.ref)
    env = {**os.environ, AGENT_ENV: "1"}
    try:
        proc = subprocess.Popen(args, cwd=ws.root, env=env, start_new_session=True)
        os.write(fd, str(proc.pid).encode())
        os.close(fd)
        fd = None
        try:
            out["exit_code"] = proc.wait(timeout=BUILD_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, 9)  # claude and any foundry command it started
            proc.wait()
            out["exit_code"] = "timeout"
    finally:
        if fd is not None:
            os.close(fd)
        pidfile.unlink(missing_ok=True)
    out["state"] = piece.status["state"]
    out["blocked_gate"] = piece.status.get("blocked_gate") if out["state"] == "blocked" else None
    return out


def _claim_pidfile(pidfile, ref: str) -> int:
    """O_EXCL create: two builds racing for one piece cannot both win. A stale file from a dead build is reclaimed."""
    for _ in range(2):
        try:
            return os.open(pidfile, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            try:
                pid = int(pidfile.read_text().strip() or 0)
                os.kill(pid, 0)
            except (ValueError, ProcessLookupError):
                pidfile.unlink(missing_ok=True)
                continue
            except PermissionError:
                pass
            raise FoundryError(f"a build is already running for {ref} (pidfile {pidfile})")
    raise FoundryError(f"could not claim {pidfile}")
