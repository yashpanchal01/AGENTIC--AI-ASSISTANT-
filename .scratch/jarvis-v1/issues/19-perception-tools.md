# 19 — Perception tools: let the brain observe, not just act

Status: ready-for-agent

## What to build

Read-only "senses" on the MCP tool bridge (`jarvis/brain/mcp_bridge.py`) so the brain can observe current state before acting. Today it acts blind: it can open/close/play but cannot see what is open, playing, or recently downloaded — so "open the other one", "close that", "kill whatever is eating my RAM" cannot work.

New bridge tools (all read-only, no confirm gate, audit-logged like everything else):

1. **`observe_windows`** — list open top-level windows: title, process name, pid, minimized/focused state. Builds on the existing ctypes layer in `jarvis/windows/win32api.py` (EnumWindows already exists or is a small addition).
2. **`observe_processes`** — list running processes with name, pid, and RAM (working set), sorted by RAM desc, with an optional name filter. ctypes/`psutil`-free preferred: stdlib route is `tasklist /fo csv` subprocess or ctypes `EnumProcesses` + `GetProcessMemoryInfo`; pick the simpler robust one (see issue 16's brightness rationale: stdlib subprocess beat hand-rolled COM).
3. **`observe_files`** — list recent files in a named folder (downloads, desktop, documents, videos, or an approved-folder path): name, size, mtime, newest first, optional extension filter and limit. Reuses/generalizes the issue-16 `find_latest` machinery in `jarvis/system/`.
4. **`observe_music`** — what's playing now (track, artist, playing/paused). Thin read-only wrapper over the existing Spotify now-playing path; when Spotify is unconfigured, return the same honest "not set up" text the reflex speaks.

Each tool returns compact structured text (the model reads it), NOT huge dumps: cap window/process/file counts (~25 rows), truncate long titles. `num_ctx`-style discipline: the brain pays tokens for every byte.

Also append one sentence to the brain system prompt (`JARVIS_SYSTEM_PROMPT`): observe before acting when the request refers to current state ("that", "the other one", "the one eating RAM").

## Scope

In: the four observe tools, bridge registration (`_TOOLS`, schemas with optional filter args — this is the first tool family that takes structured args instead of a plain-English `command`), fakes for tests, system-prompt nudge, audit entries.
Out: acting on observations (existing act tools do that); conversation memory (issue 20); shell/file mutations (issue 21); screenshots/OCR; UI automation trees.

## Acceptance criteria

- [ ] Brain can answer "what windows are open right now?" via `observe_windows` with real titles on this laptop
- [ ] Brain can answer "what's eating my RAM?" via `observe_processes` with real RAM numbers, sorted desc
- [ ] Brain resolves "open the movie I downloaded last night" by calling `observe_files(downloads)` then the existing `media` tool — verified end-to-end with fakes (utterance → observe call → act call)
- [ ] `observe_music` returns now-playing when configured, honest "not set up" when not
- [ ] None of the four prompts for confirmation; all four write audit entries; outputs are capped/truncated
- [ ] Real-OS behavior behind `os_smoke` marker; default suite stays quota-safe and green

## Test plan

- Unit: each observe tool against fake adapters (window list, process list, temp folder tree, fake spotify) — shape, sorting, caps, filters
- Unit: bridge `tools/list` exposes the new tools with correct schemas; tool-call path routes args correctly
- Integration (FakeBrain or scripted claude transcript): two-step observe→act flow for the "movie from last night" case
- `os_smoke`: real EnumWindows lists this session's own console/IDE; real process list includes python; real downloads listing on this machine

## Blocked by

— (starts now)

## User stories covered

None — v1.2 "make it smart" wave (perception gap identified 2026-07-13 live testing)

## Comments

### 2026-07-16 — implemented (agent, left in tree for review; not committed)

New module `jarvis/perception.py` (the four senses) + four `observe_*` tools on
the MCP bridge. Summary:

- **Structured args (first tool family):** the observe tools carry their own
  explicit JSON schemas in a new `mcp_bridge._OBSERVE_TOOLS` catalogue
  (optional filters/limits, `additionalProperties: false`); the six act tools
  and `_command_schema` are untouched. `TOOL_NAMES`/`tool_definitions`/
  `allowed_tool_ids` now include all ten, so the CLI can call the senses.
- **Processes impl choice:** stdlib `tasklist /fo csv /nh` subprocess, not
  ctypes `EnumProcesses`+`GetProcessMemoryInfo` — same rationale as issue 16's
  brightness (call the OS, don't reimplement it; no psutil/pywin32). Locale-safe
  Mem-Usage parse (digits only). Windows ride the existing ctypes layer plus two
  small `win32api` additions (`is_minimized`, `foreground_hwnd`) for the
  minimized/focused flags; focused window sorts first (it is what "that" means).
- **Files:** `Observer.observe_files` generalizes issue 16's one-level
  newest-by-mtime discipline to a listing (`default_scan_files`), with named
  roots (downloads/desktop/documents/videos from `Path.home()`) or an
  approved-folder path only — unknown folder words and out-of-approved paths get
  plain refusals (`unknown_folder` / `folder_not_allowed`), never a guess.
- **Music:** thin read-only wrapper — the bridge routes `observe_music` into the
  existing Spotify controller's now-playing path (`_NOW_PLAYING_COMMAND`), so the
  honest "isn't set up yet" reply is the controller's own, not a copy.
- **No confirm gate, still observable:** observe calls skip `_needs_confirm`
  entirely (read-only) but stay serialized under `_call_lock`, emit
  StepStarted→StepFinished/StepFailed like the act tools, AND publish an
  `AuditRecord(name="observe", details={tool, args, ok, error, rows})` on the bus
  — the JSONL writer's `AuditSubscriber` (issue 12 wiring) records it. This is a
  small extension over the act tools (which are audited per-turn, not per-call):
  read-only calls have no `command_handled` record, so they get their own.
- **Token discipline:** every reply is a one-line count header + `- ` rows,
  hard-capped at `MAX_ROWS=25` (limit args clamp to it), titles/names truncated
  to `TITLE_MAX=60` with `…`; StepFinished detail is just the header line.
- **Fakes/isolation:** real OS access only in `default_list_windows` /
  `default_list_processes` / `default_scan_files`, all injected `Observer`
  fields; `cli.make_observer` wires it from config's `approved_folders`, and
  conftest's hermetic fixture patches it to empty fakes for CLI-driven tests.
- **System prompt:** one observe-before-acting sentence appended to
  `JARVIS_SYSTEM_PROMPT` (before the final reply-style sentence); the bridge's
  MCP `instructions` string also mentions the senses.
- **Tests:** default suite 395→415 passing (+20 in `test_perception.py`: sense
  units with fake adapters, bridge arg-routing/no-confirm/audit/failure paths,
  observe_music honesty, and the two-step observe→act "movie from last night"
  flow through `handle_command`; updated the two bridge tests that hard-coded
  the seven-tool set). os_smoke +4 in `test_perception_os_smoke.py` — ran on
  this laptop, 4 passed: real EnumWindows (13 windows, focused terminal first),
  real tasklist (320 processes, python present, RAM sorted desc), real Downloads
  listing (1187 files → capped at 25), real approved-path newest-first.
- **Acceptance:** all 6 criteria met (windows with real titles ✓, RAM sorted
  desc ✓, observe_files→media two-step with fakes ✓, observe_music honest both
  ways ✓, no confirmation + audit entries + capped/truncated ✓, os_smoke-gated
  real OS + default suite quota-safe ✓). Deviation: none functionally.
- **Bug found mid-build:** none in product code; one os_smoke assertion was too
  strict (didn't expect the "(showing top 25)" header on a 1187-file Downloads)
  — caught by the real run, loosened the test.
