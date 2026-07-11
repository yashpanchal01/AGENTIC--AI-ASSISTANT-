"""Markdown long-term memory store (issue 07).

One human-editable markdown file per remembered fact — dated, tagged,
summarized. The user can open, edit, or delete any note by hand and the store
keeps working: parsing is deliberately lenient. Credentials and secrets are
categorically refused and never written under this tree (see also
jarvis.google.tokens.TokenStore which hard-guards the other direction).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from jarvis.confirm import is_secret_request
from jarvis.paths import jarvis_home

_DATE_FMT = "%Y-%m-%d %H:%M"

_STOPWORDS = frozenset(
    "a an and are as at be but by did do does for from has have he her his "
    "i in is it its me my of on or our she so that the their them they this "
    "to was we were what when where which who will with you your".split()
)

_META_RE = re.compile(r"^[-*]\s*(date|tags|source)\s*:\s*(.*)$", re.IGNORECASE)


def default_memory_dir() -> Path:
    """Markdown memory root: ``JARVIS_MEMORY_DIR``, else ``~/.jarvis/memory``.

    Google tokens and other credentials must never be written under this tree.
    """
    env = os.environ.get("JARVIS_MEMORY_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return (jarvis_home() / "memory").resolve()


@dataclass(frozen=True)
class MemoryNote:
    """One remembered fact parsed from a markdown note file."""

    fact: str
    summary: str
    tags: tuple[str, ...]
    date: str  # "YYYY-MM-DD HH:MM" (best-effort for hand-edited files)
    source: str
    path: Path


class MemoryStore:
    """Folder of plain markdown notes — the persistence behind "remember that …"."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root is not None else default_memory_dir()

    # -- write ----------------------------------------------------------------

    def remember(self, fact: str, *, source: str = "voice") -> MemoryNote:
        """Persist one fact as a dated, tagged markdown note. Refuses secrets."""
        text = " ".join((fact or "").split())
        if not text:
            raise ValueError("nothing to remember")
        if is_secret_request(text):
            # Belt and suspenders: the handler refuses first, and the store
            # must also never let credential material reach disk.
            raise ValueError("secrets are never written to memory notes")
        now = datetime.now()
        summary = _summarize(text)
        tags = _tags_for(text)
        path = self._new_note_path(now, summary)
        body = (
            f"# {summary}\n"
            f"\n"
            f"- Date: {now.strftime(_DATE_FMT)}\n"
            f"- Tags: {', '.join(tags) if tags else 'note'}\n"
            f"- Source: {source}\n"
            f"\n"
            f"{text}\n"
        )
        self.root.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        return MemoryNote(
            fact=text,
            summary=summary,
            tags=tags,
            date=now.strftime(_DATE_FMT),
            source=source,
            path=path,
        )

    def forget(self, query: str) -> list[MemoryNote]:
        """Delete notes matching *query* (user correction). Returns the removed."""
        removed: list[MemoryNote] = []
        for note in self.search(query):
            try:
                note.path.unlink()
            except OSError:
                continue
            removed.append(note)
        return removed

    # -- read -----------------------------------------------------------------

    def notes(self) -> list[MemoryNote]:
        """All parseable notes, newest first. Broken/foreign files are skipped."""
        try:
            paths = sorted(self.root.glob("*.md"))
        except OSError:
            return []
        found: list[MemoryNote] = []
        for path in paths:
            note = self._parse(path)
            if note is not None:
                found.append(note)
        found.sort(key=lambda n: n.date, reverse=True)
        return found

    def search(self, query: str) -> list[MemoryNote]:
        """Notes whose fact/summary/tags overlap the query's significant words."""
        words = _significant_words(query)
        if not words:
            return []
        scored: list[tuple[int, MemoryNote]] = []
        for note in self.notes():
            haystack = " ".join(
                (note.fact, note.summary, " ".join(note.tags))
            ).lower()
            score = sum(1 for w in words if w in haystack)
            if score:
                scored.append((score, note))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [note for _, note in scored]

    # -- internals --------------------------------------------------------

    def _new_note_path(self, now: datetime, summary: str) -> Path:
        slug = _slugify(summary) or "note"
        base = f"{now.strftime('%Y-%m-%d')}-{slug}"
        path = self.root / f"{base}.md"
        n = 2
        while path.exists():
            path = self.root / f"{base}-{n}.md"
            n += 1
        return path

    def _parse(self, path: Path) -> MemoryNote | None:
        try:
            raw = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None
        title = ""
        meta: dict[str, str] = {}
        body: list[str] = []
        for line in raw.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("#") and not title:
                title = stripped.lstrip("#").strip()
                continue
            m = _META_RE.match(stripped)
            if m:
                meta[m.group(1).lower()] = m.group(2).strip()
                continue
            body.append(stripped)
        fact = " ".join(body).strip() or title
        if not fact:
            return None
        date = meta.get("date", "")
        if not date:
            try:
                date = datetime.fromtimestamp(path.stat().st_mtime).strftime(
                    _DATE_FMT
                )
            except OSError:
                date = ""
        tags = tuple(
            t.strip().lower() for t in meta.get("tags", "").split(",") if t.strip()
        )
        return MemoryNote(
            fact=fact,
            summary=title or _summarize(fact),
            tags=tags,
            date=date,
            source=meta.get("source", "note"),
            path=path,
        )


def memory_context_for_prompt(
    root: Path | None = None, *, limit: int = 20, max_chars: int = 1500
) -> str:
    """Compact digest of memory notes for the cloud brain's system prompt.

    Empty string when there are no notes (the prompt stays clean). Never
    raises — the brain must start even if the notes folder is unreadable.
    """
    try:
        store = MemoryStore(root)
        notes = store.notes()
    except Exception:  # noqa: BLE001 — memory must never block the brain
        return ""
    if not notes:
        return ""
    parts: list[str] = []
    used = 0
    for note in notes[:limit]:
        day = note.date.split(" ")[0] if note.date else ""
        entry = note.fact + (f" (noted {day})" if day else "")
        if used + len(entry) > max_chars:
            break
        parts.append(entry)
        used += len(entry)
    if not parts:
        return ""
    return (
        "Long-term memory — facts the user asked JARVIS to remember: "
        + "; ".join(parts)
        + f". Use them when relevant. They live as markdown notes in {store.root}; "
        "never write passwords, API keys, or credentials there."
    )


def _summarize(fact: str, *, max_len: int = 72) -> str:
    # Whole fact, trimmed — sentence-splitting mangles abbreviations ("Dr. Rao").
    text = " ".join((fact or "").split()).rstrip(".!?")
    if len(text) > max_len:
        text = text[: max_len - 1].rstrip() + "…"
    if not text:
        return "Note"
    return text[0].upper() + text[1:]


def _slugify(text: str, *, max_len: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return slug[:max_len].rstrip("-")


def _significant_words(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9']+", (text or "").lower())
    out: list[str] = []
    for word in words:
        word = word.strip("'")
        if len(word) < 3 or word in _STOPWORDS:
            continue
        if word not in out:
            out.append(word)
    return out


def _tags_for(fact: str, *, limit: int = 4) -> tuple[str, ...]:
    return tuple(_significant_words(fact)[:limit])


__all__ = [
    "MemoryNote",
    "MemoryStore",
    "default_memory_dir",
    "memory_context_for_prompt",
]
