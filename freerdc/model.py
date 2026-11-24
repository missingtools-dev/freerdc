"""Connection profile: everything the GUI lets the user configure."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Floatbar:
    sticky: bool = True
    default_visible: bool = True
    show: str = "always"  # always | fullscreen | window


@dataclass
class Drive:
    name: str
    path: str


@dataclass
class Profile:
    host: str = ""
    port: int = 3389
    username: str = ""
    domain: str = ""
    password: str = ""  # runtime only; store in keyring, never in the profile file

    # Display
    fullscreen: bool = False
    width: Optional[int] = None
    height: Optional[int] = None
    monitors: list[int] = field(default_factory=list)  # empty = primary only
    multimon: bool = False
    dynamic_resolution: bool = True
    smart_sizing: bool = False
    color_depth: Optional[int] = None  # 8/15/16/24/32

    # Local resources
    clipboard: bool = True
    sound: bool = False
    microphone: bool = False
    drives: list[Drive] = field(default_factory=list)
    home_drive: bool = False

    # Experience
    gfx_h264: Optional[str] = None  # None | "AVC420" | "AVC444"

    # Advanced
    security: Optional[str] = None  # rdp | tls | nla | ext
    # How to treat the server's X.509 certificate:
    #   "ask"   - prompt in the GUI when an unknown certificate is seen
    #   "saved" - only accept certificates in trusted_fingerprints (never prompt)
    #   "any"   - ignore certificate errors altogether (insecure)
    cert_mode: str = "ask"
    trusted_fingerprints: list[str] = field(default_factory=list)  # sha256 hex, no colons
    auto_reconnect: bool = True
    auto_reconnect_retries: int = 5
    floatbar: Optional[Floatbar] = field(default_factory=Floatbar)
    show_log: bool = False  # stream the FreeRDP console log in the UI
    log_level: str = "INFO"  # used when show_log is on
    extra_args: list[str] = field(default_factory=list)  # escape hatch, passed verbatim
