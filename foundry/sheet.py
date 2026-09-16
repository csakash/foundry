"""The single human gate: one page with the layout sketch, real first-frame candidates,
the product clip thumbnail and the caption in place. Approving a candidate freezes the invoice.
"""
from __future__ import annotations

import base64
import html
import io
import shlex
import shutil
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from engine.providers import get_image_provider
from engine.providers.openai_images import ImageRefused
from engine.qc import safety_lint

from . import cast, media
from .caption import overlay, render as render_caption
from .imaging import capture_treatment, find_font, font, save_png
from .loop import _attempts
from .piece import APPROVED, Piece
from .spec import first_frame_prompt, layout_prompt
from .util import CANDIDATE_RE, FoundryError, check_name, human_only, inside, now, write_json
from .workspace import Workspace


def cover(src: Path, dst: Path, size=media.OUTPUT_SIZE) -> Path:
    im = Image.open(src).convert("RGB")
    w, h = size
    s = max(w / im.width, h / im.height)
    im = im.resize((round(im.width * s), round(im.height * s)))
    x, y = (im.width - w) // 2, (im.height - h) // 2
    im.crop((x, y, x + w, y + h)).save(dst)
    return dst


def _call(piece: Piece, provider, prompt: str, refs: list[Path], size: str, note: str) -> bytes | None:
    """One image, one reservation. A safety refusal returns None (the candidate is lost, not the piece)."""
    lint = safety_lint.lint(prompt)
    hits = ", ".join(h["phrase"] for h in lint["measures"]["hits"])
    eid = piece.reserve("image_call", 1.0, note + (f" (safety rewrites: {hits})" if hits else ""))
    try:
        out = provider.edit(lint["rewritten"], refs, n=1, size=size)[0]
    except ImageRefused:
        piece.settle(eid, ok=False, actual=_attempts(provider))
        return None
    except Exception:
        piece.settle(eid, ok=False, actual=_attempts(provider))
        raise
    piece.settle(eid, ok=True, actual=_attempts(provider))
    return out


def render(ws: Workspace, piece: Piece, n: int | None = None, provider=None) -> dict[str, Any]:
    human_only("sheet")
    piece.require("specced", "sheet_pending")
    spec = piece.spec
    n = int(n or ws.defaults.get("sheet_candidates", 3))
    if not 2 <= n <= 4:
        raise FoundryError("the sheet shows 2 to 4 candidates")
    pdir = cast.pdir(ws, spec["creator"])
    master, char_sheet = pdir / "master.png", pdir / "sheet.png"
    provider = provider or get_image_provider(ws.image, str(ws.root / ".foundry"))
    sd = piece.rel("sheet")
    if sd.exists():
        shutil.rmtree(sd)
    (sd / "candidates").mkdir(parents=True)

    ff_prompt = first_frame_prompt(ws, spec)
    (sd / "first-frame-prompt.txt").write_text(ff_prompt)
    names, refused = [], 0
    for i in range(1, n + 1):
        data = _call(piece, provider, ff_prompt, [master, char_sheet], "1024x1536", f"sheet candidate c{i}")
        if data is None:
            refused += 1
            continue
        raw = save_png(data, sd / "candidates/raw" / f"c{i}.png")
        capture_treatment(raw, sd / "candidates" / f"c{i}.png", seed=i)
        names.append(f"c{i}")
    if len(names) < 2:
        hits = safety_lint.lint(ff_prompt)["measures"]["hits"]
        raise FoundryError(f"the image provider refused {refused} of {n} candidates on safety grounds, leaving "
                           f"{len(names)}; reword the shot (wardrobe, action) with foundry set and render again"
                           + (f". Lint already rewrote: {', '.join(h['phrase'] for h in hits)}" if hits else ""))
    lay = _call(piece, provider, layout_prompt(spec), [master], "1536x1024", "sheet layout sketch")
    if lay is None:  # the sketch is context, not the decision: fall back to a plain panel strip
        Image.new("RGB", (1536, 1024), (238, 236, 230)).save(sd / "layout.png")
    else:
        save_png(lay, sd / "layout.png")

    asset = spec["assets"][0]
    media.frame_at(inside(ws.root, asset["path"], "product clip"), float(asset["trim_s"][0]) + 0.5, sd / "product.jpg")
    cap_meta = render_caption(spec["captions"], sd / "caption.png")
    cover(sd / f"candidates/{names[0]}.png", sd / "c1-9x16.png")
    overlay(sd / "c1-9x16.png", sd / "caption.png", sd / "caption-preview.png")

    compose(spec, piece, sd, names, cap_meta)
    write_html(spec, piece, sd, names, cap_meta)
    piece.set_state("sheet_pending", sheet_rendered_at=now(), sheet_spec_sha256=piece.spec_hash())
    return {"piece": piece.ref, "sheet": str(sd / "sheet.png"), "html": str(sd / "index.html"),
            "candidates": names, "refused": refused, "layout_refused": lay is None,
            "font_used": cap_meta["font_used"], "font_substituted": cap_meta["font_substituted"]}


def compose(spec: dict[str, Any], piece: Piece, sd: Path, names: list[str], cap: dict[str, Any]) -> Path:
    W, pad = 2400, 32
    _, fp = find_font("Arial Bold")
    f_title, f_lab = font(fp, 44), font(fp, 28)
    lay = Image.open(sd / "layout.png").convert("RGB")
    lay_h = min(900, round((W - 2 * pad) * lay.height / lay.width))  # the candidates are the decision, not the sketch
    lay = lay.resize((round(lay_h * lay.width / lay.height), lay_h))
    tiles = [(sd / "candidates" / f"{c}.png", c) for c in names]
    tiles += [(sd / "caption-preview.png", f"caption in place (on {names[0]})"),
              (sd / "product.jpg", f"product clip @ {spec['assets'][0]['enter_at_s']} s")]
    tw = (W - pad * (len(tiles) + 1)) // len(tiles)
    th = round(tw * 16 / 9)
    H = pad + 70 + lay.height + pad + th + 60 + 90
    canvas = Image.new("RGB", (W, H), (21, 20, 15))
    d = ImageDraw.Draw(canvas)
    d.text((pad, pad), f"{piece.ref}  ·  \"{spec['hook']['line']}\"", fill=(233, 228, 216), font=f_title)
    y = pad + 70
    canvas.paste(lay, ((W - lay.width) // 2, y))
    y += lay.height + pad
    for i, (p, label) in enumerate(tiles):
        im = Image.open(p).convert("RGB")
        s = max(tw / im.width, th / im.height)
        im = im.resize((round(im.width * s), round(im.height * s)))
        im = im.crop(((im.width - tw) // 2, (im.height - th) // 2, (im.width - tw) // 2 + tw, (im.height - th) // 2 + th))
        x = pad + i * (tw + pad)
        canvas.paste(im, (x, y))
        d.text((x, y + th + 10), label, fill=(233, 228, 216), font=f_lab)
    b = spec["budget"]
    d.text((pad, H - 80), f"Approving freezes the invoice: ceiling {b['ceiling']['video_credits']:.1f} video credits, "
                          f"{b['ceiling']['image_call']:.0f} image calls. Font: {cap['font_used']}"
                          + (" (SUBSTITUTED)" if cap["font_substituted"] else ""), fill=(200, 190, 170), font=f_lab)
    canvas.save(sd / "sheet.png")
    return sd / "sheet.png"


def _b64(p: Path, max_w: int = 720) -> str:
    """Display-size JPEG for the page; the full-size PNGs stay on disk for approval."""
    im = Image.open(p).convert("RGB")
    if im.width > max_w:
        im = im.resize((max_w, round(max_w * im.height / im.width)))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    return f"data:image/jpeg;base64,{base64.b64encode(buf.getvalue()).decode()}"


def write_html(spec: dict[str, Any], piece: Piece, sd: Path, names: list[str], cap: dict[str, Any]) -> Path:
    e = html.escape
    cards = "".join(
        f'<figure><img src="{_b64(sd / "candidates" / f"{c}.png")}" alt="candidate {c}"><figcaption>{c}'
        f'<button data-cmd="{e(shlex.join(["foundry", "approve", piece.ref, "--candidate", c]))}">Approve {c}</button></figcaption></figure>'
        for c in names)
    structure = "".join(f"<li>{s['t'][0]:.0f}–{s['t'][1]:.0f} s · {e(s['beat'])}</li>" for s in spec["structure"])
    b = spec["budget"]
    page = f"""<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sheet · {e(piece.ref)}</title>
<style>
:root{{--bg:#f6f4ef;--fg:#1d1b16;--mute:#6b665b;--card:#fff;--line:#ddd7ca;--accent:#2f5d50}}
@media (prefers-color-scheme:dark){{:root{{--bg:#15140f;--fg:#e9e4d8;--mute:#a39d8f;--card:#201e18;--line:#3a372e;--accent:#8fc1ae}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 -apple-system,Helvetica,Arial,sans-serif;padding:24px 16px}}
main{{max-width:1180px;margin:0 auto}} h1{{font-size:22px;margin:0 0 4px}} .mute{{color:var(--mute)}}
.hook{{font-size:20px;font-weight:700;margin:12px 0 20px}} img{{max-width:100%;display:block;border-radius:6px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px;margin:16px 0}}
figure{{margin:0;background:var(--card);border:1px solid var(--line);border-radius:8px;padding:8px}}
figcaption{{display:flex;justify-content:space-between;align-items:center;padding-top:8px;font-weight:600}}
button{{font:inherit;font-size:13px;border:1px solid var(--accent);color:var(--accent);background:none;border-radius:6px;padding:4px 10px;cursor:pointer}}
code{{background:var(--card);border:1px solid var(--line);padding:2px 6px;border-radius:4px;overflow-wrap:anywhere}}
</style>
<main>
<h1>{e(piece.ref)}</h1><div class="mute">Approve one candidate. That is the only decision before spend.</div>
<div class="hook">“{e(spec['hook']['line'])}”</div>
<img src="{_b64(sd / 'layout.png', 1180)}" alt="layout sketch">
<div class="grid">{cards}
<figure><img src="{_b64(sd / 'caption-preview.png')}" alt="caption preview"><figcaption>caption in place</figcaption></figure>
<figure><img src="{_b64(sd / 'product.jpg')}" alt="product clip"><figcaption>product clip</figcaption></figure></div>
<ul>{structure}</ul>
<p>Approving freezes the invoice: at most <b>{b['ceiling']['video_credits']:.1f}</b> video credits and
<b>{b['ceiling']['image_call']:.0f}</b> image calls for the whole build.
Caption font: {e(cap['font_used'])}{' <b>(substituted)</b>' if cap['font_substituted'] else ''}.</p>
<p id="out" class="mute">Buttons copy the command. Run it in the workspace.</p>
</main>
<script>
document.querySelectorAll('button[data-cmd]').forEach(b=>b.addEventListener('click',async()=>{{
  const cmd=b.dataset.cmd, out=document.getElementById('out');
  try{{await navigator.clipboard.writeText(cmd); out.innerHTML='Copied: <code></code>';}}
  catch(_){{out.innerHTML='Run: <code></code>';}}
  out.querySelector('code').textContent=cmd;
}}));
</script>"""
    (sd / "index.html").write_text(page)
    return sd / "index.html"


def approve(ws: Workspace, piece: Piece, candidate: str) -> dict[str, Any]:
    human_only("approve")
    check_name(candidate, CANDIDATE_RE, "candidate")
    piece.require("sheet_pending")
    src = piece.rel("sheet", "candidates", f"{candidate}.png")
    if not src.exists():
        raise FoundryError(f"no candidate {candidate} on the sheet")
    if piece.status.get("sheet_spec_sha256") != piece.spec_hash():
        raise FoundryError("the spec changed after the sheet was rendered; render the sheet again so the approval "
                           "covers what will be built")
    piece.rel("frames").mkdir(exist_ok=True)
    shutil.copyfile(src, piece.rel(APPROVED))
    spec = piece.spec
    inv = piece.invoice
    inv.update(frozen=True, frozen_at=now(), planned=spec["budget"]["planned"], ceilings=spec["budget"]["ceiling"],
               baseline={u: piece.spent(u) for u in spec["budget"]["ceiling"]}, approved_candidate=candidate)
    write_json(piece.rel("invoice.json"), inv)
    lock = piece.write_lock(ws.defaults["fix_cycles"])
    piece.touch(f"sheet approval: {candidate}")
    piece.set_state("approved", approved_candidate=candidate)
    return {"piece": piece.ref, "approved": candidate, "ceilings": inv["ceilings"], "fix_cycles": lock["fix_cycles"]}
