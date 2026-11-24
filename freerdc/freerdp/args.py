"""Translate a Profile into FreeRDP command-line arguments for a given client.

Each option is written once, with the 2.x and 3.x spellings side by side, so the
GUI never has to know which version it is talking to. Options a client cannot
honour (e.g. the floatbar in the SDL client) are dropped and reported in
`BuildResult.warnings` so the GUI can tell the user.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..model import Profile
from .detect import FreeRDPClient


@dataclass
class BuildResult:
    args: list[str] = field(default_factory=list)     # everything except secrets
    secrets: list[str] = field(default_factory=list)  # e.g. /p:..., never put on argv
    warnings: list[str] = field(default_factory=list)
    v3: bool = True
    stdin_v2: list[str] = field(default_factory=list)  # FreeRDP 2: the password line

    def command(self, client: FreeRDPClient) -> list[str]:
        """The argv to execute, keeping secrets off it.

        FreeRDP 3: `/args-from:stdin` (which refuses any other argument, so *all* arguments
        travel over stdin).  FreeRDP 2 has no such option; `/from-stdin:force` makes it read
        the password as a line on stdin instead."""
        if not self.secrets:
            return [client.path, *self.args]
        if self.v3:
            return [client.path, "/args-from:stdin"]
        return [client.path, *self.args, "/from-stdin:force"]

    def stdin_payload(self) -> str:
        if not self.secrets:
            return ""
        lines = [*self.args, *self.secrets] if self.v3 else self.stdin_v2
        return "\n".join(lines) + "\n"

    def display_command(self, client: FreeRDPClient) -> list[str]:
        """Full command line for the preview, with secret values masked."""
        masked = [s.split(":", 1)[0] + ":********" for s in self.secrets]
        return [client.path, *self.args, *masked]


def _colon_hex(h: str) -> str:
    return ":".join(h[i:i + 2] for i in range(0, len(h), 2))


def _on_off(flag: str, enabled: bool) -> str:
    return ("+" if enabled else "-") + flag


def _cert_args(p: Profile, r: BuildResult) -> None:
    # Both versions take sha256 fingerprints; FreeRDP 2 only matches the colon-separated form.
    fps = [f"fingerprint:sha256:{_colon_hex(f)}" for f in p.trusted_fingerprints]
    if p.cert_mode == "any":
        r.args.append("/cert:ignore")
    elif p.cert_mode == "saved":
        # 'deny' makes unknown certificates fail immediately instead of prompting.
        r.args.append("/cert:" + ",".join(["deny", *fps]))
    elif fps:  # ask: known fingerprints pass silently, anything else triggers the GUI prompt
        r.args.append("/cert:" + ",".join(fps))


def build_args(p: Profile, client: FreeRDPClient) -> BuildResult:
    v3 = client.major >= 3
    r = BuildResult(v3=v3)
    a = r.args

    # --- connection -------------------------------------------------------
    a.append(f"/v:{p.host}:{p.port}" if p.port != 3389 else f"/v:{p.host}")
    if p.username:
        a.append(f"/u:{p.username}")
    if p.domain:
        a.append(f"/d:{p.domain}")
    if p.password:
        # Keep the password out of argv (visible in `ps`).
        if v3:
            r.secrets.append(f"/p:{p.password}")
        elif p.username:
            r.secrets.append(f"/p:{p.password}")
            r.stdin_v2 = [p.password]  # FreeRDP 2 reads just the password from stdin
        else:
            # Without /u FreeRDP 2 also asks for user name and domain through buffered
            # stdio, which swallows the password line; there is no safe way to send it.
            r.warnings.append("FreeRDP 2 needs a user name to take the password via stdin; "
                              "the password was not sent.")
    if p.security:
        a.append(f"/sec:{p.security}")

    # --- display ----------------------------------------------------------
    if p.fullscreen:
        a.append("/f")
    elif p.width and p.height:
        a.append(f"/size:{p.width}x{p.height}")
    if p.monitors:
        a.append("/monitors:" + ",".join(str(m) for m in p.monitors))
    if p.multimon:
        a.append("/multimon:force")
    dynamic = p.dynamic_resolution
    if dynamic and p.smart_sizing:
        # FreeRDP 3 aborts with a usage error if both are given; the explicit choice wins.
        dynamic = False
        r.warnings.append("Smart sizing and dynamic resolution are mutually exclusive; "
                          "dynamic resolution was turned off.")
    if dynamic:
        a.append("+dynamic-resolution")
    if p.smart_sizing:
        a.append("/smart-sizing")
    if p.color_depth:
        a.append(f"/bpp:{p.color_depth}")

    # --- local resources --------------------------------------------------
    # 2.x: +clipboard / -clipboard.  3.x: /clipboard (with sub-options); -clipboard disables.
    a.append("/clipboard" if (v3 and p.clipboard) else _on_off("clipboard", p.clipboard))
    if p.sound:
        a.append("/sound")
    if p.microphone:
        a.append("/microphone")
    for d in p.drives:
        a.append(f"/drive:{d.name},{d.path}")
    if p.home_drive:
        a.append("+home-drive")

    # --- experience -------------------------------------------------------
    if p.gfx_h264 and not client.h264:
        # Passing it anyway makes such a client reject the whole command line.
        r.warnings.append(f"This FreeRDP ({client.version}) was built without H.264 support; "
                          "the H.264 setting is ignored.")
    elif p.gfx_h264:
        # 2.x: separate /gfx-h264 switch.  3.x: folded into /gfx.
        a.append(f"/gfx:{p.gfx_h264}" if v3 else f"/gfx-h264:{p.gfx_h264}")

    # --- advanced ---------------------------------------------------------
    _cert_args(p, r)
    if p.auto_reconnect:
        a.append("+auto-reconnect")
        a.append(f"/auto-reconnect-max-retries:{p.auto_reconnect_retries}")
    if p.floatbar:
        fb = p.floatbar
        a.append(
            "/floatbar:sticky:{},default:{},show:{}".format(
                "on" if fb.sticky else "off",
                "visible" if fb.default_visible else "hidden",
                fb.show,
            )
        )

    if p.show_log:
        a.append(f"/log-level:{p.log_level}")

    a.extend(p.extra_args)
    return r
