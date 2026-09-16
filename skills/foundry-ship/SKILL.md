---
name: foundry-ship
description: Ship a green Foundry piece — re-run cut QC, write the publish handoff, save the piece as a reusable recipe, and tell the human exactly how to post it. Never posts. Use when a piece is green. Wraps `foundry ship`.
allowed-tools:
  - Bash
  - Read
---

# /foundry-ship <piece>

1. `foundry status <piece> --json`. Not `green`: stop and send the user to `/foundry-build`.
   Never ship red.
2. `foundry ship <piece> [--recipe <name>] --json`. It re-runs cut QC; a refusal here means
   the cut changed since it went green: report the guidance and stop.
3. Report, in a few lines: the video path, the recipe path (next piece:
   `foundry new <@account> <slug> --recipe <name>`, usually one question), credits spent,
   human touches (should be 2), and the two posting steps from `instructions`.
4. After the user says it is posted: `foundry posted <piece> --url <url>`. `foundry reap`
   clears the media from posted pieces later and keeps SPEC.md, qc/ and invoice.json.
