# Pipelines — saved, reusable production recipes

A **pipeline** is a produced post, frozen as a recipe. Every approved decision —
the ingredients, the script skeleton, the board structure, the voice, the edit
route — is captured so the next run **skips the interview entirely**: change a
few parameters, regenerate, done.

This is how one good video becomes a series, and how a series becomes a
parallel batch.

## Lifecycle

1. **Save.** After a piece passes QC, `/foundry save <name>` writes
   `pipelines/<name>.json` from the piece's artifacts. Nothing is authored by
   hand — the recipe is derived from what was actually approved.
2. **Run.** `/foundry run <name>` (optionally with overrides:
   `topic="silver"`, `geo=india`, `voice=...`) regenerates only the stages the
   changed parameters touch. Unchanged, human-approved decisions are NOT
   re-asked and NOT re-judged — they were already gated once.
3. **Gate collapse.** A recipe run has exactly **one human gate before spend**:
   the review page with the new parameters filled in ("same recipe, new
   values — good to produce?"). QC still runs per piece after production.
4. **Batch.** `/foundry run <name> --matrix` over a list of parameter sets
   fans out one run per set — the parallel-production unit (see the router
   skill).

## Recipe schema (`pipelines/<name>.json`)

Copy `example-recipe.json`. The important fields:

- `id`, `name`, `made_from` — provenance: which `work/<account>/<slug>/` this
  was frozen from, and when.
- `post_type` — `video` | `image` | `carousel`, plus style
  (`ugc` / `faceless` / `ambient` / `clip` / …).
- `ingredients` — the locked ingredient manifest (see the router skill's
  ingredient list): sound, voice, character, hero image, duration, video
  model, edit route, render spec, brand assets. These are the decisions that
  do NOT change between runs.
- `parameters` — the knobs that DO change per run, each with a name, a plain
  description, and a default (e.g. `topic`, `hook_line`, `ticker`, `geo`,
  `language`). Keep this list minimal — a recipe with twenty parameters is an
  interview wearing a costume.
- `stage_map` — for each parameter, which stages must re-run when it changes
  (e.g. `topic` → script + board + produce; `voice` → produce only).
- `cost_per_run` — the known invoice, from the frozen piece's actuals.

## Rules

- A recipe is **derived, never hand-edited** — to change a locked decision,
  run the piece through the normal journey once and re-save.
- Recipes are parallel-safe by construction: every locked decision was
  already human-approved, so N runs need no shared state beyond the recipe
  file and each run's own `work/` directory.
- Charter and compliance lint STILL run on every recipe run — a recipe never
  bypasses Gate-4 checks, only the creative re-interrogation.
