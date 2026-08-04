"""Discovery: what the APIs publish, without making a request."""

from __future__ import annotations

import datetime as _dt

import pandas as pd

from . import _client, _schema
from ._errors import SchemaError

__all__ = ["modules", "tables", "fields", "schema_date"]


def modules() -> pd.DataFrame:
    """List the TransfereGov API modules.

    Returns
    -------
    pandas.DataFrame
        One row per module: its name, the label used in this documentation, the
        number of tables it publishes, and its API base URL.
    """
    names = _schema.module_names()

    return pd.DataFrame(
        {
            "module": names,
            "label": [_schema.label(m) for m in names],
            "tables": [len(_schema.table_names(m)) for m in names],
            "url": [f"{_client.base_url(m)}/{m}" for m in names],
        }
    )


def tables(module: str | None = None, counts: bool = False) -> pd.DataFrame:
    """List the tables a module publishes.

    Parameters
    ----------
    module:
        A module name from :func:`modules`. Aliases such as ``"fundo_a_fundo"``
        are accepted. ``None`` lists the tables of every module.
    counts:
        Add a ``rows`` column with the number of rows each table currently
        holds. This is the only part of this function that needs a network
        connection: it makes one request per table, so ``tables(counts=True)``
        with no module makes fifty-five. Responses are cached.

    Returns
    -------
    pandas.DataFrame
        One row per table: its module, name, the endpoint path it maps to, its
        number of columns and filterable parameters, and the description
        published in the schema.
    """
    names = _schema.module_names() if module is None else [_schema.match_module(module)]

    records = [
        {
            "module": name,
            "table": table,
            "path": _schema.table_path(name, table),
            "columns": len(_schema.table_fields(name, table)),
            "params": len(_schema.table_params(name, table)),
            "description": _schema.table_description(name, table),
        }
        for name in names
        for table in _schema.table_names(name)
    ]

    frame = pd.DataFrame.from_records(records)

    if counts:
        frame["rows"] = _row_counts(frame)

    return frame


def _row_counts(frame: pd.DataFrame) -> list[int]:
    """One request per table.

    A progress bar because fifty-five throttled requests take the better part
    of a minute the first time, and none after that while the cache is warm.
    """
    from .query import count as _count

    pairs = list(zip(frame["module"], frame["table"]))

    try:
        from tqdm.auto import tqdm

        pairs = tqdm(pairs, unit="table", desc="counting rows")
    except ImportError:
        pass

    return [_count(module, table) for module, table in pairs]


def fields(module: str, table: str, nested: str | None = None) -> pd.DataFrame:
    """List the columns of a table.

    Column names stay in Portuguese because they are the API's own contract.
    Not every column can be filtered on; :func:`~transferegovpy.params` lists
    the ones that can.

    Parameters
    ----------
    module:
        A module name from :func:`modules`.
    table:
        A table name from :func:`tables`.
    nested:
        The name of a list column, to describe the columns of the objects
        inside it instead of the table's own. ``None`` describes the table.

    Returns
    -------
    pandas.DataFrame
        One row per column: its name, the pandas dtype the package coerces it
        to, the type the API declares, the sub-schema it nests when it is a
        list column, and its description.
    """
    module = _schema.match_module(module)
    table = _schema.match_table(module, table)

    if nested is None:
        entries = _schema.table_fields(module, table)
    else:
        available = _schema.table_nested(module, table)
        if not isinstance(nested, str) or nested not in available:
            detail = (
                "That table has none."
                if not available
                else f"It has {', '.join(repr(c) for c in available)}."
            )
            raise SchemaError(f"nested must name a list column of {table!r}. {detail}")
        entries = available[nested]

    records = [
        {
            "field": name,
            "dtype": spec["dtype"],
            "api_type": spec["api_type"],
            "nested": spec["nested"],
            "description": spec["description"],
        }
        for name, spec in entries.items()
    ]

    return pd.DataFrame.from_records(records)


def schema_date() -> _dt.date:
    """When the packaged schema was taken from the APIs.

    The package validates filters and types columns against a copy of the APIs'
    OpenAPI documents taken on this date. A column added upstream since then is
    still returned, but is typed by inspection rather than from the schema.
    """
    return _schema.built_at()
