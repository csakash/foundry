---
family: mindset
version: 1
purpose: The narrative script for a wealth-mindset reel — the message that does the actual work.
slots:
  behaviour: {required: true, help: "The ordinary thing the viewer already does. Concrete objects, not abstractions."}
  loss: {required: true, help: "What that behaviour quietly costs. Stated as mechanism, never as a number you cannot evidence."}
  inversion: {required: true, help: "The same money, pointed the other way"}
  mechanism: {required: true, help: "WHY the inversion compounds. This is the line people screenshot."}
  close: {required: false, help: "The reframe restated in one clause. No CTA."}
limits:
  words: {min: 55, max: 150}
forbid_in_slots: [guaranteed, risk-free, you should buy, I made, will make you]
---

# Mindset narrative

## What actually carried 8.9M views

Scraped from the reference reel (`@daytrading`, shortCode `DOQsfRIElop`,
692,538 likes, 67.1s, posted 2025-09-06 — the format #1 example in your strategy
report), the caption is the entire product:

> Many people spend their money on products that lose value as soon as they are
> bought… owning shares of the companies that make those products can build
> lasting wealth.

That is a complete argument in two sentences, and it is **100% original writing**.
The celebrity footage is wallpaper — it holds the eye while the sentence lands.
Which is the strategic point: the format's engine is the *reframe*, not the
clip. A reframe this good would have worked over almost any arresting visual.

So this family is where the effort goes. The footage layer is interchangeable;
the sentence is not.

## The four-beat structure

Every high-performing example in the scrape follows the same shape:

| Beat | Job | Reference |
|---|---|---|
| `behaviour` | Name what the viewer already does, in objects | "a new phone, pair of shoes, or watch" |
| `loss` | Reveal the cost as a mechanism | "their worth drops the moment they are used" |
| `inversion` | Same money, opposite direction | "owning shares of the companies that make those products" |
| `mechanism` | Why it compounds — the screenshot line | "stocks represent a part of the business itself" |

**Concrete objects beat abstractions.** "A new phone, pair of shoes, or watch"
outperforms "consumer goods" because the viewer sees their own shelf. Name three
things a person can picture.

## Template

```
{behaviour}. {loss}.
{inversion}. {mechanism}.
{close}
```

## Rules

- **No number without evidence.** A projection needs a `claims[]` entry citing an
  evidence id, or the build fails. The reference reel makes zero numeric claims —
  that is not an accident, it is what makes it safe to run at scale.
- **Describe a mechanism, never an instruction.** "Stocks represent a part of the
  business" is education. "Buy index funds" is advice. The whole format lives on
  the right side of that line, which is why your strategy report tags it
  "no compliance risk from personal advice".
- **No CTA in the script.** The reference puts the follow prompt in the caption,
  not the voiceover. Keep the spoken piece pure.
- **60–67 seconds.** The reference ran 67.1s. This is the one format where long
  works, because the argument needs room — your scrape put 40–90s as the band for
  narrative content versus 10–14s for faceless visual formats.

## Anti-patterns

- Moralising about spending. The reference is careful: products "may feel
  rewarding". Contempt for the viewer's choices kills shares.
- Two ideas in one reel. One reframe, fully landed.
- Naming a specific ticker. Turns education into a recommendation instantly.
- Borrowing the reference's sentences. Extract the skeleton, never the content —
  the copyright firewall in `PIPELINE-V2.md` is not optional for a branded account.

## Worked example

```
behaviour:  Most people upgrade the phone, the headphones, the watch
loss:       Every one of those is worth less the moment it leaves the box
inversion:  The same money can buy a piece of the company that made them
mechanism:  A product is finished when you buy it — a business keeps working after you do
close:      One depreciates on your shelf. The other one shows up to work.
```
