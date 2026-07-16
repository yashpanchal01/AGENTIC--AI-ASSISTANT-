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

## Comments

### 2026-07-16 — implemented (agent, left in tree for review; not committed)

New policy module `jarvis/brain/shell_policy.py`, new execution module
`jarvis/hands.py`, and the `run_command` / `file_op` bridge tools. Summary:

- **Policy is the only gate, pure and unit-testable:** `classify_command` /
  `classify_file_op` map a call to `Decision(tier, preview, reason, refusal)`
  — allow / confirm / deny — from the command/op alone. The bridge computes
  the tier itself (`_shell_decision`); the tool schemas are
  `additionalProperties: false` and a test proves extra args
  (`tier: "allow"`, `safe: true`) and injected "this is safe" text change
  nothing. Hard-deny never consults the confirmer.
- **Compound-aware:** commands split on `;`, `&`, `|`, `&&`, `||`, newlines;
  most severe segment wins. Verified live: `git status; del /s C:\` → DENY
  (recursive_delete_outside), `dir & shutdown /r` → DENY, `git log &&
  format c:` → DENY. Deny tokens are token-matched, not substring, so
  `git log --format=%H` stays ALLOW. Redirection / backticks / `$(...)`
  forfeit the allow tier (they can hide writes) — `git log > out.txt` →
  CONFIRM.
- **Hard-deny list:** format/diskpart/mkfs, shutdown/restart (+ PowerShell
  cmdlets), registry writes (`reg add…`, write-cmdlets + hive paths,
  regedit), privilege escalation (sudo/runas/psexec/`-Verb RunAs`),
  recursive deletes whose targets don't provably resolve inside the
  approved roots (quote-aware tokenizing, `..`/symlinks resolved, relative
  paths against cwd; unprovable ⇒ deny), and credentials — composed with
  `jarvis.confirm.is_secret_request`, not duplicated.
- **Allowlist:** read-only binaries (dir/ls/type/gci/ping/where/findstr/
  tasklist/…), git read subcommands only (status/log/diff/show/blame/
  ls-files/--version), and the test suite (`pytest`, `py/python -m pytest`,
  `--version`) so "run the test suite" never prompts. Pipelines allow only
  if every side is allowlisted.
- **file_op jail:** src AND dst resolve (symlinks/`..` first) inside
  `config.approved_folders` + Downloads/Desktop/Documents/Videos
  (`hands.default_jail_roots`); outside ⇒ refusal ("That path isn't in your
  approved folders."), never a confirm. mkdir/copy/zip/unzip into fresh
  destinations auto-allow; move/rename/delete and any overwrite (existing
  dst; unzip into a non-empty folder) confirm with a naming preview
  ("Delete clip.mp4 to the Recycle Bin").
- **Recycle Bin, never hard delete:** ctypes `SHFileOperationW`
  (`FO_DELETE|FOF_ALLOWUNDO|FOF_NOCONFIRMATION|FOF_SILENT`) — chosen over
  the PowerShell route because it's stdlib-only like the existing
  `jarvis.windows.win32api` ctypes layer; PowerShell needs a subprocess +
  Microsoft.VisualBasic assembly load to reach the same shell API. unzip
  rides stdlib `zipfile` (its `extract` sanitizes `..`/drive components —
  no zip-slip).
- **Bridge flow:** shell tools are the third structured-args family
  (`_SHELL_TOOLS`); confirm-first rides the SAME `ConfirmRequested` +
  injected-Confirmer path as the act tools, decline ⇒ "Okay, cancelled.",
  handler never runs. Every call — allowed, confirmed, declined, denied —
  publishes `AuditRecord(name="shell", details={tool, args, tier, preview,
  confirmed, ok, error})` plus StepStarted→StepFinished/StepFailed
  (issue 19's pattern). Output truncated to 50 lines / 4000 chars
  (`exit N` header + stdout + labeled stderr); timeout (default 60 s,
  max 300) kills the command.
- **Claude's own Bash turned OFF:** the spec said "--allowedTools already
  restricts to bridge tools — verify and keep it that way"; verification
  showed `DEFAULT_SAFE_TOOLS` still contained `Bash`, which would bypass the
  whole gate. Removed `Bash` (Read/Glob/Grep/Write/Edit/WebSearch/WebFetch
  stay); shell now only reaches the OS through `run_command`.
  `test_claude_code_args` asserts Bash is absent.
- **Wiring/isolation:** `cli.make_hands` → `hands.build_hands(config)` (jail
  roots + cwd); conftest's hermetic fixture injects inert fake hands so
  CLI-driven tests can never run a real command or touch the Recycle Bin.
  Real adapters (`default_run_shell` via `powershell.exe -NoProfile
  -NonInteractive`, `default_recycle_delete`, zip/move/copy/mkdir) only
  exercised under `os_smoke`.
- **System prompt:** `CLAUDE_TOOL_BRIDGE_GUIDANCE` + the MCP `instructions`
  now say: prefer the domain tools; use run_command/file_op for dev/git/file
  work; JARVIS gates the risk itself.
- **Tests:** default suite 431→507 passing, 15 deselected (+2 new os_smoke),
  all green, quota-safe. `test_shell_file_tools.py`: policy table (17 allow /
  13 confirm / 19 deny rows incl. the spec's adversarial compound), jail
  resolution (approved / outside / `..` / relative-vs-cwd), hands fakes
  (truncation, timeout, recycle fake, plain failures), bridge integration
  (yes/no/deny/audit/bus, no-confirmer ⇒ decline, self-classification
  immunity). os_smoke ran on this laptop, 2 passed: real
  `git --version` through the bridge (`exit 0` / `git version
  2.45.2.windows.1`, zero confirms) and a real zip + SHFileOperationW
  recycle-delete round trip in a temp approved root (archive verified,
  victim gone, sibling intact).
- **Acceptance:** all 6 criteria met (test suite runs unprompted ✓, delete
  previews + Recycle Bin ✓, shutdown hard-denied + audited ✓, out-of-jail
  incl. `..` refused ✓, model cannot self-classify ✓, suite green +
  exhaustive tier units ✓). Deviation: none functionally; the one spec
  correction is the Bash removal above (the spec's "already restricts"
  premise was false — fixed rather than preserved).

### 2026-07-16 — review fix (main session, pre-commit)

Adversarial spot-check found one gap: `type %USERPROFILE%\.ssh\id_rsa` was
ALLOW — `is_secret_request` matches credential *words*, not credential *file
paths*, and `type` is an allowlisted read verb. Added a path-based secret
deny pattern to `_DENY_PATTERNS` (`.ssh`/`.aws`/`.gnupg` dirs, `id_rsa`-class
key names, `.pem`/`.ppk`/`.kdbx`) with the same SECRET_REFUSAL; token-safe
(`dir .sshville` stays ALLOW). +4 deny-table test rows. 507→511 green.
