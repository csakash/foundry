---
name: foundry-screenwriting
description: The two-column script craft — beat format, camera intent, the 5-slot visual spec, anti-subjective language lint, word bands, compliance and delivery cues. Load at the script stage (02-script.json) of any foundry piece, or when reviewing/rewriting a script.
---

# Screenwriting — the two-column contract

The script is the last free-to-change artifact. Everything downstream (voice,
board, motion, captions) is generated FROM it, so it must be complete enough that
no stage after it invents anything.

## Beat format

Every beat row carries ALL of:

```
beat | name | PLAIN | t_start–t_end | VISUAL (5-slot spec) | AUDIO | plates | evidence[] | delivery_cue
```

- **`plain` comes first and is not optional.** One sentence, no jargon, on what a
  viewer actually sees and experiences in this beat — the line that reaches the
  review page and the only line a non-specialist will read. Write it BEFORE the
  5-slot spec. **If a beat cannot be said plainly in one sentence, it is not
  clear enough to build**, and no amount of shot detail rescues it. "That card is
  wiped straight off the screen and the frame goes completely empty for more than
  half a second while she tells you it wasn't the point" — not "DISAPPEARING
  transition on round-1 overlays, 0.6s negative-space beat".

- **Timing**: beats sum exactly to target duration. Word band: ~2.2–2.5 words/sec
  spoken (60s ≈ 130–150 words; 12s ≈ 30). Short-form VO runs faster than
  long-form — energy, no dead air.
- **Plates**: on-screen text with its named slot (persona `setups` carry plate
  coords). 3–5 words per plate block, 2–4s on screen.
- **Evidence**: every number or claim on screen cites a ledger id
  (`engine/evidence.py`) or the script fails lint before Gate 2.

## The 5-slot visual spec (fill every slot, N/A explicitly)

Video models describe subject and scene well but fail on motion, spatial framing,
and camera — so the script forces all five, per beat:

```
Subject:   type + distinguishing attributes; disambiguate if multiple
Motion:    actions in temporal order; interactions; locomotion vs gesture vs facial
Scene:     overlays listed SEPARATELY from setting + POV + time of day + dynamics
Spatial:   shot size (ECU/CU/MS/WS) + position in frame + FG/MG/BG depth + how these CHANGE
Camera:    speed · lens · height · angle · focus/DoF · steadiness · movement
```

Mark unused slots "N/A" out loud — silent omission is the classic failure that
produces ambiguous generation prompts. One line of camera intent per beat is
enough; the board stage expands it. This spec maps 1:1 onto
`engine/prompts/shot.md` slots.

## Subject transitions are named, not implied

When focus moves, label the mechanism: **revealing** (new subject enters/uncovered)
· **disappearing** (leaves/removed) · **switching** (cut/rack focus A→B) ·
**alternating** (repeated trade, e.g. split-presenter). One sentence on the
mechanism (cut, pan, reveal-by-light) so the board doesn't guess.

## Language lint (anti-subjective + anti-generic)

Forbidden as visual description — they constrain no pixels:
mood adjectives ("epic", "stunning", "cinematic", "powerful", "beautiful",
"dynamic", "sleek", "modern", "breathtaking") and empty product-speak
("innovative", "seamless", "state-of-the-art", "revolutionary", "cutting-edge").
Replace each with the visual cause: framing, light, movement, timing.

Also merged at this gate: `brand.tokens.json` banned phrases, charter never-list,
no return claims, no first-person AI-persona experience claims, disclaimer beat
present.

**On-screen AI labelling is charter-driven, never assumed.** Read
`accounts/@handle/charter.json` `visual_identity.label` and follow it in both
directions — some accounts require a persistent burned-in label, some forbid any
mark in the frame at all. Getting this backwards is a lint failure either way.
Two things are true regardless of the charter and are never traded away: the
platform's own AI-disclosure toggle stays ON (a platform-policy obligation, not a
creative choice), and an AI persona never claims personal experience — that is
the actual FTC exposure, and no label substitutes for it.

## Delivery cues (consumed by foundry-voice)

Each beat may carry a `delivery_cue`: pace, energy, emphasis words, pause
before/after in seconds. "Read naturally" is banned as a direction. One delivery
idea per beat — a beat needing three emotional turns is three beats.

Silence is structure: pause before a reversal, after a surprising claim, before
the final takeaway. Mark these in the script; they become audio timing, plate
timing, and (for key insights) 1–3s of deliberate visual hold.

## Spoken language rules

Write for the mouth, not the page: short sentences, contractions, concrete nouns.
Numbers pre-normalized for TTS ("twelve hundred", not "1,200"). Hinglish scripts:
Devanagari + Latin mix per `engine/prompts/voice.md`; authored script is the
caption source of truth (whisper translates Hinglish — align, don't transcribe).
