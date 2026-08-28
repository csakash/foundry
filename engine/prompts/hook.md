---
family: hook
version: 1
purpose: The first 1-3 seconds of spoken script plus its opening frame.
slots:
  archetype: {required: true, enum: [negative_frame, pattern_interrupt, number_tease, contradiction, pov, comment_bait, vibe_check]}
  claim: {required: true, help: "The single idea, plain language, no numbers unless evidence-backed"}
  subject: {required: true, help: "What the viewer is looking at in frame 1"}
  turn: {required: false, help: "The pivot the hook promises to deliver"}
limits:
  spoken_words: {min: 4, max: 14}
  visual_change_by_s: 1.5
spoken_from: [claim]
forbid_in_output: [link in bio, sign up, download now, buy now]
---

# Hook

The highest-leverage 40 words in the whole pipeline. Your Apify data put the
strongest share rates on reels whose first second did one thing: **contradicted
something the viewer already believed.** Everything below follows from that.

## Archetypes

| Archetype | Shape | Live example from the scrape |
|---|---|---|
| `negative_frame` | Name the mistake before the fix | "The MOST COMMON beginner mistake in crypto" — 1.28M views |
| `pattern_interrupt` | Challenge current behaviour | "Many people spend their money on products that lose value…" — 8.9M views |
| `number_tease` | A number with the mechanism withheld | "$100/month for 10 years is $23,000 — here's why" |
| `contradiction` | Two true things that shouldn't both be true | "Nothing was bought. Nothing was sold. The price moved 4%." |
| `pov` | Put the viewer inside the moment | "POV: you set a stop loss and the market reverses" |
| `comment_bait` | Withhold the payoff behind an action | "Comment TRADE for the full breakdown" |
| `vibe_check` | Name an aspiration, then prove it with B-roll | "If this is your vibe…" — 450K views (DcLhmbRvEzG) |

`negative_frame` is the default. It carried the highest engagement in the scrape
and it is the safest for a regulated brand, because naming a mistake is education
rather than a recommendation.

## Template

```
[frame 1: {subject}, already mid-motion — no establishing shot, no logo]
[delivery: {archetype}]
{claim}
{turn}
```

## Rules the linter enforces

- **The claim is 4–14 words.** Under four is a fragment; past fourteen the viewer
  has already scrolled. At ~150 wpm, fourteen words is about 5.6 seconds — the
  claim itself should land well inside three. `turn` is measured separately: it
  extends the hook unit to roughly five seconds, and it is the promise the body
  has to pay off.
- **The frame must change by 1.5s.** A static opening frame reads as an ad. Cut,
  push in, or move something.
- **No CTA in the hook.** A hard CTA in the first three seconds is the single
  most reliable scroll-past trigger in the "What Fails" column of your research.
- **No banned phrases.** Checked against `brand.tokens.json`.

## Anti-patterns

- Starting with the brand name or a logo sting. Nobody grants attention to an
  advertiser; they grant it to a person making a point.
- A question with an obvious answer ("Want to make money?"). Rhetorical questions
  cost a beat and return nothing.
- Front-loading the disclaimer. Disclaimers ride as a persistent super and in the
  outro — never as the opening line.
- A number the spec cannot evidence. If `claim` contains a figure, the VideoSpec
  needs a matching `claims[]` entry with an evidence id, or the build fails.

## Worked example

```
archetype: negative_frame
subject:   a phone showing an order ticket, thumb hovering over Confirm
claim:     Most people size a position by what they hope to make
turn:      Professionals size it by what they can afford to lose
```

An 11-word claim, one visual, and a turn that the next eight seconds must pay
off. That last part is not optional — an unpaid hook trains the algorithm against
the whole account.
