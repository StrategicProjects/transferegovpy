"""Comparison operators for the 'PostgREST' services behind the TransfereGov APIs.

A filter is a query parameter whose name is the column and whose value is
``operator.operand``. These builders produce that value while keeping the
escaping rules in one place.

Pass them as keyword arguments to :func:`~transferegovpy.get` and
:func:`~transferegovpy.count`, where the keyword is the column being filtered::

    get("ted", "plano_acao", aa_ano_plano_acao=gte(2024))

A bare value is shorthand for :func:`eq`, and a bare list or tuple is shorthand
for :func:`in_`. Pass a list of operators to apply several conditions to the
same column, which the API combines with AND::

    get("ted", "plano_acao",
        dt_inicio_vigencia=[gte("2024-01-01"), lt("2025-01-01")])
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from ._errors import FilterError

__all__ = [
    "Filter",
    "eq",
    "neq",
    "gt",
    "gte",
    "lt",
    "lte",
    "like",
    "ilike",
    "re_match",
    "re_imatch",
    "in_",
    "is_null",
    "is_true",
    "is_false",
    "not_",
    "operators",
]

# PostgREST reads the first "." as the operator separator and treats "," "(" ")"
# as structure, so a value carrying any of them, or leading or trailing spaces,
# has to be double quoted. Values that need no quoting are left alone: quoting a
# `like` pattern would be a behaviour change, not just a formatting one.
_NEEDS_QUOTES = set(',()"\\')


@dataclass(frozen=True)
class Filter:
    """One condition on one column."""

    op: str
    value: Any = None
    negate: bool = False
    quote_all: bool = field(default=False, compare=False)

    def __str__(self) -> str:
        encoded = _encode(self.value, self.quote_all)
        operand = f"({','.join(encoded)})" if self.op == "in" else encoded[0]
        return f"{'not.' if self.negate else ''}{self.op}.{operand}"

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"<Filter {self}>"


def _encode(value: Any, quote_all: bool = False) -> list[str]:
    values = value if isinstance(value, (list, tuple)) else [value]
    return [_encode_one(v, quote_all) for v in values]


def _encode_one(value: Any, quote_all: bool) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, _dt.datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(value, _dt.date):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        # `repr` would render 1e+05 for a plain integer-valued float, which the
        # API compares as text for some column types.
        text = f"{value:.15g}"
        return text
    text = str(value)
    if quote_all or not text or any(c in _NEEDS_QUOTES for c in text) or text != text.strip():
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return text


def _check_scalar(value: Any, who: str) -> None:
    if isinstance(value, (list, tuple, set, dict)):
        raise FilterError(f"{who}() takes a single value, not {type(value).__name__}.")
    if value is None:
        raise FilterError(f"{who}() operand must not be None. Use is_null() to match nulls.")


def _check_pattern(pattern: Any, who: str) -> None:
    if not isinstance(pattern, str):
        raise FilterError(f"{who}() takes a string pattern, not {type(pattern).__name__}.")


def eq(value: Any) -> Filter:
    """Equals."""
    _check_scalar(value, "eq")
    return Filter("eq", value)


def neq(value: Any) -> Filter:
    """Does not equal."""
    _check_scalar(value, "neq")
    return Filter("neq", value)


def gt(value: Any) -> Filter:
    """Greater than."""
    _check_scalar(value, "gt")
    return Filter("gt", value)


def gte(value: Any) -> Filter:
    """Greater than or equal to."""
    _check_scalar(value, "gte")
    return Filter("gte", value)


def lt(value: Any) -> Filter:
    """Less than."""
    _check_scalar(value, "lt")
    return Filter("lt", value)


def lte(value: Any) -> Filter:
    """Less than or equal to."""
    _check_scalar(value, "lte")
    return Filter("lte", value)


def like(pattern: str) -> Filter:
    """Matches a pattern, case sensitive. The wildcard is ``*`` or ``%``."""
    _check_pattern(pattern, "like")
    return Filter("like", pattern)


def ilike(pattern: str) -> Filter:
    """Matches a pattern, case insensitive. The wildcard is ``*`` or ``%``."""
    _check_pattern(pattern, "ilike")
    return Filter("ilike", pattern)


def re_match(pattern: str) -> Filter:
    """Matches a POSIX regular expression, case sensitive."""
    _check_pattern(pattern, "re_match")
    return Filter("match", pattern)


def re_imatch(pattern: str) -> Filter:
    """Matches a POSIX regular expression, case insensitive."""
    _check_pattern(pattern, "re_imatch")
    return Filter("imatch", pattern)


def in_(values: Iterable[Any]) -> Filter:
    """Is one of ``values``."""
    if isinstance(values, (str, bytes)) or not isinstance(values, (Sequence, set, frozenset)):
        raise FilterError("in_() takes a sequence of values.")
    items = list(values)
    if not items:
        raise FilterError("in_() needs at least one value.")
    if any(v is None for v in items):
        raise FilterError("in_() values must not be None. Use is_null() to match nulls.")
    # Every element is quoted: an unquoted comma inside a value would be read as
    # a separator and silently widen the set being matched.
    return Filter("in", items, quote_all=True)


def is_null() -> Filter:
    """Is null."""
    return Filter("is", "null")


def is_true() -> Filter:
    """Is true."""
    return Filter("is", "true")


def is_false() -> Filter:
    """Is false."""
    return Filter("is", "false")


def not_(filter_: Filter) -> Filter:
    """Negates another operator."""
    if not isinstance(filter_, Filter):
        raise FilterError("not_() takes a filter, for example not_(eq(1)).")
    if filter_.negate:
        raise FilterError("A filter cannot be negated twice.")
    return Filter(filter_.op, filter_.value, negate=True, quote_all=filter_.quote_all)


_OPERATORS = [
    ("eq", "eq", "equals"),
    ("neq", "neq", "does not equal"),
    ("gt", "gt", "greater than"),
    ("gte", "gte", "greater than or equal to"),
    ("lt", "lt", "less than"),
    ("lte", "lte", "less than or equal to"),
    ("like", "like", "matches pattern, case sensitive"),
    ("ilike", "ilike", "matches pattern, case insensitive"),
    ("re_match", "match", "matches regular expression, case sensitive"),
    ("re_imatch", "imatch", "matches regular expression, case insensitive"),
    ("in_", "in", "is one of"),
    ("is_null", "is.null", "is null"),
    ("is_true", "is.true", "is true"),
    ("is_false", "is.false", "is false"),
    ("not_", "not", "negates another operator"),
]


def operators():
    """List the available filter operators.

    Returns
    -------
    pandas.DataFrame
        The exported operator, the 'PostgREST' operator it sends, and what it
        means.
    """
    import pandas as pd

    return pd.DataFrame(_OPERATORS, columns=["operator", "postgrest", "meaning"])


def to_params(filters: dict) -> list[tuple[str, str]]:
    """Turn a mapping of column to filter into repeated query parameters.

    PostgREST reads two parameters with the same column name as two conditions
    combined with AND, which is how ``col=[gte(1), lte(5)]`` is expressed. The
    result is a list of pairs rather than a dict for exactly that reason.
    """
    params: list[tuple[str, str]] = []

    for column, value in filters.items():
        if value is None:
            continue
        for condition in _column_conditions(column, value):
            params.append((column, condition))

    return params


def _column_conditions(column: str, value: Any) -> list[str]:
    if isinstance(value, Filter):
        return [str(value)]

    if isinstance(value, (list, tuple, set, frozenset)):
        items = list(value)
        if not items:
            raise FilterError(f"Filter {column!r} is empty.")
        if all(isinstance(v, Filter) for v in items):
            return [str(v) for v in items]
        if any(isinstance(v, Filter) for v in items):
            raise FilterError(
                f"Filter {column!r} mixes operators and plain values; use one or the other."
            )
        if any(v is None for v in items):
            raise FilterError(f"Filter {column!r} must not contain None. Use is_null().")
        return [str(in_(items))]

    return [str(eq(value))]
