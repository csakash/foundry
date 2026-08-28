"""Evidence ledger.

Every factual thing that reaches a rendered frame — a price series, a regulator
screenshot, a screen recording the user handed us — gets a row here. A VideoSpec
claim cites an evidence id; the compliance linter fails the build if the id does
not resolve. That is the whole mechanism that makes "real evidence" real rather
than decorative.

Layout:
    evidence/manifest.json      the ledger (append/update by id)
    evidence/files/<id>.<ext>   the payload, content-addressed by sha256
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE_DIR = ROOT / "evidence"
FILES_DIR = EVIDENCE_DIR / "files"
MANIFEST = EVIDENCE_DIR / "manifest.json"

# What a row is allowed to be. Anything else is a bug, not a new category.
KINDS = (
    "screenshot", "screen_recording", "video", "market_data", "document", "audio",
    # Figure kinds — a stated number with no file payload behind it. Added
    # 2026-08-28 for @mary.premarket, whose every piece renders exactly these
    # three claim types and which therefore failed the evidence lint on piece 01
    # (priors M2). Registered via put_figure(), not put().
    "company_guidance",   # a number the company itself stated (release / call)
    "analyst_estimate",   # a consensus or average estimate, with its publisher
    "market_close",       # a settled daily close or single-session move
)

# Which figure kinds put_figure() will accept.
FIGURE_KINDS = ("company_guidance", "analyst_estimate", "market_close")


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_manifest() -> dict[str, Any]:
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text())
    return {"version": 1, "updated_at": utcnow(), "entries": {}}


def save_manifest(m: dict[str, Any]) -> None:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    m["updated_at"] = utcnow()
    MANIFEST.write_text(json.dumps(m, indent=2, sort_keys=False) + "\n")


def put(
    entry_id: str,
    kind: str,
    *,
    file: str | Path | None = None,
    source_url: str | None = None,
    licence: str = "unknown",
    note: str = "",
    captured_at: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Register (or update) one evidence row. Returns the row."""
    if kind not in KINDS:
        raise ValueError(f"unknown evidence kind {kind!r}; expected one of {KINDS}")

    row: dict[str, Any] = {
        "id": entry_id,
        "kind": kind,
        "captured_at": captured_at or utcnow(),
        "source_url": source_url,
        "licence": licence,
        "note": note,
    }

    if file is not None:
        p = Path(file)
        if not p.exists():
            raise FileNotFoundError(p)
        row["file"] = str(p.relative_to(ROOT)) if p.is_absolute() and ROOT in p.parents else str(p)
        row["sha256"] = sha256_file(p)
        row["bytes"] = p.stat().st_size
        probe = probe_media(p)
        if probe:
            row["media"] = probe

    if extra:
        row.update(extra)

    m = load_manifest()
    m["entries"][entry_id] = row
    save_manifest(m)
    return row


def get(entry_id: str) -> dict[str, Any] | None:
    return load_manifest()["entries"].get(entry_id)


def resolve_all(ids: list[str]) -> tuple[list[str], list[str]]:
    """Split ids into (found, missing). The linter's core call."""
    entries = load_manifest()["entries"]
    found = [i for i in ids if i in entries]
    missing = [i for i in ids if i not in entries]
    return found, missing


def figure_digest(payload: dict[str, Any]) -> str:
    """Content-address a figure by its canonical claim, not by a file."""
    canon = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256_bytes(canon)


def put_figure(
    kind: str,
    *,
    ticker: str,
    metric: str,
    period: str,
    value: Any,
    unit: str,
    source_url: str,
    publisher: str,
    as_of: str,
    stated_by: str | None = None,
    corroborating_urls: list[str] | None = None,
    note: str = "",
) -> dict[str, Any]:
    """Register a figure claim — a number with a source but no file payload.

    market_data rows are pulled and cached, so they content-address by file.
    A guidance figure or a consensus estimate has no file: it is a number a
    named party stated on a named date. This addresses it by the canonical
    claim instead, so the same claim always resolves to the same id and a
    changed claim is a NEW id rather than a silent overwrite.

    Every argument up to `as_of` is required on purpose. A figure without a
    publisher and an as-of date is a rumour, and the linter exists to keep
    rumours off the frame.

        put_figure("analyst_estimate", ticker="NVDA",
                   metric="fy2028_revenue_growth", period="FY2028",
                   value=44, unit="percent",
                   source_url="https://...", publisher="CNBC",
                   as_of="2026-08-26")
    """
    if kind not in FIGURE_KINDS:
        raise ValueError(f"put_figure kind must be one of {FIGURE_KINDS}, got {kind!r}")
    for name, val in (("ticker", ticker), ("metric", metric), ("period", period),
                      ("unit", unit), ("source_url", source_url),
                      ("publisher", publisher), ("as_of", as_of)):
        if not val:
            raise ValueError(f"put_figure requires a non-empty {name}")
    if value is None:
        raise ValueError("put_figure requires a value")

    claim = {"kind": kind, "ticker": ticker.upper(), "metric": metric,
             "period": period, "value": value, "unit": unit, "as_of": as_of}
    digest = figure_digest(claim)
    entry_id = f"fig/{kind}/{ticker.upper()}/{metric}/{digest[:12]}"

    return put(
        entry_id, kind,
        source_url=source_url,
        licence="reported figure; attribute publisher",
        note=note,
        extra={
            "claim": claim,
            "value": value,
            "unit": unit,
            "publisher": publisher,
            "stated_by": stated_by,
            "as_of": as_of,
            "corroborating_urls": corroborating_urls or [],
            "sha256": digest,
        },
    )


def figures_for(ticker: str) -> dict[str, dict[str, Any]]:
    """Every registered figure row for one ticker, newest capture first."""
    entries = load_manifest()["entries"]
    rows = {k: v for k, v in entries.items()
            if v.get("kind") in FIGURE_KINDS
            and v.get("claim", {}).get("ticker") == ticker.upper()}
    return dict(sorted(rows.items(), key=lambda kv: kv[1].get("captured_at", ""), reverse=True))


def probe_media(path: str | Path) -> dict[str, Any] | None:
    """ffprobe wrapper — dimensions, duration, fps. Silent on non-media."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        if out.returncode != 0:
            return None
        data = json.loads(out.stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None

    v = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    if not v:
        return None

    info: dict[str, Any] = {
        "width": v.get("width"),
        "height": v.get("height"),
        "codec": v.get("codec_name"),
    }
    dur = data.get("format", {}).get("duration")
    if dur:
        info["duration_s"] = round(float(dur), 3)
    rate = v.get("avg_frame_rate") or ""
    if "/" in rate:
        num, den = rate.split("/")
        if den not in ("0", ""):
            fps = float(num) / float(den)
            if fps > 0:
                info["fps"] = round(fps, 3)
    if info.get("width") and info.get("height"):
        info["aspect"] = round(info["width"] / info["height"], 4)
        info["is_vertical_9x16"] = abs(info["aspect"] - 9 / 16) < 0.02
    return info
