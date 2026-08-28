---
name: foundry-sound
description: Sound design and mix craft — ducking levels, music selection, SFX timing, loudness targets, AI-TTS processing chain, silent-master rules. Load at the produce/assemble stage of any foundry piece and when QC-ing audio.
---

# Sound — numbers, not taste

Every level below is a starting point measured against platform specs; adjust by
ear in 1dB steps, then write what you chose into the piece's manifest.

## Mix levels

| Element | Level | Note |
|---|---|---|
| VO / narration | −12 to −14 dB peak | the primary; everything ducks under it |
| Music under speech | −26 to −28 dB | our proven duck for talking pieces (deeper than the −18/−20 minimum accessibility asks) |
| Music under real clip audio | −26 to −28 dB | clip speech is primary (clip reels: `sound`/`volume` props) |
| SFX | −18 to −14 dB | brief accents only |
| Master | −14 LUFS integrated, −1 dBTP true peak | IG/TikTok/YT normalize down, not up |

EQ trick when speech fights music: cut 2–4kHz on the music bed (the
intelligibility band). Instrumental tracks only under VO — lyrics compete.

## Music selection

- BPM by energy: calm/explainer 90–110 · upbeat 110–130 · high-energy 120–140.
- Dynamically even tracks — no crescendos or drops under continuous narration.
- ElevenLabs Music v2 is our bed source (~$0.15); music starts at frame 1 for
  short-form (no silent intro).
- **Trending-audio formats master SILENT**: the sound is attached in-app at post
  time, so the visual arc must be timed to the chosen audio's emotional turn
  (`audio_turn_s` from `engine/moments.py` — e.g. peak lands ON the turn).

## SFX timing

Start a whoosh **10–20ms BEFORE the visual cut** — audio is processed faster than
image, and sound-then-sight reads as caused rather than decorated. Peak of the
SFX coincides with the moment of greatest visual change. Whoosh 400–500ms, pops
<200ms, impact hits <300ms at −12 to −6dB reserved for THE key stat/reveal.
Stacked SFX live in different frequency bands. Fine-tune in 1-frame steps.

## AI-TTS processing chain (before mixing)

AI voices have inconsistent dynamics — process, don't use raw:

1. High-pass 80–100Hz (rumble + TTS artefacts)
2. Cut ~500Hz (boxiness); boost 2–5kHz +2–3dB (presence); gentle cut 6–8kHz
   (AI sibilance)
3. Compress 3:1, attack 1–5ms, release 10–20ms, target 4–6dB reduction
4. De-ess 6–8kHz if needed; limit at −1.5dBTP

ffmpeg is sufficient (`highpass`, `equalizer`, `acompressor`, `deesser`,
`alimiter`) — add as a pipeline pass alongside `engine/degrade.py` (which handles
video; this chain is its audio sibling, run on VO before the composite).

## The phone test

Master check happens on phone speakers at arm's length, not headphones. If the
voice disappears, boost 2–4kHz on VO. If the music disappears entirely — fine;
if the SFX startle — drop 3dB. Captions carry the muted case (~80% watch muted);
the mix carries the other 20%.
