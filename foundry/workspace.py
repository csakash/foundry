"""The workspace: a directory with foundry.json, holding personas, accounts, work and recipes.

Foundry is installed once (a CLI on PATH, like gloop). A workspace such as
gmm-contents holds only data and this file; it never carries engine code.
"""
from __future__ import annotations

import copy
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import __version__
from .util import FoundryError, load_dotenv, read_json, write_json

CONFIG = "foundry.json"

DEFAULT_CONFIG: dict[str, Any] = {
    "requires": "0.1.x",
    "dirs": {"personas": "personas", "accounts": "accounts", "work": "work", "pipelines": "pipelines"},
    "providers": {
        "image": {"kind": "openai-images", "model": "gpt-image-2.5", "quality": "high", "rpm_images": 5},
        "vision": {"kind": "agent"},
        "video": {"kind": "higgsfield-mcp", "model": "seedance_2_5", "resolution": "720p", "aspect": "9:16",
                  "audio": False},
    },
    "defaults": {"mode": "bypass", "fix_cycles": 2, "credit_ceiling_multiplier": 3, "max_duration_s": 60,
                 "sheet_candidates": 3},
    "cast": {"max_sheet_lum_delta": 12, "max_panel_spread": 45},
    "publish": {"kind": "buffer", "channels": {}},
}


def _merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def version_ok(requires: str, version: str = __version__) -> bool:
    """'0.1.x' matches 0.1.*; '0.1.0' matches exactly."""
    pat = "^" + re.escape(requires).replace(r"x", r"\d+") + "$"
    return re.match(pat, version) is not None


@dataclass
class Workspace:
    root: Path
    config: dict[str, Any]

    def dir(self, name: str) -> Path:
        return self.root / self.config["dirs"][name]

    @property
    def image(self) -> dict[str, Any]:
        return self.config["providers"]["image"]

    @property
    def defaults(self) -> dict[str, Any]:
        return self.config["defaults"]


def find_root(start: str | Path | None = None) -> Path | None:
    d = Path(start or os.getcwd()).resolve()
    for cand in [d, *d.parents]:
        if (cand / CONFIG).exists():
            return cand
    return None


def load(start: str | Path | None = None, check_version: bool = True) -> Workspace:
    root = find_root(start)
    if root is None:
        raise FoundryError(f"No {CONFIG} here or in any parent. Run `foundry init` in your workspace first.")
    raw = read_json(root / CONFIG, {})
    requires = raw.get("requires", DEFAULT_CONFIG["requires"])
    if check_version and not version_ok(requires):
        raise FoundryError(f"{CONFIG} requires foundry {requires}, installed is {__version__}. "
                           f"Upgrade the CLI or change `requires`.")
    load_dotenv(root / ".env")
    return Workspace(root, _merge(DEFAULT_CONFIG, raw))


def init(target: str | Path | None = None) -> tuple[Workspace, bool]:
    root = Path(target or os.getcwd()).resolve()
    root.mkdir(parents=True, exist_ok=True)
    created = False
    if not (root / CONFIG).exists():
        write_json(root / CONFIG, DEFAULT_CONFIG)
        created = True
    ws = load(root)
    for name in ws.config["dirs"]:
        ws.dir(name).mkdir(parents=True, exist_ok=True)
    return ws, created
