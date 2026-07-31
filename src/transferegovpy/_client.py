"""HTTP transport: throttling, retries, error reporting and pagination state."""

from __future__ import annotations

import random
import re
import threading
import time
from collections.abc import Sequence

import requests

from . import _cache, _schema
from ._errors import HTTPError, ResponseError, URLTooLongError

__version_header__ = "transferegovpy"

# A filter built with `in_()` over a few thousand identifiers produces a URL the
# service cannot accept, and the failure it produces is not readable: curl
# reports "Error in the HTTP2 framing layer", which says nothing about the
# query. Failing before the request names the cause instead.
MAX_URL = 7000

# Only these are worth retrying. A 400 is PostgREST rejecting the query itself
# and will fail identically every time.
TRANSIENT = frozenset({429, 500, 502, 503, 504})

_config = {
    "base_url": None,
    "timeout": 60.0,
    "max_tries": 4,
    "requests_per_minute": 60.0,
    "validate": True,
}

_throttle_lock = threading.Lock()
_last_request = [0.0]

_session_lock = threading.Lock()
_session: requests.Session | None = None


def configure(**options) -> dict:
    """Set connection options for the session, or read them back."""
    unknown = set(options) - set(_config)
    if unknown:
        raise ValueError(f"Unknown option(s): {', '.join(sorted(unknown))}.")
    _config.update({k: v for k, v in options.items() if v is not None})
    return dict(_config)


def base_url() -> str:
    return _config["base_url"] or _schema.default_base_url()


def validate() -> bool:
    return bool(_config["validate"])


def _user_agent() -> str:
    from . import __version__

    return f"transferegovpy/{__version__} (https://github.com/StrategicProjects/transferegovpy)"


def session() -> requests.Session:
    global _session
    with _session_lock:
        if _session is None:
            _session = requests.Session()
            _session.headers.update(
                {"Accept": "application/json", "User-Agent": _user_agent()}
            )
        return _session


def _wait_turn() -> None:
    """Keep the package a considerate client of a public service."""
    rate = float(_config["requests_per_minute"])
    if rate <= 0:
        return

    interval = 60.0 / rate
    with _throttle_lock:
        elapsed = time.monotonic() - _last_request[0]
        if elapsed < interval:
            time.sleep(interval - elapsed)
        _last_request[0] = time.monotonic()


def build_url(module: str, table: str, url: str) -> str:
    return f"{url.rstrip('/')}/{module}/{table}"


def fetch(
    module: str,
    table: str,
    params: Sequence[tuple[str, str]],
    count: bool = False,
    use_cache: bool | None = None,
    url: str | None = None,
) -> dict:
    """Perform one request and return ``{"rows", "total", "cached"}``."""
    target = build_url(module, table, url or base_url())
    prepared = requests.Request("GET", target, params=list(params)).prepare()

    if len(prepared.url) > MAX_URL:
        raise URLTooLongError(
            f"The request URL is {len(prepared.url)} bytes, over the {MAX_URL} the service "
            "accepts. A filter built with in_() over a long sequence is the usual cause. "
            "Split the values into batches of a few hundred and concatenate the results."
        )

    wants_cache = _cache.enabled() if use_cache is None else bool(use_cache)

    if wants_cache:
        hit = _cache.read(prepared.url)
        if hit is not None:
            return {"rows": hit["rows"], "total": hit["total"], "cached": True}

    payload = _perform(prepared.url, count=count)

    if wants_cache:
        _cache.write(prepared.url, payload)

    return {"rows": payload["rows"], "total": payload["total"], "cached": False}


def _perform(url: str, count: bool) -> dict:
    headers = {"Prefer": "count=exact"} if count else {}
    last_error: Exception | None = None

    for attempt in range(1, int(_config["max_tries"]) + 1):
        _wait_turn()

        try:
            response = session().get(url, headers=headers, timeout=_config["timeout"])
        except requests.RequestException as error:  # connection, DNS, timeout
            last_error = error
            if attempt == _config["max_tries"]:
                raise ResponseError(
                    f"The request to the TransfereGov API failed: {error}"
                ) from error
            _backoff(attempt)
            continue

        if response.status_code in TRANSIENT and attempt < _config["max_tries"]:
            _backoff(attempt, response)
            continue

        _raise_for_status(response)
        return _payload(response)

    raise ResponseError(f"The request to the TransfereGov API failed: {last_error}")


def _backoff(attempt: int, response: requests.Response | None = None) -> None:
    if response is not None:
        after = response.headers.get("Retry-After")
        if after and after.isdigit():
            time.sleep(min(60, int(after)))
            return

    time.sleep(min(60.0, 2.0**attempt) * random.uniform(0.5, 1.5))


def _raise_for_status(response: requests.Response) -> None:
    if response.status_code < 400:
        return

    # PostgREST reports errors as a JSON object carrying the Postgres SQLSTATE
    # and message, which name the offending column. Surfacing them turns an
    # opaque 400 into something the caller can act on.
    detail: dict = {}
    try:
        body = response.json()
        if isinstance(body, dict):
            detail = {
                k: v for k, v in body.items() if k in ("message", "details", "hint", "code") and v
            }
    except ValueError:
        pass

    message = f"The TransfereGov API returned HTTP {response.status_code} ({response.reason})."
    for key in ("message", "details", "hint"):
        if detail.get(key):
            message += f" {detail[key]}"
    if response.status_code == 400 and not detail.get("hint"):
        message += " Check the column names with fields()."

    raise HTTPError(message, status=response.status_code, detail=detail)


def _payload(response: requests.Response) -> dict:
    try:
        rows = response.json()
    except ValueError as error:
        raise ResponseError(
            "The TransfereGov API returned a body that is not valid JSON."
        ) from error

    if not isinstance(rows, list):
        raise ResponseError(
            "The TransfereGov API returned an unexpected payload; "
            "a table query must answer with a JSON array of rows."
        )

    return {"rows": rows, "total": parse_content_range(response.headers.get("Content-Range"))}


def parse_content_range(header: str | None) -> float | None:
    """The total from ``Content-Range``.

    The header carries the pagination state: ``0-99/6176`` with an exact count,
    ``0-99/*`` without one, and ``*/0`` for an empty result. ``None`` means the
    service did not say.
    """
    if not header:
        return None

    match = re.match(r"^(?:items\s+)?(\*|\d+-\d+)/(\*|\d+)$", header.strip())
    if not match:
        return None

    total = match.group(2)
    return None if total == "*" else float(total)
