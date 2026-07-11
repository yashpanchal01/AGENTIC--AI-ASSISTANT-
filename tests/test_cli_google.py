"""CLI wiring for Google OAuth / fake Gmail-Calendar path."""

from __future__ import annotations

from jarvis.cli import main


def test_fake_once_any_new_email(capsys) -> None:
    code = main(["--fake", "--no-speak", "--once", "any new email?"])
    captured = capsys.readouterr()
    assert code == 0
    assert "unread" in captured.out.lower() or "invoice" in captured.out.lower()
    assert "gmail_unread" in captured.out


def test_fake_once_send_email_denied(capsys) -> None:
    code = main(
        ["--fake", "--no-speak", "--once", "send an email to bob saying hello"]
    )
    captured = capsys.readouterr()
    assert code == 0  # denied is still ok=True
    assert "read-only" in captured.out.lower() or "won't" in captured.out.lower()
    assert "denied" in captured.out.lower()


def test_no_google_falls_through_to_brain(capsys) -> None:
    code = main(
        ["--fake", "--no-google", "--no-speak", "--once", "any new email?"]
    )
    captured = capsys.readouterr()
    assert code == 0
    # Without google, FakeBrain rule-based path handles it (not gmail_unread).
    assert "gmail_unread" not in captured.out
