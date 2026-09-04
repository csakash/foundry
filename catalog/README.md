# Catalog — the preference & inspiration layer

Everything in this directory is **data, not code**. The foundry skills read the
catalog at brief/interview time; the engine never hard-codes a hook, persona,
geo, or intent. To extend the system you drop a file here — no script changes.

## Layout

| Dir | One file = | Consumed at |
|---|---|---|
| `briefs/` | a raw reference doc (markdown, any shape) — creative briefs, tone direction, client notes | `/foundry interview` + `/foundry brief` (read as inspiration context) |
| `hooks/` | one hook family (JSON) — opener, structure, example lines, compliance notes | Stage 1 (brief) and Stage 2 (script) |
| `personas/` | one creator archetype (JSON) — voice, energy, setting, what they'd never say | account birth + Stage 2 |
| `geos/` | one target market (JSON) — language mix, cultural cues, settings, local pain point, distribution notes | campaign fan-out + Stage 2 localization |
| `intents/` | one campaign intent (JSON) — why the piece exists, success metric, CTA style | Stage 1 (brief) + campaign layer |

**Formats** (chart replay, quote clip, news, myth buster, listicle, ambient loop)
live in `JOURNEY.md` + the foundry skills — they are *how* a piece is made.
Catalog entries are *why/who/where*. A piece = intent × format × hook × persona × geo.

## Adding your own preferences

1. **Quickest:** drop any markdown doc into `briefs/`. It will be read as
   inspiration context. Name it descriptively (`<topic>-<source>.md`).
2. **Structured (preferred once an idea recurs):** add a JSON file to the right
   subdirectory. Copy an existing file as the template — the schema is just the
   fields you see; unknown extra fields are fine and preserved.
3. Every JSON entry carries:
   - `id` — kebab-case, matches the filename
   - `source` — where it came from (doc path, meeting date, artifact URL)
   - `compliance` — claims that must be verified true for the geo before use
4. Delete or edit freely — git is the audit trail. Nothing else references
   entries by anything but `id`.

## The variation matrix

Campaign fan-out combines: **HOOK × BENEFIT × PERSONA × GEO × SETTING × PROOF
DEVICE × CTA** (see `briefs/ugc-creative-brief.md` §18). One video = ONE
surprising discovery — never stack every benefit into one script
(`briefs/ugc-tone-direction.md`, "Don't overload each video").

## Director's lint (applies to every script produced from this catalog)

1. "Would this person actually say this sentence to a friend?" — if no, rewrite.
2. "Can I tell it's an ad with the sound off?" — if yes, make it less produced.
3. "Are we explaining too many things?" — if yes, keep only the best discovery.
4. Claims (leverage, fees, 24/7, P&L, rewards, no-KYC) only where factually true
   and legally available for that geography. Historical performance is never a
   promise of future returns.
