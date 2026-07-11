"""Google Workspace integration — Gmail + Calendar, read-only (issue 08)."""

from jarvis.google.base import GoogleResult, GoogleWorkspace
from jarvis.google.fake import FakeCalendar, FakeGmail, FakeGoogleWorkspace, sample_workspace
from jarvis.google.tokens import TokenStore, default_token_path, memory_notes_dir
from jarvis.google.workspace import GoogleWorkspaceImpl, build_google_workspace

__all__ = [
    "FakeCalendar",
    "FakeGmail",
    "FakeGoogleWorkspace",
    "GoogleResult",
    "GoogleWorkspace",
    "GoogleWorkspaceImpl",
    "TokenStore",
    "build_google_workspace",
    "default_token_path",
    "memory_notes_dir",
    "sample_workspace",
]
