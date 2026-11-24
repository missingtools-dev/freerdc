"""Turn FreeRDP's console output into something a person can act on.

Detection keys on the error *names* FreeRDP logs (ERRCONNECT_* while connecting, ERRINFO_*
once a session was up). They are identical on FreeRDP 2 and 3 and on every client flavour,
whereas exit codes are not: the Wayland client reports 255 for everything. The exit code is
only a fallback. Verified on 2.11.7 and 3.15; entries marked (source) come from FreeRDP's
error tables and could not be provoked on the test server.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Attempt:
    """What the user asked for; used to make a message specific."""
    target: str                   # host:port as shown to the user
    username: str = ""
    security: str | None = None   # forced security mode, or None for negotiate
    cert_mode: str = "ask"
    timeout_s: int = 0


@dataclass(frozen=True)
class Diagnosis:
    title: str
    message: str
    hint: str = ""
    code: str = ""             # the FreeRDP error name this came from
    informative: bool = False  # not a failure: a session that ended for a stated reason
    silent: bool = False       # nothing worth telling the user (a normal end)


_NAME_RE = re.compile(r"\b(ERRCONNECT_[A-Z_]+|ERRINFO_[A-Z_0-9]+)\b")
_NEGO_RE = re.compile(r"Error: (SSL_REQUIRED_BY_SERVER|SSL_NOT_ALLOWED_BY_SERVER|"
                      r"SSL_CERT_NOT_ON_SERVER|INCONSISTENT_FLAGS|HYBRID_REQUIRED_BY_SERVER)")

# --- errors while connecting -------------------------------------------------------
# Ordered: when several names appear, the first one listed here wins, so the specific cause
# beats the generic transport/cancel noise that usually follows it.
_CONNECT: dict[str, tuple[str, str, str]] = {
    "LOGON_FAILURE": (
        "Logon failed", "The server rejected the user name or password for {user}.",
        "Check the user name and password. For a domain account, fill in the Domain field "
        "or use user@domain."),
    "WRONG_PASSWORD": (
        "Wrong password", "The password for {user} is incorrect.", "Check the password."),
    "ACCOUNT_LOCKED_OUT": (  # (source)
        "Account locked", "The account {user} is locked out on the server.",
        "Wait for the lockout to expire or ask an administrator to unlock it."),
    "ACCOUNT_DISABLED": (  # (source)
        "Account disabled", "The account {user} is disabled.", "Ask an administrator to enable it."),
    "ACCOUNT_EXPIRED": (  # (source)
        "Account expired", "The account {user} has expired.", "Ask an administrator to extend it."),
    "PASSWORD_EXPIRED": (  # (source)
        "Password expired", "The password for {user} has expired.",
        "Change the password (for example from another Windows machine or on the server) "
        "and try again; this client cannot change it."),
    "PASSWORD_CERTAINLY_EXPIRED": (  # (source)
        "Password expired", "The password for {user} has expired.",
        "Change the password and try again."),
    "PASSWORD_MUST_CHANGE": (  # (source)
        "Password change required", "The password for {user} must be changed before logging on.",
        "Change it on another machine or ask an administrator; this client cannot change it."),
    "ACCOUNT_RESTRICTION": (  # (source)
        "Account restricted", "A restriction on {user} prevents this logon (for example "
        "logon hours or allowed workstations).", "Ask an administrator."),
    "LOGON_TYPE_NOT_GRANTED": (  # (source)
        "Not allowed to log on", "{user} is not allowed to log on through Remote Desktop.",
        "The account must be a member of the 'Remote Desktop Users' group on the server."),
    "INSUFFICIENT_PRIVILEGES": (  # (source)
        "Not permitted", "{user} does not have permission to connect to this server.",
        "The account must be a member of the 'Remote Desktop Users' group on the server."),
    "ACCESS_DENIED": (  # (source)
        "Access denied", "The server denied access for {user}.", "Ask an administrator."),
    "CLIENT_REVOKED": (  # (source)
        "Client revoked", "The server refuses this client or its credentials.", "Ask an administrator."),
    "KDC_UNREACHABLE": (  # (source)
        "Domain controller unreachable",
        "The domain controller for Kerberos authentication could not be reached.",
        "Check the VPN/network connection to the domain, or use the host's IP address."),
    "NO_OR_MISSING_CREDENTIALS": (
        "Credentials missing", "A user name and password are needed to connect to {target}.",
        "Enter them in the main window and connect again."),
    "SECURITY_NEGO_CONNECT_FAILED": (
        "Security negotiation failed",
        "The server and this client could not agree on a security protocol.", ""),  # detail below
    "TLS_CONNECT_FAILED": (
        "Secure connection failed", "The TLS handshake with {target} failed.",
        "The server may use an unsupported TLS version, or its certificate was not accepted."),
    "DNS_NAME_NOT_FOUND": (
        "Server not found", "The name in the Computer field cannot be resolved.",
        "Check the spelling of the name, or use the IP address."),
    "DNS_ERROR": (
        "Name lookup failed", "The name of the server could not be looked up.",
        "Check the network connection and the name."),
    "CONNECT_FAILED": (
        "No answer from the server", "{target} did not answer (the connection attempt timed out).",
        "Check the address, that the machine is switched on and reachable (VPN?), and that no "
        "firewall is dropping the traffic."),
    "CONNECT_TRANSPORT_FAILED": (
        "Connection closed", "The server closed or refused the connection to {target}.", ""),  # detail below
    "MCS_CONNECT_INITIAL_ERROR": (
        "Connection rejected", "The server rejected the remote desktop session setup.",
        "The server may be overloaded, or it limits the number of sessions."),
    "AUTHENTICATION_FAILED": (
        "Authentication failed", "Authentication with {target} failed.", "Check the credentials."),
    "PRE_CONNECT_FAILED": (
        "Could not start the connection", "FreeRDP rejected the connection settings before connecting.",
        "Check the options, especially 'Extra arguments' on the Advanced tab."),
    "POST_CONNECT_FAILED": (
        "Connection failed", "The connection to {target} was made but the session could not be set up.", ""),
    "CONNECT_UNDEFINED": ("Connection failed", "The connection to {target} failed for an unknown reason.", ""),
}

_NEGO_DETAIL = {
    "HYBRID_REQUIRED_BY_SERVER": (
        "The server requires Network Level Authentication (NLA).",
        "Set Security to 'Negotiate' or 'NLA' on the Advanced tab."),
    "SSL_REQUIRED_BY_SERVER": (
        "The server requires TLS.", "Set Security to 'Negotiate' or 'TLS' on the Advanced tab."),
    "SSL_NOT_ALLOWED_BY_SERVER": (
        "The server does not allow TLS.", "Set Security to 'Negotiate' or 'RDP' on the Advanced tab."),
    "SSL_CERT_NOT_ON_SERVER": (
        "The server has no TLS certificate.", "Ask an administrator to set one up, or use Security 'RDP'."),
    "INCONSISTENT_FLAGS": (
        "The security settings are inconsistent.", "Set Security to 'Negotiate' on the Advanced tab."),
}

_SEC_LABEL = {"rdp": "RDP", "tls": "TLS", "nla": "NLA", "ext": "Extended NLA"}

# --- ended sessions: why the *server* closed a session that was up -----------------
_SESSION: dict[str, tuple[str, str]] = {
    "RPC_INITIATED_DISCONNECT": (
        "Disconnected by the server",
        "An administrator or another session on the server disconnected you."),
    "RPC_INITIATED_LOGOFF": ("Logged off", "You were logged off by an administrator on the server."),
    "IDLE_TIMEOUT": ("Session timed out", "The server disconnected you because the session was idle for too long."),
    "LOGON_TIMEOUT": ("Logon timed out", "The server disconnected you because logging on took too long."),
    "DISCONNECTED_BY_OTHER_CONNECTION": (
        "Session taken over", "Another connection to this server took over your session."),
    "OUT_OF_MEMORY": ("Server out of memory", "The server ran out of memory and ended the session."),
    "SERVER_DENIED_CONNECTION": ("Connection denied", "The server denied the connection."),
    "SERVER_INSUFFICIENT_PRIVILEGES": (
        "Not permitted", "You do not have permission to connect to this session."),
    "SERVER_FRESH_CREDENTIALS_REQUIRED": (
        "New credentials required", "The server requires you to enter your credentials again."),
}
_SESSION_SILENT = {"RPC_INITIATED_DISCONNECT_BY_USER", "LOGOFF_BY_USER", "NONE"}  # user's own doing

# exit code -> name, for clients/versions that don't log a name (X11/SDL clients; Wayland always 255)
_EXIT_CONNECT = {
    133: "SECURITY_NEGO_CONNECT_FAILED", 134: "LOGON_FAILURE", 135: "ACCOUNT_LOCKED_OUT",
    136: "PRE_CONNECT_FAILED", 137: "CONNECT_UNDEFINED", 138: "POST_CONNECT_FAILED",
    139: "DNS_ERROR", 140: "DNS_NAME_NOT_FOUND", 141: "CONNECT_FAILED",
    142: "MCS_CONNECT_INITIAL_ERROR", 143: "TLS_CONNECT_FAILED", 144: "INSUFFICIENT_PRIVILEGES",
    146: "SECURITY_NEGO_CONNECT_FAILED", 147: "CONNECT_TRANSPORT_FAILED", 148: "PASSWORD_EXPIRED",
    149: "PASSWORD_MUST_CHANGE", 150: "KDC_UNREACHABLE", 151: "ACCOUNT_DISABLED",
    152: "PASSWORD_CERTAINLY_EXPIRED", 153: "CLIENT_REVOKED", 154: "WRONG_PASSWORD",
    155: "ACCESS_DENIED", 156: "ACCOUNT_RESTRICTION", 157: "ACCOUNT_EXPIRED",
    158: "LOGON_TYPE_NOT_GRANTED", 159: "NO_OR_MISSING_CREDENTIALS", 132: "AUTHENTICATION_FAILED",
}
_EXIT_SESSION = {1: "RPC_INITIATED_DISCONNECT", 2: "RPC_INITIATED_LOGOFF", 3: "IDLE_TIMEOUT",
                 4: "LOGON_TIMEOUT", 5: "DISCONNECTED_BY_OTHER_CONNECTION", 7: "SERVER_DENIED_CONNECTION",
                 9: "SERVER_INSUFFICIENT_PRIVILEGES", 10: "SERVER_FRESH_CREDENTIALS_REQUIRED",
                 11: "RPC_INITIATED_DISCONNECT_BY_USER"}


def error_names(text: str) -> list[str]:
    """ERRCONNECT_*/ERRINFO_* names in the output, in order of first appearance."""
    return list(dict.fromkeys(_NAME_RE.findall(text)))


def _connect_diagnosis(name: str, output: str, at: Attempt) -> Diagnosis:
    title, message, hint = _CONNECT[name]
    ctx = dict(user=at.username or "this user", target=at.target)
    if name == "SECURITY_NEGO_CONNECT_FAILED":
        m = _NEGO_RE.search(output)
        if m:
            message, hint = _NEGO_DETAIL[m.group(1)]
        else:
            hint = "Set Security to 'Negotiate' on the Advanced tab."
    elif name == "CONNECT_TRANSPORT_FAILED":
        if at.security:
            hint = (f"Security is fixed to {_SEC_LABEL.get(at.security, at.security)}. A server "
                    "that requires a different mode (usually NLA) drops the connection like "
                    "this. Try Security 'Negotiate' on the Advanced tab.")
        else:
            hint = ("Check that Remote Desktop is enabled on the server, that the port is "
                    "right and that no firewall is closing the connection.")
    elif name == "TLS_CONNECT_FAILED" and at.cert_mode == "saved":
        message = "The server certificate is not in this connection's trusted list."
        hint = ("Set 'Server certificate' on the Advanced tab to 'Ask me at connect time' "
                "to review and trust it.")
    return Diagnosis(title, message.format(**ctx), hint, code="ERRCONNECT_" + name)


def _session_diagnosis(name: str) -> Diagnosis:
    if name in _SESSION_SILENT:
        return Diagnosis("Session ended", "", code="ERRINFO_" + name, silent=True)
    title, message = _SESSION.get(name, ("Session ended", f"The server ended the session ({name})."))
    return Diagnosis(title, message, code="ERRINFO_" + name, informative=True)


def diagnose(output: str, exit_code: int, at: Attempt, cancelled: bool = False) -> Diagnosis:
    """Explain how a FreeRDP run ended. `cancelled` = we stopped it ourselves."""
    if cancelled:
        return Diagnosis("Cancelled", "", silent=True)
    names = error_names(output)
    connect = {n.removeprefix("ERRCONNECT_") for n in names if n.startswith("ERRCONNECT_")}
    session = [n.removeprefix("ERRINFO_") for n in names if n.startswith("ERRINFO_")]

    for key in _CONNECT:  # most specific first
        if key in connect:
            return _connect_diagnosis(key, output, at)
    if session:
        return _session_diagnosis(session[0])
    # FreeRDP 3 reports a missing password as "cancelled" after failing to prompt for it.
    if "CONNECT_CANCELLED" in connect and re.search(
            r"Domain:|Password:|get_line returned|GetLine returned", output):
        return _connect_diagnosis("NO_OR_MISSING_CREDENTIALS", output, at)
    if exit_code in _EXIT_CONNECT:
        return _connect_diagnosis(_EXIT_CONNECT[exit_code], output, at)
    if exit_code in _EXIT_SESSION:
        return _session_diagnosis(_EXIT_SESSION[exit_code])
    if exit_code == 0:
        return Diagnosis("Session ended", "", silent=True)
    return Diagnosis(
        "Connection failed",
        f"FreeRDP ended unexpectedly (exit code {exit_code}).",
        "Turn on 'Show connection log' in the main window to see FreeRDP's own messages.")


def timeout_diagnosis(at: Attempt) -> Diagnosis:
    return Diagnosis(
        "No response",
        f"{at.target} did not complete the connection within {at.timeout_s} seconds.",
        "The server may be unreachable, a firewall may be dropping the traffic, or the address "
        "may not be a Remote Desktop server at all. You can change the time limit on the "
        "Advanced tab.",
        code="TIMEOUT")
