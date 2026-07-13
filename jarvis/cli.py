"""Terminal front door for JARVIS (core loop + wake/hotkey + Aurora overlay).

Usage:
  py -3.13 -m jarvis                  # interactive REPL (text)
  py -3.13 -m jarvis --once "open notepad"
  py -3.13 -m jarvis --fake --once "what's 2+2"
  py -3.13 -m jarvis --listen         # one-shot mic → silence → whisper → brain
  py -3.13 -m jarvis --daemon         # wake word + hotkey front door (continuous)
  py -3.13 -m jarvis --overlay --listen
  py -3.13 -m jarvis --overlay --daemon
  py -3.13 -m jarvis --install-autostart
  py -3.13 -m jarvis --uninstall-autostart
  py -3.13 -m jarvis --shoot-overlay
  py -3.13 -m jarvis --demo-overlay
"""

from __future__ import annotations

import argparse
import sys
import threading
from pathlib import Path
from typing import Any

from jarvis.audio.capture import MicRecorder
from jarvis.audio.silence import SilenceConfig
from jarvis.brain.claude_code import ClaudeCodeBrain
from jarvis.brain.fake import FakeBrain
from jarvis.brain.grok_cli import GrokCliBrain
from jarvis.config import JarvisConfig
from jarvis.connectivity import SocketConnectivity
from jarvis.confirm import FixedConfirmer, VoiceOrClickConfirmer, parse_yes_no
from jarvis.core import handle_command
from jarvis.stt.fake import FakeTranscriber
from jarvis.tasks import LongTaskService
from jarvis.tts.fake import FakeSpeaker
from jarvis.tts.piper import PiperSpeaker
from jarvis.voice import listen_and_handle


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="jarvis",
        description=(
            "JARVIS — wake/hotkey or text → whisper → brain → Piper (+ Aurora overlay)"
        ),
    )
    p.add_argument(
        "--once",
        metavar="COMMAND",
        help="Run a single typed command and exit",
    )
    p.add_argument(
        "--listen",
        action="store_true",
        help="Record from mic until silence, transcribe, run one command, exit",
    )
    p.add_argument(
        "--daemon",
        "--front-door",
        action="store_true",
        dest="daemon",
        help="Continuous front door: local wake word + optional hotkey push-to-talk",
    )
    p.add_argument(
        "--brain",
        choices=("grok", "claude", "fake"),
        default=None,
        help="Brain provider (default: claude, or JARVIS_BRAIN). 'fake' = no cloud CLI",
    )
    p.add_argument(
        "--fake",
        action="store_true",
        help="Shortcut for --brain fake (no cloud brain CLI)",
    )
    p.add_argument(
        "--fake-stt",
        metavar="TEXT",
        default=None,
        help="Skip mic/whisper; inject this transcript (for tests / demos)",
    )
    p.add_argument(
        "--fake-wake",
        action="store_true",
        help="Use FakeWakeDetector (fires once per cycle via scripted frames)",
    )
    p.add_argument(
        "--max-cycles",
        type=int,
        default=None,
        help="With --daemon, exit after N armed command cycles (tests / demos)",
    )
    p.add_argument(
        "--hotkey",
        default=None,
        help="Push-to-talk hotkey (default: ctrl+shift+j or JARVIS_HOTKEY)",
    )
    p.add_argument(
        "--no-hotkey",
        action="store_true",
        help="Disable global hotkey (wake word only)",
    )
    p.add_argument(
        "--wake-threshold",
        type=float,
        default=None,
        help="openWakeWord detection threshold (default 0.5)",
    )
    p.add_argument(
        "--no-speak",
        action="store_true",
        help="Do not run Piper; print replies only",
    )
    p.add_argument(
        "--model",
        default=None,
        help="Brain model id (Claude: JARVIS_MODEL/sonnet; Grok: JARVIS_GROK_MODEL)",
    )
    p.add_argument(
        "--cwd",
        type=Path,
        default=None,
        help="Working directory for the brain",
    )
    p.add_argument(
        "--overlay",
        action="store_true",
        help="Show the Aurora overlay during listen/once/daemon (requires PySide6)",
    )
    p.add_argument(
        "--no-overlay",
        action="store_true",
        help="Force-disable overlay even for --daemon",
    )
    p.add_argument(
        "--shoot-overlay",
        action="store_true",
        help="Render overlay states to PNGs and exit (screenshot harness)",
    )
    p.add_argument(
        "--demo-overlay",
        action="store_true",
        help="Cycle the live overlay through armed→heard→working→speaking",
    )
    p.add_argument(
        "--overlay-out",
        type=Path,
        default=Path("benches") / "overlay_shots" / "results",
        help="Output directory for --shoot-overlay",
    )
    p.add_argument(
        "--google-login",
        action="store_true",
        help="One-time Google OAuth (Gmail + Calendar read-only); then exit",
    )
    p.add_argument(
        "--fake-google",
        action="store_true",
        help="Use sample in-process Gmail/Calendar data (no OAuth)",
    )
    p.add_argument(
        "--no-google",
        action="store_true",
        help="Disable Gmail/Calendar integration for this run",
    )
    p.add_argument(
        "--spotify-login",
        action="store_true",
        help="One-time Spotify sign-in (PKCE, free developer app); then exit",
    )
    p.add_argument(
        "--fake-spotify",
        action="store_true",
        help="Use sample in-process Spotify playback data (no OAuth)",
    )
    p.add_argument(
        "--no-spotify",
        action="store_true",
        help="Disable Spotify voice control for this run",
    )
    p.add_argument(
        "--no-memory",
        action="store_true",
        help="Disable markdown long-term memory for this run",
    )
    p.add_argument(
        "--install-autostart",
        action="store_true",
        help="Register JARVIS --daemon to start with Windows (HKCU Run key), then exit",
    )
    p.add_argument(
        "--uninstall-autostart",
        action="store_true",
        help="Remove JARVIS from Windows startup, then exit",
    )
    p.add_argument(
        "--no-tray",
        action="store_true",
        help="Do not show the system tray icon in --daemon mode",
    )
    p.add_argument(
        "--no-audit",
        action="store_true",
        help="Disable the append-only audit log for this run",
    )
    p.add_argument(
        "--settings",
        type=Path,
        default=None,
        help="Path to settings.json (default: %%USERPROFILE%%\\.jarvis\\settings.json)",
    )
    return p


def make_brain(
    config: JarvisConfig,
    *,
    fake: bool = False,
    provider: str | None = None,
    bus=None,
):
    """Build the configured brain. Default provider is Claude (see JARVIS_BRAIN).

    Claude is the only brain wired to the MCP tool bridge (issue 15), so it is the
    only one that can actually act; Grok stays a working fallback.

    With *bus* (issue 12), cloud brains stream live StepStarted/StepFinished/
    TokenTick events during each call and BrainSelected announces the provider.
    """
    name = (provider or config.brain_provider or "claude").strip().lower()
    if fake or name == "fake":
        name = "fake"
        brain = FakeBrain()
    elif name == "claude":
        brain = ClaudeCodeBrain(config=config, bus=bus)
    else:
        name = "grok"
        brain = GrokCliBrain(config=config, bus=bus)
    if bus is not None:
        from jarvis.events import BrainSelected

        bus.publish(BrainSelected(provider=name))
    return brain


def make_speaker(config: JarvisConfig, *, no_speak: bool):
    if no_speak or not config.speak:
        return FakeSpeaker()
    return PiperSpeaker(config=config, fallback_to_print=True)


def make_transcriber(config: JarvisConfig, *, fake_stt: str | None):
    if fake_stt is not None:
        return FakeTranscriber(text=fake_stt)
    from jarvis.stt.whisper import WhisperTranscriber

    return WhisperTranscriber(
        model_name=config.whisper_model,
        device=config.whisper_device,
        compute_type=config.whisper_compute,
        dictionary_path=config.dictionary_path,
    )


def make_recorder(config: JarvisConfig, *, fake_stt: str | None) -> MicRecorder:
    silence = SilenceConfig(
        silence_duration_s=config.silence_duration_s,
        max_record_s=config.max_record_s,
    )
    if fake_stt is not None:
        # Synthetic speech then silence so SilenceTracker completes without a mic.
        import numpy as np

        sr = silence.sample_rate
        speech = np.full(int(sr * 0.5), 0.2, dtype=np.float32)
        quiet = np.zeros(int(sr * (config.silence_duration_s + 0.2)), dtype=np.float32)
        return MicRecorder(config=silence, blocks=[speech, quiet])
    return MicRecorder(config=silence)


def make_wake_detector(config: JarvisConfig, *, fake_wake: bool):
    if fake_wake:
        from jarvis.wake.fake import FakeWakeDetector

        # Fire once per wait: FakeWakeDetector.reset() re-arms fire_after_frames
        # at the start of each FrontDoorSession.wait_for_trigger().
        return FakeWakeDetector(fire_after_frames=1)
    from jarvis.wake.factory import create_wake_detector

    return create_wake_detector(
        access_key=config.picovoice_access_key,
        threshold=config.wake_threshold,
        sensitivity=config.wake_sensitivity,
    )


def make_google(*, fake_google: bool, no_google: bool):
    if no_google:
        return None
    from jarvis.google.workspace import build_google_workspace

    return build_google_workspace(force_fake=fake_google)


def make_spotify(config: JarvisConfig, *, fake_spotify: bool, no_spotify: bool):
    if no_spotify:
        return None
    from jarvis.spotify.controller import build_spotify

    return build_spotify(config, force_fake=fake_spotify)


def make_media(config: JarvisConfig):
    """Local media: search approved folders and open with the OS default player."""
    from jarvis.media.handler import build_local_media

    return build_local_media(config)


def make_windows():
    """Win32 window control (focus / min / max / fullscreen / close)."""
    from jarvis.windows.handler import build_window_handler

    return build_window_handler()


def make_apps():
    """Smart app open: focus if running, else launch once."""
    from jarvis.apps.handler import build_app_handler

    return build_app_handler()


def make_system(config: JarvisConfig):
    """System controls: screen brightness + latest-capture resolver (issue 16)."""
    from jarvis.system.handler import build_system_handler

    return build_system_handler(config)


def make_memory(config: JarvisConfig, *, no_memory: bool = False):
    """Markdown long-term memory handler (issue 07), or None when disabled."""
    if no_memory:
        return None
    from jarvis.memory.handler import build_memory_handler

    return build_memory_handler(config.memory_dir)


def make_connectivity(config: JarvisConfig):
    """Real socket check when enabled; None skips the pre-check (tests / offline demos)."""
    if not config.check_connectivity:
        return None
    return SocketConnectivity()


def make_confirmer(
    *,
    interactive: bool = True,
    overlay=None,
    recorder=None,
    transcriber=None,
):
    """Build a Confirmer for CLI / listen / daemon.

    Priority:
      - interactive TTY → stdin y/n (with overlay click re-check)
      - mic available → voice yes/no + overlay click
      - overlay only → wait for Yes/No click
      - else → FixedConfirmer(False) safe decline
    """
    if interactive and sys.stdin.isatty() and recorder is None:
        def _decide(prompt: str, proposed_action: str) -> bool:
            print(f"  confirm: {proposed_action}")
            print(
                "  [y/n] (or click Yes/No on overlay)",
                flush=True,
            )
            if overlay is not None:
                take = getattr(overlay, "take_confirm_decision", None)
                if callable(take):
                    clicked = take()
                    if clicked is not None:
                        return bool(clicked)
            try:
                line = input("  > ").strip()
            except EOFError:
                return False
            if overlay is not None:
                take = getattr(overlay, "take_confirm_decision", None)
                if callable(take):
                    clicked = take()
                    if clicked is not None:
                        return bool(clicked)
            parsed = parse_yes_no(line)
            # Unclear → False (safe decline).
            return bool(parsed) if parsed is not None else False

        from jarvis.confirm import CallableConfirmer

        return CallableConfirmer(decide=_decide)

    if recorder is not None and transcriber is not None:
        return VoiceOrClickConfirmer(
            overlay=overlay,
            recorder=recorder,
            transcriber=transcriber,
            default=False,
        )

    if overlay is not None:
        from jarvis.confirm import OverlayClickConfirmer

        return OverlayClickConfirmer(overlay=overlay, default=False)

    return FixedConfirmer(answer=False)


def _attach_bridge_confirmer(brain: Any, confirmer: Any) -> None:
    """Give the Claude brain's MCP tool bridge the same confirmer the core uses.

    Brain tool calls (issue 15) then pass the identical ask-first gate as a
    direct voice command. No-op for Grok/fake brains (no bridge).
    """
    bridge = getattr(brain, "tool_bridge", None)
    if bridge is not None and confirmer is not None:
        bridge.confirmer = confirmer


def run_once(
    command: str,
    *,
    brain,
    speaker,
    overlay=None,
    google=None,
    memory=None,
    spotify=None,
    media=None,
    windows=None,
    apps=None,
    system=None,
    connectivity=None,
    long_tasks=None,
    confirmer=None,
    long_task_threshold_s: float | None = None,
    audit=None,
) -> int:
    if confirmer is None:
        confirmer = make_confirmer(interactive=sys.stdin.isatty(), overlay=overlay)
    _attach_bridge_confirmer(brain, confirmer)
    if overlay is not None:
        from jarvis.overlay.lifecycle import handle_command_with_overlay

        result = handle_command_with_overlay(
            command,
            brain=brain,
            speaker=speaker,
            overlay=overlay,
            google=google,
            memory=memory,
            spotify=spotify,
            media=media,
            windows=windows,
            apps=apps,
            system=system,
            connectivity=connectivity,
            long_tasks=long_tasks,
            confirmer=confirmer,
            long_task_threshold_s=long_task_threshold_s,
            audit=audit,
        )
    else:
        result = handle_command(
            command,
            brain=brain,
            speaker=speaker,
            google=google,
            memory=memory,
            spotify=spotify,
            media=media,
            windows=windows,
            apps=apps,
            system=system,
            connectivity=connectivity,
            long_tasks=long_tasks,
            confirmer=confirmer,
            long_task_threshold_s=long_task_threshold_s,
            audit=audit,
        )
    _print_result(result)
    # --once used to return on "On it." and exit the process, which killed the
    # background brain worker mid-task (e.g. find+play movie never finished).
    # Wait for the worker so one-shot CLI matches daemon behavior.
    if getattr(result, "backgrounded", False) and long_tasks is not None:
        wait_fn = getattr(long_tasks, "wait", None)
        if callable(wait_fn):
            print("JARVIS> (waiting for background task…)", flush=True)
            wait_fn(timeout=600.0)
            final = getattr(long_tasks, "last_final", None)
            if final is not None:
                _print_result(final)
                return 0 if final.ok else 1
    return 0 if result.ok else 1


def _handle_autostart(args) -> int:
    """Install or remove Windows autostart; always exits."""
    from jarvis.autostart import (
        install_autostart,
        uninstall_autostart,
    )

    # Reuse the same disable rules as the main process (env + --no-audit).
    audit = _make_audit(args)
    if args.install_autostart and args.uninstall_autostart:
        print("Use either --install-autostart or --uninstall-autostart.", file=sys.stderr)
        return 2
    try:
        if args.install_autostart:
            cmd = install_autostart()
            if audit is not None:
                audit.log("autostart_install", command=cmd)
            print(f"JARVIS> autostart installed (starts with Windows):\n  {cmd}")
            print(
                "  Reboot demo: restart Windows, then speak a command — "
                "no manual launch needed."
            )
            return 0
        removed = uninstall_autostart()
        if audit is not None:
            audit.log("autostart_uninstall", removed=removed)
        if removed:
            print("JARVIS> autostart removed.")
        else:
            print("JARVIS> autostart was not registered.")
        return 0
    except OSError as exc:
        print(f"JARVIS> autostart failed: {exc}", file=sys.stderr)
        return 2


def run_listen(
    *,
    brain,
    speaker,
    recorder,
    transcriber,
    announce: bool = True,
    overlay=None,
    google=None,
    memory=None,
    spotify=None,
    media=None,
    windows=None,
    apps=None,
    system=None,
    connectivity=None,
    long_tasks=None,
    confirmer=None,
    unload_stt_after: bool = False,
    long_task_threshold_s: float | None = None,
    audit=None,
) -> int:
    if announce:
        print("Listening… (speak a command; ends on silence)")
    if confirmer is None:
        confirmer = make_confirmer(
            interactive=False,
            overlay=overlay,
            recorder=recorder,
            transcriber=transcriber,
        )
    _attach_bridge_confirmer(brain, confirmer)
    try:
        if overlay is not None:
            from jarvis.overlay.lifecycle import listen_and_handle_with_overlay

            outcome = listen_and_handle_with_overlay(
                recorder=recorder,
                transcriber=transcriber,
                brain=brain,
                speaker=speaker,
                overlay=overlay,
                google=google,
                memory=memory,
                spotify=spotify,
                media=media,
                windows=windows,
                apps=apps,
                system=system,
                connectivity=connectivity,
                long_tasks=long_tasks,
                confirmer=confirmer,
                unload_stt_after=unload_stt_after,
                long_task_threshold_s=long_task_threshold_s,
                audit=audit,
            )
        else:
            outcome = listen_and_handle(
                recorder=recorder,
                transcriber=transcriber,
                brain=brain,
                speaker=speaker,
                google=google,
                memory=memory,
                spotify=spotify,
                media=media,
                windows=windows,
                apps=apps,
                system=system,
                connectivity=connectivity,
                long_tasks=long_tasks,
                confirmer=confirmer,
                unload_stt_after=unload_stt_after,
                long_task_threshold_s=long_task_threshold_s,
                audit=audit,
            )
    except RuntimeError as e:
        print(f"JARVIS> voice error: {e}", file=sys.stderr)
        return 2

    if outcome.error:
        msg = {
            "no_speech": "I didn't hear anything.",
            "empty_transcript": "I heard sound but couldn't transcribe it.",
            "stt_failed": "I couldn't transcribe that.",
            "brain_unreachable": "My brain is unreachable right now.",
        }.get(outcome.error, outcome.error)
        print(f"JARVIS> {msg}")
        return 1

    print(f"You (voice)> {outcome.transcript}")
    assert outcome.command is not None
    _print_result(outcome.command)
    result = outcome.command
    if getattr(result, "backgrounded", False) and long_tasks is not None:
        wait_fn = getattr(long_tasks, "wait", None)
        if callable(wait_fn):
            print("JARVIS> (waiting for background task…)", flush=True)
            wait_fn(timeout=600.0)
            final = getattr(long_tasks, "last_final", None)
            if final is not None:
                _print_result(final)
                return 0 if final.ok else 1
    return 0 if result.ok else 1


def run_daemon(
    *,
    config: JarvisConfig,
    brain,
    speaker,
    transcriber,
    recorder,
    detector,
    overlay=None,
    google=None,
    memory=None,
    spotify=None,
    media=None,
    windows=None,
    apps=None,
    system=None,
    connectivity=None,
    long_tasks=None,
    confirmer=None,
    max_cycles: int | None = None,
    frames_factory=None,
    hotkey_controller=None,
    announce: bool = True,
    resident=None,
    audit=None,
) -> int:
    """Continuous wake + hotkey loop. Returns 0 after clean stop / max_cycles."""
    from jarvis.wake.session import FrontDoorSession

    if announce:
        hk = config.hotkey if config.enable_hotkey else "(disabled)"
        print(
            f"JARVIS front door  detector={getattr(detector, 'name', type(detector).__name__)}  "
            f"phrase={getattr(detector, 'phrase', '?')!r}  hotkey={hk}"
        )
        print("  Say the wake word or press the hotkey for each command. Ctrl+C to stop.")
        if resident is not None:
            print("  Tray: Pause (deaf) / Resume / Quit when the system tray icon is shown.")
        print()

    if long_tasks is None:
        long_tasks = LongTaskService(
            threshold_s=config.long_task_threshold_s, audit=audit
        )
    elif audit is not None and getattr(long_tasks, "audit", None) is None:
        long_tasks.audit = audit

    if confirmer is None:
        confirmer = make_confirmer(
            interactive=False,
            overlay=overlay,
            recorder=recorder,
            transcriber=transcriber,
        )
    _attach_bridge_confirmer(brain, confirmer)

    session = FrontDoorSession(
        detector=detector,
        recorder=recorder,
        transcriber=transcriber,
        brain=brain,
        speaker=speaker,
        overlay=overlay,
        google=google,
        memory=memory,
        spotify=spotify,
        media=media,
        windows=windows,
        apps=apps,
        system=system,
        long_tasks=long_tasks,
        confirmer=confirmer,
        hotkey=config.hotkey,
        enable_hotkey=config.enable_hotkey,
        frames_factory=frames_factory,
        hotkey_controller=hotkey_controller,
        connectivity=connectivity,
        unload_stt_after=config.unload_stt_between_commands,
        long_task_threshold_s=config.long_task_threshold_s,
        resident=resident,
        audit=audit,
    )

    def on_cycle(cycle) -> None:
        src = cycle.source
        out = cycle.outcome
        if out.error:
            msg = {
                "no_speech": "I didn't hear anything.",
                "empty_transcript": "I heard sound but couldn't transcribe it.",
                "stt_failed": "I couldn't transcribe that.",
            }.get(out.error, out.error)
            print(f"[{src}] JARVIS> {msg}")
            return
        print(f"[{src}] You (voice)> {out.transcript}")
        if out.command is not None:
            _print_result(out.command)

    session.on_cycle = on_cycle

    if audit is not None:
        try:
            audit.log(
                "daemon_started",
                hotkey=config.hotkey if config.enable_hotkey else None,
                detector=getattr(detector, "name", type(detector).__name__),
            )
        except Exception:
            pass

    try:
        session.run(max_cycles=max_cycles)
    except KeyboardInterrupt:
        print()
        session.stop()
    finally:
        if hasattr(detector, "close"):
            try:
                detector.close()
            except Exception:
                pass
        if audit is not None:
            try:
                audit.log("daemon_stopped")
            except Exception:
                pass

    if announce:
        print("front door stopped")
    return 0


def run_repl(
    *,
    brain,
    speaker,
    config: JarvisConfig,
    fake_stt: str | None,
    google=None,
    memory=None,
    spotify=None,
    media=None,
    windows=None,
    apps=None,
    system=None,
    connectivity=None,
    long_tasks=None,
    audit=None,
) -> int:
    print(
        "JARVIS  "
        "(type a command, :listen mic once, :n new session, :q quit)"
    )
    if isinstance(brain, GrokCliBrain):
        model = brain.config.grok_model or "(cli default)"
        print(f"  brain: Grok CLI  model={model}")
    elif isinstance(brain, ClaudeCodeBrain):
        print(f"  brain: Claude Code  model={brain.config.claude_model}")
    else:
        print("  brain: FakeBrain")
    print(f"  speaker: {type(speaker).__name__}")
    if google is not None:
        signed = getattr(google, "signed_in", True)
        print(f"  google: {'signed in' if signed else 'not signed in'} "
              f"({type(google).__name__})")
    else:
        print("  google: off")
    if memory is not None:
        root = getattr(getattr(memory, "store", None), "root", None)
        print(f"  memory: {root if root is not None else 'on'}")
    else:
        print("  memory: off")
    if spotify is not None:
        if not getattr(spotify, "configured", True):
            state = "not set up (see docs/spotify-setup.md)"
        elif not getattr(spotify, "signed_in", True):
            state = "not signed in (run --spotify-login)"
        else:
            state = "linked"
        print(f"  spotify: {state} ({type(spotify).__name__})")
    else:
        print("  spotify: off")
    if media is not None:
        n = len(getattr(media, "roots", ()) or ())
        print(f"  media: local open ({n} folder(s))")
    else:
        print("  media: off")
    if windows is not None:
        print("  windows: Win32 control on")
    else:
        print("  windows: off")
    if apps is not None:
        print("  apps: smart open (focus if running)")
    else:
        print("  apps: off")
    print()

    # Lazy STT — only load whisper when the user actually listens.
    transcriber = None
    if long_tasks is None:
        long_tasks = LongTaskService(
            threshold_s=config.long_task_threshold_s, audit=audit
        )
    elif audit is not None and getattr(long_tasks, "audit", None) is None:
        long_tasks.audit = audit

    # Brain tool bridge (issue 15) shares the REPL's stdin confirmer.
    _attach_bridge_confirmer(brain, make_confirmer(interactive=True))

    while True:
        try:
            line = input("You> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not line:
            continue
        if line in (":q", ":quit", "quit", "exit"):
            break
        if line in (":n", ":new"):
            if hasattr(brain, "reset_session"):
                brain.reset_session()
            print("(new conversation)")
            continue
        if line in (":listen", ":v", ":voice"):
            if transcriber is None:
                print("(loading speech model…)")
                try:
                    transcriber = make_transcriber(config, fake_stt=fake_stt)
                except RuntimeError as e:
                    print(f"JARVIS> voice error: {e}")
                    continue
            recorder = make_recorder(config, fake_stt=fake_stt)
            run_listen(
                brain=brain,
                speaker=speaker,
                recorder=recorder,
                transcriber=transcriber,
                google=google,
                memory=memory,
                spotify=spotify,
                media=media,
                windows=windows,
                apps=apps,
                system=system,
                connectivity=connectivity,
                long_tasks=long_tasks,
                unload_stt_after=config.unload_stt_between_commands,
                long_task_threshold_s=config.long_task_threshold_s,
                audit=audit,
            )
            continue

        result = handle_command(
            line,
            brain=brain,
            speaker=speaker,
            google=google,
            memory=memory,
            spotify=spotify,
            media=media,
            windows=windows,
            apps=apps,
            system=system,
            connectivity=connectivity,
            long_tasks=long_tasks,
            confirmer=make_confirmer(interactive=True),
            long_task_threshold_s=config.long_task_threshold_s,
            audit=audit,
        )
        _print_result(result)

    print("bye")
    return 0


def _print_result(result) -> None:
    flags = []
    if result.denied:
        flags.append("denied")
    if result.error == "confirmation_declined":
        flags.append("cancelled")
    if not result.ok:
        flags.append("failed")
    flag_s = f"  [{', '.join(flags)}]" if flags else ""
    print(f"JARVIS> {result.reply}{flag_s}")
    if result.actions:
        names = " → ".join(
            f"{a.name}({a.detail})" if a.detail else a.name for a in result.actions
        )
        print(f"  actions: {names}")
    if result.session_id:
        sid = result.session_id
        shown = sid if len(sid) <= 12 else sid[:12] + "…"
        print(f"  session: {shown}")


def _run_with_qt_overlay(
    work,
    *,
    hold_after_s: float = 0.8,
    resident=None,
    enable_tray: bool = False,
    use_overlay: bool = True,
    bus=None,
    overlay_style: str = "aurora",
) -> int:
    """Run *work(overlay)* on a worker thread while the Qt event loop paints.

    When *enable_tray* is True, shows a system tray icon bound to *resident*
    (Pause / Resume / Quit). Quit from the tray stops the resident controller
    and exits the Qt loop.

    With *bus* (issue 12), Aurora is attached as a bus subscriber and the
    pipeline receives a BusOverlay front — same set_state sequence, but other
    subscribers (audit, future SPINE) observe the identical event stream.
    """
    try:
        from PySide6 import QtCore, QtWidgets
    except ImportError:
        print(
            'JARVIS> overlay/tray needs PySide6. Install with: py -3.13 -m pip install -e ".[ui]"',
            file=sys.stderr,
        )
        return 2

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    overlay = None
    overlay_front = None
    if use_overlay:
        if overlay_style == "spine":
            from jarvis.overlay.spine import SpineOverlay

            overlay = SpineOverlay()
        else:
            from jarvis.overlay.aurora import AuroraOverlay

            overlay = AuroraOverlay()
        overlay_front = overlay
        if bus is not None:
            from jarvis.overlay.bus import BusOverlay, attach_overlay

            attach_overlay(bus, overlay)
            # SPINE additionally rides the rich instrument events; Aurora only
            # needs the StateChanged path above.
            attach_events = getattr(overlay, "attach_events", None)
            if callable(attach_events):
                attach_events(bus)
            overlay_front = BusOverlay(bus, overlay)
    result_box: dict[str, int] = {"code": 1}
    tray = None

    class _Bridge(QtCore.QObject):
        finished = QtCore.Signal()

    bridge = _Bridge()

    def _quit_soon() -> None:
        # Runs on the UI thread (signal slot) — safe for QTimer.
        QtCore.QTimer.singleShot(int(hold_after_s * 1000), app.quit)

    bridge.finished.connect(_quit_soon)

    def _tray_quit() -> None:
        if resident is not None:
            resident.quit()
        app.quit()

    if enable_tray and resident is not None:
        try:
            from jarvis.tray import JarvisTray

            if not QtWidgets.QSystemTrayIcon.isSystemTrayAvailable():
                print("JARVIS> system tray not available on this desktop", file=sys.stderr)
            else:
                tray = JarvisTray(resident, on_quit=_tray_quit)
        except Exception as exc:  # noqa: BLE001 — tray is non-fatal
            print(f"JARVIS> tray icon unavailable: {exc}", file=sys.stderr)

    def runner() -> None:
        try:
            result_box["code"] = int(work(overlay_front))
        except Exception as exc:  # noqa: BLE001 — surface to console, quit UI
            print(f"JARVIS> overlay session error: {exc}", file=sys.stderr)
            result_box["code"] = 2
        finally:
            bridge.finished.emit()

    threading.Thread(target=runner, daemon=True).start()
    app.exec()
    if tray is not None:
        try:
            tray.hide()
        except Exception:
            pass
    if overlay is not None:
        overlay.close()
    return result_box["code"]


def _want_overlay(args) -> bool:
    if args.no_overlay:
        return False
    if args.overlay:
        return True
    # Default on for daemon when Qt is available (issue 05).
    if args.daemon:
        try:
            import PySide6  # noqa: F401
        except ImportError:
            return False
        return True
    return False


def _want_tray(args) -> bool:
    if getattr(args, "no_tray", False):
        return False
    if not args.daemon:
        return False
    try:
        import PySide6  # noqa: F401
    except ImportError:
        return False
    return True


def _make_audit(args):
    """Build the process audit log, or None when disabled.

    Disabled by ``--no-audit`` or env ``JARVIS_AUDIT=0`` (tests use the latter
    via conftest so older CLI tests never write ``~/.jarvis/audit.log``).
    """
    import os

    if getattr(args, "no_audit", False):
        return None
    env = os.environ.get("JARVIS_AUDIT", "1").strip().lower()
    if env in ("0", "false", "no", "off"):
        return None
    from jarvis.audit import default_audit_log

    return default_audit_log()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.install_autostart or args.uninstall_autostart:
        return _handle_autostart(args)

    # Settings file (optional explicit path) then env/defaults.
    if args.settings is not None:
        from jarvis.settings import apply_user_settings, load_settings

        config = JarvisConfig.from_env(apply_settings=False)
        config = apply_user_settings(config, load_settings(args.settings))
    else:
        config = JarvisConfig.from_env()
    if args.brain:
        config.brain_provider = args.brain
    if args.fake:
        config.brain_provider = "fake"
    if args.model:
        # Apply model to whichever cloud brain is selected.
        if config.brain_provider == "claude":
            config.claude_model = args.model
        else:
            config.grok_model = args.model
            # Keep claude_model in sync only when explicitly on Claude.
    if args.cwd:
        config.cwd = args.cwd
    if args.no_speak:
        config.speak = False
    if args.hotkey:
        config.hotkey = args.hotkey
    if args.no_hotkey:
        config.enable_hotkey = False
    if args.wake_threshold is not None:
        config.wake_threshold = args.wake_threshold

    if args.google_login:
        from jarvis.google.oauth import run_oauth_login

        try:
            path = run_oauth_login()
        except (FileNotFoundError, RuntimeError) as e:
            print(f"JARVIS> Google login failed: {e}", file=sys.stderr)
            return 2
        print(f"JARVIS> Google signed in (Gmail + Calendar read-only). Token: {path}")
        return 0

    if args.spotify_login:
        from jarvis.spotify.base import SpotifyError
        from jarvis.spotify.oauth import run_spotify_login
        from jarvis.spotify.tokens import spotify_token_store

        try:
            store = spotify_token_store(config.spotify_token_path)
            path = run_spotify_login(
                client_id=config.spotify_client_id, token_store=store
            )
        except SpotifyError as e:
            print(f"JARVIS> Spotify login failed: {e}", file=sys.stderr)
            return 2
        print(f"JARVIS> Spotify linked (playback control). Token: {path}")
        return 0

    if args.shoot_overlay:
        from jarvis.overlay.aurora import shoot_overlay_states

        paths = shoot_overlay_states(args.overlay_out)
        for path in paths:
            print(f"wrote {path}")
        return 0

    if args.demo_overlay:
        from jarvis.overlay.aurora import run_overlay_demo

        return run_overlay_demo()

    # In-process event bus (issue 12): brains stream live tool steps, the
    # overlay and audit log ride it as subscribers.
    from jarvis.events import EventBus

    bus = EventBus()

    brain = make_brain(
        config, fake=args.fake, provider=config.brain_provider, bus=bus
    )
    speaker = make_speaker(config, no_speak=args.no_speak)
    use_overlay = _want_overlay(args)
    use_tray = _want_tray(args)
    # --fake enables sample Google data so demos work offline; real runs load
    # tokens via build_google_workspace when signed in. --no-google disables.
    use_fake = config.brain_provider == "fake" or args.fake
    use_fake_google = bool(args.fake_google or (use_fake and not args.no_google))
    google = make_google(fake_google=use_fake_google, no_google=args.no_google)
    # Same for Spotify: --fake runs on sample playback data (offline demos).
    use_fake_spotify = bool(args.fake_spotify or (use_fake and not args.no_spotify))
    spotify = make_spotify(
        config, fake_spotify=use_fake_spotify, no_spotify=args.no_spotify
    )
    media = make_media(config)
    windows = make_windows()
    apps = make_apps()
    system = make_system(config)
    # Markdown long-term memory is local and works with every brain (incl. fake).
    memory = make_memory(config, no_memory=args.no_memory)
    # MCP tool bridge (issue 15): give the Claude brain JARVIS's own tools over
    # an in-process HTTP MCP server. Tool calls run through the real confirm
    # gate + event bus. Only the Claude provider gets the bridge (Grok has none;
    # its capability gap is documented in the Grok system prompt).
    if isinstance(brain, ClaudeCodeBrain):
        from jarvis.brain.mcp_bridge import JarvisToolBridge

        brain.tool_bridge = JarvisToolBridge(
            bus=bus,
            spotify=spotify,
            apps=apps,
            system=system,
            windows=windows,
            media=media,
            memory=memory,
            google=google,
        )
    # Fake brain needs no network; skip connectivity pre-check so offline demos work.
    connectivity = None if use_fake else make_connectivity(config)
    audit = _make_audit(args)
    if audit is not None:
        # Audit becomes a bus subscriber (issue 12): call sites log through the
        # bus; the real JSONL writer subscribes — records byte-identical.
        from jarvis.audit import BusAuditor, attach_audit

        attach_audit(bus, audit)
        audit = BusAuditor(bus)
    # Shared across daemon cycles / REPL turns so "cancel" aborts in-flight work.
    long_tasks = LongTaskService(
        threshold_s=config.long_task_threshold_s, audit=audit
    )

    if args.daemon:
        if args.once is not None or args.listen:
            print(
                "Use --daemon alone (not with --once / --listen).",
                file=sys.stderr,
            )
            return 2
        try:
            # Fake STT for daemon demos still needs multi-session audio for each cycle.
            if args.fake_stt is not None:
                import numpy as np

                silence = SilenceConfig(
                    silence_duration_s=config.silence_duration_s,
                    max_record_s=config.max_record_s,
                )
                sr = silence.sample_rate
                speech = np.full(int(sr * 0.5), 0.2, dtype=np.float32)
                quiet = np.zeros(
                    int(sr * (config.silence_duration_s + 0.2)), dtype=np.float32
                )
                n = args.max_cycles or 1
                sessions = [[speech, quiet] for _ in range(max(n * 2, 2))]
                recorder = MicRecorder(config=silence, block_sessions=sessions)
                transcriber = FakeTranscriber(text=args.fake_stt)
            else:
                transcriber = make_transcriber(config, fake_stt=None)
                recorder = make_recorder(config, fake_stt=None)
            detector = make_wake_detector(config, fake_wake=args.fake_wake)
        except RuntimeError as e:
            print(f"JARVIS> front door error: {e}", file=sys.stderr)
            return 2

        frames_factory = None
        if args.fake_wake:
            import itertools

            import numpy as np

            fl = detector.frame_length

            def frames_factory() -> Any:
                # Endless silence frames; FakeWakeDetector fires via fire_after
                # (re-armed by detector.reset() at the start of each wait).
                return (np.zeros(fl, dtype=np.int16) for _ in itertools.count())

        from jarvis.resident import ResidentController

        resident = ResidentController(audit=audit)

        # Drive the SPINE mic privacy-shutter from the REAL front-door state:
        # paused = verifiably deaf = shutter closed; running = listening = open.
        # Published on the shared bus so the overlay reflects it (issue 18).
        def _publish_listening(state: str) -> None:
            from jarvis.events import ListeningChanged

            bus.publish(ListeningChanged(listening=(state == "running")))

        resident.on_state_change = _publish_listening

        def _daemon_work(overlay=None) -> int:
            return run_daemon(
                config=config,
                brain=brain,
                speaker=speaker,
                transcriber=transcriber,
                recorder=recorder,
                detector=detector,
                overlay=overlay,
                google=google,
                memory=memory,
                spotify=spotify,
                media=media,
                windows=windows,
                apps=apps,
                system=system,
                connectivity=connectivity,
                long_tasks=long_tasks,
                max_cycles=args.max_cycles,
                frames_factory=frames_factory,
                announce=True,
                resident=resident,
                audit=audit,
            )

        # Tray and/or overlay need a Qt app. Prefer that path when either is on.
        if use_overlay or use_tray:
            return _run_with_qt_overlay(
                lambda ov: _daemon_work(ov),
                hold_after_s=0.3,
                resident=resident,
                enable_tray=use_tray,
                use_overlay=use_overlay,
                bus=bus,
                overlay_style=config.overlay_style,
            )
        return _daemon_work(None)

    if args.listen or args.fake_stt is not None:
        if args.once is not None:
            print("Use either --once or --listen/--fake-stt, not both.", file=sys.stderr)
            return 2
        try:
            transcriber = make_transcriber(config, fake_stt=args.fake_stt)
            recorder = make_recorder(config, fake_stt=args.fake_stt)
        except RuntimeError as e:
            print(f"JARVIS> voice error: {e}", file=sys.stderr)
            return 2

        if use_overlay:
            return _run_with_qt_overlay(
                lambda ov: run_listen(
                    brain=brain,
                    speaker=speaker,
                    recorder=recorder,
                    transcriber=transcriber,
                    announce=args.fake_stt is None,
                    overlay=ov,
                    google=google,
                    memory=memory,
                    spotify=spotify,
                    media=media,
                    windows=windows,
                    apps=apps,
                    system=system,
                    connectivity=connectivity,
                    long_tasks=long_tasks,
                    unload_stt_after=config.unload_stt_between_commands,
                    long_task_threshold_s=config.long_task_threshold_s,
                    audit=audit,
                ),
                bus=bus,
                overlay_style=config.overlay_style,
            )
        return run_listen(
            brain=brain,
            speaker=speaker,
            recorder=recorder,
            transcriber=transcriber,
            announce=args.fake_stt is None,
            google=google,
            memory=memory,
            spotify=spotify,
            media=media,
            windows=windows,
            apps=apps,
            system=system,
            connectivity=connectivity,
            long_tasks=long_tasks,
            unload_stt_after=config.unload_stt_between_commands,
            long_task_threshold_s=config.long_task_threshold_s,
            audit=audit,
        )

    if args.once is not None:
        if use_overlay:
            return _run_with_qt_overlay(
                lambda ov: run_once(
                    args.once,
                    brain=brain,
                    speaker=speaker,
                    overlay=ov,
                    google=google,
                    memory=memory,
                    spotify=spotify,
                    media=media,
                    windows=windows,
                    apps=apps,
                    system=system,
                    connectivity=connectivity,
                    long_tasks=long_tasks,
                    long_task_threshold_s=config.long_task_threshold_s,
                    audit=audit,
                ),
                bus=bus,
                overlay_style=config.overlay_style,
            )
        return run_once(
            args.once,
            brain=brain,
            speaker=speaker,
            google=google,
            memory=memory,
            spotify=spotify,
            media=media,
            windows=windows,
            apps=apps,
            system=system,
            connectivity=connectivity,
            long_tasks=long_tasks,
            long_task_threshold_s=config.long_task_threshold_s,
            audit=audit,
        )

    if args.overlay and not args.daemon:
        print(
            "--overlay applies to --listen / --once / --fake-stt / --daemon "
            "(or use --demo-overlay / --shoot-overlay).",
            file=sys.stderr,
        )
        return 2

    return run_repl(
        brain=brain,
        speaker=speaker,
        config=config,
        fake_stt=None,
        google=google,
        memory=memory,
        spotify=spotify,
        media=media,
        windows=windows,
        apps=apps,
        system=system,
        connectivity=connectivity,
        long_tasks=long_tasks,
        audit=audit,
    )


if __name__ == "__main__":
    sys.exit(main())
