"""`foundry build`: hand an approved piece to a headless Claude session that runs the loop.

Mirrors gstack-loops' driver (a mode, a driving prompt, a spawned `claude -p`), with one
deliberate difference: the session gets NO file-editing tools and NO raw shell. It may
run `foundry` (minus the human steps), read files, and — on the MCP route only — call the video MCP server.
On the Higgsfield API route (SPEC.md "Higgsfield API route") `foundry generate` makes the call itself. Every
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

from . import video as video_mod
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
# Provider secrets the build session's shell must not hold. `foundry generate` reloads them from the workspace
# .env inside its own process, so the agent can call the API without ever being able to read or send the key.
AGENT_SECRET_ENV = ("HF_KEY", "HF_API_KEY", "HF_API_SECRET")


def prompt(ws: Workspace, piece: Piece, cycles: int, route: dict[str, Any] | None = None,
           headless: bool = False) -> str:
    video = ws.config["providers"]["video"]
    route = route or {"route": "mcp", "reason": "not resolved"}
    # An in-session build has whatever connectors the session has; only a headless one is limited to mcp_server.
    mcp_ok = not headless or bool(video.get("mcp_server")) or route["route"] == "mcp"
    ref = piece.ref
    d = piece.path.relative_to(ws.root)
    shots = ", ".join(sh["id"] for sh in (read_json(piece.rel("spec.json")) or {}).get("shots", [])) or "shot01"
    mcp_steps = [
        "   MCP route:",
        f"   a. `foundry prompt {ref} --kind motion --shot <shot id>` prints that shot's motion prompt and generate_video params.",
        "   b. Use the video MCP: models_explore once for the start-image media role and durations; media_upload for approved.png;",
        f"      `foundry upload {ref} --url <upload_url>`; media_confirm; generate_video with get_cost true (model {video['model']},",
        f"      aspect {video['aspect']}, no audio). A preset recommendation instead of a cost: re-send with declined_preset_id.",
        f"   c. `foundry reserve {ref} --unit video_credits --amount <cost>` (BLOCKED means stop). generate_video for real.",
        f"      jobs_wait until terminal. `foundry settle {ref} <entry> --ok --ref <job_id>` (or --failed if the job failed).",
        f"   d. `foundry fetch {ref} --url <result url> --job <job_id> --shot <shot id>`.",
        "      Never resubmit a generation whose outcome is unknown after a timeout; reuse the job id.",
    ] if mcp_ok else [
        "   MCP route: not available in this session (no providers.video.mcp_server). If foundry route says mcp,",
        "   print `BLOCKED video.route: <its reason>` and stop.",
    ]
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
        f"4. `foundry route {ref}` says which video route to use now: api (the Higgsfield API) or mcp. Ask again for each",
        f"   shot. At build start it said {route['route']} ({route['reason']}).",
        "5. Generate the shot's clip on that route.",
        "   API route:",
        f"   `foundry generate {ref} --shot <shot id>` (add `--guidance-from clip` on a regeneration). It prices, reserves,",
        "   uploads, submits, waits, downloads and ingests; you call no video tools. If it says the request is not finished,",
        "   run it again: it resumes the same request and never resubmits. If it refuses and says to use the MCP steps,",
        "   follow the MCP route for this shot. If it says a human must check the Higgsfield console, print",
        "   `BLOCKED video.unknown_submit: <its message>` and stop: never try to generate that shot another way.",
        *mcp_steps,
        f"6. Look at clips/<shot id>/frames/. Record the hands verdict for stage clip. `foundry qc {ref} --stage clip`.",
        "   If red and not blocked: repeat 4-6 for that shot, regenerating with the clip guidance",
        f"   (API: --guidance-from clip; MCP: `foundry prompt {ref} --kind motion --shot <shot id> --guidance-from clip`).",
        "",
        "STAGE CUT",
        f"7. `foundry cut {ref}` then `foundry qc {ref} --stage cut`. A red cut cannot be fixed by you: report the guidance.",
        "",
        "RULES",
        "- NEVER ship red. You cannot edit files; do not try. The human runs `foundry ship`.",
        "- Any command printing BLOCKED ends the run: print `BLOCKED <gate>: <evidence>` and stop.",
        "- On green (`foundry qc --stage cut` reports state green): print `DONE` and the `foundry ls --json` row for this piece.",
    ])


def argv(ws: Workspace, piece: Piece, mode: str, cycles: int, route: dict[str, Any] | None = None) -> list[str]:
    route = route or {"route": "mcp", "reason": "not resolved"}
    server = ws.config["providers"]["video"].get("mcp_server")
    if route["route"] == "mcp" and not server:
        raise FoundryError("providers.video.mcp_server is not set in foundry.json; the headless session needs the "
                           f"video MCP server's name to call its tools (the Higgsfield API is not in use: "
                           f"{route['reason']})")
    if server and not SERVER_RE.match(server):
        raise FoundryError(f"providers.video.mcp_server {server!r} must match {SERVER_RE.pattern}")
    piece_dir = piece.path.relative_to(ws.root)  # the agent reads only its own piece
    allowed = ["Bash(foundry:*)", f"Read(./{piece_dir}/**)"] + ([f"mcp__{server}__{t}" for t in VIDEO_TOOLS]
                                                                 if server else [])
    # dontAsk + the allowlist already confine reads to this piece's directory. Never deny a home-wide pattern: the
    # workspace itself usually lives under the home directory and deny rules beat allow rules.
    denied = (["Edit", "Write", "NotebookEdit", "WebFetch", "WebSearch", "Read(./.env)", "Read(~/.ssh/**)",
               "Read(~/.aws/**)", "Read(~/.config/**)"]
              + [f"Bash(foundry {s}:*)" for s in HUMAN_STEPS])
    return ["claude", "-p", prompt(ws, piece, cycles, route, headless=True), "--permission-mode", PERMISSION_MODE[mode],
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
            piece.set_fix_cycles(cycles)  # re-checks the state under the piece lock
    budget = cycles if cycles is not None else lock["fix_cycles"]
    route = video_mod.resolve(ws, piece)  # live, once per build; the agent re-asks per shot
    text = prompt(ws, piece, budget, route, headless=mode != "interactive")
    if mode == "interactive":
        return {"piece": piece.ref, "mode": mode, "fix_cycles": budget, "prompt": text, "video_route": route,
                "next": f"run /foundry-build {piece.ref} in a Claude session in this workspace"}
    args = argv(ws, piece, mode, budget, route)
    out = {"piece": piece.ref, "mode": mode, "fix_cycles": budget, "prompt": text, "video_route": route,
           "argv": args[:2] + ["<prompt>"] + args[3:]}
    if dry_run:
        return out
    if not shutil.which("claude"):
        raise FoundryError("claude CLI not on PATH")
    pidfile = piece.rel(".build.pid")
    fd = _claim_pidfile(pidfile, piece.ref)
    env = {k: v for k, v in os.environ.items() if k not in AGENT_SECRET_ENV}
    env[AGENT_ENV] = piece.ref  # the session may only act on this piece
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
