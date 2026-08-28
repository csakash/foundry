"""The router: the ten strategy formats, and what each one needs to render.

Source: drevon-findings/outputs/ai_ugc_content_strategy_gm_markets.html
(10 formats derived from 36 Apify-scraped reels, Aug 2026).

This module is deliberately executable rather than documentation. `status`
checks the real filesystem and reports what can actually be produced today, so
the readiness answer cannot drift away from the code.

    python -m engine.formats list
    python -m engine.formats status
    python -m engine.formats show chart_pattern
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

from . import evidence

ROOT = evidence.ROOT
MOTION_SRC = ROOT / "motion" / "src"


@dataclass
class Format:
    key: str
    rank: int                      # rank in the strategy report
    title: str
    lanes: list[str]
    duration_s: tuple[int, int]
    composition: str               # the Remotion composition it renders through
    needs_capabilities: list[str]
    prompt_families: list[str]
    marginal_cost: str
    note: str = ""
    evidence_required: bool = True
    _: field(default=None) = None


# Capabilities are the atoms every format is assembled from. A format is
# renderable exactly when all of its capabilities are present.
CAPABILITIES: dict[str, dict] = {
    "captions":        {"probe": MOTION_SRC / "components" / "Captions.tsx"},
    "evidence_card":   {"probe": MOTION_SRC / "components" / "Pieces.tsx", "symbol": "EvidenceCard"},
    "number_counter":  {"probe": MOTION_SRC / "components" / "Pieces.tsx", "symbol": "NumberCounter"},
    "text_plate":      {"probe": MOTION_SRC / "components" / "Pieces.tsx", "symbol": "TextPlate"},
    "bar_compare":     {"probe": MOTION_SRC / "components" / "Pieces.tsx", "symbol": "BarCompare"},
    "split_presenter": {"probe": MOTION_SRC / "NewsReel.tsx", "symbol": "NewsReel"},
    "market_data":     {"probe": ROOT / "engine" / "marketdata.py"},
    "web_screenshot":  {"probe": ROOT / "pipeline" / "capture_assets.mjs"},
    "asset_inbox":     {"probe": ROOT / "engine" / "inbox.py"},
    "prompt_library":  {"probe": ROOT / "engine" / "prompts" / "__init__.py"},
    "voice_tts":       {"probe": ROOT / "pipeline" / "el_tts.py"},

    # --- not built yet ---
    "candlestick":     {"probe": MOTION_SRC / "components" / "Candles.tsx", "symbol": "CandleChart",
                        "how": "bar-replay from OHLCV, non-linear pacing, terminal skin"},
    "moment_finder":   {"probe": ROOT / "engine" / "moments.py",
                        "how": "scan real OHLCV for dramatic arcs instead of clipping others' footage"},
    "chart_annotation": {"probe": MOTION_SRC / "components" / "Annotations.tsx", "symbol": "PatternAnnotation",
                        "how": "timed pattern labels, trendlines and zones over the candles"},
    "allocation_chart": {"probe": MOTION_SRC / "components" / "Allocation.tsx", "symbol": "AllocationChart",
                        "how": "donut + animated legend for portfolio splits"},
    "fullbleed_montage": {"probe": MOTION_SRC / "MontageReel.tsx", "symbol": "MontageReel",
                        "how": "full-frame B-roll sequence with VO + music bed"},
    "card_stack":      {"probe": MOTION_SRC / "ListicleReel.tsx", "symbol": "ListicleReel",
                        "how": "sequential screenshot cards with numbered overlay"},
    "text_plate_sticker": {"probe": MOTION_SRC / "AmbientLoop.tsx", "symbol": "Plate",
                        "how": "native-IG-style white sticker plate over full-bleed video"},
    "image_to_video":  {"probe": ROOT / "personas",
                        "how": "Higgsfield seedance_2_5 mode=omni_reference, start_image -> silent clip"},
    "meme_plate":      {"probe": MOTION_SRC / "MemeReel.tsx", "symbol": "MemeReel",
                        "how": "text-over-clip, top/bottom caption bar, trending-audio safe"},
    "screencast":      {"probe": ROOT / "pipeline" / "screencast.mjs",
                        "how": "CDP Page.startScreencast -> frames -> ffmpeg CFR; cursor track from action log"},
    "punch_in":        {"probe": MOTION_SRC / "components" / "Screencast.tsx", "symbol": "ScreencastLayer",
                        "how": "OffthreadVideo + keyframed zoom/pan + synthetic cursor + callouts"},
    "persona_pack":    {"probe": ROOT / "personas",
                        "how": "identity sheet -> LoRA lock -> designed ElevenLabs voice"},
    "lipsync":         {"probe": ROOT / "pipeline" / "lipsync_fal.py",
                        "how": "fal InfiniteTalk / OmniHuman: persona still + ElevenLabs audio -> clip"},
    "broll_source":    {"probe": ROOT / "engine" / "broll.py",
                        "how": "Pexels API adapter (needs PEXELS_API_KEY) + generative fallback"},
    "music_bed":       {"probe": ROOT / "engine" / "music.py",
                        "how": "ElevenLabs Music v2 -> bed, ducked under VO in the mix"},
}


FORMATS: list[Format] = [
    Format("profit_replay", 5, "Profit screen recording / trade replay", ["B"], (10, 14),
           "ScreencastReel", ["candlestick", "moment_finder", "market_data"],
           ["hook", "music"], "≈ ₹0",
           "Highest share rate in the scrape (2.95%). v1 renders the replay in our own "
           "UI skin; v2 swaps in a real CDP screencast of the live app. Frame as replay "
           "+ mechanics, never achieved P&L — a profit number on screen is a claim."),
    Format("chart_pattern", 9, "Chart pattern / technical education", ["A"], (11, 30),
           "ScreencastReel", ["candlestick", "chart_annotation", "market_data", "captions", "voice_tts"],
           ["hook", "voice", "music"], "≈ ₹0",
           "Bar-replay from real OHLCV. Do not screen-record TradingView."),
    Format("compound_math", 2, "Compound interest / wealth math visualiser", ["A"], (13, 45),
           "MathReel", ["number_counter", "text_plate", "market_data", "voice_tts"],
           ["hook", "voice", "music"], "₹15–25",
           "Highest save rate of the faceless formats. Assumptions must be on screen."),
    Format("listicle", 8, "Resource listicle / 'save this'", ["B", "A"], (12, 30),
           "ListicleReel", ["card_stack", "web_screenshot", "captions", "voice_tts"],
           ["hook", "voice"], "₹15–25",
           "Put the brand third in a five-item list, never first."),
    Format("portfolio_breakdown", 6, "Portfolio / '$10K breakdown'", ["A", "B"], (45, 94),
           "PortfolioReel", ["allocation_chart", "market_data", "captions", "voice_tts"],
           ["hook", "voice"], "₹15–40",
           "Allocation, not recommendation. No 'here's what to buy'."),
    Format("millionaire_math", 7, "'How to become a millionaire' math", ["A", "C"], (30, 60),
           "MathReel", ["number_counter", "text_plate", "market_data", "voice_tts"],
           ["hook", "voice", "music"], "₹20–330",
           "Comment-bait CTA is the mechanic. Highest projection-claim risk of the set."),
    Format("meme", 4, "Trading meme / relatable humour", ["A"], (8, 15),
           "MemeReel", ["meme_plate", "captions"], ["hook"], "₹0–30",
           "Trending audio attached in-app at post time, never baked into the render."),
    Format("mindset", 1, "Wealth mindset narrative", ["C"], (30, 67),
           "MontageReel", ["fullbleed_montage", "broll_source", "music_bed", "voice_tts", "captions"],
           ["hook", "voice", "music"], "₹40–70",
           "8.9M-view format. Narrative, not factual — the one format needing no evidence."),
    Format("myth_buster", 3, "Beginner mistake / myth buster", ["C", "A"], (30, 67),
           "NewsReel", ["split_presenter", "persona_pack", "lipsync", "captions", "evidence_card"],
           ["hook", "voice", "shot", "persona-identity"], "₹300–350",
           "The split_presenter composition already exists — this is the closest Lane C format."),
    Format("journey_doc", 10, "Journey documentary / day-in-the-life", ["C", "B"], (11, 60),
           "NewsReel", ["split_presenter", "persona_pack", "lipsync", "screencast", "punch_in"],
           ["hook", "voice", "shot", "persona-identity"], "₹300–400",
           "Serialised. Needs a persona that can post daily without drifting."),
]

FORMATS.append(
    Format("ambient_loop", 11, "Silent ambient loop (text-on-video)", ["C"], (5, 10),
           "AmbientLoop", ["text_plate_sticker", "image_to_video", "persona_pack"],
           ["persona-identity", "hook"], "≈ ₹75",
           "Not in the original ten — added 2026-08-25 from live reference reels. One person "
           "doing almost nothing, hook on a sticker plate, all value in the caption. No voice, "
           "no lipsync, no captions. Cheapest Lane C format by a wide margin because there is "
           "no audio to drive and no mouth to get wrong. Hard constraint: the persona has no "
           "biography, so the hook must be information, never autobiography.",
           evidence_required=False))

BY_KEY = {f.key: f for f in FORMATS}


def capability_present(name: str) -> bool:
    cap = CAPABILITIES.get(name)
    if not cap:
        return False
    probe: Path = cap["probe"]
    if not probe.exists():
        return False
    sym = cap.get("symbol")
    if sym and probe.is_file():
        return sym in probe.read_text(errors="ignore")
    if probe.is_dir():
        return any(probe.iterdir())
    return True


def registered_compositions() -> set[str]:
    """Compositions actually registered in Root.tsx.

    Primitives existing is not the same as a renderable composition. Without
    this check the router reports formats as ready when all that exists is a
    box of parts.
    """
    root = MOTION_SRC / "Root.tsx"
    if not root.exists():
        return set()
    import re
    return set(re.findall(r'<Composition\s[^>]*?id="([^"]+)"', root.read_text(), re.S))


def readiness() -> list[dict]:
    comps = registered_compositions()
    out = []
    for f in FORMATS:
        missing = [c for c in f.needs_capabilities if not capability_present(c)]
        comp_missing = f.composition not in comps
        out.append({
            "key": f.key, "rank": f.rank, "title": f.title, "lanes": f.lanes,
            "composition": f.composition,
            "composition_registered": not comp_missing,
            "missing": missing,
            "ready": not missing and not comp_missing,
            "marginal_cost": f.marginal_cost,
        })
    return sorted(out, key=lambda r: (not r["ready"], len(r["missing"]) + (not r["composition_registered"]), r["rank"]))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="engine.formats", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="the ten formats")
    s = sub.add_parser("status", help="what can actually be rendered today")
    s.add_argument("--json", action="store_true")
    sh = sub.add_parser("show", help="one format in detail")
    sh.add_argument("key")
    a = ap.parse_args(argv)

    if a.cmd == "show":
        f = BY_KEY.get(a.key)
        if not f:
            print(f"unknown format {a.key!r}; have: {', '.join(BY_KEY)}", file=sys.stderr)
            return 1
        d = asdict(f); d.pop("_", None)
        d["missing_capabilities"] = [c for c in f.needs_capabilities if not capability_present(c)]
        print(json.dumps(d, indent=2, default=str))
        return 0

    rows = readiness()

    if a.cmd == "list":
        for r in sorted(rows, key=lambda x: x["rank"]):
            print(f"#{r['rank']:<3} {r['key']:22} {'/'.join(r['lanes']):6} "
                  f"{r['marginal_cost']:>10}  {r['title']}")
        return 0

    if getattr(a, "json", False):
        print(json.dumps(rows, indent=2))
        return 0

    ready = [r for r in rows if r["ready"]]
    print(f"\n  {len(ready)} of {len(rows)} formats renderable today\n")
    for r in rows:
        mark = "READY" if r["ready"] else "    ·"
        print(f"  {mark}  #{r['rank']:<3} {r['key']:22} {r['title']}")
        if not r["composition_registered"]:
            print(f"{'':13}no <Composition id=\"{r['composition']}\"> in Root.tsx")
        if r["missing"]:
            print(f"{'':13}needs: {', '.join(r['missing'])}")

    # what unlocks the most, per capability
    blockers: dict[str, int] = {}
    for r in rows:
        for c in r["missing"]:
            blockers[c] = blockers.get(c, 0) + 1
        if not r["composition_registered"]:
            k = f"composition:{r['composition']}"
            blockers[k] = blockers.get(k, 0) + 1
            CAPABILITIES.setdefault(k, {"how": "Remotion composition + Root.tsx registration"})
    if blockers:
        print("\n  missing capabilities, by how many formats they unblock:\n")
        for cap, n in sorted(blockers.items(), key=lambda kv: -kv[1]):
            how = CAPABILITIES[cap].get("how", "")
            print(f"    {n} format{'s' if n > 1 else ' '}  {cap:20} {how}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
