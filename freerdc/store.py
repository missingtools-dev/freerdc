"""Saved connection profiles (JSON files) and optional keyring-backed passwords."""
from __future__ import annotations

import dataclasses
import json
import os
import re
from pathlib import Path

from .model import Drive, Floatbar, Profile

SERVICE = "freerdc"


def config_dir() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    d = base / "freerdc" / "profiles"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _settings_file() -> Path:
    return config_dir().parent / "settings.json"


def _load_settings() -> dict:
    try:
        data = json.loads(_settings_file().read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_settings(data: dict) -> None:
    _settings_file().write_text(json.dumps(data, indent=2))


def get_setting(key: str, default):
    return _load_settings().get(key, default)


def set_setting(key: str, value) -> None:
    data = _load_settings()
    data[key] = value
    try:
        _save_settings(data)
    except OSError:
        pass  # a preference that fails to persist must not break the UI


def client_paths() -> list[str]:
    """FreeRDP binaries the user added with Browse; they are rescanned on every start."""
    return [p for p in _load_settings().get("client_paths", []) if os.path.exists(p)]


def add_client_path(path: str) -> None:
    data = _load_settings()
    paths = data.get("client_paths", [])
    if path not in paths:
        data["client_paths"] = [*paths, path]
        _save_settings(data)


# --- recently used servers (like the Windows client's Computer drop-down) ----------
MAX_RECENT = 20


def server_label(host: str, port: int) -> str:
    """How a server is shown and typed: host, plus :port when it isn't the default."""
    return host if port == 3389 or ":" in host else f"{host}:{port}"


def recent_servers() -> list[dict]:
    """Newest first: [{"host", "port", "username", "remember"}, ...].

    "remember" only says that a password for this server is in the system keyring; the
    password itself is never written to the settings file."""
    out = []
    for e in _load_settings().get("recent_servers", []):
        if isinstance(e, dict) and e.get("host"):
            out.append({"host": str(e["host"]), "port": int(e.get("port", 3389)),
                        "username": str(e.get("username", "")),
                        "remember": bool(e.get("remember", False))})
    return out


def _same_server(e: dict, key: str) -> bool:
    return server_label(e["host"], e["port"]).lower() == key


def record_recent_server(host: str, port: int, username: str) -> None:
    """Remember a server and the user name last used with it (never a password here)."""
    host = host.strip()
    if not host:
        return
    key = server_label(host, port).lower()
    previous = next((e for e in recent_servers() if _same_server(e, key)), None)
    kept = [e for e in recent_servers() if not _same_server(e, key)]
    data = _load_settings()
    data["recent_servers"] = [
        {"host": host, "port": port, "username": username,
         "remember": bool(previous and previous["remember"])},  # a connect doesn't change it
        *kept][:MAX_RECENT]
    try:
        _save_settings(data)
    except OSError:
        pass  # history is a convenience; never block a connection on it


def _set_remember_flag(host: str, port: int, flag: bool) -> None:
    key = server_label(host, port).lower()
    data = _load_settings()
    entries = data.get("recent_servers", [])
    changed = False
    for e in entries:
        if isinstance(e, dict) and e.get("host") and _same_server(
                {"host": str(e["host"]), "port": int(e.get("port", 3389))}, key):
            e["remember"] = flag
            changed = True
    if changed:
        try:
            _save_settings(data)
        except OSError:
            pass


# --- certificates the user chose to trust, per server -------------------------------
# Public data (SHA-256 fingerprints), kept in settings.json so a trust decision survives
# restarts even when the connection was never saved under a name.
def _cert_key(host: str, port: int) -> str:
    return server_label(host.strip(), port).lower()


def trusted_certificates(host: str, port: int) -> list[str]:
    entries = _load_settings().get("trusted_certificates", {})
    found = entries.get(_cert_key(host, port), []) if isinstance(entries, dict) else []
    return [str(f) for f in found]


def trust_certificate(host: str, port: int, fingerprint: str) -> None:
    host = host.strip()
    if not host:
        return
    data = _load_settings()
    entries = data.setdefault("trusted_certificates", {})
    known = entries.setdefault(_cert_key(host, port), [])
    if fingerprint not in known:
        known.append(fingerprint)
        _save_settings(data)


def forget_certificate(host: str, port: int, fingerprint: str) -> None:
    data = _load_settings()
    entries = data.get("trusted_certificates", {})
    key = _cert_key(host, port)
    if isinstance(entries, dict) and fingerprint in entries.get(key, []):
        entries[key].remove(fingerprint)
        if not entries[key]:
            del entries[key]
        _save_settings(data)


def _server_key(host: str, port: int) -> str:
    return "server:" + server_label(host, port).lower()


def remember_server_password(host: str, port: int, password: str) -> None:
    """Keep the password for a server in the system keyring (raises CredentialStoreError)."""
    _set_password(_server_key(host, port), password)
    _set_remember_flag(host, port, True)


def server_password(host: str, port: int) -> str | None:
    """The remembered password for a server, or None (raises CredentialStoreError)."""
    return _get_password(_server_key(host, port), "")


def find_saved_password(host: str, port: int, username: str) -> str | None:
    """A password already saved for this server and user, wherever it was saved: for the
    server itself (after a connect with 'Allow me to save credentials') or under a named
    saved connection for the same host, port and user. The user name must match, so one
    account's password is never offered for another. Raises CredentialStoreError, but only
    if there was a candidate to look up."""
    host = host.strip()
    key = server_label(host, port).lower()
    for e in recent_servers():
        if (e["remember"] and _same_server(e, key)
                and (not username or e["username"].casefold() == username.casefold())):
            password = server_password(e["host"], e["port"])
            if password:
                return password
    if not username:
        return None
    for name in list_profiles():
        try:
            prof = load_profile(name, with_password=False)
        except (OSError, ValueError):
            continue
        if (server_label(prof.host.strip(), prof.port).lower() == key
                and prof.username.casefold() == username.casefold()):
            password = _get_password(_slug(name), prof.username)
            if password:
                return password
    return None


def forget_server_password(host: str, port: int) -> None:
    """Remove a remembered password. Does nothing (and never touches the keyring) if none
    was remembered for this server, so it is safe to call on every connect."""
    key = server_label(host, port).lower()
    if any(_same_server(e, key) and e["remember"] for e in recent_servers()):
        _delete_quietly(_server_key(host, port))
        _set_remember_flag(host, port, False)


def clear_recent_servers() -> None:
    """Forget the whole history, including the passwords remembered for those servers.
    Raises CredentialStoreError if the keyring refused to remove some (the history is
    cleared regardless)."""
    entries = recent_servers()
    data = _load_settings()
    if data.pop("recent_servers", None) is not None:
        _save_settings(data)
    failure = None
    for e in entries:
        if e["remember"]:
            try:
                _delete_quietly(_server_key(e["host"], e["port"]))
            except CredentialStoreError as err:
                failure = err
    if failure:
        raise failure


def _slug(name: str) -> str:
    return re.sub(r"[^\w.@-]+", "_", name).strip("_") or "profile"


def profile_to_dict(p: Profile) -> dict:
    d = dataclasses.asdict(p)
    d.pop("password", None)  # never written to disk
    return d


def profile_from_dict(d: dict) -> Profile:
    d = dict(d)
    if d.pop("cert_ignore", False):  # older profiles
        d.setdefault("cert_mode", "any")
    d["drives"] = [Drive(**x) for x in d.get("drives", [])]
    fb = d.get("floatbar")
    d["floatbar"] = Floatbar(**fb) if fb else None
    known = {f.name for f in dataclasses.fields(Profile)}
    return Profile(**{k: v for k, v in d.items() if k in known})


# --- the user's own defaults for every new connection ------------------------------
# Options only: nothing that identifies a server or an account.
_NOT_A_DEFAULT = ("host", "port", "username", "domain", "password", "trusted_fingerprints")


def load_defaults() -> tuple[Profile, str | None]:
    """The user's preferred options and preferred FreeRDP client path (None = automatic).
    Falls back to the factory settings when nothing was saved."""
    data = _load_settings().get("defaults")
    if not isinstance(data, dict):
        return Profile(), None
    client = data.get("client")
    options = {k: v for k, v in data.items() if k not in _NOT_A_DEFAULT and k != "client"}
    try:
        return profile_from_dict(options), (str(client) if client else None)
    except (TypeError, ValueError):
        return Profile(), None


def save_defaults(p: Profile, client: str | None) -> None:
    data = _load_settings()
    d = {k: v for k, v in profile_to_dict(p).items() if k not in _NOT_A_DEFAULT}
    d["client"] = client
    data["defaults"] = d
    _save_settings(data)


def reset_defaults() -> None:
    data = _load_settings()
    if data.pop("defaults", None) is not None:
        _save_settings(data)


def list_profiles() -> list[str]:
    """Names of the saved connections as the user typed them (the file name is a sanitised
    form of the name, so the real name is kept inside the file)."""
    names = []
    for path in config_dir().glob("*.json"):
        try:
            names.append(str(json.loads(path.read_text()).get("_name") or path.stem))
        except (OSError, ValueError):
            names.append(path.stem)
    return sorted(names, key=str.casefold)


class CredentialStoreError(Exception):
    """The system keyring could not be read or written (missing, locked, access denied)."""


def save_profile(name: str, p: Profile, remember_password: bool) -> None:
    """Write the profile file, then store or remove its password.

    remember_password=False removes any stored password; True with a non-empty password
    stores it; True with an empty password leaves the stored one untouched.

    The file is always written first; if the keyring then fails, CredentialStoreError is
    raised so the caller can tell the user the connection was saved without its password."""
    path = config_dir() / f"{_slug(name)}.json"
    path.write_text(json.dumps({"_name": name, **profile_to_dict(p)}, indent=2))
    key = _slug(name)  # the keyring entry follows the file, so it is found again by any spelling
    if not remember_password:
        _delete_password(key)
        _delete_legacy_password(name, p.username)
    elif p.password:
        _set_password(key, p.password)
        _delete_legacy_password(name, p.username)
    # remember ticked but the password box is empty: keep whatever is already stored


def load_profile(name: str, with_password: bool = True) -> Profile:
    p = profile_from_dict(json.loads((config_dir() / f"{_slug(name)}.json").read_text()))
    if with_password:
        p.password = _get_password(_slug(name), p.username) or ""
    return p


def delete_profile(name: str) -> None:
    path = config_dir() / f"{_slug(name)}.json"
    username = ""
    if path.exists():
        username = profile_from_dict(json.loads(path.read_text())).username
        path.unlink()
    _delete_password(_slug(name))
    _delete_legacy_password(name, username)


# --- keyring (system Secret Service / KWallet via the `keyring` package) ------
# Entries are keyed by connection name only, so changing a connection's user name
# never orphans or loses its password.
def _keyring():
    try:
        import keyring
        import keyring.errors
    except ImportError as e:
        raise CredentialStoreError("the 'keyring' package is not installed") from e
    return keyring


def _fail(action: str, e: Exception) -> CredentialStoreError:
    return CredentialStoreError(f"could not {action} the password in the system keyring: {e}")


def _set_password(name: str, password: str) -> None:
    kr = _keyring()
    try:
        kr.set_password(SERVICE, name, password)
    except Exception as e:
        raise _fail("save", e) from e


def _get_password(name: str, username: str) -> str | None:
    kr = _keyring()
    try:
        value = kr.get_password(SERVICE, name)
        if value is None and username:  # entry written by an older version
            legacy = kr.get_password(SERVICE, _legacy_key(name, username))
            if legacy is not None:
                kr.set_password(SERVICE, name, legacy)  # migrate to the new key
                _delete_legacy_password(name, username)
                value = legacy
        return value
    except Exception as e:
        raise _fail("read", e) from e


def _delete_quietly(key: str) -> None:
    kr = _keyring()
    try:
        kr.delete_password(SERVICE, key)
    except kr.errors.PasswordDeleteError:
        pass  # nothing stored under that key
    except Exception as e:
        raise _fail("remove", e) from e


def _delete_password(name: str) -> None:
    _delete_quietly(name)


def _legacy_key(name: str, username: str) -> str:
    return f"{name}|{username}"


def _delete_legacy_password(name: str, username: str) -> None:
    if username:
        _delete_quietly(_legacy_key(name, username))


def keyring_available() -> bool:
    try:
        import keyring
        from keyring.backends.fail import Keyring as FailKeyring
        return not isinstance(keyring.get_keyring(), FailKeyring)
    except Exception:
        return False
