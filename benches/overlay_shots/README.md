# Aurora overlay screenshot harness

Renders the real PySide6 `AuroraOverlay` in each lifecycle state to PNGs for
visual review (issue 05). No pixel-diff CI — judge by eye.

## Run

```powershell
py -3.13 -m pip install -e ".[ui]"
py -3.13 -m jarvis --shoot-overlay
# or:
py -3.13 -m jarvis.overlay --shoot --out benches/overlay_shots/results
```

Writes:

- `aurora-1-armed.png`
- `aurora-2-heard.png` (sample transcript visible)
- `aurora-3-working.png`
- `aurora-4-speaking.png`

Live cycle:

```powershell
py -3.13 -m jarvis --demo-overlay
```
