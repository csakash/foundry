#!/usr/bin/env python3
"""Master review page — the human-readable face of a piece's artifacts.

JSON is the storage format, not the review format. Every gate in JOURNEY.md asks
a human a question ("right idea?", "right words?", "right look?"), and a human
cannot answer it from a wall of braces. This module reads every artifact a piece
has produced so far and renders ONE self-contained HTML page:

    work/<account>/<slug>/review.html

It is a derived view. Nothing is authored here — if a fact is not in an artifact,
it does not appear on the page. Re-run after any stage to refresh.

Robust to missing stages by design: the page is meant to be opened at Gate 1,
when only a brief exists, exactly as much as at Gate 4. Absent stages render as
explicit "not yet produced" states rather than being hidden, so the page always
shows what is still owed.

Usage:
    python3 engine/review.py work/@handle/slug
    python3 engine/review.py work/@handle/slug --open
"""
from __future__ import annotations

import base64
import json
import mimetypes
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

# Per-asset and whole-page embed ceilings. The page must stay portable (and
# publishable as an Artifact, which caps at 16MB), so oversized media degrades
# to a path reference rather than silently bloating or being dropped.
MAX_EMBED_BYTES = 4 * 1024 * 1024
MAX_TOTAL_EMBED = 12 * 1024 * 1024

# Provisional 9:16 plate geometry, as fractions of frame width/height.
# persona.json setups[*].plates overrides the `top` of any slot it names.
# These exist so the frame preview can be drawn BEFORE a board exists; the
# board stage re-measures against the real master still and wins.
SLOT_GEOMETRY: dict[str, dict[str, Any]] = {
    "brandChip":       {"x": 0.06, "y": 0.040, "w": 0.24, "align": "left",   "style": "brandmark"},
    "aiLabel":         {"x": 0.06, "y": 0.780, "w": 0.34, "align": "left",   "style": "label"},
    "labelLeftTop":    {"x": 0.06, "y": 0.090, "w": 0.40, "align": "left",   "style": "header"},
    "labelRightTop":   {"x": 0.54, "y": 0.090, "w": 0.40, "align": "left",   "style": "header"},
    "columnLeft.card1":{"x": 0.06, "y": 0.160, "w": 0.40, "align": "left",   "style": "card"},
    "columnRight.card1":{"x": 0.54,"y": 0.160, "w": 0.40, "align": "left",   "style": "card"},
    "centrePlate":     {"x": 0.14, "y": 0.150, "w": 0.72, "align": "center", "style": "hero"},
    "gapPlate":        {"x": 0.16, "y": 0.400, "w": 0.68, "align": "center", "style": "gap"},
    "stampLowerRight": {"x": 0.52, "y": 0.640, "w": 0.42, "align": "right",  "style": "stamp"},
    "wordmark":        {"x": 0.06, "y": 0.715, "w": 0.44, "align": "left",   "style": "wordmark"},
    "captionTop":      {"x": 0.10, "y": 0.600, "w": 0.80, "align": "center", "style": "caption"},
    "hookTop":         {"x": 0.08, "y": 0.100, "w": 0.84, "align": "left",   "style": "hero"},
    "subhookTop":      {"x": 0.08, "y": 0.660, "w": 0.84, "align": "left",   "style": "caption"},
}
DEFAULT_SLOT = {"x": 0.08, "y": 0.300, "w": 0.84, "align": "left", "style": "card"}

# 900x1400 universal safe zone inside 1080x1920, plus the bottom ~320px dead
# zone the platforms' own chrome occupies. Drawn as guides on the preview.
SAFE = {"x0": 90 / 1080, "x1": 990 / 1080, "y0": 100 / 1920, "y1": 1600 / 1920}
DEAD_BOTTOM = 1600 / 1920


# ---------------------------------------------------------------- loading

def read_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


class Budget:
    """Tracks total embedded bytes so one huge asset cannot blow the page."""

    def __init__(self, cap: int = MAX_TOTAL_EMBED) -> None:
        self.cap = cap
        self.used = 0

    def data_uri(self, path: Path) -> tuple[str | None, str]:
        """Return (data_uri | None, reason). None means: link, don't embed."""
        try:
            size = path.stat().st_size
        except OSError:
            return None, "missing"
        if size > MAX_EMBED_BYTES:
            return None, f"{size / 1e6:.1f}MB — over the {MAX_EMBED_BYTES / 1e6:.0f}MB per-asset embed cap"
        if self.used + size > self.cap:
            return None, f"{size / 1e6:.1f}MB — page embed budget exhausted"
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        try:
            blob = base64.b64encode(path.read_bytes()).decode()
        except OSError:
            return None, "unreadable"
        self.used += size
        return f"data:{mime};base64,{blob}", "embedded"


def collect(work_dir: Path) -> dict[str, Any]:
    """Assemble every artifact a piece has produced. Missing stages -> None."""
    wd = work_dir.resolve()
    budget = Budget()

    intake = read_json(wd / "00-intake.json")
    brief = read_json(wd / "01-brief.json")
    script = read_json(wd / "02-script.json")
    board = read_json(wd / "03-board" / "board.json")
    qc = read_json(wd / "06-qc.json")

    src = script or brief or intake or {}
    account_handle = src.get("account")
    persona_slug = src.get("persona") or (brief or {}).get("persona")

    account = charter = portfolio = priors = None
    if account_handle:
        adir = ROOT / "accounts" / account_handle
        account = read_json(adir / "account.json")
        charter = read_json(adir / "charter.json")
        portfolio = read_json(adir / "portfolio.json")
        priors = read_json(adir / "priors.json")

    persona = read_json(ROOT / "personas" / persona_slug / "persona.json") if persona_slug else None

    # --- plate geometry: persona setups override the provisional tops
    geometry = {k: dict(v) for k, v in SLOT_GEOMETRY.items()}
    setup_name = src.get("setup")
    geo_source = "provisional defaults (engine/review.py SLOT_GEOMETRY)"
    if persona and setup_name:
        setup = (persona.get("setups") or {}).get(setup_name) or {}
        for slot, top in (setup.get("plates") or {}).items():
            geometry.setdefault(slot, dict(DEFAULT_SLOT))
            geometry[slot]["y"] = top
            geometry[slot]["from_persona"] = True
        if setup.get("plates"):
            geo_source = f"persona setup '{setup_name}' for named slots, provisional for the rest"

    # --- storyboard keyframes
    keyframes: list[dict[str, Any]] = []
    board_dir = wd / "03-board"
    if board_dir.is_dir():
        for row in (board.get("beats") if isinstance(board, dict) else None) or []:
            kf = row.get("keyframe")
            item = {"beat": row.get("beat"), "t": row.get("t"), "status": row.get("status"),
                    "est_cost": row.get("est_cost"), "route": row.get("motion_route"),
                    "src": None, "note": None}
            if kf:
                p = (board_dir / kf) if not Path(kf).is_absolute() else Path(kf)
                if not p.exists():
                    p = ROOT / kf
                if p.exists():
                    uri, why = budget.data_uri(p)
                    item["src"], item["note"] = uri, (None if uri else f"{p.name} — {why}")
                else:
                    item["note"] = f"{kf} — file not found"
            keyframes.append(item)

    # --- audio + video assets
    media: list[dict[str, Any]] = []
    for sub, kinds in (("04-assets", (".mp3", ".wav", ".m4a", ".mp4", ".mov")),
                       ("05-cut", (".mp4", ".mov"))):
        d = wd / sub
        if not d.is_dir():
            continue
        for p in sorted(d.iterdir()):
            if p.suffix.lower() not in kinds:
                continue
            uri, why = budget.data_uri(p)
            media.append({
                "name": p.name, "dir": sub,
                "kind": "audio" if p.suffix.lower() in (".mp3", ".wav", ".m4a") else "video",
                "src": uri, "note": None if uri else why,
                "path": str(p.relative_to(ROOT)),
                "size_mb": round(p.stat().st_size / 1e6, 2),
            })

    # --- evidence resolution
    evidence: list[dict[str, Any]] = []
    manifest = (read_json(ROOT / "evidence" / "manifest.json") or {}).get("entries", {})
    for beat in (script or {}).get("beats", []) or []:
        for ev in beat.get("evidence", []) or []:
            row = dict(ev)
            row["beat"] = beat.get("beat")
            entry = manifest.get(ev.get("id")) if ev.get("id") else None
            row["resolved"] = entry is not None
            if entry:
                row["value"] = entry.get("value")
                row["unit"] = entry.get("unit")
                row["publisher"] = entry.get("publisher")
                row["as_of"] = entry.get("as_of")
                row["stated_by"] = entry.get("stated_by")
                row["source_url"] = entry.get("source_url")
                row["corroborating_urls"] = entry.get("corroborating_urls") or []
                row["entry_note"] = entry.get("note")
            evidence.append(row)

    # --- the reference template this piece was decomposed from
    template = None
    for inp in (intake or {}).get("inputs", []) or []:
        if inp.get("output") and isinstance(inp["output"], str) and inp["output"].startswith("templates/"):
            template = read_json(ROOT / inp["output"])
            if template:
                template["_path"] = inp["output"]
                # A decomposed reference may carry a shot-by-shot frame map with
                # thumbnails. Embed them so the page shows what the reference
                # actually does rather than asserting it in prose.
                for row in (template.get("format") or {}).get("frame_map", []) or []:
                    thumb = row.get("thumb")
                    if not thumb:
                        continue
                    tp = Path(thumb) if Path(thumb).is_absolute() else ROOT / thumb
                    uri, why = budget.data_uri(tp) if tp.exists() else (None, "file not found")
                    row["_thumb"] = uri
                    if not uri:
                        row["_thumb_note"] = f"{Path(thumb).name} — {why}"
            break

    return {
        "slug": src.get("slug") or wd.name,
        "work_dir": str(wd.relative_to(ROOT)) if ROOT in wd.parents else str(wd),
        "account_handle": account_handle,
        "persona_slug": persona_slug,
        "intake": intake, "brief": brief, "script": script, "board": board, "qc": qc,
        "account": account, "charter": charter, "portfolio": portfolio, "priors": priors,
        "persona": persona,
        "geometry": geometry, "geometry_source": geo_source,
        "safe": SAFE, "dead_bottom": DEAD_BOTTOM,
        "keyframes": keyframes, "media": media, "evidence": evidence, "template": template,
        "stages": {
            "intake": intake is not None, "brief": brief is not None,
            "script": script is not None, "board": board is not None,
            "assets": any(m["dir"] == "04-assets" for m in media),
            "cut": any(m["dir"] == "05-cut" for m in media),
            "qc": qc is not None,
        },
        "embed_used_mb": round(budget.used / 1e6, 2),
    }


# ---------------------------------------------------------------- rendering

# ---------------------------------------------------------------- plain language
#
# The page is read by a person deciding whether to make a video, not by an
# engineer reading a spec. Every raw key, status string and slot id that would
# otherwise leak onto the page gets a human label here. Anything genuinely
# technical still belongs on the page — it is the production contract — but it
# lives behind a "production detail" disclosure, never in the default view.

LINT_LABELS = {
    "word_band": "The script fits the runtime",
    "beat_timing": "The moments add up to exactly the runtime",
    "but_therefore_chain": "Every moment earns the next one",
    "five_slot_spec": "Every shot is fully described",
    "anti_subjective_language": "Shot descriptions say what the camera does, not how it feels",
    "subject_transitions_named": "Every change on screen is spelled out",
    "banned_phrases": "No banned phrases",
    "charter_never_list": "Nothing this account has promised never to do",
    "ftc_persona": "She never claims personal experience",
    "ai_label": "The AI-generated label is on screen throughout",
    "no_ai_label": "Nothing is burned into the frame — no AI label, watermark or corner mark",
    "disclaimer": "The disclaimer is in the caption",
    "delivery_cues": "Every line has real direction, not 'read naturally'",
    "evidence": "Every number on screen is sourced",
    "overall": "Overall",
}

SLOT_LABELS = {
    "brandChip": "the gm mark, top left",
    "aiLabel": "the AI-generated label",
    "labelLeftTop": "heading, left side",
    "labelRightTop": "heading, right side",
    "columnLeft.card1": "card on the left",
    "columnRight.card1": "card on the right",
    "centrePlate": "big card, centre",
    "gapPlate": "the gap line",
    "stampLowerRight": "the price stamp",
    "wordmark": "the brand sign-off",
    "captionTop": "caption",
    "hookTop": "hook text",
    "subhookTop": "second line of hook text",
}

VISUAL_SLOT_LABELS = {
    "Subject": "Who's in shot",
    "Motion": "What moves",
    "Scene": "Where, and what's laid over it",
    "Spatial": "How it's framed",
    "Camera": "Camera",
    "shot": "Framing",
}

GATE_QUESTIONS = {
    1: "Is this the right idea?",
    2: "Are these the right words?",
    3: "Is this the right look?",
    4: "Does the finished video match the plan?",
}


def humanize_slug(slug: str, tickers: set[str]) -> str:
    """Fallback page name for a piece whose brief has no plain `title`."""
    body = re.sub(r"^\d{4}-\d{2}-\d{2}-", "", slug)
    words = [w.upper() if w.upper() in tickers else w.capitalize()
             for w in body.replace("_", "-").split("-") if w]
    return " ".join(words) or slug


HTML = r"""<meta charset="utf-8">
<title>__TITLE__</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;700&family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&display=swap">
<style>
:root{
  --paper:#f2f4f3; --surface:#ffffff; --surface-2:#e9ecea; --line:#d3d9d5; --line-soft:#e3e7e4;
  --ink:#101a1c; --ink-2:#46534f; --ink-3:#75817c;
  --accent:#0f4f32; --accent-soft:#e2ede6; --accent-line:#a9c7b7;
  --signal:#a8641a; --signal-bg:#fbeeda; --signal-line:#e6c68f;
  --pass:#2f7d52; --pass-bg:#e4f0e8; --fail:#b64038; --fail-bg:#fae7e5; --warn:#9a6a10; --warn-bg:#faf0da;
  --frame-ink:#1b2422; --frame-paper:#cfd6d1;
  --sans:"Archivo",system-ui,-apple-system,"Segoe UI",sans-serif;
  --mono:"JetBrains Mono",ui-monospace,SFMono-Regular,Menlo,monospace;
  --serif:"Source Serif 4",Georgia,"Times New Roman",serif;
  --r:3px; --pad:clamp(16px,3.2vw,34px);
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --paper:#0d1414; --surface:#141d1d; --surface-2:#1b2625; --line:#2b3836; --line-soft:#212d2c;
  --ink:#e6ece9; --ink-2:#9daaa5; --ink-3:#6f7d78;
  --accent:#6cc294; --accent-soft:#16302a; --accent-line:#2f5748;
  --signal:#e0913a; --signal-bg:#33240f; --signal-line:#6d4c1b;
  --pass:#5fbd85; --pass-bg:#142c1f; --fail:#e0776c; --fail-bg:#331a18; --warn:#d7a445; --warn-bg:#2f2612;
  --frame-ink:#e6ece9; --frame-paper:#242e2c;
}}
:root[data-theme="dark"]{
  --paper:#0d1414; --surface:#141d1d; --surface-2:#1b2625; --line:#2b3836; --line-soft:#212d2c;
  --ink:#e6ece9; --ink-2:#9daaa5; --ink-3:#6f7d78;
  --accent:#6cc294; --accent-soft:#16302a; --accent-line:#2f5748;
  --signal:#e0913a; --signal-bg:#33240f; --signal-line:#6d4c1b;
  --pass:#5fbd85; --pass-bg:#142c1f; --fail:#e0776c; --fail-bg:#331a18; --warn:#d7a445; --warn-bg:#2f2612;
  --frame-ink:#e6ece9; --frame-paper:#242e2c;
}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font-family:var(--sans);font-size:16px;
  line-height:1.55;-webkit-font-smoothing:antialiased}
a{color:var(--accent)} a:focus-visible,button:focus-visible,input:focus-visible,summary:focus-visible{outline:2px solid var(--signal);outline-offset:2px}
h1,h2{margin:0;text-wrap:balance;font-weight:600}
.wrap{max-width:1120px;margin:0 auto;padding:0 var(--pad) 96px}

.mast{padding:44px 0 0}
.mast h1{font-size:clamp(30px,5vw,52px);letter-spacing:-.025em;line-height:1.05}
.kicker{font-size:14px;color:var(--ink-2);margin:12px 0 0}
.story{font-family:var(--serif);font-size:clamp(18px,2.1vw,21px);line-height:1.6;max-width:64ch;margin:26px 0 0;color:var(--ink)}
.strip{display:flex;flex-wrap:wrap;gap:8px;margin:26px 0 0}
.chip{font-size:13px;padding:5px 12px;border:1px solid var(--line);border-radius:999px;color:var(--ink-2);background:var(--surface)}
.chip b{font-weight:600;color:var(--ink);font-variant-numeric:tabular-nums}

section{margin:58px 0 0}
.shead{border-bottom:1px solid var(--line);padding-bottom:9px;margin-bottom:22px;display:flex;align-items:baseline;gap:14px;flex-wrap:wrap}
.shead h2{font-size:21px;letter-spacing:-.015em}
.shead .meta{margin-left:auto;font-size:13px;color:var(--ink-3)}
.lede{font-family:var(--serif);font-size:17px;line-height:1.6;max-width:66ch;color:var(--ink-2);margin:0 0 20px}
.small{font-size:13px;color:var(--ink-3);line-height:1.6}

.stand{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:1px;background:var(--line-soft);border:1px solid var(--line-soft)}
.stand>div{background:var(--surface);padding:15px 17px}
.stand .q{font-size:15px;font-weight:500;margin-bottom:9px}
.stand .why{font-size:13px;color:var(--ink-2);line-height:1.55;margin-top:9px}
.pill{display:inline-block;font-size:12px;font-weight:500;padding:3px 10px;border-radius:999px;border:1px solid}
.p-pass{color:var(--pass);background:var(--pass-bg);border-color:var(--pass)}
.p-fail{color:var(--fail);background:var(--fail-bg);border-color:var(--fail)}
.p-warn{color:var(--warn);background:var(--warn-bg);border-color:var(--warn)}
.p-idle{color:var(--ink-3);background:var(--surface-2);border-color:var(--line)}

.deck{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:26px;align-items:start}
@media(max-width:900px){.deck{grid-template-columns:1fr}}
.transport{display:flex;align-items:center;gap:12px;margin-bottom:14px;flex-wrap:wrap}
.tbtn{font-size:14px;font-weight:500;padding:8px 18px;border:1px solid var(--line);background:var(--surface);
  color:var(--ink);border-radius:999px;cursor:pointer}
.tbtn:hover{border-color:var(--accent);color:var(--accent)}
.tbtn[aria-pressed="true"]{background:var(--accent);color:var(--paper);border-color:var(--accent)}
.tc{font-family:var(--mono);font-size:19px;font-weight:700;color:var(--signal);font-variant-numeric:tabular-nums;
  padding:2px 10px;background:var(--signal-bg);border:1px solid var(--signal-line);border-radius:var(--r)}
.scrub{flex:1;min-width:150px;accent-color:var(--signal)}
.tl{border:1px solid var(--line);background:var(--surface);position:relative;overflow:hidden}
.ruler{height:22px;border-bottom:1px solid var(--line);position:relative;background:var(--surface-2)}
.tick{position:absolute;top:0;bottom:0;border-left:1px solid var(--line)}
.tick span{position:absolute;left:4px;top:4px;font-family:var(--mono);font-size:9.5px;color:var(--ink-3)}
.lane{display:grid;grid-template-columns:150px 1fr;border-bottom:1px solid var(--line-soft);min-height:27px}
.lane:last-child{border-bottom:0}
.lane .ln{font-size:11.5px;color:var(--ink-3);padding:6px 9px;border-right:1px solid var(--line-soft);
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.track{position:relative;padding:3px 0}
.blk{position:absolute;top:3px;bottom:3px;border-radius:2px;font-size:11px;padding:2px 7px;overflow:hidden;
  white-space:nowrap;text-overflow:ellipsis;line-height:1.6;cursor:pointer}
.blk.clip{background:var(--surface-2);border:1px solid var(--line);color:var(--ink-2)}
.blk.beat{background:var(--accent-soft);border:1px solid var(--accent-line);color:var(--accent);font-weight:500}
.blk.plate{background:var(--signal-bg);border:1px solid var(--signal-line);color:var(--signal)}
.blk.sil{background:repeating-linear-gradient(45deg,transparent,transparent 4px,var(--line) 4px,var(--line) 5px);
  border:1px solid var(--line);color:var(--ink-3)}
.play{position:absolute;top:0;bottom:0;width:2px;background:var(--signal);pointer-events:none;z-index:5}
.playhead-wrap{position:absolute;left:150px;right:0;top:0;bottom:0;pointer-events:none}

.frame{position:relative;width:100%;aspect-ratio:9/16;background:var(--frame-paper);border:1px solid var(--line);overflow:hidden}
.frame .zone{position:absolute;border:1px dashed color-mix(in srgb,var(--ink-3) 45%,transparent);pointer-events:none}
.frame .dead{position:absolute;left:0;right:0;bottom:0;background:color-mix(in srgb,var(--fail) 8%,transparent);
  border-top:1px dashed color-mix(in srgb,var(--fail) 55%,transparent);pointer-events:none}
.frame .dead b{position:absolute;bottom:3px;left:5px;font-size:7.5px;font-weight:400;color:var(--fail)}
.frame .persona{position:absolute;left:50%;bottom:0;transform-origin:50% 100%;width:56%;height:52%;
  border-radius:44% 44% 0 0;background:color-mix(in srgb,var(--ink-3) 22%,transparent);
  display:flex;align-items:flex-end;justify-content:center;padding-bottom:7px}
.frame .persona span{font-size:8px;color:var(--ink-3)}
.pl{position:absolute;white-space:pre-line;line-height:1.24;border-radius:2px}
.pl.card{background:var(--frame-ink);color:var(--frame-paper);font-family:var(--mono);font-size:8px;padding:4px 5px;font-weight:500}
.pl.header{background:transparent;color:var(--frame-ink);font-size:9px;font-weight:700}
.pl.hero{background:transparent;color:var(--frame-ink);font-size:12px;font-weight:700;text-align:center;letter-spacing:-.02em}
.pl.gap{background:var(--signal);color:#fff;font-size:8.5px;font-weight:700;padding:3px 6px;text-align:center}
.pl.stamp{background:var(--frame-ink);color:var(--frame-paper);font-family:var(--mono);font-size:7.5px;padding:3px 5px;text-align:right}
.pl.brandmark{background:transparent;color:var(--frame-ink);font-size:9px;font-weight:700}
.pl.label{background:color-mix(in srgb,var(--frame-ink) 62%,transparent);color:var(--frame-paper);font-size:6.5px;padding:2px 4px}
.pl.wordmark{background:transparent;color:var(--frame-ink);font-size:11px;font-weight:700;letter-spacing:-.02em}
.pl.caption{background:transparent;color:var(--frame-ink);font-size:10px;font-weight:600;text-align:center}
.readout{border:1px solid var(--line);border-top:0;background:var(--surface);padding:14px}
.readout .seeing{font-size:13.5px;color:var(--ink-2);line-height:1.55;min-height:4.3em}
.readout .vo{font-family:var(--serif);font-size:16px;line-height:1.45;margin-top:11px;padding-top:10px;
  border-top:1px solid var(--line-soft);min-height:2.9em}
.readout .cue{font-size:12.5px;color:var(--ink-3);margin-top:9px}

table{width:100%;border-collapse:collapse;font-size:14.5px}
.scroll{overflow-x:auto;border:1px solid var(--line-soft)}
th{font-size:12px;color:var(--ink-3);text-align:left;padding:10px 14px;background:var(--surface-2);
  border-bottom:1px solid var(--line);font-weight:500;white-space:nowrap}
td{padding:14px;border-bottom:1px solid var(--line-soft);vertical-align:top;background:var(--surface)}
tr:last-child td{border-bottom:0}
td.t{font-family:var(--mono);font-size:12px;color:var(--signal);white-space:nowrap;font-variant-numeric:tabular-nums}
td.num{font-family:var(--mono);font-variant-numeric:tabular-nums;white-space:nowrap;font-size:14px}
.said{font-family:var(--serif);font-size:16px;line-height:1.45}
details{margin-top:11px}
summary{font-size:12.5px;color:var(--ink-3);cursor:pointer;list-style:none;display:inline-flex;align-items:center;gap:5px}
summary::-webkit-details-marker{display:none}
summary::before{content:"▸";font-size:10px}
details[open] summary::before{content:"▾"}
summary:hover{color:var(--accent)}
.detail{margin-top:9px;padding:11px 13px;background:var(--surface-2);border-radius:var(--r);font-size:12.5px;line-height:1.6}
.detail p{margin:0 0 7px} .detail p:last-child{margin:0}
.detail b{color:var(--ink-3);font-weight:500}

.grid{display:grid;gap:16px}
.g3{grid-template-columns:repeat(auto-fill,minmax(190px,1fr))}
.card{border:1px solid var(--line-soft);background:var(--surface);padding:16px 18px}
.card h3{margin:0 0 8px;font-size:15px;font-weight:600}
.kf{border:1px solid var(--line);background:var(--surface)}
.kf img{display:block;width:100%;aspect-ratio:9/16;object-fit:cover;background:var(--surface-2)}
.kf .empty{display:flex;align-items:center;justify-content:center;aspect-ratio:9/16;background:var(--surface-2);
  font-size:12px;color:var(--ink-3);text-align:center;padding:14px;line-height:1.55}
.kf .cap{padding:10px 12px;font-size:12px;color:var(--ink-2);display:flex;justify-content:space-between;gap:8px;
  border-top:1px solid var(--line-soft)}
.checks{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:1px;background:var(--line-soft);border:1px solid var(--line-soft)}
.checks .row{background:var(--surface);padding:12px 14px;display:flex;gap:11px;align-items:flex-start}
.dot{width:8px;height:8px;border-radius:50%;flex:0 0 auto;margin-top:6px}
.d-pass{background:var(--pass)} .d-fail{background:var(--fail)} .d-warn{background:var(--warn)}
.checks .nm{font-size:14px}
.checks .dt{font-size:12.5px;color:var(--ink-3);margin-top:3px;line-height:1.5}
ul.plain{margin:0;padding-left:20px;line-height:1.75}
ul.plain li{margin-bottom:6px}
blockquote{margin:0;padding:16px 20px;border-left:3px solid var(--signal);background:var(--signal-bg);
  font-family:var(--serif);font-size:17px;line-height:1.55}
.owed{border:1px solid var(--signal-line);background:var(--signal-bg);padding:18px 20px}
.copy{position:relative}
.copybtn{position:absolute;top:12px;right:12px;font-size:12px;padding:6px 13px;border:1px solid var(--line);
  background:var(--surface);color:var(--ink-2);border-radius:999px;cursor:pointer}
.copybtn:hover{border-color:var(--accent);color:var(--accent)}
pre{font-family:var(--serif);font-size:15.5px;line-height:1.6;white-space:pre-wrap;margin:0;color:var(--ink)}
footer{margin-top:70px;padding-top:18px;border-top:1px solid var(--line);font-size:12.5px;color:var(--ink-3);line-height:1.75}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
</style>

<div class="wrap">
  <header class="mast">
    <h1 id="title"></h1>
    <p class="kicker" id="kicker"></p>
    <p class="story" id="story"></p>
    <div class="strip" id="strip"></div>
  </header>
  <main id="main"></main>
  <footer id="footer"></footer>
</div>

<script>
const P = __PIECE__;
const L = __LABELS__;

const el=(t,c,x)=>{const n=document.createElement(t);if(c)n.className=c;if(x!=null)n.textContent=x;return n;};
const tc=s=>Math.max(0,s).toFixed(2).padStart(5,"0")+"s";
const S=P.script||{}, B=P.brief||{}, BEATS=S.beats||[];
const DUR=S.duration_s||(BEATS.length?BEATS[BEATS.length-1].t[1]:0);
const slotName=s=>L.slots[s]||s;

/* A raw status string is never shown. It is mapped to a state and a plain phrase. */
function state(v){const s=String(v||"").toUpperCase();
  if(s.includes("FAIL")||s.includes("BLOCK")||s.includes("REJECT"))return"fail";
  if(s.includes("AWAIT")||s.includes("OPEN")||s.includes("PENDING")||s.includes("NOT REACHED"))return"warn";
  if(s.includes("PASS")||s.includes("APPROVED")||s.includes("RESOLVED"))return"pass";
  return"idle";}
function phrase(v){const s=String(v||"").toUpperCase();
  if(!v)return"Not there yet";
  if(s.includes("BLOCK"))return"Blocked";
  if(s.includes("FAIL")||s.includes("REJECT"))return"Rejected";
  if(s.includes("AWAIT"))return"Waiting on you";
  if(s.includes("APPROVED"))return"Approved";
  if(s.includes("RESOLVED"))return"Sorted";
  if(s.includes("PASS"))return"Fine";
  return"Not there yet";}
function cueSentence(c){if(!c)return"";
  const bits=[];
  if(c.pace||c.energy)bits.push([c.pace,c.energy].filter(Boolean).join(", "));
  if(c.emphasis&&c.emphasis.length)bits.push("leaning on "+c.emphasis.map(w=>"“"+w+"”").join(" and "));
  if(c.internal_pause)bits.push("with a "+c.internal_pause.seconds+" second silence in the middle");
  else if(c.pause_after)bits.push("then a "+c.pause_after+" second beat of nothing");
  if(!bits.length)return"";
  return bits.join(", ").replace(/^./,m=>m.toUpperCase())+".";}
function section(title,meta,lede){const s=el("section");
  const h=el("div","shead");h.append(el("h2",null,title));
  if(meta)h.append(el("div","meta",meta));
  s.append(h);if(lede)s.append(el("p","lede",lede));return s;}

/* ---------- masthead ---------- */
document.getElementById("title").textContent=P.page_title;
document.getElementById("kicker").textContent=
  [P.persona_slug?P.persona_slug.charAt(0).toUpperCase()+P.persona_slug.slice(1):null,
   DUR?DUR.toFixed(0)+" seconds":null,
   (P.account&&P.account.platforms)?P.account.platforms.map(x=>L.platforms[x]||x).join(", "):null
  ].filter(Boolean).join("   ·   ");
document.getElementById("story").textContent=B.story||B.one_idea||"No brief written yet — this piece is still at intake.";
const strip=document.getElementById("strip");
[[BEATS.length,"moments"],[(S.clips||[]).length,"pieces of footage"],
 [S.word_budget?S.word_budget.actual_words:null,"words she says"],
 [B.cost_ceiling_inr?"₹"+B.cost_ceiling_inr.total_ceiling:null,"to make, at most"]
].forEach(([v,lab])=>{if(!v)return;const c=el("span","chip");
  c.append(el("b",null,String(v)),document.createTextNode(" "+lab));strip.append(c);});

const M=document.getElementById("main");

/* ---------- where it stands ---------- */
{
  const s=section("Where it stands",null,
    "Four moments where a person decides. Nothing expensive happens until the first three say yes.");
  const g=el("div","stand");
  [[1,B.gate],[2,S.gate],[3,P.board&&P.board.gate],[4,P.qc&&P.qc.gate]].forEach(([n,gt])=>{
    const d=el("div");
    d.append(el("div","q",L.gates[n]));
    d.append(el("span","pill p-"+(gt?state(gt.status):"idle"),gt?phrase(gt.status):"Not there yet"));
    if(gt&&gt.amendment)d.append(el("div","why",gt.amendment));
    g.append(d);});
  s.append(g);M.append(s);}

/* ---------- watch it ---------- */
if(BEATS.length){
  const s=section("Watch it",DUR.toFixed(0)+" seconds",
    "Press play. This is the real timing of everything that appears on screen — you can see the whole video's rhythm before a single frame is generated. The grey shape is where she stands.");
  const deck=el("div","deck");
  const tr=el("div","transport");
  const btn=el("button","tbtn");btn.textContent="▶  Play";btn.setAttribute("aria-pressed","false");
  const tcv=el("div","tc","00.00s");
  const range=el("input","scrub");range.type="range";range.min=0;range.max=DUR;range.step=0.01;range.value=0;
  range.setAttribute("aria-label","Scrub through the video");
  tr.append(btn,tcv,range);

  const tl=el("div","tl");
  const ruler=el("div","ruler");
  for(let t=0;t<=DUR+0.001;t+=(DUR<=20?1:5)){const k=el("div","tick");k.style.left=(t/DUR*100)+"%";
    k.append(el("span",null,t.toFixed(0)+"s"));ruler.append(k);}
  tl.append(ruler);
  const lanes=el("div");tl.append(lanes);
  function lane(name,items,cls){const Ln=el("div","lane");Ln.append(el("div","ln",name));
    const tk=el("div","track");
    items.forEach(it=>{const b=el("div","blk "+(it.cls||cls));
      b.style.left=(it.t[0]/DUR*100)+"%";
      b.style.width=(Math.max(it.t[1]-it.t[0],0.05)/DUR*100)+"%";
      b.textContent=it.label;b.title=it.title||it.label;
      b.onclick=()=>{stop();seek(it.t[0]+0.01);};tk.append(b);});
    Ln.append(tk);lanes.append(Ln);}

  lane("camera takes",(S.clips||[]).map(c=>({t:c.t,label:"take "+c.clip,title:c.note||""})),"clip");
  const moves=BEATS.filter(b=>b.shot&&b.shot.move&&b.shot.move!=="still"&&b.shot.move.indexOf("still")!==0)
    .map(b=>({t:b.t,label:"camera "+b.shot.move,title:b.shot.size}));
  if(moves.length)lane("camera moves",moves,"beat");
  lane("moments",BEATS.map(b=>({t:b.t,label:b.beat+". "+(b.name||"").split(" — ")[0],title:b.plain||""})),"beat");
  const slots=[],bySlot={};
  BEATS.forEach(b=>(b.plates||[]).forEach(p=>{
    if(!bySlot[p.slot]){bySlot[p.slot]=[];slots.push(p.slot);}
    bySlot[p.slot].push({t:p.t,label:(p.text||"").replace(/\n/g," / "),
      title:slotName(p.slot)+", on screen "+tc(p.t[0])+" to "+tc(p.t[1])});}));
  slots.forEach(sl=>lane(slotName(sl),bySlot[sl],"plate"));
  const sil=[];BEATS.forEach(b=>{const c=b.delivery_cue||{};
    if(c.internal_pause)sil.push({t:[b.t[1]-c.internal_pause.seconds,b.t[1]],
      label:c.internal_pause.seconds+"s of silence",title:c.internal_pause.why||""});});
  if(sil.length)lane("silence",sil,"sil");
  const ph=el("div","playhead-wrap");const head=el("div","play");ph.append(head);tl.append(ph);

  const left=el("div");left.append(tr,tl);
  const right=el("div");
  const frame=el("div","frame");
  const sz=el("div","zone");const SF=P.safe;
  sz.style.cssText="left:"+SF.x0*100+"%;top:"+SF.y0*100+"%;width:"+(SF.x1-SF.x0)*100+"%;height:"+(SF.y1-SF.y0)*100+"%";
  const dz=el("div","dead");dz.style.height=((1-P.dead_bottom)*100)+"%";
  dz.append(el("b",null,"covered by Instagram's own buttons"));
  const per=el("div","persona");per.append(el("span",null,(P.persona_slug||"she")+" stands here"));
  frame.append(per,sz,dz);
  const readout=el("div","readout");
  const seeing=el("div","seeing");const vo=el("div","vo");const cue=el("div","cue");const cam=el("div","cue");
  readout.append(seeing,vo,cue,cam);
  right.append(frame,readout);
  right.append(el("p","small","The dashed box is the area every platform shows. Positions here are a first guess — they get measured properly against the real photograph at the next stage."));
  deck.append(left,right);s.append(deck);M.append(s);

  let T=0,playing=false,raf=null,last=0;
  function draw(){
    tcv.textContent=tc(T);range.value=T;head.style.left=(T/DUR*100)+"%";
    frame.querySelectorAll(".pl").forEach(n=>n.remove());
    BEATS.forEach(b=>(b.plates||[]).forEach(p=>{
      if(T<p.t[0]||T>=p.t[1])return;
      const g=P.geometry[p.slot]||{x:.08,y:.3,w:.84,align:"left",style:"card"};
      const n=el("div","pl "+(g.style||"card"),p.text||"");
      n.style.cssText="left:"+g.x*100+"%;top:"+g.y*100+"%;width:"+g.w*100+"%;text-align:"+(g.align||"left");
      frame.append(n);}));
    const b=BEATS.find(x=>T>=x.t[0]&&T<x.t[1]);
    if(b){seeing.textContent=b.plain||b.name||"";
      vo.textContent=(b.audio&&b.audio.vo)?"“"+b.audio.vo+"”":"[she isn't speaking here]";
      cue.textContent=cueSentence(b.delivery_cue);
      const sh=b.shot;
      if(sh){
        /* Interpolate the framing across the beat so the camera move is something
           you watch rather than something you read about. */
        const from=sh.scale_from!=null?sh.scale_from:1, to=sh.scale_to!=null?sh.scale_to:from;
        const start=sh.starts_at!=null?sh.starts_at:b.t[0];
        const end=sh.settles_at!=null?sh.settles_at:b.t[1];
        let k=end>start?(T-start)/(end-start):1;
        k=Math.min(Math.max(k,0),1);
        if(sh.ease==="decelerate")k=1-Math.pow(1-k,3);
        per.style.transform="translateX(-50%) scale("+(from+(to-from)*k).toFixed(3)+")";
        cam.textContent="Camera: "+sh.size+", "+sh.move+".";
      }else{per.style.transform="translateX(-50%)";cam.textContent="";}}
    else{seeing.textContent="";vo.textContent="";cue.textContent="";cam.textContent="";}}
  function seek(t){T=Math.min(Math.max(t,0),DUR);draw();}
  function tick(ts){if(!playing)return;if(!last)last=ts;T+=(ts-last)/1000;last=ts;
    if(T>=DUR){T=DUR;stop();draw();return;}draw();raf=requestAnimationFrame(tick);}
  function play(){if(T>=DUR)T=0;playing=true;last=0;btn.textContent="❚❚  Pause";
    btn.setAttribute("aria-pressed","true");raf=requestAnimationFrame(tick);}
  function stop(){playing=false;if(raf)cancelAnimationFrame(raf);btn.textContent="▶  Play";
    btn.setAttribute("aria-pressed","false");}
  btn.onclick=()=>playing?stop():play();
  range.oninput=()=>{stop();seek(parseFloat(range.value));};
  document.addEventListener("keydown",e=>{if(e.target.tagName==="INPUT")return;
    if(e.code==="Space"){e.preventDefault();playing?stop():play();}
    if(e.code==="ArrowRight"){e.preventDefault();stop();seek(T+(e.shiftKey?1:0.1));}
    if(e.code==="ArrowLeft"){e.preventDefault();stop();seek(T-(e.shiftKey?1:0.1));}});
  draw();}

/* ---------- moment by moment ---------- */
if(BEATS.length){
  const s=section("Moment by moment",null,
    "What a viewer sees and hears, in order. The production detail under each row is what the camera and the voice actually get told to do.");
  const sc=el("div","scroll");const t=el("table");
  t.innerHTML="<thead><tr><th>when</th><th style='width:42%'>what you see</th><th style='width:30%'>what she says</th><th>how she says it</th></tr></thead>";
  const tb=el("tbody");
  BEATS.forEach(b=>{const r=el("tr");
    r.append(el("td","t",tc(b.t[0])));
    const see=el("td");
    see.append(el("div",null,b.plain||b.name||""));
    if(b.plates&&b.plates.length){
      const words=b.plates.filter(p=>p.slot!=="aiLabel").map(p=>"“"+(p.text||"").replace(/\n/g," ")+"” "+"("+slotName(p.slot)+")");
      if(words.length)see.append(el("div","small","On screen: "+words.join("; ")));}
    const d=el("details");d.append(el("summary",null,"production detail"));
    const dd=el("div","detail");
    Object.entries(b.visual||{}).forEach(([k,v])=>{const p=el("p");
      p.append(el("b",null,(L.visual[k]||k)+": "),document.createTextNode(v));dd.append(p);});
    d.append(dd);see.append(d);r.append(see);
    const a=el("td");a.append(el("div","said",(b.audio&&b.audio.vo)?"“"+b.audio.vo+"”":"—"));
    if(b.audio&&b.audio.music)a.append(el("div","small",b.audio.music));
    r.append(a);
    r.append(el("td","small",cueSentence(b.delivery_cue)||"—"));
    tb.append(r);});
  t.append(tb);sc.append(t);s.append(sc);
  if(S.performance_plan&&S.performance_plan.performance_intent)
    s.append(el("blockquote",null,S.performance_plan.performance_intent));
  M.append(s);}

/* ---------- how it looks ---------- */
{
  const has=P.keyframes.length>0;
  const s=section("How it looks",has?P.keyframes.length+" frames":null,
    has?"One picture per moment, approved before anything moves."
       :"Nobody has drawn this yet. Each moment becomes a still photograph first — a still costs a rupee or two, a moving clip costs a hundred or more, so the picture is where you change your mind.");
  if(has){const g=el("div","grid g3");
    P.keyframes.forEach(k=>{const c=el("div","kf");
      if(k.src){const i=el("img");i.src=k.src;i.alt="Frame for moment "+k.beat;c.append(i);}
      else c.append(el("div","empty",k.note||"no picture yet"));
      const cap=el("div","cap");cap.append(el("span",null,"moment "+k.beat),
        el("span",null,(k.status||"draft")+(k.est_cost?" · ₹"+k.est_cost:"")));
      c.append(cap);g.append(c);});
    s.append(g);}
  else{const o=el("div","owed");o.append(el("div",null,"Pictures still needed, one per moment:"));
    const u=el("ul","plain");BEATS.forEach(b=>u.append(el("li",null,(b.name||"").split(" — ")[0]+" — "+(b.plain||""))));
    o.append(u);s.append(o);}
  M.append(s);}

/* ---------- voice and video ---------- */
{
  const s=section("Voice and video",null,
    P.media.length?null:"No voice recorded and no footage generated. Her voice is never made before the words are signed off — once audio exists, changing a single word breaks the subtitles, the music timing and the lip sync.");
  if(P.media.length){const g=el("div","grid");
    P.media.forEach(m=>{const c=el("div","card");
      c.append(el("h3",null,m.kind==="audio"?"Her voice":"The video"),el("div","small",m.name+" · "+m.size_mb+"MB"));
      if(m.src){const pl=document.createElement(m.kind==="audio"?"audio":"video");
        pl.controls=true;pl.src=m.src;pl.style.width="100%";pl.style.marginTop="10px";
        if(m.kind==="video")pl.style.maxHeight="420px";c.append(pl);}
      else c.append(el("div","small","Too large to embed — open it at "+m.path));
      g.append(c);});
    s.append(g);}
  M.append(s);}

/* ---------- where the numbers come from ---------- */
if(P.evidence.length){
  const ok=P.evidence.filter(e=>e.resolved).length;
  const s=section("Where the numbers come from",ok+" of "+P.evidence.length+" checked",
    "Every figure that appears on screen has to trace back to somewhere a person can go and read. If one doesn't, the video can't be built.");
  const sc=el("div","scroll");const t=el("table");
  t.innerHTML="<thead><tr><th>the claim</th><th>the number</th><th>who reported it</th><th></th></tr></thead>";
  const tb=el("tbody");
  P.evidence.forEach(e=>{const r=el("tr");
    const c=el("td");c.append(el("div",null,e.claim||"—"));
    if(e.needs)c.append(el("div","small","Still needs: "+e.needs));
    if(e.stated_by)c.append(el("div","small","Said by "+e.stated_by));
    r.append(c);
    r.append(el("td","num",e.value!==undefined?(Array.isArray(e.value)?e.value.join("–"):e.value)+" "+(e.unit||"").replace(/_/g," "):"—"));
    const src=el("td");
    if(e.source_url){const a=el("a",null,e.publisher||"read it");a.href=e.source_url;a.target="_blank";a.rel="noopener";src.append(a);}
    else src.append(document.createTextNode("nobody yet"));
    if(e.as_of)src.append(el("div","small",e.as_of));
    if(e.corroborating_urls&&e.corroborating_urls.length)
      src.append(el("div","small",e.corroborating_urls.length+" other outlets said the same"));
    r.append(src);
    const st=el("td");st.append(el("span","pill p-"+(e.resolved?"pass":(e.status==="DERIVED"?"warn":"fail")),
      e.resolved?"checked":(e.status==="DERIVED"?"works out from the two above":"not sourced")));
    r.append(st);tb.append(r);});
  t.append(tb);sc.append(t);s.append(sc);M.append(s);}

/* ---------- checks ---------- */
if(S.lint){const fails=Object.values(S.lint).filter(v=>state(v)==="fail").length;
  const s=section("Checks we ran",fails?fails+" failing":"all clear",
    "Automatic checks that run before a person is ever asked to look.");
  const g=el("div","checks");
  Object.entries(S.lint).forEach(([k,v])=>{if(k==="overall")return;
    const r=el("div","row");const st=state(v);
    r.append(el("div","dot d-"+(st==="idle"?"warn":st)));
    const b2=el("div");b2.append(el("div","nm",L.lint[k]||k.replace(/_/g," ")));
    const detail=String(v).replace(/\*\*/g,"").replace(/^(PASS|FAIL)\s*—\s*/,"");
    if(detail&&detail!=="PASS")b2.append(el("div","dt",detail));
    r.append(b2);g.append(r);});
  s.append(g);M.append(s);}

/* ---------- what we can't say ---------- */
if(B.compliance||P.charter){
  const s=section("What we can't say",null,
    "Rules this piece is built around. Some are law, some are promises this account has made to its audience.");
  const g=el("div","grid");g.style.gridTemplateColumns="repeat(auto-fit,minmax(300px,1fr))";
  const a=el("div","card");a.append(el("h3",null,"Rules for this video"));
  const u1=el("ul","plain");((B.compliance||{}).authored_restrictions||[]).forEach(x=>u1.append(el("li",null,x)));
  a.append(u1);
  const b3=el("div","card");b3.append(el("h3",null,"Things this account never does"));
  const u2=el("ul","plain");((P.charter||{}).never_list||[]).forEach(x=>u2.append(el("li",null,x.split(". AMENDED")[0])));
  b3.append(u2);g.append(a,b3);s.append(g);
  Object.entries(B.compliance||{}).forEach(([k,v])=>{if(!k.startsWith("OPEN_RISK"))return;
    const c=el("div","card");c.style.marginTop="16px";
    c.append(el("h3",null,v.problem?"A risk we spotted":"A risk, now handled"));
    c.append(el("span","pill p-"+state(v.status),phrase(v.status)));
    if(v.problem)c.append(el("p",null,v.problem));
    if(v.resolution)c.append(el("p",null,v.resolution));
    if(v.india_safe_variant)c.append(el("div","small","To make it safe for India: "+v.india_safe_variant));
    s.append(c);});
  M.append(s);}

/* ---------- why the numbers changed ---------- */
if(B.sourcing_correction){const sc2=B.sourcing_correction;
  const s=section("Why the numbers changed",null,
    "The figures this piece started from turned out to be wrong. Here is what changed and why.");
  s.append(el("blockquote",null,sc2.consequence||""));
  const g=el("div","grid");g.style.cssText="grid-template-columns:repeat(auto-fit,minmax(300px,1fr));margin-top:18px";
  const a=el("div","card");a.append(el("h3",null,"What we were told"),el("p",null,sc2.what_the_supplied_copy_said||"—"));
  const b4=el("div","card");b4.append(el("h3",null,"What turned out to be true"));
  const u=el("ul","plain");Object.values(sc2.what_the_sources_say||{}).forEach(v=>u.append(el("li",null,String(v))));
  b4.append(u);g.append(a,b4);s.append(g);
  if(sc2.lesson_for_the_account)s.append(el("blockquote",null,sc2.lesson_for_the_account));
  M.append(s);}

/* ---------- the reference ---------- */
if(P.template){const T2=P.template,F=T2.format||{},pv=T2.provenance||{},mt=pv.metrics||{};
  const s=section("The video this one learned from",null,
    "We copied how it is built, never what it says.");
  const g=el("div","grid");g.style.gridTemplateColumns="repeat(auto-fit,minmax(300px,1fr))";
  const a=el("div","card");a.append(el("h3",null,"@"+(pv.owner||"?")));
  a.append(el("div","small",[mt.videoPlayCount?mt.videoPlayCount.toLocaleString()+" views":null,
    mt.commentsCount?mt.commentsCount.toLocaleString()+" comments":null,
    mt.videoDuration?Math.round(mt.videoDuration)+" seconds long":null].filter(Boolean).join("  ·  ")));
  if(F.structural_thesis)a.append(el("p",null,F.structural_thesis));
  if(pv.source_url){const w=el("p");const lk=el("a",null,"Watch it");lk.href=pv.source_url;lk.target="_blank";lk.rel="noopener";w.append(lk);a.append(w);}
  const b5=el("div","card");b5.append(el("h3",null,"What we took"));
  const u1=el("ul","plain");(F.droppable||[]).forEach(x=>u1.append(el("li",null,x)));b5.append(u1);
  const c5=el("div","card");c5.append(el("h3",null,"What we refused"));
  const u2=el("ul","plain");(F.anti_anchors||[]).forEach(x=>u2.append(el("li",null,x.element+" — "+x.reason)));c5.append(u2);
  g.append(a,b5,c5);s.append(g);

  /* how the reference is built — the setups it cuts between */
  if((F.shot_grammar||[]).length){
    const sg=el("div","grid g3");sg.style.marginTop="16px";
    F.shot_grammar.forEach(sh=>{const c=el("div","card");
      c.append(el("h3",null,sh.name||sh.id));
      if(sh.desc)c.append(el("p","small",sh.desc));
      if(sh.screen_time)c.append(el("div","small","On screen for "+sh.screen_time));
      sg.append(c);});
    s.append(el("p","lede","Every shot in the reference is one of these setups."));
    s.append(sg);}

  /* the frame map — what happens second by second, and what ours does instead */
  if((F.frame_map||[]).length){
    s.append(el("p","lede",
      "Read left to right: what the reference does at that moment, and what we do in its place. "+
      "Nothing on the right is copied — the three things that never carry across a reference "+
      "(the proof, the ask, and the rules) are written fresh."));
    const wrap=el("div","scroll");const t=el("table");
    const hd=el("tr");["Frame","When","Theirs","Ours"].forEach(h=>hd.append(el("th",null,h)));
    const th=el("thead");th.append(hd);t.append(th);
    const tb=el("tbody");
    F.frame_map.forEach(r=>{const tr=el("tr");
      const td0=el("td");
      if(r._thumb){const im=el("img");im.src=r._thumb;im.alt="";im.loading="lazy";
        im.style.cssText="width:78px;display:block;border:1px solid var(--line)";td0.append(im);}
      else td0.append(el("div","small",r._thumb_note||""));
      tr.append(td0);
      const td1=el("td","t");
      td1.append(document.createTextNode((r.t?r.t[0].toFixed(1)+"–"+r.t[1].toFixed(1)+"s":"")));
      if(r.beat)td1.append(el("div","small",r.beat.replace(/_/g," ")));
      tr.append(td1);
      tr.append(el("td",null,r.ref||""));
      const td3=el("td");td3.innerHTML=r.ours||"";
      td3.style.background="var(--surface-2)";tr.append(td3);
      tb.append(tr);});
    t.append(tb);wrap.append(t);s.append(wrap);}

  M.append(s);}

/* ---------- caption ---------- */
if(S.caption){const s=section("The caption","copy and paste");
  const box=el("div","card copy");
  const txt=[S.caption.body,"",S.caption.disclaimer,S.caption.affiliation?"— "+S.caption.affiliation:null].filter(Boolean).join("\n");
  const cb=el("button","copybtn","copy");
  cb.onclick=()=>navigator.clipboard.writeText(txt).then(()=>{cb.textContent="copied";setTimeout(()=>cb.textContent="copy",1400);});
  box.append(cb,el("pre",null,txt));s.append(box);M.append(s);}

/* ---------- what's left ---------- */
{
  const owed=[],st=P.stages;
  if(!st.brief)owed.push("Decide what this video is about");
  if(!st.script)owed.push("Write what she says");
  if(st.script&&S.lint)Object.entries(S.lint).forEach(([k,v])=>{
    if(state(v)==="fail")owed.push("Fix: "+(L.lint[k]||k.replace(/_/g," ")).toLowerCase());});
  ((S.next_stage||{}).blocked_on||[]).forEach(x=>owed.push(x));
  if(!st.board)owed.push("Draw one picture per moment, and approve them");
  if(!st.assets)owed.push("Record her voice, then generate the footage");
  if(!st.cut)owed.push("Cut it together");
  if(!st.qc)owed.push("Check the finished video against this plan");
  const s=section("What's left");
  const o=el("div","owed");const u=el("ul","plain");owed.forEach(x=>u.append(el("li",null,x)));
  o.append(u);s.append(o);M.append(s);}

document.getElementById("footer").textContent=
  "This page is built from the plan files in "+P.work_dir+" — change those and rebuild it, don't edit this page. "+
  "Press space to play, arrow keys to step through frame by frame.";
</script>
"""


def render(data: dict[str, Any]) -> str:
    manifest = (read_json(ROOT / "evidence" / "manifest.json") or {}).get("entries", {})
    tickers = {str(e.get("claim", {}).get("ticker", "")).upper()
               for e in manifest.values() if isinstance(e, dict)}
    tickers.discard("")

    brief = data.get("brief") or {}
    title = brief.get("title") or humanize_slug(data["slug"], tickers)
    data["page_title"] = title

    labels = {
        "lint": LINT_LABELS, "slots": SLOT_LABELS, "visual": VISUAL_SLOT_LABELS,
        "gates": {str(k): v for k, v in GATE_QUESTIONS.items()},
        "platforms": {"instagram_reels": "Instagram Reels", "youtube_shorts": "YouTube Shorts",
                      "tiktok": "TikTok"},
    }
    payload = json.dumps(data, ensure_ascii=False, default=str).replace("</", "<\\/")
    return (HTML.replace("__TITLE__", title)
                .replace("__PIECE__", payload)
                .replace("__LABELS__", json.dumps(labels, ensure_ascii=False)))


def build(work_dir: str | Path) -> Path:
    wd = Path(work_dir)
    if not wd.is_dir():
        raise SystemExit(f"not a directory: {wd}")
    out = wd / "review.html"
    out.write_text(render(collect(wd)), encoding="utf-8")
    return out


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        raise SystemExit(__doc__)
    out = build(args[0])
    print(f"-> {out}  ({out.stat().st_size / 1024:.0f}KB)")
    if "--open" in sys.argv:
        import subprocess
        subprocess.run(["open", str(out)], check=False)


if __name__ == "__main__":
    main()
