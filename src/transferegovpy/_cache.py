"""Response cache.

The APIs send no ``ETag``, ``Cache-Control`` or ``Last-Modified`` header, so
nothing that keys off those would store anything. This is a small cache of its
own, keyed on the request URL.

It writes to the session's temporary directory by default, so nothing is left
on the user's filesystem without being asked for. Call
:func:`~transferegovpy.cache_dir` with a path, or set the
``TRANSFEREGOVPY_CACHE_DIR`` environment variable, to keep responses between
sessions.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import tempfile
import time

_DEFAULT_TTL = 3600.0

_state: dict = {"dir": None, "enabled": True, "ttl": _DEFAULT_TTL}


def default_dir() -> pathlib.Path:
    return pathlib.Path(tempfile.gettempdir()) / "transferegovpy-cache"


def cache_dir(path: str | os.PathLike | None = None) -> pathlib.Path:
    """Where cached responses are stored.

    Called with no argument, reports the directory in use. Called with a path,
    switches to it for the rest of the session and creates it.

    By default responses are cached in the session's temporary directory, so
    they are discarded when the process exits. To keep them between sessions,
    pass a persistent path or set ``TRANSFEREGOVPY_CACHE_DIR``.
    """
    if path is not None:
        resolved = pathlib.Path(path).expanduser()
        resolved.mkdir(parents=True, exist_ok=True)
        _state["dir"] = resolved
        return resolved

    if _state["dir"] is not None:
        return _state["dir"]

    from_env = os.environ.get("TRANSFEREGOVPY_CACHE_DIR", "").strip()
    return pathlib.Path(from_env).expanduser() if from_env else default_dir()


def set_enabled(enabled: bool) -> None:
    """Turn the cache on or off for the session."""
    _state["enabled"] = bool(enabled)


def enabled() -> bool:
    return bool(_state["enabled"])


def set_ttl(seconds: float) -> None:
    """How long a cached response stays fresh. The data is refreshed daily."""
    if seconds < 0:
        raise ValueError("ttl must not be negative.")
    _state["ttl"] = float(seconds)


def ttl() -> float:
    return float(_state["ttl"])


def cache_clear() -> int:
    """Delete cached responses. Returns how many files were removed."""
    directory = cache_dir()
    if not directory.exists():
        return 0

    removed = 0
    for entry in directory.glob("*.json"):
        try:
            entry.unlink()
            removed += 1
        except OSError:
            pass

    return removed


def _key(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]


def read(url: str):
    """Return a cached payload, or ``None`` on a miss."""
    path = cache_dir() / f"{_key(url)}.json"

    try:
        entry = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # A truncated or foreign file is a miss, not a failure: the request
        # will simply be made again.
        return None

    created = entry.get("created")
    if not isinstance(created, (int, float)):
        return None

    age = time.time() - created
    if age < 0 or age > ttl():
        return None

    return entry.get("value")


def write(url: str, value) -> bool:
    directory = cache_dir()

    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False

    path = directory / f"{_key(url)}.json"
    # Write to a temporary name and replace, so a crash mid-write cannot leave
    # a half-written file that a later session would read as a hit.
    temporary = path.with_suffix(f".{os.getpid()}.tmp")

    try:
        temporary.write_text(
            json.dumps({"created": time.time(), "value": value}), encoding="utf-8"
        )
        os.replace(temporary, path)
        return True
    except OSError:
        try:
            temporary.unlink()
        except OSError:
            pass
        return False
