"""Skill packs — the borrowed craft the foundry ships with.

The foundry owns the production stack; it does not own writing, offer design, or
channel marketing. Those come from three public skill repos that every foundry
install is expected to have (`engine/skill_packs.json`):

    no-ai-slop   petergyang/no-ai-slop        the human-editor lint
    hormozi      alexsmedile/hormozi-skills   offer / hook / objection craft
    marketing    coreyhaines31/marketingskills channel + campaign craft

A pack skill is *borrowed*: copied in, loaded at named stages, never edited in
place (an upgrade re-copies it). Foundry-specific rules live in
`.claude/skills/foundry*/` and cite the borrowed skill by name.

Resolution order matches Claude Code: a skill present in the project's
`.claude/skills/` wins, a skill in `~/.claude/skills/` counts as available, and
anything else is missing. `install` only fetches what is missing, so a machine
that already has a pack globally is left alone.

    python3 -m engine.skillpacks check                # what's here, what's owed
    python3 -m engine.skillpacks install              # everything missing -> project
    python3 -m engine.skillpacks install hormozi      # one pack
    python3 -m engine.skillpacks install --global     # -> ~/.claude/skills
    python3 -m engine.skillpacks install --force      # re-copy even if present
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = Path(__file__).resolve().parent / "skill_packs.json"
PROJECT_SKILLS = ROOT / ".claude" / "skills"
USER_SKILLS = Path.home() / ".claude" / "skills"


def load_packs() -> list[dict[str, Any]]:
    packs = json.loads(MANIFEST.read_text(encoding="utf-8"))["packs"]
    for p in packs:
        excl = set(p.get("exclude", []))
        p["skills"] = [s for s in p["skills"] if s not in excl]
    return packs


def get_pack(pack_id: str) -> dict[str, Any]:
    for p in load_packs():
        if p["id"] == pack_id:
            return p
    raise SystemExit(f"unknown pack: {pack_id} (have: {', '.join(p['id'] for p in load_packs())})")


def where(skill: str) -> str | None:
    """'project' | 'user' | None — first place Claude Code would find the skill."""
    if (PROJECT_SKILLS / skill / "SKILL.md").is_file():
        return "project"
    if (USER_SKILLS / skill / "SKILL.md").is_file():
        return "user"
    return None


def status(pack: dict[str, Any]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {"project": [], "user": [], "missing": []}
    for s in pack["skills"]:
        out[where(s) or "missing"].append(s)
    return out


def _clone(pack: dict[str, Any], dest: Path) -> Path:
    cmd = ["git", "clone", "--depth", "1", "--branch", pack.get("ref", "main"),
           pack["repo"], str(dest)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"clone failed for {pack['id']}:\n{r.stderr.strip()}")
    src = dest / pack.get("skills_dir", "skills")
    if not src.is_dir():
        raise SystemExit(f"{pack['id']}: no {pack.get('skills_dir', 'skills')}/ in {pack['repo']}")
    return src


def install(pack: dict[str, Any], *, target: Path, force: bool, dry_run: bool) -> list[str]:
    """Copy the pack's missing skills into `target`. Returns what was written."""
    wanted = pack["skills"] if force else [s for s in pack["skills"] if where(s) is None]
    if not wanted:
        return []
    if dry_run:
        return wanted
    written: list[str] = []
    with tempfile.TemporaryDirectory(prefix=f"foundry-pack-{pack['id']}-") as tmp:
        src = _clone(pack, Path(tmp) / "repo")
        target.mkdir(parents=True, exist_ok=True)
        for skill in wanted:
            s = src / skill
            if not (s / "SKILL.md").is_file():
                print(f"  !! {skill}: not in {pack['repo']} — manifest is stale")
                continue
            d = target / skill
            if d.exists():
                if d.name.startswith("foundry"):   # never clobber foundry-owned
                    print(f"  !! {skill}: refusing to overwrite a foundry skill")
                    continue
                shutil.rmtree(d)
            shutil.copytree(s, d)
            written.append(skill)
    return written


def cmd_check() -> int:
    owed = 0
    for pack in load_packs():
        st = status(pack)
        n = len(pack["skills"])
        have = len(st["project"]) + len(st["user"])
        mark = "ok " if not st["missing"] else "GAP"
        scope = "project" if st["project"] else ("user" if st["user"] else "-")
        print(f"[{mark}] {pack['id']:<12} {have}/{n} available  (from: {scope})")
        print(f"       {pack['role']}")
        print(f"       stages: {', '.join(pack['stages'])}")
        if st["missing"]:
            owed += len(st["missing"])
            miss = ", ".join(st["missing"][:8]) + (" …" if len(st["missing"]) > 8 else "")
            print(f"       missing: {miss}")
            print(f"       fix: python3 -m engine.skillpacks install {pack['id']}")
    if owed:
        print(f"\n{owed} skill(s) missing — the foundry will route to skills that aren't there.")
    else:
        print("\nAll skill packs available.")
    return 1 if owed else 0


def cmd_list() -> int:
    for pack in load_packs():
        print(f"{pack['id']}  {pack['repo']}  ({len(pack['skills'])} skills)")
        for s in pack["skills"]:
            print(f"    {where(s) or 'missing':<8} {s}")
    return 0


def cmd_install(ids: list[str], *, use_global: bool, force: bool, dry_run: bool) -> int:
    target = USER_SKILLS if use_global else PROJECT_SKILLS
    packs = [get_pack(i) for i in ids] if ids else load_packs()
    total = 0
    for pack in packs:
        written = install(pack, target=target, force=force, dry_run=dry_run)
        total += len(written)
        verb = "would install" if dry_run else "installed"
        if written:
            print(f"{pack['id']}: {verb} {len(written)} skill(s) -> {target}")
            for s in written:
                print(f"    {s}")
        else:
            print(f"{pack['id']}: nothing to do (all available)")
    if total and not dry_run:
        print("\nRestart the Claude Code session (or /doctor) so the new skills register.")
    return 0


def main() -> None:
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        raise SystemExit(0)
    cmd, rest = argv[0], argv[1:]
    flags = {a for a in rest if a.startswith("--")}
    ids = [a for a in rest if not a.startswith("--")]
    if cmd == "check":
        raise SystemExit(cmd_check())
    if cmd == "list":
        raise SystemExit(cmd_list())
    if cmd == "install":
        raise SystemExit(cmd_install(ids, use_global="--global" in flags,
                                     force="--force" in flags, dry_run="--dry-run" in flags))
    raise SystemExit(f"unknown command: {cmd}\n{__doc__}")


if __name__ == "__main__":
    main()
