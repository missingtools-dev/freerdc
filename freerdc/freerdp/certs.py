"""Parse FreeRDP's 'Do you trust the above certificate?' prompt from its console output."""
from __future__ import annotations

import re
from dataclasses import dataclass

PROMPT_MARKER = "Do you trust the above certificate"
_FIELDS = {
    "common_name": r"Common Name:\s*(.+)",
    "subject": r"Subject:\s*(.+)",
    "issuer": r"Issuer:\s*(.+)",
    "valid_from": r"Valid from:\s*(.+)",
    "valid_to": r"Valid to:\s*(.+)",
    "thumbprint": r"Thumbprint:\s*([0-9A-Fa-f:]+)",
}


@dataclass
class CertInfo:
    host: str = ""
    common_name: str = ""
    subject: str = ""
    issuer: str = ""
    valid_from: str = ""
    valid_to: str = ""
    thumbprint: str = ""  # lowercase hex, no colons

    @property
    def pinnable(self) -> bool:
        """FreeRDP 3 accepts sha256 fingerprints (64 hex digits)."""
        return len(self.thumbprint) == 64

    @property
    def thumbprint_display(self) -> str:
        t = self.thumbprint
        return ":".join(t[i:i + 2] for i in range(0, len(t), 2)).upper()


def normalize_fingerprint(value: str) -> str:
    return value.replace(":", "").replace(" ", "").lower()


def has_prompt(text: str) -> bool:
    """True once FreeRDP has reported an untrusted certificate.

    FreeRDP 3 prints the interactive question. FreeRDP 2 skips the question when
    credentials come from stdin and just aborts, so also accept the details block
    followed by its 'not trusted' error."""
    if PROMPT_MARKER in text:
        return True
    return "Certificate details for" in text and "certificate not trusted" in text


def parse_certificate_prompt(text: str) -> CertInfo | None:
    start = text.rfind("Certificate details for")
    if start < 0:
        return None
    block = text[start:]
    end = block.find(PROMPT_MARKER)
    if end >= 0:
        block = block[:end]
    info = CertInfo()
    m = re.match(r"Certificate details for ([^\s(]+)", block)
    if m:
        info.host = m.group(1)
    for attr, pattern in _FIELDS.items():
        m = re.search(r"^\s*" + pattern, block, re.M)
        if m:
            value = m.group(1).strip()
            setattr(info, attr, normalize_fingerprint(value) if attr == "thumbprint" else value)
    return info if info.thumbprint else None
