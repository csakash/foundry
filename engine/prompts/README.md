# Prompt library

Prompts are **build artefacts, not chat improvisation**. Every prompt that reaches
a paid model comes from a versioned template in this directory, gets its slots
filled from the VideoSpec, and passes a linter before it costs anything.

Three reasons this is a directory and not a habit:

1. **Reproducibility.** A video that cost 390 credits should be re-creatable. The
   rendered prompt is archived next to the output, with the template version.
2. **Compounding.** When a hook archetype outperforms, the win lands in a template
   where every future video inherits it. Improvisation does not compound.
3. **Compliance.** `brand/brand.tokens.json → compliance.banned_phrases` is checked
   at build time. A prompt containing "guaranteed returns" fails before render,
   not after publish.

## Architecture

Each family is one markdown file: **YAML frontmatter is the machine contract**
(slots, limits, validators) and **the body is the researched craft guidance**
(why the structure is what it is, worked examples, anti-patterns).

```
python -m engine.prompts list
python -m engine.prompts show shot
python -m engine.prompts build shot --slots slots.json
python -m engine.prompts build hook --set archetype=negative_frame --set claim="..."
```

The builder refuses to emit a prompt that is missing a required slot, falls
outside the family's researched word band, or contains a banned phrase.

## Families

| File | Feeds | Research basis |
|---|---|---|
| `hook.md` | first 1–3s of every script | `research/05` §1, Drevon strategy §"What Works" |
| `shot.md` | Seedance / Kling / Higgsfield video gen | 7-layer SAEC structure, 60–120 word band |
| `voice.md` | ElevenLabs `eleven_v3` | `research/09`, v3 audio-tag docs |
| `music.md` | ElevenLabs Music v2 | licensed-training model, self-serve commercial |
| `persona-identity.md` | Nano Banana Pro / Seedream identity lock | `research/07`, Higgsfield character-sheet workflow |

## The one rule

**A template never contains a factual claim.** Claims live in the VideoSpec and
cite an evidence id. Templates contain structure, craft and constraints. This is
what keeps a model from inventing a number inside a prompt where no linter can
see it.
