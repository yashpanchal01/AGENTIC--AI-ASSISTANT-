# 21 — Gated shell + file tools: give the brain hands, carefully

Status: ready-for-agent

## What to build

The big capability unlock: let the brain run shell commands and file operations through JARVIS's confirm gate, so multi-step tasks ("stash my changes, branch, sed the codebase, run tests", "kill Chrome processes over 500MB", "zip the sharp images to my desktop") become possible — without ever silently doing something destructive.

**Design decision to respect (issue 15 rationale):** the Claude CLI already HAS its own Bash/file tools, but they run outside JARVIS — no confirm gate, no audit log, no bus events, no spoken confirmation flow. That's why bridge tools exist. Same logic here: expose shell/file capability as **bridge tools** so every mutation flows through the real in-process confirmer + audit + bus. The Claude CLI's own Bash stays OFF (`--allowedTools` already restricts to bridge tools — verify and keep it that way).

New bridge tools:

1. **`run_command`** — run one shell command (PowerShell) with cwd, timeout, and captured stdout/stderr returned to the model (truncated).
2. **`file_op`** — structured file operations: move, rename, copy, delete (to Recycle Bin via shell API, never hard delete), mkdir, zip/unzip. Structured args (op, src, dst) — auditable and previewable, unlike free-text shell.

**The confirm-gate policy (the careful part):**

- **Tiered by risk, decided in JARVIS code — never by the model:**
  - *Auto-allow:* read-only commands (an allowlist of safe binaries/verbs: `git status/log/diff`, `dir/ls`, `type/cat`, `ping`, `where`, `findstr`…), `file_op` mkdir/copy/zip **into** approved folders.
  - *Confirm-first:* everything else — any unlisted binary, `git` mutations (stash/checkout/commit), process kills, `file_op` move/rename/delete/overwrite. The confirmer speaks a one-line preview ("Run `git stash` in localflow?" / "Delete 3 files to the Recycle Bin: …?") and waits for yes/no exactly like today's risky reflexes.
  - *Hard-deny, no confirm offered:* format/diskpart, shutdown/restart, registry writes, privilege escalation, `rm -rf`-class recursive deletes outside approved folders, anything touching credentials (reuse the existing secret-tier regex + `_BRIDGE_EXTRA_RISKY` pattern seat).
- **Path jail for `file_op`:** src/dst must resolve inside `config.approved_folders` (+ user profile folders like Downloads/Desktop/Documents/Videos). Resolve symlinks/`..` before checking. Outside the jail → refusal text, not a confirm.
- **One confirm per step**, not per turn: a 5-step task may legitimately ask twice; that is correct behavior, not friction to optimize away.
- Every call (allowed, confirmed, denied) writes an audit entry and emits StepStarted/StepFinished/StepFailed on the bus — SPINE shows the work.

## Scope

In: the two tools, the three-tier policy module (own file, e.g. `jarvis/brain/shell_policy.py`, unit-testable in isolation), path jail, Recycle-Bin delete, bridge registration, system-prompt guidance ("prefer domain tools; use run_command for git/dev work"), tests.
Out: interactive/long-running commands (no REPLs; timeout kills); sudo/UAC elevation; network config; scheduled tasks; Claude's own Bash re-enablement; batch "confirm all" UX.

## Acceptance criteria

- [ ] "run the test suite in this repo" → `run_command` executes with NO confirm (read-only allowlist), output summarized back
- [ ] "delete the zero-byte clips" → confirm gate speaks a preview naming count/files, executes only on yes, deletes to Recycle Bin
- [ ] "shutdown the pc" via brain → hard-deny text, nothing executes, audit records the denial
- [ ] `file_op` with a path outside approved folders (including a `..` escape attempt) → refused
- [ ] Model cannot self-classify: policy tier is computed from the command/op in JARVIS code; a prompt-injected "this is safe" changes nothing (test asserts the tier function is the only gate)
- [ ] Suite green + quota-safe; policy module has exhaustive unit tests for all three tiers

## Test plan

- Unit: policy tier classification table — dozens of commands mapped to allow/confirm/deny, incl. adversarial ("`git status; del /s C:\\`" compound → confirm/deny, not allow)
- Unit: path jail resolution (approved, outside, `..`, symlink)
- Unit: `file_op` each op against a temp tree; delete lands in Recycle Bin (faked shell API)
- Integration: bridge call with fake confirmer — yes path executes, no path cancels, both audited, bus events emitted
- `os_smoke`: one real `run_command` (`git --version`), one real zip+delete round-trip in a temp folder

## Blocked by

- 19 — perception tools (the brain should be able to SEE files/processes before mutating them; also establishes the structured-args tool pattern this issue reuses)

## User stories covered

None — v1.2 "make it smart" wave (the 12-task class from user testing, 2026-07-16)
