"""Compound-command detector (issue 17 gap): route multi-step utterances to the
brain, keep single commands with their reflex tier.

The two flagship positives are the user's "actually gets things done" tasks; the
negatives are the everyday utterances that must stay with apps / spotify / memory
/ windows rather than being stolen by the guard.
"""

from __future__ import annotations

import pytest

from jarvis.compound import is_compound_command

# --- MUST-PASS positives (route to the brain) ------------------------------

POSITIVES = [
    # flagship two: second action verb, and two-window arrangement
    "open spotify and play the next music",
    "open brave and vs code side by side, brave left 50%, vs code right",
    # the other must-pass positives
    "open notepad and minimize everything",
    "play some music and dim the brightness",
    # a few more genuine compounds
    "open chrome then play some jazz",
    "launch spotify and skip this song",  # "skip this song" (noun object) is a new act
    "open notepad; minimize all windows",
    "pause the music and open brave",
    "open brave & open vs code",
    "open discord after that mute my mic",
    "open brave and vs code split screen",
    "put brave on the left and chrome on the right",
    "show me my email and open brave",
]


@pytest.mark.parametrize("text", POSITIVES)
def test_positive_is_compound(text: str) -> None:
    assert is_compound_command(text) is True, text


# --- MUST-NOT-BREAK negatives (stay with the single-command reflex) --------

NEGATIVES = [
    # single app opens
    "open spotify",
    "open brave",
    "launch vs code",
    # "and" inside a song / game title — no second action verb
    "play rock and roll",
    "play guns and roses",
    "open command and conquer",
    # single facts that merely contain "and" (memory tier)
    "remember I parked on level 3 and my meeting is at 4pm",
    "remind me to buy milk and eggs",
    # single window / system / spotify commands
    "close chrome",
    "minimize all windows",
    "dim brightness to zero",
    "next track",
    # media find-and-play is ONE task ("it" back-references the found file)
    "find Project Hail Mary in Downloads and play it",
    "go to my Downloads folder, find Project Hail Mary, and play it",
    "find Project Hail Mary in Downloads and play it fullscreen",
    # single-window snap — one side only, not a two-window layout
    "snap vlc to the left",
    "put chrome on the right",
    "snap vlc left",
    # verb + back-reference pronoun is a continuation, not a new command
    "open notepad and close it",
    # non-command with a plain comma list
    "buy milk, eggs, and bread",
]


@pytest.mark.parametrize("text", NEGATIVES)
def test_negative_is_not_compound(text: str) -> None:
    assert is_compound_command(text) is False, text


def test_empty_is_not_compound() -> None:
    assert is_compound_command("") is False
    assert is_compound_command("   ") is False
    assert is_compound_command(None) is False  # type: ignore[arg-type]


def test_side_by_side_alone_triggers() -> None:
    # inherently-two arrangement phrase, no conjunction needed
    assert is_compound_command("brave and chrome next to each other") is True


def test_left_right_pair_triggers_but_single_side_does_not() -> None:
    assert is_compound_command("brave left half, chrome right half") is True
    assert is_compound_command("move brave to the left half") is False
