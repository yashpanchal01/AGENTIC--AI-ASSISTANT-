# 05 — Aurora overlay: armed / heard / working / speaking (+ transcript)

Status: done

## What to build

A native PySide6 floating overlay (Aurora-style, LocalFlow painting approach as reference only) that always shows JARVIS lifecycle: **armed → heard → working → speaking**. Show the transcript of what was heard. Minimal, slick, above other windows without stealing focus — not a browser/Electron UI. Verify with a screenshot-render harness (render real widget states to PNGs and judge by eye).

## Acceptance criteria

- [x] Overlay displays distinct armed, heard, working, and speaking states driven by the real pipeline
- [x] Heard state shows the transcript text
- [x] Overlay does not steal keyboard focus from the user's work
- [x] No web/browser/Electron shell
- [x] Screenshot harness can render each state to PNGs for visual review

## Blocked by

- 04 — Wake word + hotkey front doors

## User stories covered

37–41

## Comments

- `jarvis/overlay/aurora.py` — Aurora Mono pill; flags: Frameless | StayOnTop | Tool | TransparentForInput | DoesNotAcceptFocus
- Lifecycle helpers drive states from voice/front-door pipeline
- Harness: `py -3.13 -m jarvis --shoot-overlay` → `benches/overlay_shots/results/`
- Tests: `tests/test_overlay_lifecycle.py` (FakeOverlay), `tests/test_overlay_widget.py` (flags + harness smoke, skip without PySide6)
- CLI: `--overlay` / default-on for `--daemon` when Qt installed; `--no-overlay` to force off
