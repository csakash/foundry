"""One piece of content = one directory = one state machine.

    work/<account>/<slug>/
        spec.json SPEC.md status.json invoice.json sheet/ frames/ clips/ cut/ qc/ publish.json

status.json is the only place state lives; every command reads it, checks the
transition is legal, and writes it back. invoice.json records a reservation
BEFORE any provider call, so a crash never loses the spend record.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .util import Blocked, FoundryError, now, read_json, write_json
from .workspace import Workspace

STATES = ["created", "specced", "sheet_pending", "approved", "building", "green", "blocked", "shipped"]
STAGES = ["frames", "clip", "cut"]


class Piece:
    def __init__(self, ws: Workspace, path: Path):
        self.ws, self.path = ws, path

    # ------------------------------------------------------------ locate
    @classmethod
    def create(cls, ws: Workspace, account: str, slug: str) -> "Piece":
        if not account.startswith("@"):
            raise FoundryError(f"account must start with @, got {account!r}")
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
        cands = [Path(ref), ws.root / ref, ws.dir("work") / ref.lstrip("/")]
        for c in cands:
            if (c / "status.json").exists():
                return cls(ws, c.resolve())
        raise FoundryError(f"no piece at {ref!r} (expected work/<@account>/<slug>/status.json)")

    @classmethod
    def all(cls, ws: Workspace) -> list["Piece"]:
        return [cls(ws, s.parent) for s in sorted(ws.dir("work").glob("@*/*/status.json"))]

    @property
    def ref(self) -> str:
        return f"{self.status['account']}/{self.status['slug']}"

    def rel(self, *parts: str) -> Path:
        return self.path.joinpath(*parts)

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
        assert state in STATES, state
        st = self.status
        st["state"] = state
        st.update(fields)
        st["history"].append({"state": state, "at": now(), **{k: v for k, v in fields.items() if k != "history"}})
        self.save_status(st)
        return st

    def touch(self, what: str) -> int:
        """Count a human decision. Acceptance criterion 12 reads this counter."""
        st = self.status
        st["touches"] = int(st.get("touches", 0)) + 1
        st.setdefault("touch_log", []).append({"what": what, "at": now()})
        self.save_status(st)
        return st["touches"]

    def bump_cycle(self, stage: str) -> int:
        st = self.status
        st["cycles"][stage] = int(st["cycles"].get(stage, 0)) + 1
        self.save_status(st)
        return st["cycles"][stage]

    def block(self, gate: str, evidence: str) -> Blocked:
        self.set_state("blocked", blocked_gate=gate, blocked_evidence=evidence)
        return Blocked(gate, evidence)

    # ------------------------------------------------------------ spec
    @property
    def spec(self) -> dict[str, Any]:
        s = read_json(self.path / "spec.json")
        if s is None:
            raise FoundryError(f"{self.ref} has no spec.json")
        return s

    def save_spec(self, spec: dict[str, Any]) -> None:
        from .spec import render_md  # local import: spec imports piece
        write_json(self.path / "spec.json", spec)
        (self.path / "SPEC.md").write_text(render_md(spec, self))

    # ------------------------------------------------------------ invoice
    @property
    def invoice(self) -> dict[str, Any]:
        return read_json(self.path / "invoice.json", {"frozen": False, "ceilings": {}, "planned": {}, "entries": []})

    def spent(self, unit: str) -> float:
        return round(sum(e["amount"] for e in self.invoice["entries"]
                         if e["unit"] == unit and e["state"] in ("reserved", "settled")), 2)

    def reserve(self, unit: str, amount: float, note: str) -> str:
        """Write the spend BEFORE the call. Refuses (BLOCKED budget.<unit>) past the frozen ceiling."""
        inv = self.invoice
        ceiling = inv["ceilings"].get(unit) if inv.get("frozen") else None
        if ceiling is not None and self.spent(unit) + amount > ceiling + 1e-9:
            raise self.block(f"budget.{unit}",
                             f"{note} needs {amount} {unit}; spent {self.spent(unit)} of ceiling {ceiling}")
        eid = f"e{len(inv['entries']) + 1:03d}"
        inv["entries"].append({"id": eid, "unit": unit, "amount": amount, "note": note,
                               "state": "reserved", "at": now()})
        write_json(self.path / "invoice.json", inv)
        return eid

    def settle(self, eid: str, ok: bool, actual: float | None = None, ref: str | None = None) -> None:
        inv = self.invoice
        for e in inv["entries"]:
            if e["id"] == eid:
                e["state"] = "settled" if ok else "failed"
                if actual is not None:
                    e["amount"] = actual
                if ref:
                    e["ref"] = ref
                e["settled_at"] = now()
        write_json(self.path / "invoice.json", inv)
