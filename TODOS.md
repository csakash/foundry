# TODOS

## Build loop

### First real headless bypass build

**What:** Run `foundry build <piece> --mode bypass` on a real approved piece and watch it reach green with no human input.

**Why:** Acceptance criterion 7 is the unattended loop. Only the in-session `/foundry-build` path has run on real providers; the headless path (`claude -p`, `dontAsk`, the six named Higgsfield tools, `foundry upload`/`fetch`) is only simulated in tests.

**Context:** Set `providers.video.mcp_server` to the server name `claude mcp list` shows. The allowlist in `foundry/build.py` uses `mcp__<server>__<tool>`; a claude.ai connector name with spaces or dots is refused by `SERVER_RE` and may need a normalised name. If the run fails, capture the session output and `status.json`.

**Effort:** S
**Priority:** P1
**Depends on:** None

### Tie video generations to reservations at the provider

**What:** Stop the agent from generating a video without a reservation, or detect it after the fact.

**Why:** `foundry reserve` has a floor (one clip's price) and a ceiling, and a clip is only ingested with its settled reservation, but a `generate_video` call made without reserving leaves no trace in `invoice.json`.

**Context:** Options: reconcile against Higgsfield's job list or transactions before `foundry ship`; or let `foundry` call the provider itself so the agent never holds the generate tool. See the review note on `foundry/cli.py` reserve.

**Effort:** M
**Priority:** P2
**Depends on:** First real headless bypass build

### Doctor should confirm the MCP server name the build will use

**What:** When `providers.video.mcp_server` is set, check it against the tool prefix Claude Code actually exposes for the connected Higgsfield server.

**Why:** Doctor matches the Higgsfield server by host, but a headless build allows tools as `mcp__<mcp_server>__<tool>` under `dontAsk`; a name that differs from the real prefix denies every video tool and the build fails after approval.

**Context:** `claude mcp list` shows display names like `claude.ai Higgsfield`, not tool prefixes. Confirm the real prefix on the first headless run before encoding a rule (see "First real headless bypass build").

**Effort:** S
**Priority:** P2
**Depends on:** First real headless bypass build

### A green re-measure with a different face box after a drift

**What:** Decide whether a sheet that once measured as `sheet_drift` may later pass a numeric re-measure with a different `--face` box.

**Why:** `drift_seen` stops a by-eye approval of those images, but a new box drawn on a patch that happens to match could still turn the gate green.

**Context:** Options: refuse `--remeasure` with a different box once drift was seen for these image hashes, or require `--pick` (a new sheet). `foundry/cast.py` `remeasure` / `_gate`.

**Effort:** S
**Priority:** P2
**Depends on:** None

### A way out of `blocked`

**What:** A human-only command to resume a blocked piece (reset one stage's cycles, or re-open the spec) with the reason recorded.

**Why:** A blocked piece currently has no exit; the only recovery is a new piece, which re-spends the sheet.

**Context:** Must stay human-only (`human_only`), must not raise the approved ceiling silently, and should append to `status.json` history.

**Effort:** M
**Priority:** P2
**Depends on:** None

### Correcting a mistyped face box or hands verdict

**What:** Allow one correction of a recorded observation without regenerating, with the correction logged.

**Why:** Observations are one-per-image-version so QC cannot be re-rolled by moving the box; a genuine typo currently costs a regeneration and its credits.

**Context:** `foundry/loop.py` `record_region` / `record_verdict`. A correction should count against something (e.g. one per stage) so it is not a retry loophole.

**Effort:** S
**Priority:** P3
**Depends on:** None

## Skills

### Remove the legacy staged router

**What:** Delete the "Legacy router" section of `skills/foundry/SKILL.md` and the retired staged skills once the headless loop is proven.

**Why:** SPEC.md section 11 keeps them only as a rollback path until acceptance criterion 7 passes.

**Context:** Keep the craft skills (`foundry-carousel`, `-review`, `-sound`, `-voice`, `-storytelling`, `-screenwriting`, `-storyboard`).

**Effort:** S
**Priority:** P2
**Depends on:** First real headless bypass build

### Version check in skill preambles

**What:** Have each `/foundry-*` skill run `foundry --version` and compare with the workspace `requires` before doing anything.

**Why:** SPEC.md section 1; today the check happens only inside the CLI, so a skill can give stale instructions for an older CLI.

**Effort:** S
**Priority:** P3
**Depends on:** None

## QC

### Prompt regression evals

**What:** A small paid eval that regenerates a first frame and a clip for a fixed creator and checks the QC numbers stay inside tolerance.

**Why:** The prompt templates were validated by one live run; later edits to `engine/prompts/*` or `foundry/templates/*` are unguarded.

**Context:** Run on demand, not per PR (it spends credits). Record the numbers alongside the Imani calibration.

**Effort:** M
**Priority:** P3
**Depends on:** None

### Sheet brightness margin

**What:** Revisit `cast.max_sheet_lum_delta` (12) with more real casts.

**Why:** Imani's accepted sheet measures +10.9, close to the limit; a similar sheet could block on a real but acceptable lighter render.

**Effort:** S
**Priority:** P3
**Depends on:** None

## Completed
