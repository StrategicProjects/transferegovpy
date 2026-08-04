"""JSON to DataFrame.

The services answer with an array of objects under ``data``, one per row, with
a JSON ``null`` wherever the column is NULL. Columns are typed from the frozen
schema rather than inferred, so a column made entirely of nulls on one page
does not come back ``object`` while the next page returns it as ``string``.

A few columns hold an array of objects rather than a scalar. They stay as
``object``, holding the lists as they arrived; ``fields(nested=)`` describes
what is inside.
"""

from __future__ import annotations

import warnings

import pandas as pd

from . import _schema
from ._errors import ColumnTypeWarning


def to_frame(rows: list, module: str, table: str) -> pd.DataFrame:
    fields = _schema.table_fields(module, table)

    names = _row_names(rows) or list(fields)
    frame = pd.DataFrame(rows, columns=names) if rows else pd.DataFrame({n: [] for n in names})

    for name in names:
        dtype = fields.get(name, {}).get("dtype")
        frame[name] = _coerce(frame[name], dtype, name)

    return frame


def _row_names(rows: list) -> list[str]:
    """The column set comes from the response, not the schema.

    A column added upstream since the schema was frozen must still come
    through. Every key seen is kept, in the order the first row presents them.
    """
    names: dict[str, None] = {}
    for row in rows:
        if isinstance(row, dict):
            names.update(dict.fromkeys(row))
    return list(names)


def _coerce(series: pd.Series, dtype: str | None, name: str) -> pd.Series:
    if dtype is None:
        # A column the frozen schema does not know is left as pandas found it
        # rather than dropped, so the package keeps working when the API gains
        # a column.
        return series

    if dtype == "object":
        # A declared array column: the lists arrived as pandas found them, and
        # flattening would lose what they hold.
        return series.astype("object")

    if dtype == "datetime64[ns]":
        return _to_datetime(series, name)

    try:
        return series.astype(dtype)
    except (TypeError, ValueError):
        warnings.warn(
            f"Column {name!r} does not fit {dtype}; leaving it as {series.dtype}.",
            ColumnTypeWarning,
            stacklevel=3,
        )
        return series


def _to_datetime(series: pd.Series, name: str) -> pd.Series:
    """Parse strictly, or leave the column alone.

    ``pd.to_datetime`` with ``errors="coerce"`` would turn an unparseable value
    into ``NaT`` and hide it. Parsing without a fallback and checking that no
    non-null value became null keeps a bad value visible.
    """
    if series.empty:
        return series.astype("datetime64[ns]")

    present = series.notna()

    try:
        parsed = pd.to_datetime(series, format="ISO8601", errors="coerce", utc=False)
    except (TypeError, ValueError):
        parsed = None

    if parsed is None or bool((present & parsed.isna()).any()):
        warnings.warn(
            f"Column {name!r} holds date values that cannot be parsed; leaving it as text.",
            ColumnTypeWarning,
            stacklevel=3,
        )
        return series.astype("string")

    # A timezone-aware column is converted to UTC and made naive, so the whole
    # column has one dtype whatever offsets the rows carried.
    if getattr(parsed.dtype, "tz", None) is not None:
        parsed = parsed.dt.tz_convert("UTC").dt.tz_localize(None)

    # pandas 2 picks a resolution from the values, so the same column arrives as
    # datetime64[us] with rows and datetime64[ns] without them. Pinning it keeps
    # the dtype from depending on what a page happened to contain.
    try:
        return parsed.astype("datetime64[ns]")
    except (OverflowError, ValueError, pd.errors.OutOfBoundsDatetime):
        # Outside the nanosecond range, which spans 1677 to 2262. Keeping the
        # coarser resolution beats losing the values.
        warnings.warn(
            f"Column {name!r} holds dates outside the nanosecond range; "
            f"keeping {parsed.dtype}.",
            ColumnTypeWarning,
            stacklevel=3,
        )
        return parsed
