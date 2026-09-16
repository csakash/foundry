"""One piece of content = one directory = one state machine.

    work/<account>/<slug>/
        spec.json SPEC.md status.json invoice.json approved.lock.json
        sheet/ frames/ clips/ cut/ qc/ publish.json

status.json is the only place state lives; every command reads it, checks the
transition is legal, and writes it back. invoice.json records a reservation
BEFORE any provider call, so a crash never loses the spend record. At approval,
approved.lock.json freezes the QC thresholds, the retry budget and a hash of
spec.json: QC reads its limits from the lock and refuses if the spec changed.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import math
import uuid
from pathlib import Path
from typing import Any, Iterator

from .util import (ACCOUNT_RE, SLUG_RE, Blocked, FoundryError, check_name, file_lock, now, read_json, sha256_file,
                   write_json)
from .workspace import Workspace

STATES = ["created", "specced", "sheet_pending", "approved", "building", "green", "blocked", "shipped"]
STAGES = ["frames", "clip", "cut"]
APPROVED = "frames/approved.png"
LOCK = "approved.lock.json"
COUNTED = ("reserved", "settled", "failed")  # a failed call may still have been billed


class Piece:
    def __init__(self, ws: Workspace, path: Path):
        self.ws, self.path = ws, path

    # ------------------------------------------------------------ locate
    @classmethod
    def create(cls, ws: Workspace, account: str, slug: str) -> "Piece":
        check_name(account, ACCOUNT_RE, "account")
        check_name(slug, SLUG_RE, "slug")
        path = ws.dir("work") / account / slug
        if (path / "status.json").exists():
            raise FoundryError(f"{path.relative_to(ws.root)} already exists")
        path.mkdir(parents=True, exist_ok=True)
        p = cls(ws, path)
        write_json(p.path / "status.json", {
            "state": "created", "account": account, "slug": slug, "created_at": now(),
            "cycles": {s: 0 for s in STAGES}, "blocked_gate": None, "touches": 0,
            "touch_log": [], "history": [{"state": "created", "at": now()}]})
        return p

    @classmethod
    def open(cls, ws: Workspace, ref: str) -> "Piece":
        work = ws.dir("work").resolve()
        for c in (Path(ref), ws.root / ref, work / ref.lstrip("/")):
            c = c.resolve()
            if (c / "status.json").exists() and work in c.parents:
                return cls(ws, c)
        raise FoundryError(f"no piece at {ref!r} (expected work/<@account>/<slug>/status.json)")

    @classmethod
    def all(cls, ws: Workspace) -> list["Piece"]:
        return [cls(ws, s.parent) for s in sorted(ws.dir("work").glob("@*/*/status.json"))]

    @property
    def ref(self) -> str:
        return f"{self.status['account']}/{self.status['slug']}"

    def rel(self, *parts: str) -> Path:
        return self.path.joinpath(*parts)

    @contextlib.contextmanager
    def exclusive(self) -> Iterator[None]:
        """One foundry command at a time per piece: parallel tool calls cannot race the invoice or the cycles.

        Re-entrant within this object (flock would deadlock against a second descriptor in the same process)."""
        if getattr(self, "_held", 0):
            self._held += 1
            try:
                yield
            finally:
                self._held -= 1
            return
        with file_lock(self.path / ".lock"):
            self._held = 1
            try:
                yield
            finally:
                self._held = 0

    # ------------------------------------------------------------ status
    @property
    def status(self) -> dict[str, Any]:
        return read_json(self.path / "status.json")

    @property
    def state(self) -> str:
        return self.status["state"]

    def save_status(self, st: dict[str, Any]) -> None:
        write_json(self.path / "status.json", st)

    def require(self, *states: str) -> None:
        if self.state not in states:
            raise FoundryError(f"{self.ref} is '{self.state}'; this step needs {' or '.join(states)}")

    def set_state(self, state: str, **fields: Any) -> dict[str, Any]:
        with self.exclusive():
            assert state in STATES, state
            st = self.status
            st["state"] = state
            st.update(fields)
            st["history"].append({"state": state, "at": now(), **fields})
            self.save_status(st)
            if (self.path / "spec.json").exists():  # SPEC.md carries the state line; keep it current
                from .spec import render_md
                (self.path / "SPEC.md").write_text(render_md(self.spec, self))
            return st

    def touch(self, what: str) -> int:
        """Count a human decision. Acceptance criterion 12 reads this counter."""
        with self.exclusive():
            st = self.status
            st["touches"] = int(st.get("touches", 0)) + 1
            st.setdefault("touch_log", []).append({"what": what, "at": now()})
            self.save_status(st)
            return st["touches"]

    def bump_cycle(self, stage: str) -> int:
        with self.exclusive():
            st = self.status
            st["cycles"][stage] = int(st["cycles"].get(stage, 0)) + 1
            self.save_status(st)
            return st["cycles"][stage]

    def block(self, gate: str, evidence: str) -> Blocked:
        self.set_state("blocked", blocked_gate=gate, blocked_evidence=evidence)
        return Blocked(gate, evidence)

    # ------------------------------------------------------------ spec + lock
    @property
    def spec(self) -> dict[str, Any]:
        s = read_json(self.path / "spec.json")
        if s is None:
            raise FoundryError(f"{self.ref} has no spec.json")
        return s

    def save_spec(self, spec: dict[str, Any]) -> None:
        from .spec import render_md  # local import: spec imports piece
        if (self.path / LOCK).exists():
            raise FoundryError(f"{self.ref} is approved; its spec is frozen")
        write_json(self.path / "spec.json", spec)
        (self.path / "SPEC.md").write_text(render_md(spec, self))

    def spec_hash(self) -> str:
        return sha256_file(self.path / "spec.json")

    def locked_inputs(self) -> dict[str, str]:
        """This piece's own inputs besides spec.json, hashed at approval: the creator's identity files, the
        product clip and any music track. Shared files (the account charter, repo scenes and templates) are
        deliberately not hashed: editing them for the next piece must not block this one. The charter the
        cut is linted against is snapshotted into the lock instead."""
        from .util import inside
        spec = self.spec
        paths = {}
        pdir = self.ws.dir("personas") / spec["creator"]
        for name in ("master.png", "sheet.png"):
            paths[f"persona/{name}"] = pdir / name
        pack_path = pdir / "pack.json"
        for i, a in enumerate(spec["assets"]):
            paths[f"asset/{i}"] = inside(self.ws.root, a["path"], "product clip")
        if spec["audio"].get("path") and spec["audio"].get("kind") == "trending":
            paths["audio"] = inside(self.ws.root, spec["audio"]["path"], "audio track")
        missing = [k for k, v in paths.items() if not v.exists()] + ([] if pack_path.exists() else ["persona/pack.json"])
        if missing:
            raise FoundryError("approval needs these inputs, which are missing: " + ", ".join(missing))
        hashes = {k: self._cached_hash(v) for k, v in paths.items()}
        # the pack is hashed by the fields a build reads, not its bytes: re-approving the same numbers
        # (new locked_at, new touch count) must not block pieces already approved against them
        pack = read_json(pack_path)
        material = {k: pack.get(k) for k in ("qc_targets", "face_box", "skin_rule", "wardrobe_default", "camera_rule")}
        hashes["persona/pack"] = hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()
        return hashes

    def _input_paths(self) -> dict[str, Path]:
        from .util import inside
        spec = self.spec
        pdir = self.ws.dir("personas") / spec["creator"]
        paths = {f"persona/{n}": pdir / n for n in ("master.png", "sheet.png", "pack.json")}
        for i, a in enumerate(spec["assets"]):
            paths[f"asset/{i}"] = inside(self.ws.root, a["path"], "product clip")
        if spec["audio"].get("path") and spec["audio"].get("kind") == "trending":
            paths["audio"] = inside(self.ws.root, spec["audio"]["path"], "audio track")
        return paths

    def _input_stats(self) -> dict[str, list[int] | None]:
        out: dict[str, list[int] | None] = {}
        for k, v in self._input_paths().items():
            try:
                st = v.stat()
                out[k] = [st.st_size, st.st_mtime_ns]
            except FileNotFoundError:
                out[k] = None
        return out

    def _cached_hash(self, path: Path) -> str:
        """sha256 of a file, re-read only when its size or mtime changed (product clips can be hundreds of MB)."""
        st = path.stat()
        key = (str(path), st.st_size, st.st_mtime_ns)
        cache = self.__dict__.setdefault("_hashes", {})
        if key not in cache:
            cache[key] = sha256_file(path)
        return cache[key]

    def write_lock(self, fix_cycles: int) -> dict[str, Any]:
        spec = self.spec
        charter = read_json(self.ws.dir("accounts") / self.status["account"] / "charter.json")
        lock = {"spec_sha256": self.spec_hash(), "inputs": self.locked_inputs(), "input_stats": self._input_stats(),
                "charter": charter,
                "qc_targets": spec["qc_targets"],
                "fix_cycles": int(fix_cycles), "max_duration_s": self.ws.defaults["max_duration_s"],
                "min_video_reservation": min_video_reservation(spec), "locked_at": now()}
        write_json(self.path / LOCK, lock)
        return lock

    @property
    def lock(self) -> dict[str, Any]:
        """The approved limits. Blocks when spec.json or any locked input changed after approval."""
        lock = read_json(self.path / LOCK)
        if not lock:
            raise FoundryError(f"{self.ref} has no {LOCK}; approve the sheet first")
        if self.spec_hash() != lock["spec_sha256"]:
            raise self.block("spec.changed_after_approval",
                             "spec.json no longer matches the approved hash; QC limits cannot be trusted")
        if "inputs" not in lock:  # approved before inputs were locked
            return lock
        try:
            stats = self._input_stats()
            if lock.get("input_stats") and stats == lock["input_stats"]:
                return lock  # nothing on disk changed size or mtime since approval: no need to re-hash a large clip
            current = self.locked_inputs()
        except (OSError, FoundryError) as e:
            raise self.block("inputs.changed_after_approval", f"an approved input is missing or unreadable: {e}")
        if "persona/pack.json" in lock["inputs"]:  # locks written before packs were hashed by their build fields
            current.pop("persona/pack", None)
            current["persona/pack.json"] = sha256_file(self.ws.dir("personas") / self.spec["creator"] / "pack.json")
        changed = sorted(k for k in set(lock["inputs"]) | set(current) if lock["inputs"].get(k) != current.get(k))
        if changed:
            raise self.block("inputs.changed_after_approval", "changed since approval: " + ", ".join(changed))
        if stats != lock.get("input_stats"):  # contents verified identical: remember the new stats, skip re-hashing
            with self.exclusive():
                fresh = read_json(self.path / LOCK)
                fresh["input_stats"] = stats
                write_json(self.path / LOCK, fresh)
            lock["input_stats"] = stats
        return lock

    def set_fix_cycles(self, n: int) -> None:
        with self.exclusive():
            if self.state != "approved":
                raise FoundryError("the retry budget is fixed once the build has started")
            lock = read_json(self.path / LOCK)
            lock["fix_cycles"] = int(n)
            write_json(self.path / LOCK, lock)

    def require_pass(self, stage: str) -> dict[str, Any]:
        r = read_json(self.rel("qc", f"{stage}.json"))
        if not r or not r["pass"]:
            raise FoundryError(f"{stage} QC is not green yet; run foundry qc --stage {stage} first")
        return r

    # ------------------------------------------------------------ invoice
    @property
    def invoice(self) -> dict[str, Any]:
        return read_json(self.path / "invoice.json",
                         {"frozen": False, "ceilings": {}, "baseline": {}, "planned": {}, "entries": []})

    def spent(self, unit: str) -> float:
        return round(sum(e["amount"] for e in self.invoice["entries"]
                         if e["unit"] == unit and e["state"] in COUNTED), 2)

    def reserve(self, unit: str, amount: float, note: str) -> str:
        """Write the spend BEFORE the call. After approval, refuses (BLOCKED budget.<unit>) past the ceiling.

        The ceiling covers spend since approval: sheet renders before approval are the price of deciding.
        """
        with self.exclusive():
            if not math.isfinite(amount) or amount <= 0:
                raise FoundryError("reserve amount must be a positive finite number")
            inv = self.invoice
            floor = (read_json(self.path / LOCK) or {}).get("min_video_reservation")
            if unit == "video_credits" and floor and amount < floor:
                raise FoundryError(f"a clip costs at least {floor:g} video credits for this spec; reserve the preflight cost")
            if inv.get("frozen") and unit in inv["ceilings"]:
                since = self.spent(unit) - float(inv.get("baseline", {}).get(unit, 0))
                if since + amount > inv["ceilings"][unit] + 1e-9:
                    raise self.block(f"budget.{unit}", f"{note} needs {amount} {unit}; {since:g} spent since approval "
                                                       f"of ceiling {inv['ceilings'][unit]:g}")
            eid = f"e{len(inv['entries']) + 1:03d}-{uuid.uuid4().hex[:6]}"
            inv["entries"].append({"id": eid, "unit": unit, "amount": amount, "note": note,
                                   "state": "reserved", "at": now()})
            write_json(self.path / "invoice.json", inv)
            return eid

    def settle(self, eid: str, ok: bool, actual: float | None = None, ref: str | None = None) -> dict[str, Any]:
        """One-way: reserved -> settled | failed. Never lowers a recorded charge."""
        with self.exclusive():
            inv = self.invoice
            e = next((x for x in inv["entries"] if x["id"] == eid), None)
            if e is None:
                raise FoundryError(f"no invoice entry {eid}")
            if e["state"] != "reserved":
                raise FoundryError(f"invoice entry {eid} is already {e['state']}")
            if actual is not None and not math.isfinite(actual):
                raise FoundryError("actual must be a finite number")
            if actual is not None and actual < e["amount"]:
                raise FoundryError(f"actual {actual} is lower than the reserved {e['amount']}; charges are never lowered")
            e["state"] = "settled" if ok else "failed"
            if actual is not None:
                e["amount"] = actual
            if ref:
                e["ref"] = ref
            e["settled_at"] = now()
            write_json(self.path / "invoice.json", inv)
            unit = e["unit"]
            if inv.get("frozen") and unit in inv["ceilings"]:
                since = self.spent(unit) - float(inv.get("baseline", {}).get(unit, 0))
                if since > inv["ceilings"][unit] + 1e-9:  # the charge is real: record it, then stop spending
                    raise self.block(f"budget.{unit}", f"settled {e['amount']} {unit} on {eid}; {since:g} spent since "
                                                       f"approval is over the ceiling {inv['ceilings'][unit]:g}")
            return e

    def consume(self, unit: str, ref: str, check_only: bool = False) -> dict[str, Any]:
        """Tie a generated asset to the settled reservation that paid for it, once."""
        with self.exclusive():
            inv = self.invoice
            e = next((x for x in inv["entries"] if x["unit"] == unit and x.get("ref") == ref
                      and x["state"] == "settled" and not x.get("consumed")), None)
            if e is None:
                raise FoundryError(f"no settled, unused {unit} reservation with ref {ref!r}; "
                                   f"reserve before generating and settle with --ref {ref}")
            if check_only:
                return e
            e["consumed"] = now()
            write_json(self.path / "invoice.json", inv)
            return e


def min_video_reservation(spec: dict[str, Any]) -> float:
    """The cheapest one clip can be: the per-5 s unit price times the shortest shot's 5 s blocks."""
    unit = float(((spec.get("budget") or {}).get("unit_credits") or {}).get("video_5s", 0))
    shots = [math.ceil(float(sh["duration_s"]) / 5) for sh in spec.get("shots", [])]
    return round(unit * min(shots), 2) if unit and shots else 0.0
