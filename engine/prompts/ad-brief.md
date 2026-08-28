---
family: ad-brief
version: 1
purpose: The structured decomposition of an inspiration reel, and the authoring brief that comes out of it.
slots:
  duration: {required: true, help: "Seconds, integer"}
  aspect: {required: false, default: "9:16 vertical"}
  product: {required: true, help: "What is being sold or taught"}
  audience: {required: true, help: "Who this is for — specific enough to exclude people"}
  hook: {required: true, help: "First 1-3 seconds, spoken. 4-14 words."}
  problem: {required: true, help: "What the viewer already cares about"}
  product_moment: {required: true, help: "What the product does or shows on screen"}
  proof_moment: {required: true, help: "Visual proof — demo, mechanism, document. NOT a results claim."}
  camera: {required: true, help: "Shot style and movement"}
  style: {required: true, enum: [ugc, product_ad, cinematic, app_promo, direct_response, native_social]}
  audio: {required: false, help: "Voiceover, music, sound design"}
  energy: {required: true, enum: [jolly, serious, no_main_character]}
  cta: {required: true, help: "Soft visual ending or spoken action"}
  restrictions: {required: false, default: "no fabricated claims, no fake testimonials, no logo distortion, no unreadable text, no performance or return promises"}
limits:
  words: {min: 90, max: 320}
forbid_in_slots:
  - guaranteed
  - risk-free
  - or your money back
  - we work for free
  - double your
  - profit
  - returns of
---

# Ad brief

## The rule this family encodes

**Every inspiration reel is decomposed into these fields before anything is
generated.** Not summarised, not "vibed" — filled in, field by field, from what
the reference actually does. Only then is each field re-authored for our topic.

This exists because the failure mode is subtle: watching a reel and "making one
like it" reproduces the surface (a talking head, a caption bar) while losing the
thing that made it work (a qualification line at 25s that filters the audience,
a proof moment that isn't a claim). Fields force you to notice both.

Two passes, same template:

1. **Decompose** — fill every field from the reference. Where the reference does
   something you cannot copy, write what it does anyway; you need to see it.
2. **Translate** — re-author each field for our product and audience. Fields
   that carry legal weight (`proof_moment`, `cta`, `restrictions`) are rewritten
   from our compliance posture, never carried across.

Then classify: does the translated brief fall into one of the existing formats
in `engine/formats.py`, or is it a new one? A brief that needs a composition
nothing else uses is a new format, and it gets added to the router.

## Template

```
Create a {duration}-second {aspect} video for {product}.
Audience: {audience}.
Hook: {hook}.
Problem or desire: {problem}.
Product moment: {product_moment}.
Proof moment: {proof_moment}.
Camera: {camera}.
Style: {style}.
Audio: {audio}.
Main character energy: {energy}.
CTA: {cta}.
Restrictions: {restrictions}.
```

## The three fields that do not translate

Most fields carry across from a reference more or less intact. Three never do:

- **`proof_moment`.** In a direct-response ad this is almost always a results
  claim — client counts, revenue figures, named case studies. For a regulated
  financial product a results claim is the single highest-exposure thing you can
  put on screen. **Our proof is always mechanism, never outcome**: show the
  custody structure, the order ticket, the fee line, the audit. Something the
  viewer can verify rather than something they have to believe.
- **`cta`.** A hard direct-response CTA ("click below", "book a call") converts,
  and it also turns education into solicitation. Keep it soft and informational.
- **`restrictions`.** Rewritten from `brand.tokens.json → compliance`, never
  copied from the reference. The reference had none.

## Field notes

- **`hook`** is validated separately by the `hook` family — 4–14 spoken words.
  Fill it here, then build it there.
- **`audience`** should exclude people. "Anyone interested in investing" is not
  an audience; the reference's "online service businesses selling at $2,500 or
  higher" is, and it is doing real work — the disqualification is what makes the
  qualified viewer lean in.
- **`energy`** maps to the persona and to the shot prompt's delivery line. The
  three values are deliberately coarse; anything finer is the voice family's job.
- **`product_moment`** for our formats is usually a screen capture or a rendered
  chart, not a hand holding an object. Name the artefact.

## What the linter blocks

`forbid_in_slots` rejects the vocabulary that direct-response ads run on and a
financial brand cannot: guarantees, risk reversals, profit and return language.
If a translated brief trips it, the offer is wrong — not the wording.
