---
name: foundry-cast
description: Cast a Foundry creator — bootstrap master candidates, have the human pick one, generate the mandatory character sheet, measure skin on both, and lock a pack only when they match. Use before the first piece for a new creator, or when the user says "new influencer / persona / creator". Wraps `foundry cast`.
allowed-tools:
  - Bash
  - Read
  - AskUserQuestion
---

# /foundry-cast <name>

Two human touches: pick the master, approve the sheet. No pack exists until the sheet's
measured skin matches the master's. That is what keeps a creator identical across a series.

1. **Brief.** If the user gave a look, use it. Otherwise ask once, in one question: who
   they are (age, look, skin tone and undertone, hair, signature details). Original
   character only; never a real person's likeness. Never describe clothing as sheer.
2. `foundry cast <name> --brief "<brief>" --json` (default 3 candidates). Show
   `personas/<name>/candidates/contact.png`.
3. **Touch 1.** AskUserQuestion: which candidate is the master (c1..cN), or regenerate.
4. Open the chosen `candidates/cN.png` and find the face. Run
   `foundry cast <name> --pick cN --face x0,y0,x1,y1 --json` with the face box as fractions
   (forehead to chin, ear to ear).
   - `BLOCKED sheet_drift`: the face was found on the sheet and its skin really differs. Show
     `sheet.png` and the numbers from `measure.json`, say in one line which way it drifted, and
     re-run the same `--pick` once. A second drift: stop and report.
   - `BLOCKED sheet_unmeasurable`: the numbers could not find the face on the sheet. Show
     `sheet.png` and ask the human whether it is the same person with the same skin. On yes:
     `foundry cast <name> --approve --visual-check "<what they checked>"` (counts as touch 2).
   - If the face box was wrong, `foundry cast <name> --remeasure --face x0,y0,x1,y1` checks the
     same images again without generating anything.
5. Show `sheet.png`. **Touch 2.** AskUserQuestion: approve the sheet, or re-pick.
6. `foundry cast <name> --approve [--story "..."] [--wardrobe "..."] --json`.
7. Report the pack's skin targets and that the creator is ready for `/foundry-spec`.
