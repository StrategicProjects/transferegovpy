"""The query verbs: :func:`get`, :func:`count`, :func:`updated_at` and the
module shortcuts."""

from __future__ import annotations

import datetime as _dt
import math
import warnings

import pandas as pd

from . import _client, _params, _parse, _schema
from ._errors import IncompleteResultWarning, ResponseError

__all__ = [
    "get",
    "count",
    "updated_at",
    "metadata",
    "especiais",
    "fundo_a_fundo",
    "parcerias",
    "MAX_PAGE",
]

#: Rows per request the services cap at. Asking for more is a 422.
MAX_PAGE = _schema.max_page()

_METADATA_ATTR = "transferegovpy"


def get(
    module: str,
    table: str,
    *,
    limit: float | int = 1000,
    offset: int = 0,
    page_size: int = MAX_PAGE,
    use_cache: bool | None = None,
    base_url: str | None = None,
    **filters,
) -> pd.DataFrame:
    """Retrieve rows from a TransfereGov table.

    Filters
    -------
    Name each filter after one of the table's query parameters and give it a
    single value. Parameters are combined with AND::

        tg.get("parcerias", "proposta", situacao_proposta="Aprovada")
        tg.get("parcerias", "proposta", sg_uf_recebedor="PE", ano_proposta=2025)

    The services compare for equality and nothing else: there is no
    greater-than, no pattern match and no "is one of". A parameter takes one
    value, so query each value and concatenate the results when you need
    several.

    Parameter names, and the permitted values of the enumerated ones, are in
    Portuguese because they belong to the API. Use
    :func:`~transferegovpy.params` to see them. A name the packaged schema does
    not know is an error rather than a request: these services ignore a
    parameter they do not recognise and answer with the whole table, so an
    unchecked typo would return plausible, wrong data.

    Pagination
    ----------
    The services return at most 200 rows per request, so ``limit`` above that
    is met by fetching successive pages. ``limit`` counts rows, not pages; use
    ``math.inf`` for every matching row. Several tables hold hundreds of
    thousands of rows, so check the size with :func:`count` first.

    Row order is the server's and cannot be set: these APIs publish no ordering
    parameter. It was checked to be stable across page sizes, across repeated
    calls and at depth, which is what makes multi-page collection safe. The
    number of rows collected is checked against the total the API reports, and
    a mismatch is reported as a warning.

    Parameters
    ----------
    module:
        ``"especiais"``, ``"fundoafundo"`` or ``"parcerias"``. Aliases such as
        ``"fundo_a_fundo"`` are accepted.
    table:
        A table name from :func:`~transferegovpy.tables`.
    limit:
        Maximum number of rows to return. ``math.inf`` for every matching row.
    offset:
        Rows to skip before the first one returned.
    page_size:
        Rows per request, between 1 and 200.
    use_cache:
        Serve the request from the response cache. ``None`` follows
        :func:`~transferegovpy.cache_enabled`.
    base_url:
        Override the API base URL.

    Returns
    -------
    pandas.DataFrame
        :func:`metadata` reports the totals the API gave and how many pages
        were fetched. A column the API sends as an array of objects comes back
        holding lists; ``fields(nested=)`` describes what is inside.
    """
    module = _schema.match_module(module)
    table = _schema.match_table(module, table)

    query = _params.encode(module, table, filters)

    limit = _check_count(limit, "limit", allow_infinite=True)
    offset = _check_count(offset, "offset", minimum=0)
    page_size = _check_count(page_size, "page_size", maximum=MAX_PAGE)

    collected = _collect(
        module,
        table,
        query,
        limit=limit,
        offset=offset,
        page_size=page_size,
        use_cache=use_cache,
        base_url=base_url,
    )

    frame = _parse.to_frame(collected["rows"], module, table)
    frame.attrs[_METADATA_ATTR] = {
        "module": module,
        "table": table,
        "total_rows": collected["total"],
        "rows_returned": len(frame),
        "pages": collected["pages"],
        "offset": offset,
        "page_size": page_size,
        "filters": dict(query),
        "cached": collected["cached"],
        "retrieved_at": _dt.datetime.now(_dt.timezone.utc),
    }
    return frame


def count(
    module: str,
    table: str,
    *,
    use_cache: bool | None = None,
    base_url: str | None = None,
    **filters,
) -> int:
    """Count the rows a query matches without retrieving them.

    Worth doing before a large :func:`get`: the biggest table in these APIs
    holds over a million rows, which at 200 rows a request is more than five
    thousand requests.
    """
    module = _schema.match_module(module)
    table = _schema.match_table(module, table)

    query = _params.encode(module, table, filters)

    # One row is the smallest page the service accepts, and the envelope
    # reports the full total whatever the page size.
    page = _client.fetch(
        _path(module, table),
        [*query, ("pagina", "1"), ("tamanho_da_pagina", "1")],
        use_cache=use_cache,
        url=base_url or _client.base_url(module),
    )
    return int(page["total"])


def updated_at(module: str, base_url: str | None = None) -> _dt.datetime:
    """When a module's data was last refreshed.

    Each module publishes the timestamp of its last load. It is the only
    freshness signal these APIs give: they send no ``ETag``, ``Cache-Control``
    or ``Last-Modified`` header.
    """
    module = _schema.match_module(module)

    body = _client.fetch_object(
        f"{module}/{_schema.timestamp_path(module)}",
        url=base_url or _client.base_url(module),
    )

    value = body.get("data_ultima_atualizacao")
    if not isinstance(value, str):
        raise ResponseError(
            "The TransfereGov API reported no update timestamp; its response "
            "carried no data_ultima_atualizacao."
        )

    return pd.to_datetime(value).to_pydatetime()


def metadata(frame: pd.DataFrame) -> dict | None:
    """What a :func:`get` retrieved: totals, pages, filters and timing."""
    if not isinstance(frame, pd.DataFrame):
        return None
    return frame.attrs.get(_METADATA_ATTR)


# Module shortcuts ------------------------------------------------------------


def especiais(table: str, **kwargs) -> pd.DataFrame:
    """:func:`get` with the module fixed to ``"especiais"``."""
    return get("especiais", table, **kwargs)


def fundo_a_fundo(table: str, **kwargs) -> pd.DataFrame:
    """:func:`get` with the module fixed to ``"fundoafundo"``."""
    return get("fundoafundo", table, **kwargs)


def parcerias(table: str, **kwargs) -> pd.DataFrame:
    """:func:`get` with the module fixed to ``"parcerias"``."""
    return get("parcerias", table, **kwargs)


# Collection ------------------------------------------------------------------


def _path(module: str, table: str) -> str:
    return f"{module}/{_schema.table_path(module, table)}"


def _collect(
    module: str,
    table: str,
    query: list,
    *,
    limit: float,
    offset: int,
    page_size: int,
    use_cache: bool | None,
    base_url: str | None,
) -> dict:
    """Fetch pages until ``limit`` rows are in hand.

    Pagination is by page number, so an offset that is not a whole number of
    pages is met by fetching the page it falls in and dropping the rows before
    it. That keeps ``offset`` meaning "rows to skip" whatever ``page_size`` is.
    """
    path = _path(module, table)
    url = base_url or _client.base_url(module)

    first_page = offset // page_size + 1
    drop = offset % page_size

    first = _client.fetch(
        path,
        [*query, *_page(first_page, page_size)],
        use_cache=use_cache,
        url=url,
    )

    total = first["total"]
    cached = first["cached"]
    pages = 1

    rows = first["rows"][drop:] if drop else list(first["rows"])
    wanted = _rows_wanted(limit, total, offset)

    if len(rows) >= wanted or not first["rows"]:
        return _collected(_trim(rows, wanted), total, pages, cached, wanted)

    page_number = first_page
    while len(rows) < wanted:
        page_number += 1

        page = _client.fetch(
            path,
            [*query, *_page(page_number, page_size)],
            use_cache=use_cache,
            url=url,
        )

        cached = cached and page["cached"]
        pages += 1

        # The server stops sending rows before the reported total is reached
        # only if the table shrank mid-collection. Breaking keeps this finite.
        if not page["rows"]:
            break

        rows.extend(page["rows"])

    return _collected(_trim(rows, wanted), total, pages, cached, wanted)


def _page(number: int, size: int) -> list:
    return [("pagina", str(number)), ("tamanho_da_pagina", str(size))]


def _trim(rows: list, wanted: float) -> list:
    return rows[: int(wanted)] if math.isfinite(wanted) else rows


def _rows_wanted(limit: float, total: float | None, offset: int) -> float:
    """The smaller of what was asked for and what is left after the offset."""
    if total is None:
        return limit
    return min(limit, max(0.0, total - offset))


def _collected(rows: list, total, pages: int, cached: bool, wanted: float) -> dict:
    if math.isfinite(wanted) and len(rows) != wanted:
        warnings.warn(
            f"Collected {len(rows)} row(s) where the API reported {wanted:.0f}. "
            "The table may have changed while it was being read; check "
            "metadata() on the result.",
            IncompleteResultWarning,
            stacklevel=4,
        )

    return {"rows": rows, "total": total, "pages": pages, "cached": cached}


def _check_count(
    value,
    name: str,
    *,
    minimum: int = 1,
    maximum: float = math.inf,
    allow_infinite: bool = False,
):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a whole number, not {type(value).__name__}.")

    if allow_infinite and value == math.inf:
        return value

    if isinstance(value, float) and not value.is_integer():
        raise ValueError(f"{name} must be a whole number.")

    value = int(value)
    if value < minimum or value > maximum:
        bound = (
            f"between {minimum} and {maximum:.0f}"
            if math.isfinite(maximum)
            else f"of {minimum} or more"
        )
        extra = ", or math.inf" if allow_infinite else ""
        raise ValueError(f"{name} must be a whole number {bound}{extra}.")

    return value
