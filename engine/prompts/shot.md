---
family: shot
version: 1
purpose: One generated video clip (Seedance, Kling, Higgsfield acted shots).
slots:
  subject: {required: true, help: "Who or what, with the identity anchor if a persona"}
  action: {required: true, help: "One continuous action. Not a sequence."}
  setting: {required: true}
  camera: {required: true, help: "Named move + framing. 'static medium close-up' is a valid answer."}
  lighting: {required: true, help: "Direction and quality, not just a time of day"}
  style: {required: false, default: "handheld phone video, natural colour, slight sensor grain, unretouched skin"}
  audio: {required: false, help: "Only for models with native audio"}
  negative: {required: false, default: "no text overlays, no watermarks, no logo, no split screen, no captions"}
limits:
  words: {min: 55, max: 130}
---

# Shot

## The structure, and why it is this one

Current prompt-engineering research converges on **seven ordered layers**:
subject → action → setting → camera → lighting → style → audio. The ordering is
not cosmetic. Diffusion-transformer video models map early tokens to subject
identity and later tokens to rendering treatment, so a prompt that leads with
style and buries the subject gets a beautifully lit clip of the wrong thing.

**Length band: 55–130 words.** A 60-word prompt with clear section boundaries
consistently beats a 200-word stream of consciousness, because each dimension
maps cleanly to the layer that consumes it. Past ~130 words the risk of internal
contradiction rises faster than the added control.

**Minimum bar for a prompt worth iterating on: a named camera move and a lighting
direction.** If a prompt has neither, the model picks, and it picks differently
every seed — which is exactly the identity drift that kills a persona account.

## Template

```
{subject}. {action}.
Setting: {setting}.
Camera: {camera}.
Lighting: {lighting}.
Style: {style}.
Audio: {audio}.
Avoid: {negative}.
```

Labelled sections outperform prose for this family. The labels are the "clear
section boundaries" the length research is pointing at.

## Model routing notes

| Engine | Responds best to | Watch for |
|---|---|---|
| Seedance (via Higgsfield) | Concrete physical action verbs; `omni_reference` for identity | Never call it via raw API — ~$41/min vs. subsidised credits |
| Kling | Stylised visual descriptors | Lipsync rejected in demo 002 — head/hand motion reads unnatural |
| Veo | Precise camera language; integrates audio cues natively | Most expensive tier |
| fal InfiniteTalk / OmniHuman | Audio-driven — the *audio* carries performance, not the prompt | Prompt controls framing and identity only |

For audio-driven avatar models the shot prompt shrinks: the ElevenLabs take is
doing the acting, so spend the words on framing, wardrobe and identity anchor,
and leave `action` at the level of "speaking to camera, small natural gestures".

## Framing rules from demo 004

Learned the expensive way, so they are defaults now:

- Ask for the head in the **upper-middle third with headroom**. Demo 004's
  split-screen crop took the top of the presenter's head off at
  `presenterFocus: 0.24`; 0.10 was correct. Prompting for headroom makes the
  crop forgiving.
- One continuous action per clip. A prompt describing a sequence produces a cut
  the model chooses, at a moment you did not.
- Lock the seed per persona and record it in the VideoSpec. Demo 004 used
  creator seed `3589826f` across four clips — that is why they intercut.

## Anti-patterns

- Stacking three camera moves ("dolly in while orbiting and tilting"). Pick one.
- "Cinematic, 8k, masterpiece, award-winning". Quality adjectives are noise in
  2026 models; they consume tokens that could have specified lighting direction.
- Describing what should *not* happen inside the positive prompt. That is what
  `negative` is for.
- Photoreal-plus-polish for UGC. Your research is explicit: overly polished
  production breaks authenticity. The default style string above deliberately
  asks for grain and unretouched skin.

## Worked example

```
subject:   Kavya, 28, Indian woman, shoulder-length dark hair, olive linen shirt
           [identity: persona sheet refs 1-4]
action:    speaking to camera, small natural hand gestures, occasional glance down
setting:   a plain apartment wall, soft daylight from a window at frame left
camera:    static medium close-up, phone height, head in upper-middle third with headroom
lighting:  soft directional daylight from frame left, gentle falloff on the right cheek
style:     handheld phone video, natural colour, slight sensor grain, unretouched skin
negative:  no text overlays, no watermarks, no logo, no split screen, no captions
```

72 words. Every layer specified, nothing contradictory, crop-forgiving framing.
