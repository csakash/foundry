"""Small shared helpers: errors with exit codes, JSON files, .env, time."""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class FoundryError(Exception):
    """Refusal: a precondition is not met. Exit 2."""
    code = 2


class Blocked(Exception):
    """A gate failed after its retries, or the budget ran out. Exit 1, never ships."""
    code = 1

    def __init__(self, gate: str, evidence: str):
        super().__init__(f"BLOCKED {gate}: {evidence}")
        self.gate, self.evidence = gate, evidence


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json(path: str | Path, default: Any = None) -> Any:
    p = Path(path)
    if not p.exists():
        return default
    return json.loads(p.read_text())


def write_json(path: str | Path, data: Any) -> Path:
    """Atomic write: a crash mid-write never leaves half a status or invoice file."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=f".{p.name}.")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, allow_nan=False)
            f.write("\n")
        os.replace(tmp, p)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return p


def load_dotenv(path: str | Path) -> list[str]:
    """Load KEY=VALUE lines into os.environ without overriding what is already set."""
    p = Path(path)
    loaded: list[str] = []
    if not p.exists():
        return loaded
    for line in p.read_text().splitlines():
        m = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$", line)
        if not m or line.lstrip().startswith("#"):
            continue
        key, val = m.group(1), m.group(2).strip()
        if len(val) >= 2 and val[0] in "'\"" and val[0] in val[1:]:
            val = val[1:val.index(val[0], 1)]
        else:
            val = re.split(r"\s+#", val, maxsplit=1)[0].strip()
        if key not in os.environ:
            os.environ[key] = val
            loaded.append(key)
    return loaded


def get_path(data: dict[str, Any], dotted: str) -> Any:
    cur: Any = data
    for part in dotted.split("."):
        if isinstance(cur, list):
            idx = int(part)
            if idx >= len(cur):
                return None
            cur = cur[idx]
        elif isinstance(cur, dict):
            if part not in cur:
                return None
            cur = cur[part]
        else:
            return None
    return cur


def set_path(data: dict[str, Any], dotted: str, value: Any) -> None:
    parts = dotted.split(".")
    cur: Any = data
    for i, part in enumerate(parts[:-1]):
        nxt = parts[i + 1]
        if isinstance(cur, list):
            idx = int(part)
            while len(cur) <= idx:
                cur.append({})
            cur = cur[idx]
            continue
        if part not in cur or cur[part] is None:
            cur[part] = [] if nxt.isdigit() else {}
        cur = cur[part]
    last = parts[-1]
    if isinstance(cur, list):
        idx = int(last)
        while len(cur) <= idx:
            cur.append(None)
        cur[idx] = value
    else:
        cur[last] = value


def parse_value(raw: str) -> Any:
    """CLI values: JSON when it parses (numbers, lists, objects, true/false/null), else the string."""
    import math
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return raw
    if isinstance(value, float) and not math.isfinite(value):
        raise FoundryError(f"{raw!r} is not a finite number")
    return value


# ---------------------------------------------------------------- input guards
# Every name that becomes a path component is checked here, once, so a slug or a
# persona name can never walk out of the workspace.
ACCOUNT_RE = re.compile(r"^@[A-Za-z0-9._]{1,64}$")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
CANDIDATE_RE = re.compile(r"^c[1-9][0-9]?$")
SHOT_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
AGENT_ENV = "FOUNDRY_AGENT"


def check_name(value: str, pattern: "re.Pattern[str]", what: str) -> str:
    if not isinstance(value, str) or not pattern.match(value):
        raise FoundryError(f"invalid {what} {value!r} (must match {pattern.pattern})")
    return value


def inside(root: Path, rel: str | Path, what: str) -> Path:
    """Resolve rel under root and refuse anything that escapes it (../, absolute paths, symlinks out)."""
    base = Path(root).resolve()
    p = (base / rel).resolve()
    if p != base and base not in p.parents:
        raise FoundryError(f"{what} {str(rel)!r} is outside {base}")
    return p


def human_only(step: str) -> None:
    """Steps that are the human's decision. The build agent runs with FOUNDRY_AGENT=1 and is refused."""
    if os.environ.get(AGENT_ENV):
        raise FoundryError(f"`foundry {step}` is a human step; the build agent may not run it")


@contextlib.contextmanager
def file_lock(path: str | Path):
    """Exclusive advisory lock. Every read-modify-write of piece state runs under one."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a+") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def sha256_file(path: str | Path) -> str:
    import hashlib
    with open(path, "rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


MIN_FACE_SIDE = 0.05


def check_face_box(face) -> list[float]:
    """x0,y0,x1,y1 as fractions: inside the image, positive area, at least 5 % on each side."""
    try:
        x0, y0, x1, y1 = (float(v) for v in face)
    except (TypeError, ValueError):
        raise FoundryError("a face box is four numbers x0,y0,x1,y1")
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        raise FoundryError("face box must be fractions with 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1")
    if x1 - x0 < MIN_FACE_SIDE or y1 - y0 < MIN_FACE_SIDE:
        raise FoundryError(f"face box is too small (each side must be at least {MIN_FACE_SIDE})")
    return [x0, y0, x1, y1]
