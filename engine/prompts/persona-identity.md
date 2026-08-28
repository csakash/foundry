---
family: persona-identity
version: 1
purpose: The character-sheet image prompt that locks a persona's face before any video is generated.
slots:
  name: {required: true}
  age_range: {required: true}
  heritage: {required: false, help: "Only where it is a genuine casting decision"}
  face: {required: true, help: "Two or three specific, describable features. Not adjectives."}
  hair: {required: true}
  build: {required: true}
  wardrobe: {required: true, help: "The persona's recurring uniform"}
  setting: {required: true, help: "Their recurring environment"}
  lighting: {required: false, default: "soft directional daylight from frame left, gentle falloff"}
  capture: {required: false, default: "a still frame from vertical video shot on a phone's front camera at arm's length — flat bright window light with no modelled shadows and highlights just clipping, natural skin sheen on the forehead, nose bridge and cheekbones rather than a matte finish, faint redness around the nostrils, individual flyaway hair strands catching light against the wall, mild motion softness, cool-neutral slightly desaturated colour, phone-lens depth with the background soft but not bokeh'd"}
  views: {required: false, default: "front, three-quarter left, three-quarter right, profile, plus neutral / mid-sentence / listening expressions"}
  negative: {required: false, default: "no retouching, no beauty filter, no bokeh, no studio lighting, no makeup gloss, no symmetrical perfection, no text, no watermark, not a professional photograph, no razor-sharp detail, no HDR portrait mode"}
limits:
  words: {min: 70, max: 205}
---

# Persona identity

The still library is the identity source of truth for every video model
downstream. Get this wrong and every clip inherits the drift.

## Pipeline (settled in `research/07`)

1. **Bootstrap** the master face — Nano Banana Pro or Higgsfield Soul 2, with
   the realism prompt below.
2. **Character sheet** — 6–10 angles and expressions via Nano Banana Pro edits,
   ~$1.50 per persona. Best identity hold across edits; **≤6 references is the
   sweet spot**, ≤14 the ceiling.
3. **Lock** — Flux.2 LoRA per persona on fal ($3–12 one-time, then $0.02/image)
   plus Soul ID ($3) for in-Higgsfield work.
4. **Produce** — Seedream with 3–4 sheet references ($0.04–0.08/shot). Same
   ByteDance family as Seedance video, so the stills and the motion agree.

Not gpt-image as the backbone: weakest cross-generation identity hold of the top
tier, most expensive at quality, and an editorial aesthetic that fights UGC. Its
one genuine lead is typographic end-cards.

**Total for three personas: $25–50, one time.**

## The anti-AI realism engine

The default failure mode of every current image model is a person who is too
symmetrical, too clean and too well lit to be filmed on a phone. Counter it
explicitly — this is the difference between a persona that reads as a creator
and one that reads as an ad:

- **Asymmetry, named.** One eyebrow slightly higher, a small mole, a scar, teeth
  that are not uniform. Two or three specific features beat any number of
  adjectives, and they are what the model holds onto across generations.
- **Skin that has texture.** Visible pores, faint under-eye shadow, no gloss.
- **Available light, not a rig.** One direction, honest falloff.
- **Clothing with wear.** A slightly creased collar photographs as real.
- **Ask for a video frame grab, not a portrait.** This is the single biggest lever
  and the easiest to miss. A model asked for "a photo" returns editorial-grade
  micro-detail that instantly reads as rendered. A model asked for *a still pulled
  from iPhone video* returns clipped highlights, lifted noisy shadows and softer
  skin — the exact artefacts a viewer's eye uses to decide something is real.
  The `capture` slot carries this; do not leave it empty.
- **Sheen beats matte.** "Unretouched, matte skin" was the wrong instruction — it
  produces an evenly-lit clay surface. Real phone footage of a real face shows
  specular sheen on the forehead, nose bridge and cheekbones, and faint redness
  around the nostrils. Ask for the shine, not its absence.
- **Hair must break up.** A uniform mass of hair is the second-loudest AI tell after
  matte skin. Name the flyaway strands catching light against the background.
- **Texture is not the realism lever — age is.** The correction above can be
  over-applied, and when it is, the model ages the subject a decade: pores,
  heavy freckling and specular sheen together read as sun damage, not youth. A
  real 24-year-old has smooth, even skin with a soft glow and almost no visible
  pore structure. State the age hard, ask for smooth young skin, and let only a
  *little* sheen carry the "real capture" signal. If the output looks 35 when you
  asked for 25, you over-indexed on texture.
- **Face length is the second aging tell.** Left unconstrained the model returns a
  long, angular, mature face. Name the shape — round, soft jaw, full cheeks.
- **Crop to the target ratio, THEN scale.** A model returns whatever aspect it
  likes (gpt-image-2 gives 2:3, fal returned 848x1264). Scaling straight to
  1080x1920 from anything that is not already 9:16 is a non-uniform stretch and
  the subject visibly narrows. Always `crop=W:H` to exact 9:16 first, then scale
  uniformly. For gpt-image-2's 1024x1536 that is `crop=864:1536` then scale.
- **gpt-image-2 moderation is stochastic, and it judges the OUTPUT.** Editing a
  frame whose subject wears revealing clothing can block on `categories=[sexual]`
  even when the prompt only describes the background — identical wording passes
  one call and fails the next. Wrap edits in a 3-4 attempt retry. If it blocks
  persistently, fal (`nano-banana-pro/edit`, `seedream/v4/edit`,
  `flux-pro/kontext`) does the same job without that filter.
- **Negate beautification explicitly — the don't-list outperforms the do-list.**
  Describing real skin is not enough; these models beautify by default. The most
  photoreal output of the whole build came from stacking explicit refusals:
  do NOT smooth, do NOT brighten, do NOT add a glow, do NOT even out the tone,
  no beauty filter, no retouching, no skin softening, no HDR, no sharpening.
- **Practical light sources beat described light.** Naming real emitters in the
  scene - a laptop screen throwing cool light up from the front, a lamp behind
  and out of frame putting a rim on the hair - produces far more convincing
  lighting than any adjective. Mixed colour temperature (cool front, warm back)
  is a strong realism cue on its own.
- **Flat light, not modelled light.** Creators film facing a window. Directional
  key-and-falloff is a studio signature — it reads as an ad no matter how good the
  skin is.

## Template

```
{name}, {age_range}, {heritage}. {build}.
Face: {face}. Hair: {hair}.
Wearing {wardrobe}.
Setting: {setting}.
Lighting: {lighting}.
Character sheet: {views}, consistent identity across all views, neutral background.
Capture: {capture}.
Unretouched, natural skin texture, candid framing.
Avoid: {negative}.
```

## Word band

70–205. Wider than the 55–130 that governs `shot`, because a character sheet is
specifying a reusable identity rather than a single clip — every feature you do
not name, the model re-rolls on the next generation. The band was raised from 160
when the `capture` slot landed: describing the capture treatment properly costs
~35 words and is worth every one of them.

## Rules

- **Wardrobe is a uniform.** A recurring outfit does more for recognisability at
  thumbnail size than facial detail does, and it makes the LoRA's job easier.
- **Setting recurs too.** Same wall, same window. Viewers key on the room.
- **Never a real person's likeness**, and never a description close enough to
  one to be arguable.
- **The persona has no history.** An AI persona must never claim personal
  experience or results — enforced from the persona's `banned` list, not from
  the writer remembering. This is an FTC exposure, not a style preference.

## Worked example

```
name:       Kavya
age_range:  27-30
heritage:   Indian
build:      slight, average height, slightly forward posture when listening
face:       a small mole below the left eye, faintly uneven front teeth,
            eyebrows that sit at slightly different heights
hair:       shoulder-length dark brown, centre part, a few strands out of place
wardrobe:   olive linen shirt, sleeves pushed to the forearm, thin gold chain
setting:    a plain off-white apartment wall with a window at frame left
```
