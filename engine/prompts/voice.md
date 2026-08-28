---
family: voice
version: 1
purpose: The ElevenLabs eleven_v3 script, marked up for delivery.
slots:
  script: {required: true, help: "Final spoken text, numbers already normalised"}
  persona: {required: true, help: "Persona slug — resolves the locked voice_id"}
  intent: {required: false, enum: [explain, warn, correct, walkthrough, reflect], default: explain}
  tags: {required: false, help: "1-3 audio tags, from the tested set only"}
limits:
  spoken_seconds: {max: 58}
  words: {min: 20, max: 150}
forbid_in_output: ["₹", "$", "%", "10,00,000"]
---

# Voice

## Model and settings — frozen, not tuned per video

`eleven_v3` for generation. Settings are pinned in git and do not move between
episodes: stability 0.5, similarity 0.75, style 0, speed 1.0, seed 42,
`model_id` always explicit. A voice that drifts between episodes is a different
creator every week, and the parasocial bond your research identifies as the
highest follower-conversion mechanic never forms.

**One request per episode, ≤58 seconds.** Concatenating separately-generated
takes produces audible prosody seams at the joins.

## Template

```
{tags} {script}
```

The tags slot is placed ahead of the line it modifies; the builder drops it
entirely when unset, which is the correct default for a plain explainer. Voice
selection is not part of the prompt — `{persona}` resolves to the locked
`voice_id` in `personas/<slug>/persona.json`, so a take can never be generated
against the wrong voice by editing prompt text.

## Audio tags

v3 reads bracketed cues as *performance direction rather than words to speak*.
Tags span emotion (`[excited]`, `[worried]`), delivery and pacing (`[pause]`,
`[rushed]`, `[drawn out]`, `[whispers]`), and human reactions (`[laughs]`,
`[sighs]`).

Rules that keep this from turning into a costume box:

- **1–3 tags per episode, from a tested set.** Every new tag is a variable; an
  untested tag on a locked brand voice is a coin flip you pay for.
- **Tags go where the turn happens** — before the pivot, not scattered.
- **Combine sparingly.** `[tired] It's been a long day… [upset] How many more?`
  works because the two tags mark a genuine shift. Three tags in one sentence
  fight each other.
- **The hook gets no tag.** Let the writing carry the first three seconds; a tag
  there tends to read as performed rather than urgent.

## Number normalisation — the linter blocks the raw forms

Write numbers as they should be *said*, never as they are written. The frontmatter
forbids `₹`, `$`, `%` and Indian-grouped digits in the output for this reason.

| Never | Always |
|---|---|
| `₹2,00,000` | `do lakh rupees` |
| `$10,000` | `ten thousand dollars` |
| `10.7%` | `ten point seven percent` |
| `2026` | `twenty twenty-six` |

Whisper will also mis-split these on the caption pass — demo 004 needed a cleanup
merging `1` + `.2` into `1.2` and `10` + `.7` + `%` into `10.7%`. Normalising at
the source removes half that class of bug.

## Hinglish

Devanagari for any Hindi word whose pronunciation must be exact; Latin for the
rest. faster-whisper *translates* Hinglish rather than transcribing it, so
captions come from aligning the authored script onto Whisper's timings — never
from Whisper's text. That aligner already exists in `pipeline/`.

## Consistency QA

Every render is checked against the golden episode-1 reference with a
speaker-similarity embedding. Below threshold, the take is rejected before it
reaches video — a drifted voice discovered after a 390-credit lipsync job is an
expensive way to learn the setting changed.

## Anti-patterns

- Tuning stability per video "to get more energy". Rewrite the line instead.
- Time-stretching to hit a duration. It shifts formants and the voice stops
  matching the reference. Cut words.
- An identical intro line every episode is *good* — it is a prosody anchor, and
  it gives the similarity check a fixed comparison window.
