"""Query parameters.

A filter is one of the endpoint's own query parameters. There is no operator
vocabulary: the services compare for equality, combine parameters with AND,
and on some identifier parameters accept a list meaning "is one of".

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
        is enumerated, the pattern a value must match when it has one, its
        description, whether it accepts several values (``multiple``), and how
        many at most (``max_values``).
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
            "multiple": [bool(e["multiple"]) for e in entries.values()],
            "max_values": [int(e["max_values"]) for e in entries.values()],
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


_SEQUENCES = (list, tuple, set, frozenset, pd.Series, pd.Index)


def _encode_one(name: str, value, known: dict) -> str:
    if hasattr(value, "tolist") and not isinstance(value, (pd.Series, pd.Index)):
        # A numpy array: treat it as the list it holds.
        value = value.tolist() if getattr(value, "ndim", 0) else value

    if isinstance(value, _SEQUENCES):
        values = list(value)
        entry = known.get(name, {})
        if entry.get("multiple") and len(values) > 1:
            return _encode_list(name, values, int(entry["max_values"]))
        if len(values) == 1:
            value = values[0]
        else:
            # Elsewhere there is no way to express "is one of" in one request:
            # the parameter takes one value, and a repeated parameter silently
            # keeps the last. The honest answer is to refuse and say what to do
            # instead, rather than issue several requests behind a signature
            # that promises one.
            raise FilterError(
                f"Filter {name!r} has {len(values)} values, and the API accepts one. "
                "Query each value and concatenate the results, for example "
                f"pd.concat([tg.get(module, table, **{{{name!r}: v}}) for v in values]). "
                "Only the parameters params() marks as multiple take several values "
                "in one request."
            )

    if value is pd.NA or (isinstance(value, float) and value != value):
        raise FilterError(
            f"Filter {name!r} must not be missing; these APIs cannot filter for "
            "a null column."
        )

    encoded = _to_text(value)
    _check_value(name, encoded, known)
    return encoded


def _encode_list(name: str, values: list, max_values: int) -> str:
    """A list-taking parameter wants whole numbers separated by commas.

    The service matches rows holding any of them, rejects anything else with a
    400, and caps the count -- 100 in ``especiais``, 200 elsewhere -- so both
    are checked before the request rather than discovered after it.
    """
    if any(v is None or v is pd.NA or (isinstance(v, float) and v != v) for v in values):
        raise FilterError(
            f"Filter {name!r} must not contain missing values; these APIs cannot "
            "filter for a null column."
        )

    def whole(v) -> bool:
        if isinstance(v, bool):
            return False
        if isinstance(v, int) or (hasattr(v, "dtype") and v.dtype.kind in "iu"):
            return int(v) >= 0
        if isinstance(v, float):
            return v.is_integer() and v >= 0
        return isinstance(v, str) and v.isdigit()

    if not all(whole(v) for v in values):
        raise FilterError(f"Filter {name!r} takes whole numbers when given several values.")

    encoded = list(dict.fromkeys(_to_text(int(v) if not isinstance(v, str) else v)
                                 for v in values))
    if len(encoded) > max_values:
        raise FilterError(
            f"Filter {name!r} has {len(encoded)} values, and the API accepts at most "
            f"{max_values}. Split them into groups of {max_values} and concatenate "
            "the results."
        )

    return ",".join(encoded)


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
