"""Discovery: what the APIs publish, without making a request."""

from __future__ import annotations

import datetime as _dt

import pandas as pd

from . import _client, _schema

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
            "url": [f"{_client.base_url()}/{m}" for m in names],
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
        with no module makes forty-eight. Responses are cached.

    Returns
    -------
    pandas.DataFrame
        One row per table: its module, name, number of columns, the primary key
        when the API declares one, and the description published in the schema.
    """
    names = _schema.module_names() if module is None else [_schema.match_module(module)]

    records = []
    for name in names:
        for table in _schema.table_names(name):
            keys = _schema.primary_key(name, table)
            records.append(
                {
                    "module": name,
                    "table": table,
                    "columns": len(_schema.table_fields(name, table)),
                    "primary_key": ", ".join(keys) if keys else None,
                    "description": _schema.table_description(name, table),
                }
            )

    frame = pd.DataFrame.from_records(records)

    if counts:
        frame["rows"] = _row_counts(frame)

    return frame


def _row_counts(frame: pd.DataFrame) -> list[int]:
    """One request per table.

    A progress bar because forty-eight throttled requests take the better part
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


def fields(module: str, table: str) -> pd.DataFrame:
    """List the columns of a table.

    Every column name may be used as a filter in :func:`~transferegovpy.get`
    and :func:`~transferegovpy.count`, in ``select``, and in ``order``. Column
    names and categorical values stay in Portuguese because they are the API's
    own contract.

    Returns
    -------
    pandas.DataFrame
        One row per column: its name, the pandas dtype the package coerces it
        to, the Postgres type the API reports, whether it is part of the
        declared primary key, and its description.
    """
    module = _schema.match_module(module)
    table = _schema.match_table(module, table)

    records = [
        {
            "field": name,
            "dtype": spec["dtype"],
            "pg_type": spec["pg_type"],
            "primary_key": spec["primary_key"],
            "description": spec["description"],
        }
        for name, spec in _schema.table_fields(module, table).items()
    ]

    return pd.DataFrame.from_records(records)


def schema_date() -> _dt.date:
    """When the packaged schema was taken from the APIs.

    The package validates filters and types columns against a copy of the APIs'
    OpenAPI documents taken on this date. A column added upstream since then is
    still returned, but is typed by inspection rather than from the schema.
    """
    return _schema.built_at()
