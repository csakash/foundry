---
name: foundry-voice
description: Voice performance direction — making TTS narration sound directed, not read. Delivery cues, ElevenLabs settings, sample gate, lipsync routing, locked persona voices. Load whenever generating or reviewing narration/VO for a foundry piece.
---

# Voice — directed, not read

Generated narration sounds read when nobody directed it. Every narration-led
piece carries a voice performance plan from script to asset; "read naturally" is
banned as a direction.

## The performance plan

Top level (once per piece):

```json
{
  "performance_intent": "warm, decisive; human pauses; no announcer polish",
  "pacing_profile": "conversational-fast (short-form)",
  "energy_curve": "hot hook → warmer middle → deliberate close",
  "pause_policy": "short pause after setup lines; long pause before reversals"
}
```

Per beat (from the script's `delivery_cue`): pace, energy, 1–3 emphasis words,
pause_before/after seconds. One delivery idea per beat.

## Our stack specifics (measured, not guessed)

- **Locked voices are law.** Personas use their locked ElevenLabs voice_id
  (`persona.json`; e.g. Maeve `9gTh8oJopoWLAad9GOXP`, settings frozen
  0.5/0.75/0/1.0, model eleven_v3). Never re-design a voice mid-account; voice
  drift breaks the account canon.
- **eleven_v3 audio tags** (e.g. `[excited]`) sparingly — one per script region,
  placed per `engine/prompts/voice.md`; speed 1.0–1.06 for jolly variants.
- **One request per episode**, ≤58s of audio. Pre-normalize numbers. Hinglish:
  Devanagari+Latin mix; align authored script onto whisper timings (whisper-en
  translates Hinglish — never use its text as captions).
- **Lipsync routing:** external locked-voice track → Wan 2.7 Higgsfield (≤15s
  segments; audio reference ≤15s so cut a 14s ref). Single-pass ≤30s where voice
  approximation is acceptable → Seedance 2.5 native audio + ElevenLabs take as
  style reference + script verbatim in prompt. Voice+identity reference with seed
  → Wan 3.0 via fal. Never Seedance `audio_references` + `generate_audio:false`
  expecting lipsync (it doesn't align phonemes).
- Silent formats (ambient_loop, profit_replay) have NO VO by design — do not add
  narration to them; the caption or the trending audio carries the message.

## The sample gate

Before batch generation:

1. Generate a sample from the **most performance-sensitive beat** (the reversal,
   the emotional turn) — not automatically the hook.
2. Check: pace, pauses land where the script marked them, emphasis words audible,
   energy curve present, no TTS artefacts on names/numbers.
3. Flat sample → adjust the plan or settings, resample. Only then batch.
4. **Freeze after approval.** Provider, voice, model, speed, stability change ⇒
   new sample, no exceptions. Record approved settings in the asset manifest.

## Failure conditions (treat as lint failures)

- Narration-led script with no performance plan.
- A beat direction that is only "natural/engaging/expressive" with no concrete
  pace/pause/emphasis cue.
- Final narration generated from raw script text when delivery cues existed.
- VO generated before the script passed Gate 2 (words are free until audio
  exists; after audio, every word change invalidates captions, ducking, lipsync).
