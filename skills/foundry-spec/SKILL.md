---
name: foundry-spec
description: Spec a Foundry piece in one question round (at most five questions), then render the approval sheet — layout sketch, real first-frame candidates, product clip, caption in place. Use after `foundry new`, or when the user describes a video they want. Wraps `foundry resolve / set / sheet`.
allowed-tools:
  - Bash
  - Read
  - AskUserQuestion
---

# /foundry-spec <piece>

The only round of questions for a piece. The resolver already filled everything it could
from the recipe, the creator pack, the format defaults and the account's last shipped piece.

1. `foundry resolve <piece> --json`. If `problems` is non-empty, fix or report them first.
2. If `questions` is empty, skip to 4.
3. Ask **every** open question in **one** AskUserQuestion call (never a second round, never
   a sixth question). Use each question's `options` and `recommended`. For the hook line:
   offer 2-3 lines you wrote in the shape of a mechanism from `catalog/hooks/mechanisms.json`
   that suits the scene's faces, plus "my own words". Then write all answers at once:
   `foundry set <piece> hook.line="..." assets.0.path=... hook.mechanism=<m> --touch --json`
   (`--touch` exactly once: it is the human's answer round). If `warnings` lists charter or
   slop problems with the line, say so in one sentence; the human's line stands.
4. `foundry sheet <piece> --json`. On `BLOCKED sheet.safety_refused`, name the phrase and
   stop. Report `font_substituted` if true: line breaks can move.
5. Show `sheet/sheet.png` (and point to `sheet/index.html`). Ask one question: approve which
   candidate, or change something. On approval run `foundry approve <piece> --candidate cN`.
   A change request is `foundry set` (no `--touch`) plus a re-render, not a new interview.
6. Report: approved candidate, frozen ceilings, next step `/foundry-build`.
