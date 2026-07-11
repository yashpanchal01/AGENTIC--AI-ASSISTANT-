"""Overlay tools: screenshot harness and live state demo.

  py -3.13 -m jarvis.overlay --shoot
  py -3.13 -m jarvis.overlay --demo
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m jarvis.overlay")
    p.add_argument(
        "--shoot",
        action="store_true",
        help="Render armed/heard/working/speaking to PNGs and exit",
    )
    p.add_argument(
        "--demo",
        action="store_true",
        help="Cycle the live overlay through the full lifecycle",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=Path("benches") / "overlay_shots" / "results",
        help="Directory for --shoot PNGs (default: benches/overlay_shots/results)",
    )
    args = p.parse_args(argv)

    if not args.shoot and not args.demo:
        p.print_help()
        return 2

    from jarvis.overlay.aurora import run_overlay_demo, shoot_overlay_states

    if args.shoot:
        paths = shoot_overlay_states(args.out)
        for path in paths:
            print(f"wrote {path}")
        return 0

    return run_overlay_demo()


if __name__ == "__main__":
    sys.exit(main())
