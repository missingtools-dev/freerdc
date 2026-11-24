"""Recognise from FreeRDP's console output that the remote session is actually up."""
from __future__ import annotations

import re

# Both are logged only after authentication and licensing have succeeded, when the client
# sets up the display and its channels, and neither appears for a failed login. Verified
# on FreeRDP 2.11.7 and 3.15.0 at their default log level. Two markers because the second
# survives a client that skips the first; a custom /log-level above INFO hides both, in
# which case the caller simply never learns that the session started.
_ESTABLISHED = re.compile(
    r"Local framebuffer format|Loading Dynamic Virtual Channel"
)


def session_established(text: str) -> bool:
    return _ESTABLISHED.search(text) is not None
