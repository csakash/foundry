#!/usr/bin/env python3
"""Generate the carousel's cut-out figures with OpenAI gpt-image-2.

The house style (decomposed from templates/DcnjhnmFdiS.json) puts one greyscale
classical statue on most slides, cut out and bleeding off an edge. This asks for
exactly that: a transparent-background PNG of a single marble figure, in a locked
style so four separately generated images still look like one visual world.

    python3 pipeline/gen_figures.py work/@handle/slug            # all owed figures
    python3 pipeline/gen_figures.py work/@handle/slug --only 1   # just one beat
    python3 pipeline/gen_figures.py work/@handle/slug --dry-run  # prompts + cost only

Writes brand/assets/figures/<slug>-<n>.png and records the model, prompt and cost
back into 02-script.json. Every figure is AI-generated, so the piece carries the
AI disclosure — see brand.tokens.json compliance.ai_disclosure.
"""
from __future__ import annotations

import argparse, base64, json, os, sys, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIGS = ROOT / "brand" / "assets" / "figures"
MODEL = os.environ.get("OPENAI_IMAGE_MODEL", "gpt-image-2")
ENDPOINT = "https://api.openai.com/v1/images/generations"

# The locked look. Changing this changes every future figure, so it is one
# string in one place rather than a sentence retyped per slide.
STYLE = (
    "A single classical marble statue, fully draped in carved robes, photographed "
    "for a museum catalogue. "
    "Neutral greyscale stone, soft even studio lighting from the front-left, fine "
    "chisel and weathering texture, sharp focus throughout, subtle warm-grey shadows. "
    "The figure is isolated on a fully transparent background with no plinth, no "
    "ground shadow, no backdrop, no props beyond what is described. Full figure "
    "visible, upright, photographed from slightly below eye level. "
    "No text, no lettering, no watermark, no signature, no border. "
    "Subject: {subject}"
)


def trim_alpha(path: Path) -> None:
    """Crop the transparent margin away.

    The model returns the figure centred inside a transparent canvas, so the
    image box and the figure are not the same rectangle. Laying out against the
    box is what leaves a statue floating in the middle of its own empty space
    when the design calls for it to bleed off the edge.
    """
    try:
        from PIL import Image
    except ImportError:
        print("    (Pillow not available in this interpreter — figure left untrimmed)")
        return
    im = Image.open(path).convert("RGBA")
    bbox = im.split()[3].getbbox()
    if bbox and bbox != (0, 0, *im.size):
        im.crop(bbox).save(path)
        print(f"    trimmed to {bbox[2]-bbox[0]}x{bbox[3]-bbox[1]}")


def generate(prompt: str, size: str = "1024x1536") -> bytes:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise SystemExit("OPENAI_API_KEY not set")
    body = {"model": MODEL, "prompt": prompt, "size": size, "n": 1,
            "background": "transparent", "output_format": "png", "quality": "high"}
    req = urllib.request.Request(ENDPOINT, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json",
                                          "Authorization": f"Bearer {key}"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                payload = json.load(r)
            break
        except urllib.error.HTTPError as e:                              # noqa: F821
            body = e.read().decode()[:500]
            if e.code == 429 and attempt < 3:
                wait = 45 * (attempt + 1)
                print(f"    429 — backing off {wait}s (attempt {attempt + 1}/4)")
                time.sleep(wait)
                continue
            raise SystemExit(f"openai {e.code}: {body}") from None
    else:
        raise SystemExit("openai 429: still throttled after 4 attempts — reuse the figure library "
                         "(brand/assets/figures/) and regenerate when the quota resets")
    d = payload["data"][0]
    usage = payload.get("usage") or {}
    if usage:
        print(f"    tokens: {usage}")
    return base64.b64decode(d["b64_json"])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("work_dir")
    ap.add_argument("--only", type=int, action="append", default=None, help="beat number(s)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--size", default="1024x1536")
    a = ap.parse_args()

    sp = Path(a.work_dir) / "02-script.json"
    script = json.loads(sp.read_text(encoding="utf-8"))
    FIGS.mkdir(parents=True, exist_ok=True)
    made = 0
    for b in script["beats"]:
        if b.get("signoff") or b.get("table") or b.get("bars"):
            continue
        if a.only and b["n"] not in a.only:
            continue
        subject = b.get("figure_subject")
        if not subject:
            print(f"  beat {b['n']}: no figure_subject — skipped")
            continue
        prompt = STYLE.format(subject=subject)
        print(f"\n  beat {b['n']} ({b['role']}):\n    {subject}")
        if a.dry_run:
            continue
        try:
            png = generate(prompt, a.size)
        except SystemExit as e:
            # One rejected prompt must not abort the rest of the run.
            print(f"    !! {e}")
            continue
        out = FIGS / f"{script['slug']}-{b['n']:02d}.png"
        out.write_bytes(png)
        trim_alpha(out)   # the model centres the figure in transparent padding
        b["figure"] = str(out.relative_to(ROOT))
        b["figure_provenance"] = {"model": MODEL, "size": a.size, "subject": subject,
                                  "style_locked": True,
                                  "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        print(f"    -> {out.relative_to(ROOT)}  ({len(png)/1000:.0f} KB)")
        made += 1
        # Save after every image. A four-image run that dies on the last one must
        # not lose the three that already cost money.
        sp.write_text(json.dumps(script, indent=1, ensure_ascii=False), encoding="utf-8")
    if not a.dry_run and made:
        script.setdefault("lint", {})["ai_imagery"] = (
            f"{made} figure(s) generated with {MODEL} — the piece carries the AI disclosure")
        sp.write_text(json.dumps(script, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"\n{made} figure(s) generated" if not a.dry_run else "\ndry run — nothing generated")


if __name__ == "__main__":
    main()
