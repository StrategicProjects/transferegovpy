"""Query parameters.

A filter is one of the endpoint's own query parameters. There is no operator
vocabulary: the services compare for equality and nothing else, and they
combine parameters with AND.

Every name is checked against the frozen parameter list before the request
goes out. That check is load-bearing rather than a convenience. These services
answer 200 and ignore a parameter they do not recognise, so
``situacao_proposta`` misspelt as ``in_situacao_proposta`` returns the whole
table. Without the check, a typo reads as "no rows matched that restriction" --
the answer looks plausible and is wrong.
"""

from __future__ import annotations

import datetime as _dt
import difflib
from decimal import Decimal

import pandas as pd

from . import _client, _schema
from ._errors import FilterError


def params(module: str, table: str) -> pd.DataFrame:
    """List the parameters a table accepts as filters.

    Every parameter may be passed to :func:`~transferegovpy.get` and
    :func:`~transferegovpy.count` as a keyword argument. Parameter names and
    their permitted values are in Portuguese because they belong to the API.

    :param module: A module name from :func:`~transferegovpy.modules`.
    :param table: A table name from :func:`~transferegovpy.tables`.
    :returns: One row per parameter: its name, the pandas dtype a value maps
        to, the type the API declares, the permitted values when the parameter
        is enumerated, the pattern a value must match when it has one, and its
        description.
    """
    module = _schema.match_module(module)
    table = _schema.match_table(module, table)
    entries = _schema.table_params(module, table)

    return pd.DataFrame(
        {
            "param": list(entries),
            "dtype": [e["dtype"] for e in entries.values()],
            "api_type": [e["api_type"] for e in entries.values()],
            "values": [list(e["values"]) for e in entries.values()],
            "pattern": [e["pattern"] for e in entries.values()],
            "description": [e["description"] for e in entries.values()],
        }
    )


def encode(module: str, table: str, filters: dict) -> list[tuple[str, str]]:
    """Turn keyword filters into query parameters, checking them first."""
    if not filters:
        return []

    known = _schema.table_params(module, table)
    _check_names(list(filters), known, module, table)

    return [
        (name, _encode_one(name, value, known))
        for name, value in filters.items()
        if value is not None
    ]


def _check_names(names: list[str], known: dict, module: str, table: str) -> None:
    if not _client.validate():
        return

    unknown = [n for n in names if n not in known]
    if not unknown:
        return

    message = (
        f"Unknown filter(s): {', '.join(repr(n) for n in unknown)}. "
        "The API ignores a parameter it does not recognise and returns every "
        "row, so this would look like a query that matched nothing in particular."
    )

    suggestions = _suggest(unknown, list(known))
    if suggestions:
        message += f" Did you mean {', '.join(repr(s) for s in suggestions)}?"

    message += (
        f" See params({module!r}, {table!r}) for the parameters this table accepts. "
        f"The packaged schema is from {_schema.built_at()}. If the API has gained "
        "a parameter since, call configure(validate=False)."
    )
    raise FilterError(message)


def _suggest(unknown: list[str], known: list[str]) -> list[str]:
    """The closest known name to each unknown one, when it is close enough.

    Names here are long and share prefixes, so the cutoff is generous.
    """
    out = []
    for name in unknown:
        match = difflib.get_close_matches(name, known, n=1, cutoff=0.6)
        if match and match[0] not in out:
            out.append(match[0])
    return out


def _encode_one(name: str, value, known: dict) -> str:
    # There is no way to express "is one of" in one request: the services
    # accept one value per parameter and silently keep the last of a repeated
    # one. The honest answer is to refuse and say what to do instead, rather
    # than issue several requests behind a signature that promises one.
    if isinstance(value, (list, tuple, set, frozenset)):
        raise FilterError(
            f"Filter {name!r} has {len(value)} values, and the API accepts one. "
            "Query each value and concatenate the results, for example "
            f"pd.concat([tg.get(module, table, **{{{name!r}: v}}) for v in values])."
        )

    if value is pd.NA or (isinstance(value, float) and value != value):
        raise FilterError(
            f"Filter {name!r} must not be missing; these APIs cannot filter for "
            "a null column."
        )

    encoded = _to_text(value)
    _check_value(name, encoded, known)
    return encoded


def _to_text(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, _dt.datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(value, _dt.date):
        return value.isoformat()
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(value, float):
        # `str()` would render 1e+05 for a plain integer-valued float, which
        # the service rejects as an integer.
        return format(Decimal(repr(value)).normalize(), "f")
    return str(value)


def _check_value(name: str, encoded: str, known: dict) -> None:
    """Check an enumerated value here rather than leaving it to the service.

    The service does reject a bad value with a 422, but only after a request,
    and its message does not say which of the fifty-odd parameters is
    enumerated.
    """
    if not _client.validate():
        return

    permitted = known.get(name, {}).get("values") or []
    if not permitted or encoded in permitted:
        return

    message = f"{encoded!r} is not a permitted value for {name!r}."
    suggestions = _suggest([encoded], permitted)
    if suggestions:
        message += f" Did you mean {', '.join(repr(s) for s in suggestions)}?"
    message += f" It accepts {', '.join(repr(v) for v in permitted)}."
    raise FilterError(message)
