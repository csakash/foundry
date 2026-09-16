---
name: foundry-build
description: Build an approved Foundry piece to green — record face boxes and hands verdicts, generate the clip with the Higgsfield video MCP (seedance_2_5) from the approved first frame, and loop frames → clip → cut against machine QC within the retry budget. Never ships red. Use after the sheet is approved. In-session twin of `foundry build --mode bypass`.
allowed-tools:
  - Bash(foundry:*)
  - Read
---

# /foundry-build <piece>

Get the driving prompt and follow it exactly: `foundry build <piece> --mode interactive --json`
prints it in `prompt`. The CLI enforces the policy (retry budget, invoice ceiling, BLOCKED).
Your job is the two things it cannot do: look at images, and call the video tools.

**Looking.** Open the image with Read. Face box = forehead to chin, ear to ear, as fractions
of width and height. Hands verdict: every visible hand has five distinct fingers, no fused or
extra digits, no hand melting into the face. When unsure, fail it and say why.

**Video.** Preflight reachability once with the Higgsfield `balance` tool.
1. `foundry prompt <piece> --kind motion --json` (add `--guidance-from clip` on a retry).
2. `models_explore` for `seedance_2_5` once: find the start-image media role and allowed durations.
3. `media_upload` with filename `approved.png`, then `foundry upload <piece> --url <upload_url>`
   (it can only send the approved frame), then `media_confirm` with type image.
4. `generate_video` with `get_cost: true`, the params from step 1, and the media role from step 2.
   If it returns a preset recommendation instead of a cost, re-send with `declined_preset_id`.
5. `foundry reserve <piece> --unit video_credits --amount <cost> --json`. BLOCKED means stop.
6. `generate_video` for real (same params, no `get_cost`). `jobs_wait` until terminal
   (`poll_after_seconds` between calls).
7. `foundry settle <piece> <entry> --ok --ref <job_id>` (or `--failed` if the job failed), then
   `foundry fetch <piece> --url <result url> --job <job_id> --json`. A clip is only accepted with
   the settled reservation that paid for it.

Never retry a submission whose outcome is unknown after a timeout; reuse the job id.

**Rules.** You cannot edit files and there is no raw shell: only `foundry`, Read and the video tools. Never run `foundry ship`.
Any BLOCKED: print `BLOCKED <gate>: <evidence>` and stop with the files kept. On green,
report credits used (`foundry ls --json`) and hand off to `/foundry-ship`.
