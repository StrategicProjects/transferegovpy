"""HTTP transport: throttling, retries, error reporting and pagination state.

The three modules are FastAPI services. A table query is a GET on the endpoint,
filters are typed query parameters, and the answer is an envelope carrying the
rows under ``data`` alongside the pagination state.
"""

from __future__ import annotations

import random
import threading
import time
from collections.abc import Sequence

import requests

from . import _cache, _schema
from ._errors import HTTPError, ResponseError, URLTooLongError

__version_header__ = "transferegovpy"

# A very long filter value produces a URL the service cannot accept, and the
# failure it produces is not readable: curl reports "Error in the HTTP2 framing
# layer", which says nothing about the query. Failing before the request names
# the cause instead.
MAX_URL = 7000

# Only these are worth retrying. A 422 is the service rejecting the query
# itself and will fail identically every time.
TRANSIENT = frozenset({429, 500, 502, 503, 504})

# The envelope every table endpoint answers with. ``total_items`` is what
# bounds multi-page collection, and its absence has to be an error rather than
# a silent switch to unbounded paging.
ENVELOPE = ("data", "total_pages", "total_items", "page_number", "page_size")

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


def base_url(module: str | None = None) -> str:
    if _config["base_url"]:
        return _config["base_url"]
    if module is None:
        return _schema.default_base_url()
    return _schema.module_base_url(module)


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


def build_url(path: str, url: str) -> str:
    return f"{url.rstrip('/')}/{path.lstrip('/')}"


def _prepare(path: str, params: Sequence[tuple[str, str]], url: str) -> str:
    prepared = requests.Request("GET", build_url(path, url), params=list(params)).prepare()

    if len(prepared.url) > MAX_URL:
        raise URLTooLongError(
            f"The request URL is {len(prepared.url)} bytes, over the {MAX_URL} the service "
            "accepts. A very long filter value is the usual cause."
        )

    return prepared.url


def fetch(
    path: str,
    params: Sequence[tuple[str, str]],
    use_cache: bool | None = None,
    url: str | None = None,
) -> dict:
    """One request, returning ``{"rows", "total", "page", "page_size", "cached"}``."""
    target = _prepare(path, params, url or base_url())
    wants_cache = _cache.enabled() if use_cache is None else bool(use_cache)

    if wants_cache:
        hit = _cache.read(target)
        if hit is not None:
            return {**hit, "cached": True}

    payload = _envelope(_perform(target))

    if wants_cache:
        _cache.write(target, payload)

    return {**payload, "cached": False}


def fetch_object(path: str, url: str | None = None) -> dict:
    """One request to an endpoint that answers with a bare object.

    ``/data-atualizacao`` is the only such endpoint; it is not paginated.
    """
    body = _perform(_prepare(path, (), url or base_url()))
    if not isinstance(body, dict):
        raise ResponseError("The TransfereGov API returned an unexpected payload.")
    return body


def _perform(url: str):
    last_error: Exception | None = None

    for attempt in range(1, int(_config["max_tries"]) + 1):
        _wait_turn()

        try:
            response = session().get(url, timeout=_config["timeout"])
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
        return _body(response)

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

    detail = _details(response)
    message = f"The TransfereGov API returned HTTP {response.status_code} ({response.reason})."
    for line in detail:
        message += f" {line}"
    if response.status_code == 422:
        message += " Check the parameter names and values with params()."

    raise HTTPError(message, status=response.status_code, detail=detail)


def _details(response: requests.Response) -> list[str]:
    """FastAPI reports a rejected query under ``detail``.

    That is a list of validation objects for a 422, each naming the offending
    parameter under ``loc``, and a bare string otherwise.
    """
    try:
        body = response.json()
    except ValueError:
        return []

    if not isinstance(body, dict) or "detail" not in body:
        return []

    detail = body["detail"]
    if isinstance(detail, str):
        return [detail] if detail else []
    if not isinstance(detail, list):
        return []

    lines = []
    for item in detail:
        if not isinstance(item, dict):
            continue
        message = item.get("msg")
        if not isinstance(message, str):
            continue
        where = [str(p) for p in item.get("loc", []) if p != "query"]
        lines.append(f"{'.'.join(where)}: {message}" if where else message)
    return lines


def _body(response: requests.Response):
    try:
        return response.json()
    except ValueError as error:
        raise ResponseError(
            "The TransfereGov API returned a body that is not valid JSON."
        ) from error


def _envelope(body) -> dict:
    if not isinstance(body, dict):
        raise ResponseError(
            "The TransfereGov API returned an unexpected payload; a table query "
            "must answer with a paginated envelope."
        )

    missing = [field for field in ENVELOPE if field not in body]
    if missing:
        raise ResponseError(
            "The TransfereGov API returned an unexpected payload; its response "
            f"carried no {', '.join(missing)}. A table query must answer with a "
            "paginated envelope."
        )

    if not isinstance(body["data"], list):
        raise ResponseError(
            "The TransfereGov API returned an unexpected payload; its data field "
            "must be a JSON array of rows."
        )

    return {
        "rows": body["data"],
        "total": _number(body["total_items"], "total_items"),
        "page": _number(body["page_number"], "page_number"),
        "page_size": _number(body["page_size"], "page_size"),
    }


def _number(value, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ResponseError(
            f"The TransfereGov API reported no usable {field}; multi-page "
            "collection has nothing to bound itself with."
        )
    return float(value)
