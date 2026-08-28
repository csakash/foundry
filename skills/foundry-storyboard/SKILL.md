---
name: foundry-storyboard
description: Storyboard craft — one keyframe per beat, per-lane sourcing, composed-frame review, safe zones, slideshow-risk and variation checks, board-as-invoice. Load at the board stage (03-board/) and for QC conformance ("does the render match the board?").
---

# Storyboard — see the video before it exists

The board is the spend firewall: every beat becomes an approved still before it
becomes motion. An approved frame is a production input (start_image / pinned
timestamp / render props), not a picture of one.

## Keyframe sourcing by lane

- **Lane C (generated humans):** gpt-image-2 with the phone-video-frame prompt
  discipline (`personas/*/gpt-image.prompt.txt`): "a still frame grabbed from
  low-res phone video, not a photograph" + named artefacts (soft focus, sensor
  noise, motion blur, flat contrast). Persona identity anchors asserted (age hard,
  face shape named, no-freckles rules etc. from `persona.json`). Generate stills
  singly (~90s each); iterate to approval BEFORE any motion spend.
- **Lane B (captured/archive):** the keyframe is a REAL extracted frame. Contact-
  sheet the source (`ffmpeg -ss`), look at it, pin `fromSec`. Watch for burned-in
  title cards / uploader banners — crop in the brief. Never take hit[0] blind.
- **Lane A (deterministic):** `npx remotion still` of the actual composition with
  real props — the render itself at one frame, free.

## Compose the frame as reviewed

Frames are reviewed COMPOSED, not raw: text plates at their real coords (persona
`setups`), tilt, caption strip, disclaimer strip, crop applied. Half of all
rejects are composition collisions a composed still reveals for ₹0.

**Safe zones (assert, don't eyeball):** bottom ~320px is dead on every platform
(UI overlays); universal safe zone ≈ 900×1400 centered on 1080×1920. No plate,
caption, or credit inside dead zones. Hook plates sit in the top 40% of the safe
zone.

## Craft gates before Gate 3 approval

Score the board BEFORE the human sees it; "revise" verdicts loop automatically:

1. **Slideshow risk** — does motion have narrative purpose per beat? Is any visual
   decorative rather than communicative? Is the piece text-plate-first when its
   promise was motion-led? Is there an explicit reason for each framing?
2. **Variation** — no shot size >50% of beats; no 3+ consecutive identical
   framings; backgrounds/layouts not recycled beat-to-beat unless the format's
   grammar demands it (ambient_loop legitimately holds one frame).
3. **Delivery promise** — the brief's lane and motion character still hold. A
   Lane-C motion-led brief must not have quietly become a pan-zoom slideshow.
   If it can't be honored: stop and ask, never substitute silently.
4. **Charter/visual identity** — persona, wardrobe rules, palette, caption style
   match `charter.json` + `brand.tokens.json`.

## Board mechanics

`board.json` per beat: `{beat, t, keyframe, source, still_prompt|source_ref,
motion_prompt, motion_route, audio_ref, plates[], evidence[], est_cost, status}`.
Sum of `est_cost` over approved beats = the exact Stage-4 bill — **approving the
board is approving the invoice.**

- Approved Lane-C frame = `start_image` (Higgsfield) or identity reference (fal).
  Chaining: a mid-action frame extracted from beat N's clip is a valid opening
  frame for beat N+1 — free continuity, persona look inherits.
- Image posts = one approved frame shipped. Carousels = N frames + Stage-2 copy.
  Same gates, zero extra process.

## QC conformance (Gate 4 reuse)

At QC, extract one frame per beat from the render and compare against the board:
duration in tolerance, plates present and inside safe zones, captions aligned to
whisper timings (temporal contiguity), hook content decoded within the first 2s.
A clip that doesn't match its keyframe is an objective regeneration case, not a
reopened creative debate.
