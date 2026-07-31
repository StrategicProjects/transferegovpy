"""The query verbs: :func:`get`, :func:`count` and the module shortcuts."""

from __future__ import annotations

import datetime as _dt
import math
import warnings
from collections.abc import Sequence
from typing import Any

import pandas as pd

from . import _client, _parse, _schema
from ._errors import IncompleteResultWarning, ResponseError
from .filters import to_params

__all__ = [
    "get",
    "count",
    "ted",
    "fundo_a_fundo",
    "transferencias_especiais",
    "metadata",
]

#: The service returns at most this many rows per request, whatever is asked
#: for, and says nothing about the truncation beyond ``Content-Range``.
MAX_PAGE = 1000


def get(
    module: str,
    table: str,
    *,
    select: Sequence[str] | None = None,
    order: Sequence[str] | str | None = None,
    limit: float = MAX_PAGE,
    offset: int = 0,
    page_size: int = MAX_PAGE,
    params: dict | None = None,
    progress: bool | None = None,
    cache: bool | None = None,
    base_url: str | None = None,
    filters: dict | None = None,
    **kwargs: Any,
) -> pd.DataFrame:
    """Retrieve rows from a TransfereGov table.

    Parameters
    ----------
    module:
        ``"transferenciasespeciais"``, ``"fundoafundo"`` or ``"ted"``. Aliases
        such as ``"fundo_a_fundo"`` are accepted.
    table:
        A table name from :func:`~transferegovpy.tables`.
    select:
        Columns to return. ``None`` returns every column. Selecting fewer
        columns makes large queries markedly faster.
    order:
        Sort order, as column names optionally suffixed with ``.asc`` or
        ``.desc``. ``None`` uses the table's primary key where the API declares
        one, and its identifier columns otherwise.
    limit:
        Maximum number of rows to return. ``math.inf`` for every matching row.
        Counts rows, not requests: anything above 1000 is collected page by
        page.
    offset:
        Rows to skip before the first one returned.
    page_size:
        Rows per request, between 1 and 1000.
    params:
        Extra query parameters passed to the API verbatim, the escape hatch for
        'PostgREST' features this package does not model.
    progress:
        Show a progress bar while collecting pages. ``None`` shows one when
        more than one page is needed and the session is interactive.
    cache:
        Serve the request from the response cache. ``None`` follows
        :func:`~transferegovpy.cache_enabled`.
    base_url:
        The API base URL.
    filters:
        Filters as a mapping, for columns whose names collide with the keyword
        arguments above.
    **kwargs:
        Filters, named after the columns they apply to.

    Returns
    -------
    pandas.DataFrame
        Typed from the API's own schema. :func:`metadata` reports the totals the
        API gave and how many pages were fetched.

    Examples
    --------
    >>> get("ted", "plano_acao", aa_ano_plano_acao=gte(2024), limit=50)  # doctest: +SKIP
    """
    module = _schema.match_module(module)
    table = _schema.match_table(module, table)

    conditions = dict(filters or {})
    conditions.update(kwargs)

    query = to_params(conditions)
    _schema.check_columns(module, table, [c for c, _ in query], "filter", _client.validate())

    _check_count(limit, "limit", allow_inf=True)
    _check_count(offset, "offset", minimum=0)
    _check_count(page_size, "page_size", maximum=MAX_PAGE)
    extra = _check_params(params)

    selected = _prepare_select(module, table, select)
    ordering = _prepare_order(module, table, order)

    if selected:
        query.append(("select", ",".join(selected)))
    query.append(("order", ",".join(ordering)))
    query.extend(extra)

    collected = _collect(
        module, table, query, limit, offset, int(page_size), progress, cache, base_url
    )

    frame = _parse.to_frame(collected["rows"], module, table, columns=_plain_names(select))

    frame.attrs["transferegovpy"] = {
        "module": module,
        "table": table,
        "total_rows": collected["total"],
        "rows_returned": len(frame),
        "pages": collected["pages"],
        "offset": offset,
        "page_size": int(page_size),
        "order": ordering,
        "select": list(selected) if selected else None,
        "cached": collected["cached"],
        "retrieved_at": _dt.datetime.now(_dt.timezone.utc),
    }

    return frame


def count(
    module: str,
    table: str,
    *,
    params: dict | None = None,
    cache: bool | None = None,
    base_url: str | None = None,
    filters: dict | None = None,
    **kwargs: Any,
) -> int:
    """Count the rows a query matches, without retrieving them.

    Worth doing before a large :func:`get`: the biggest table in these APIs
    holds over a million rows, which is more than a thousand requests.
    """
    module = _schema.match_module(module)
    table = _schema.match_table(module, table)

    conditions = dict(filters or {})
    conditions.update(kwargs)

    query = to_params(conditions)
    _schema.check_columns(module, table, [c for c, _ in query], "filter", _client.validate())

    # `select=` with no columns asks PostgREST for rows with no fields, so the
    # count comes back without the body carrying any data.
    query.extend([("select", ""), ("limit", "1")])
    query.extend(_check_params(params))

    page = _client.fetch(module, table, query, count=True, use_cache=cache, url=base_url)

    if page["total"] is None:
        raise ResponseError(
            "The API did not report a row count; its Content-Range header carried no total."
        )

    return int(page["total"])


def ted(table: str, **kwargs: Any) -> pd.DataFrame:
    """Query the decentralized credit module."""
    return get("ted", table, **kwargs)


def fundo_a_fundo(table: str, **kwargs: Any) -> pd.DataFrame:
    """Query the fund-to-fund module."""
    return get("fundoafundo", table, **kwargs)


def transferencias_especiais(table: str, **kwargs: Any) -> pd.DataFrame:
    """Query the special transfers module."""
    return get("transferenciasespeciais", table, **kwargs)


def metadata(frame: pd.DataFrame) -> dict | None:
    """What a query retrieved: the API's totals, the pages fetched, and more.

    ``None`` for a frame this package did not produce.
    """
    if not isinstance(frame, pd.DataFrame):
        return None
    return frame.attrs.get("transferegovpy")


# Collection ------------------------------------------------------------------


def _collect(module, table, query, limit, offset, page_size, progress, cache, base_url) -> dict:
    first_size = int(min(page_size, limit)) if math.isfinite(limit) else page_size

    first = _client.fetch(
        module,
        table,
        query + [("limit", str(first_size)), ("offset", str(int(offset)))],
        count=True,
        use_cache=cache,
        url=base_url,
    )

    rows = list(first["rows"])
    total = first["total"]
    cached = first["cached"]
    pages = 1

    wanted = _rows_wanted(limit, total, offset)

    # A first page that comes back empty while the API reports matching rows
    # means the offset is past the end, not that collection should continue.
    if len(rows) >= wanted or not rows:
        return _finish(rows, total, pages, cached, wanted)

    bar = _progress_start(progress, wanted, len(rows), page_size, module, table)

    while len(rows) < wanted:
        size = int(min(page_size, wanted - len(rows)))
        page = _client.fetch(
            module,
            table,
            query + [("limit", str(size)), ("offset", str(int(offset) + len(rows)))],
            count=False,
            use_cache=cache,
            url=base_url,
        )

        cached = cached and page["cached"]
        pages += 1

        # The server stops sending rows before the reported total is reached
        # only if the table shrank mid-collection. Breaking keeps this finite.
        if not page["rows"]:
            break

        rows.extend(page["rows"])
        _progress_step(bar, len(page["rows"]))

    _progress_done(bar)

    return _finish(rows, total, pages, cached, wanted)


def _finish(rows, total, pages, cached, wanted) -> dict:
    if math.isfinite(wanted) and len(rows) != wanted:
        warnings.warn(
            f"Collected {len(rows)} row(s) where the API reported {int(wanted)}. "
            "The table may have changed while it was being read; check metadata() "
            "on the result.",
            IncompleteResultWarning,
            stacklevel=4,
        )

    return {"rows": rows, "total": total, "pages": pages, "cached": cached}


def _rows_wanted(limit: float, total: float | None, offset: int) -> float:
    """The smaller of what was asked for and what is left after the offset."""
    if total is None:
        return limit
    return min(limit, max(0.0, total - offset))


# Validation ------------------------------------------------------------------


def _check_count(value, name, minimum=1, maximum=None, allow_inf=False) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a whole number.")
    if isinstance(value, float) and math.isinf(value):
        if allow_inf and value > 0:
            return
        raise ValueError(f"{name} must be a whole number, or math.inf where allowed.")
    if isinstance(value, float) and not value.is_integer():
        raise ValueError(f"{name} must be a whole number, not {value}.")
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}, not {value}.")
    if maximum is not None and value > maximum:
        raise ValueError(
            f"{name} must be at most {maximum}, not {value}. The service silently "
            "truncates a larger page, so the shortfall would look like missing data."
        )


def _check_params(params: dict | None) -> list[tuple[str, str]]:
    if not params:
        return []

    if not isinstance(params, dict):
        raise ValueError("params must be a mapping of name to value.")

    reserved = sorted(set(params) & {"limit", "offset"})
    if reserved:
        raise ValueError(
            f"params must not set {', '.join(reserved)}; use the limit and offset "
            "arguments, which pagination depends on."
        )

    return [(str(k), str(v)) for k, v in params.items()]


def _prepare_select(module, table, select) -> list[str] | None:
    if select is None:
        return None
    if isinstance(select, str):
        select = [select]
    columns = list(select)
    if not columns:
        raise ValueError("select must name at least one column.")
    _schema.check_columns(
        module, table, _plain_names(columns) or [], "selected", _client.validate()
    )
    return columns


def _plain_names(select) -> list[str] | None:
    """Only bare entries name a column that can be checked or used to shape an
    empty result; ``alias:column`` and ``column::type`` are PostgREST syntax."""
    if select is None:
        return None
    columns = [select] if isinstance(select, str) else list(select)
    if any(":" in c or "(" in c for c in columns):
        return None
    return columns


def _prepare_order(module, table, order) -> list[str]:
    if order is None:
        return _schema.default_order(module, table)

    entries = [order] if isinstance(order, str) else list(order)
    if not entries:
        raise ValueError("order must name at least one column.")

    columns = []
    for entry in entries:
        column = entry
        for suffix in (".nullsfirst", ".nullslast"):
            if column.endswith(suffix):
                column = column[: -len(suffix)]
        for suffix in (".asc", ".desc"):
            if column.endswith(suffix):
                column = column[: -len(suffix)]
        columns.append(column)

    _schema.check_columns(module, table, columns, "ordering", _client.validate())
    return entries


# Progress --------------------------------------------------------------------


def _progress_start(progress, wanted, have, page_size, module, table):
    if progress is False:
        return None

    if progress is None:
        import sys

        if not sys.stderr.isatty():
            return None

    remaining = max(0, math.ceil((wanted - have) / page_size)) if math.isfinite(wanted) else 0
    if remaining < 1:
        return None

    try:
        from tqdm.auto import tqdm
    except ImportError:
        return None

    return tqdm(total=int(wanted), initial=have, unit="row", desc=f"{module}/{table}")


def _progress_step(bar, rows) -> None:
    if bar is not None:
        bar.update(rows)


def _progress_done(bar) -> None:
    if bar is not None:
        bar.close()
