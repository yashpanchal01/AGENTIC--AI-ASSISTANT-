"""Three-tier risk policy for the bridge's shell + file tools (issue 21).

Pure classification, decided in JARVIS code — NEVER by the model. Every
``run_command`` / ``file_op`` call is mapped to exactly one tier before
anything executes:

* ``ALLOW``   — read-only allowlist (git status/log/diff, dir, type, ping…),
  file_op mkdir/copy/zip INTO approved folders. Runs with no prompt.
* ``CONFIRM`` — everything else: unlisted binaries, git mutations, process
  kills, move/rename/delete/overwrite. The caller speaks ``preview`` and
  waits for an explicit yes.
* ``DENY``    — never offered a confirm: format/diskpart, shutdown/restart,
  registry writes, privilege escalation, recursive deletes outside approved
  folders, and anything credential-touching (composes with
  :func:`jarvis.confirm.is_secret_request` — the same secret tier as voice).

Compound-command aware: ``git status; del /s C:\\`` is split on ``;``, ``&``,
``|``, ``&&``, ``||`` and newlines and takes the MOST SEVERE tier of any
segment, so a safe prefix can never smuggle a destructive suffix. Output
redirection, backticks, and ``$(...)`` subexpressions also forfeit the
allow tier (they can hide writes inside a read-only-looking command).

This module never executes anything — execution lives in :mod:`jarvis.hands`
behind the bridge's confirm gate.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from pathlib import Path

from jarvis.confirm import is_secret_request

# The three tiers, most severe last.
ALLOW = "allow"
CONFIRM = "confirm"
DENY = "deny"

_SEVERITY = {ALLOW: 0, CONFIRM: 1, DENY: 2}

SECRET_REFUSAL = "I never touch passwords, API keys, or credentials."

# How much of a command the confirm preview shows (one spoken line).
_PREVIEW_MAX = 80


@dataclass(frozen=True)
class Decision:
    """One policy verdict: the tier, plus the human line that explains it."""

    tier: str
    preview: str = ""  # one-line "what would happen" for the confirm prompt
    reason: str = ""  # machine code for audit / StepFailed ("" when allowed)
    refusal: str = ""  # spoken refusal text (only when tier == DENY)


# ---------------------------------------------------------------------------
# Shell commands
# ---------------------------------------------------------------------------

# Compound separators: a safe prefix must never smuggle a destructive suffix.
# ``&&`` / ``||`` first so they don't half-match as ``&`` / ``|``.
_SPLIT = re.compile(r"&&|\|\||[;&|\n]")

# Hard-deny: any bare token equal to one of these ends the discussion.
# Token-based (not substring) so ``git log --format=%H`` stays clear of
# ``format`` while ``format d:`` and ``echo hi & shutdown /s`` do not.
_DENY_TOKENS = frozenset(
    {
        # disk destroyers
        "format",
        "format.com",
        "diskpart",
        "mkfs",
        # power state
        "shutdown",
        "shutdown.exe",
        "restart-computer",
        "stop-computer",
        "reboot",
        # registry editors
        "regedit",
        "regedit.exe",
        # privilege escalation
        "sudo",
        "runas",
        "runas.exe",
        "psexec",
        "psexec.exe",
    }
)

# Hard-deny regexes: registry writes and elevation that hide mid-command.
_DENY_PATTERNS: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (
        re.compile(r"\breg(?:\.exe)?\s+(add|delete|import|load|unload|restore|copy)\b"),
        "registry_write",
        "I don't change the Windows registry.",
    ),
    (
        re.compile(
            r"\b(set-itemproperty|new-itemproperty|remove-itemproperty|set-item"
            r"|new-item|remove-item|clear-item)\b[^;]*(hklm:|hkcu:|hkey_|registry::)"
        ),
        "registry_write",
        "I don't change the Windows registry.",
    ),
    (
        re.compile(r"-verb\s+runas\b"),
        "privilege_escalation",
        "I don't run anything elevated.",
    ),
    # Credential FILES by path — is_secret_request catches the words
    # ("password", "credentials"), this catches the well-known key locations
    # an allowlisted read verb could otherwise reach (`type ...\.ssh\id_rsa`).
    (
        re.compile(
            r"(?:^|[\s\"'=%\\/])\.(?:ssh|aws|gnupg)(?:[\\/]|\b)"
            r"|\bid_(?:rsa|ed25519|ecdsa|dsa)\b"
            r"|\.(?:pem|ppk|kdbx)\b"
        ),
        "secret",
        SECRET_REFUSAL,
    ),
)

_DENY_REFUSALS = {
    "format": "I don't format or repartition drives.",
    "format.com": "I don't format or repartition drives.",
    "diskpart": "I don't format or repartition drives.",
    "mkfs": "I don't format or repartition drives.",
    "shutdown": "I don't shut down or restart the computer.",
    "shutdown.exe": "I don't shut down or restart the computer.",
    "restart-computer": "I don't shut down or restart the computer.",
    "stop-computer": "I don't shut down or restart the computer.",
    "reboot": "I don't shut down or restart the computer.",
    "regedit": "I don't change the Windows registry.",
    "regedit.exe": "I don't change the Windows registry.",
    "sudo": "I don't run anything elevated.",
    "runas": "I don't run anything elevated.",
    "runas.exe": "I don't run anything elevated.",
    "psexec": "I don't run anything elevated.",
    "psexec.exe": "I don't run anything elevated.",
}

_DENY_REASONS = {
    "format": "disk_destroyer",
    "format.com": "disk_destroyer",
    "diskpart": "disk_destroyer",
    "mkfs": "disk_destroyer",
    "shutdown": "power_state",
    "shutdown.exe": "power_state",
    "restart-computer": "power_state",
    "stop-computer": "power_state",
    "reboot": "power_state",
    "regedit": "registry_write",
    "regedit.exe": "registry_write",
    "sudo": "privilege_escalation",
    "runas": "privilege_escalation",
    "runas.exe": "privilege_escalation",
    "psexec": "privilege_escalation",
    "psexec.exe": "privilege_escalation",
}

# Recursive delete shapes (cmd, PowerShell, and unix-style spellings).
_RECURSIVE_DELETE = re.compile(
    r"\brm\s+-[a-z]*r"  # rm -r / rm -rf / rm -fr
    r"|\b(del|erase)\b[^;]*\s/s\b"  # del /s …
    r"|\b(rmdir|rd)\b[^;]*\s/s\b"  # rmdir /s …
    r"|\b(remove-item|ri)\b[^;]*\s-recurse"  # Remove-Item -Recurse …
)

# Verbs whose following non-flag tokens are the delete targets.
_DELETE_VERBS = frozenset(
    {"rm", "del", "erase", "rmdir", "rd", "remove-item", "ri"}
)

# Escalation guard: redirection / subexpressions can hide writes inside a
# read-only-looking segment, so they forfeit the allow tier (still confirm).
_NEVER_ALLOW = re.compile(r"[><`]|\$\(")

# Read-only binaries/cmdlets that auto-run with zero prompts. First token
# only; anything with side effects must NOT be here.
_ALLOW_BINARIES = frozenset(
    {
        "dir",
        "ls",
        "gci",
        "get-childitem",
        "type",
        "cat",
        "gc",
        "get-content",
        "pwd",
        "get-location",
        "echo",
        "write-output",
        "hostname",
        "whoami",
        "ver",
        "date",
        "get-date",
        "ping",
        "where",
        "where.exe",
        "get-command",
        "findstr",
        "select-string",
        "select",
        "select-object",
        "sort",
        "sort-object",
        "measure",
        "measure-object",
        "head",
        "tail",
        "tree",
        "tasklist",
        "ipconfig",
        "systeminfo",
        "pytest",
    }
)

# git: read-only subcommands only; stash/checkout/commit/push stay confirm.
_ALLOW_GIT_SUBCOMMANDS = frozenset(
    {"status", "log", "diff", "show", "blame", "ls-files", "describe",
     "--version", "version"}
)

# py/python: version checks and the test suite are the everyday read path
# ("run the test suite" must not prompt); any other script stays confirm.
_PYTHON_BINARIES = frozenset({"py", "python", "python3"})


def classify_command(
    command: str,
    *,
    approved_roots: tuple[Path, ...] = (),
    cwd: Path | None = None,
) -> Decision:
    """Map one shell command line to a tier (compound-aware, most severe wins).

    ``approved_roots`` and ``cwd`` are only used to decide whether a recursive
    delete stays inside the jail (confirm) or escapes it (deny); ``cwd`` also
    names the folder in the confirm preview.
    """
    text = (command or "").strip()
    if not text:
        return Decision(
            DENY, reason="empty_command", refusal="There's no command to run."
        )
    segments = [s.strip() for s in _SPLIT.split(text) if s.strip()]
    if not segments:
        return Decision(
            DENY, reason="empty_command", refusal="There's no command to run."
        )
    worst = Decision(ALLOW)
    for segment in segments:
        decision = _classify_segment(segment, approved_roots=approved_roots, cwd=cwd)
        if _SEVERITY[decision.tier] > _SEVERITY[worst.tier]:
            worst = decision
        if worst.tier == DENY:
            return Decision(
                DENY,
                preview=_preview(text, cwd),
                reason=worst.reason,
                refusal=worst.refusal,
            )
    if worst.tier == ALLOW:
        return Decision(ALLOW, preview=_preview(text, cwd))
    return Decision(CONFIRM, preview=_preview(text, cwd), reason=worst.reason)


def _classify_segment(
    segment: str, *, approved_roots: tuple[Path, ...], cwd: Path | None
) -> Decision:
    lower = segment.lower()
    tokens = lower.split()

    # 1. Credentials — same hard-deny tier as the voice path.
    if is_secret_request(segment):
        return Decision(DENY, reason="secret", refusal=SECRET_REFUSAL)

    # 2. Hard-deny tokens and patterns.
    for token in tokens:
        if token in _DENY_TOKENS:
            return Decision(
                DENY, reason=_DENY_REASONS[token], refusal=_DENY_REFUSALS[token]
            )
    for pattern, reason, refusal in _DENY_PATTERNS:
        if pattern.search(lower):
            return Decision(DENY, reason=reason, refusal=refusal)

    # 3. Recursive deletes: inside the jail → confirm; outside/unknown → deny.
    if _RECURSIVE_DELETE.search(lower):
        if _delete_targets_within(segment, approved_roots, cwd):
            return Decision(CONFIRM, reason="recursive_delete")
        return Decision(
            DENY,
            reason="recursive_delete_outside",
            refusal="I don't recursively delete outside your approved folders.",
        )

    # 4. Read-only allowlist (redirection/subexpressions forfeit it).
    if not _NEVER_ALLOW.search(segment) and _is_allowlisted(tokens):
        return Decision(ALLOW)

    # 5. Everything else asks first.
    return Decision(CONFIRM, reason="unlisted")


def _is_allowlisted(tokens: list[str]) -> bool:
    if not tokens:
        return False
    head = tokens[0].removesuffix(".exe") if tokens[0].endswith(".exe") else tokens[0]
    if head == "git":
        return len(tokens) > 1 and tokens[1] in _ALLOW_GIT_SUBCOMMANDS
    if head in _PYTHON_BINARIES:
        rest = " ".join(tokens[1:])
        return rest in ("--version", "-v") or "-m pytest" in rest
    return head in _ALLOW_BINARIES


def _delete_targets_within(
    segment: str, approved_roots: tuple[Path, ...], cwd: Path | None
) -> bool:
    """True only when EVERY delete target provably resolves inside the jail."""
    if not approved_roots:
        return False
    # Quote-aware split so "C:\Users\Some Name\…" stays one target token
    # (posix=False keeps Windows backslashes literal; quotes stripped below).
    try:
        tokens = shlex.split(segment, posix=False)
    except ValueError:
        tokens = segment.split()
    targets: list[str] = []
    seen_verb = False
    for token in tokens:
        lower = token.lower()
        if not seen_verb:
            seen_verb = lower in _DELETE_VERBS
            continue
        if token.startswith(("-", "/")):
            continue  # flags (del /s, rm -rf, Remove-Item -Recurse -Force)
        targets.append(token.strip("'\""))
    if not targets:
        return False  # no provable target → treat as an escape attempt
    for raw in targets:
        path = Path(raw).expanduser()
        if not path.is_absolute():
            if cwd is None:
                return False
            path = Path(cwd) / path
        if not _is_within(path, approved_roots):
            return False
    return True


def _preview(command: str, cwd: Path | None) -> str:
    """One spoken line: Run `<command>` in <folder>."""
    shown = command if len(command) <= _PREVIEW_MAX else (
        command[: _PREVIEW_MAX - 1].rstrip() + "…"
    )
    where = f" in {Path(cwd).name or Path(cwd)}" if cwd is not None else ""
    return f"Run `{shown}`{where}"


# ---------------------------------------------------------------------------
# File operations
# ---------------------------------------------------------------------------

FILE_OPS: tuple[str, ...] = (
    "move",
    "rename",
    "copy",
    "delete",
    "mkdir",
    "zip",
    "unzip",
)

# Ops that need a destination as well as a source.
_NEEDS_DST = frozenset({"move", "rename", "copy", "zip", "unzip"})

OUTSIDE_JAIL_REFUSAL = "That path isn't in your approved folders."


def classify_file_op(
    op: str,
    src: str,
    dst: str | None = None,
    *,
    approved_roots: tuple[Path, ...] = (),
) -> Decision:
    """Map one structured file operation to a tier.

    Path jail first: src (and dst when the op takes one) must resolve —
    symlinks and ``..`` included — inside *approved_roots*, else DENY (a
    refusal, never a confirm). Then: mkdir and copy/zip/unzip into fresh
    destinations auto-allow; move/rename/delete and any overwrite confirm.
    """
    kind = (op or "").strip().lower()
    if kind not in FILE_OPS:
        return Decision(
            DENY,
            reason="unknown_op",
            refusal=f"I don't know the file operation '{kind or op}'.",
        )
    if not (src or "").strip():
        return Decision(
            DENY, reason="bad_args", refusal="That file operation needs a src path."
        )
    if kind in _NEEDS_DST and not (dst or "").strip():
        return Decision(
            DENY, reason="bad_args", refusal=f"file_op {kind} needs a dst path."
        )

    src_path = Path(src).expanduser()
    dst_path = Path(dst).expanduser() if kind in _NEEDS_DST else None
    for candidate in (src_path, dst_path):
        if candidate is not None and not _is_within(candidate, approved_roots):
            return Decision(
                DENY, reason="outside_approved", refusal=OUTSIDE_JAIL_REFUSAL
            )

    if kind == "mkdir":
        return Decision(ALLOW, preview=f"Create folder {src_path.name}")
    if kind == "delete":
        return Decision(
            CONFIRM,
            preview=f"Delete {src_path.name} to the Recycle Bin",
            reason="delete",
        )
    if kind in ("move", "rename"):
        verb = "Move" if kind == "move" else "Rename"
        return Decision(
            CONFIRM, preview=f"{verb} {src_path.name} to {dst_path}", reason=kind
        )
    # copy / zip / unzip: creating something new is allowed; landing on an
    # existing destination is an overwrite and asks first.
    assert dst_path is not None
    if _would_overwrite(kind, dst_path):
        return Decision(
            CONFIRM,
            preview=f"Overwrite {dst_path.name} ({kind} from {src_path.name})",
            reason="overwrite",
        )
    verb = {"copy": "Copy", "zip": "Zip", "unzip": "Unzip"}[kind]
    return Decision(ALLOW, preview=f"{verb} {src_path.name} to {dst_path}")


def _would_overwrite(kind: str, dst: Path) -> bool:
    try:
        if kind == "unzip":
            # Extracting into a non-empty folder can silently replace files.
            return dst.is_dir() and any(dst.iterdir())
        return dst.exists()
    except OSError:
        return True  # unreadable destination → assume the risky case


def _is_within(path: Path, roots: tuple[Path, ...]) -> bool:
    """True if *path* is one of *roots* or inside one (symlinks/.. resolved).

    Same semantics as perception's jail check (issue 19), kept local so this
    module stays a pure, dependency-light policy unit.
    """
    try:
        cand = path.resolve()
    except OSError:
        return False
    for root in roots:
        try:
            base = Path(root).resolve()
        except OSError:
            continue
        if cand == base or base in cand.parents:
            return True
    return False


__all__ = [
    "ALLOW",
    "CONFIRM",
    "DENY",
    "Decision",
    "FILE_OPS",
    "OUTSIDE_JAIL_REFUSAL",
    "SECRET_REFUSAL",
    "classify_command",
    "classify_file_op",
]
