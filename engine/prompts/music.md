---
family: music
version: 1
purpose: An ElevenLabs Music v2 bed for a reel.
slots:
  mood: {required: true, help: "The emotional job, not a genre label"}
  genre: {required: true}
  instrumentation: {required: true}
  bpm: {required: true, help: "Integer. Match the cut rhythm."}
  structure: {required: false, default: "no intro — start on the downbeat; hold energy flat; no outro"}
  length_s: {required: true}
limits:
  words: {min: 15, max: 70}
forbid_in_slots: [vocals, lyrics, singing, choir]
---

# Music

## Why generate rather than use trending audio

Two different jobs, and they need different sources:

- **Organic reach** wants platform-native trending audio, attached in the
  Instagram or TikTok editor at post time. Never baked into the render — a
  trending sound baked into pixels gets no algorithmic credit and carries the
  copyright exposure.
- **Everything else** — paid usage, cross-posting, YouTube, anything that must
  survive a takedown — wants generated music. ElevenLabs Music v2 is trained on
  licensed data and every track is cleared for commercial use on self-serve
  plans (the carve-out is film, TV and studio games, which is not you).

At roughly $0.40 per minute this is about ₹35 a reel, and it removes an entire
category of platform risk.

## Template

```
{genre} instrumental for a {length_s}-second vertical video.
Mood: {mood}. Instrumentation: {instrumentation}. Tempo: {bpm} BPM.
Structure: {structure}.
Instrumental only — no vocals, no lyrics, no vocal samples.
```

## The rules that actually matter for short-form

- **No intro.** A four-bar ramp costs you the hook. Ask for the downbeat at 0:00.
- **Flat energy, not a build.** A 13-second reel loops; a track that builds to a
  drop fights the loop point. Save arcs for 60-second pieces, and place the lift
  under the turn, not the outro.
- **BPM matches the cut rhythm.** If the edit averages a 2-second shot, ~120 BPM
  puts a cut on every fourth beat. Demo 004's reference reel ran 2.06s average
  shot length across 34 cuts — that is a ~117 BPM feel.
- **Instrumental, always.** Lyrics compete with the voiceover for the same
  channel in the listener's attention. The frontmatter forbids the word outright.
- **Duck under the VO.** Mixed in post, not prompted — bed sits 14–18 dB under
  speech, with a gentle sidechain on the voice.

## Mood vocabulary that works for finance short-form

| Content | Mood slot | Avoid |
|---|---|---|
| Screen recording / trade replay | `taut, restrained, rising tension without release` | triumphant, celebratory |
| Chart education | `steady, analytical, unhurried confidence` | dramatic, cinematic |
| Wealth mindset | `warm, reflective, spacious` | inspirational-corporate |
| Myth buster | `dry, propulsive, slightly sceptical` | comedic |

"Triumphant" and "celebratory" are listed as avoids deliberately. Music that
sounds like a win turns an educational clip into an implied performance claim —
the same exposure as saying it out loud, arriving through a channel your script
linter cannot read.

## Worked example

```
genre:           minimal electronic
mood:            taut, restrained, rising tension without release
instrumentation: muted pulse bass, sparse rim-shot percussion, one held synth pad
bpm:             118
length_s:        13
structure:       no intro — start on the downbeat; hold energy flat; no outro
```
