"""doctor, ls, reap."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Any

from engine.providers import get_image_provider

from . import REPO, __version__
from .piece import Piece
from .util import read_json
from .workspace import Workspace, version_ok

SKILLS = ["foundry", "foundry-cast", "foundry-spec", "foundry-build", "foundry-ship"]


def doctor(ws: Workspace | None, offline: bool = False) -> dict[str, Any]:
    rows: list[dict[str, str]] = []

    def row(name: str, status: str, detail: str = "") -> None:
        rows.append({"check": name, "status": status, "detail": detail})

    row("python", "ok" if sys.version_info >= (3, 11) else "fail", sys.version.split()[0])
    for mod in ("PIL", "numpy"):
        try:
            __import__(mod)
            row(mod, "ok")
        except ImportError:
            row(mod, "fail", "pip install Pillow numpy")
    for tool in ("ffmpeg", "ffprobe"):
        row(tool, "ok" if shutil.which(tool) else "fail", shutil.which(tool) or "brew install ffmpeg")
    row("claude CLI", "ok" if shutil.which("claude") else "warn", shutil.which("claude") or "needed for foundry build")
    home = Path(os.environ.get("CLAUDE_SKILLS_DIR", Path.home() / ".claude/skills"))
    missing = [s for s in SKILLS if not (home / s / "SKILL.md").exists()]
    row("skills installed", "ok" if not missing else "warn", "missing: " + ", ".join(missing) if missing else str(home))
    if ws is None:
        row("workspace", "fail", "no foundry.json; run foundry init")
    else:
        req = ws.config.get("requires", "")
        row("workspace", "ok" if version_ok(req) else "fail", f"{ws.root} requires {req}, installed {__version__}")
        img = ws.image
        if img["kind"] == "openai-images":
            has_key = bool(os.environ.get("OPENAI_API_KEY"))
            row("OPENAI_API_KEY", "ok" if has_key else "fail", "set" if has_key else "add it to the workspace .env")
            if has_key and not offline:
                ok, detail = get_image_provider(img).check_model()
                row(f"image model {img['model']}", "ok" if ok else "fail", detail)
        else:
            row("image provider", "warn", f"kind={img['kind']} (offline fake, spends nothing)")
        video = ws.config["providers"]["video"]
        row("video MCP server", "ok" if video.get("mcp_server") else "warn",
            video.get("mcp_server") or "set providers.video.mcp_server; MCP tools are only visible inside a Claude "
                                       "session, so /foundry-build checks reachability with the balance tool")
    worst = "fail" if any(r["status"] == "fail" for r in rows) else ("warn" if any(r["status"] == "warn" for r in rows) else "ok")
    return {"status": worst, "checks": rows}


def ls(ws: Workspace) -> list[dict[str, Any]]:
    out = []
    for p in Piece.all(ws):
        st = p.status
        out.append({"piece": p.ref, "state": st["state"], "touches": st.get("touches", 0), "cycles": st["cycles"],
                    "video_credits": p.spent("video_credits"), "image_calls": p.spent("image_call"),
                    "blocked_gate": st.get("blocked_gate") if st["state"] == "blocked" else None,
                    "posted": bool((read_json(p.rel("publish.json")) or {}).get("posted_at"))})
    return out


KEEP = {"SPEC.md", "spec.json", "status.json", "invoice.json", "publish.json", "qc"}


def reap(ws: Workspace, dry_run: bool = False) -> list[dict[str, Any]]:
    reaped = []
    for p in Piece.all(ws):
        pub = read_json(p.rel("publish.json")) or {}
        if p.state != "shipped" or not pub.get("posted_at"):
            continue
        removed = [c.name for c in p.path.iterdir() if c.name not in KEEP]
        if not dry_run:
            for name in removed:
                c = p.path / name
                shutil.rmtree(c) if c.is_dir() else c.unlink()
        reaped.append({"piece": p.ref, "removed": sorted(removed), "kept": sorted(KEEP)})
    return reaped
