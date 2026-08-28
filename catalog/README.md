# Catalog — the preference & inspiration layer

Everything in this directory is **data, not code**. The foundry skills read the
catalog at interview/brief time; nothing in a skill or engine hard-codes a hook
line, persona, geo rule, or campaign intent. To extend the system you drop a
file here — no skill edits, no code changes.

## Layout

| Dir | One file = | Consumed at |
|---|---|---|
| `briefs/` | a raw reference doc (markdown, any shape) — creative briefs, tone direction, client notes, meeting extracts | `/foundry interview` + `/foundry brief` (read as inspiration context) |
| `hooks/` | one hook family (JSON) — opener, energy, structure, example lines, anti-pattern, compliance notes | Stage 1 (brief) and Stage 2 (script) |
| `personas/` | one creator archetype (JSON) — voice, energy, settings, what they'd never say | account birth + Stage 2 |
| `geos/` | one target market (JSON) — language mix, cultural cues, settings, local pain point, distribution notes | campaign fan-out + Stage 2 localization |
| `intents/` | one campaign intent (JSON) — why the piece exists, success metric, CTA style | Stage 1 (brief) + campaign layer |

**Formats** (how a piece is made — chart replay, quote clip, news, myth buster,
listicle, ambient loop, …) live in the skills and the host project's format
registry. Catalog entries are *why/who/where*. A piece =
**intent × format × hook × persona × geo**.

## Adding your own preferences

1. **Quickest:** drop any markdown doc into `briefs/`. It is read as inspiration
   context. Name it descriptively (`<topic>-<source>.md`).
2. **Structured (preferred once an idea recurs):** add a JSON file to the right
   subdirectory. Copy a sibling file as the template — the schema is just the
   fields you see; extra fields are fine and preserved.
3. Every JSON entry carries:
   - `id` — kebab-case, matches the filename
   - `source` — where it came from (doc path, meeting date, artifact URL)
   - `compliance` — claims that must be verified true for the audience/geo
     before use (becomes a Gate 4 check)
4. Delete or edit freely — git is the audit trail. Nothing references entries by
   anything but `id`.

Briefs record the catalog ids they used
(`01-brief.json` → `"catalog": {"hook": …, "persona": …, "geo": …, "intent": …}`),
so performance data can later be joined back to catalog picks.

## The variation matrix

Campaign fan-out combines: **HOOK × BENEFIT × PERSONA × GEO × SETTING × PROOF
DEVICE × CTA**. This produces dozens or hundreds of creatives that don't feel
like copies. One video = ONE surprising discovery — never stack every benefit
into one script.

## Director's lint (Gate 2, for UGC-style pieces)

1. "Would this person actually say this sentence to a friend?" — if no, rewrite.
2. "Can I tell it's an advertisement with the sound off?" — if yes, make it less produced.
3. "Are we explaining too many things?" — if yes, keep only the best discovery.
4. Claims are only used where factually true and legally available for that
   geography. Historical performance is never a promise of future outcomes.

## Localization rule

Recreate natively, never translate. Give the local creator the IDEA and let them
improvise in their own words — local slang, humor, settings, pacing. Same idea,
not same dialogue.
