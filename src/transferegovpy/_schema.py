"""Access to the frozen OpenAPI schema.

``_schema.json`` is built by ``scripts/build_schema.py`` from the documents the
three APIs publish at their roots. Freezing it means filter validation, column
typing and :func:`~transferegovpy.fields` work without a network connection,
and that a change upstream shows up as a reviewable diff.
"""

from __future__ import annotations

import datetime as _dt
import functools
import json
import pathlib
import re

from ._errors import SchemaError

_PATH = pathlib.Path(__file__).with_name("_schema.json")


@functools.lru_cache(maxsize=1)
def bundle() -> dict:
    return json.loads(_PATH.read_text(encoding="utf-8"))


def built_at() -> _dt.date:
    """The date the packaged schema was taken from the APIs."""
    return _dt.date.fromisoformat(bundle()["built_at"])


def default_base_url() -> str:
    return bundle()["base_url"]


def module_names() -> list[str]:
    return list(bundle()["modules"])


def label(module: str) -> str:
    return bundle()["labels"][module]


def match_module(module: str) -> str:
    """Resolve a module name or alias to its canonical form."""
    if not isinstance(module, str):
        raise SchemaError(f"module must be a string, not {type(module).__name__}.")

    key = re.sub(r"[^a-z0-9]+", "_", module.strip().lower())
    aliases = bundle()["aliases"]
    key = aliases[key] if key in aliases else key.replace("_", "")

    if key not in bundle()["modules"]:
        raise SchemaError(
            f"Unknown module {module!r}. Choose one of {', '.join(module_names())}. "
            "See modules() for what each one covers."
        )

    return key


def table_names(module: str) -> list[str]:
    return list(bundle()["modules"][module]["tables"])


def match_table(module: str, table: str) -> str:
    """Resolve a table name within a module."""
    if not isinstance(table, str):
        raise SchemaError(f"table must be a string, not {type(table).__name__}.")

    key = table.strip()
    tables = bundle()["modules"][module]["tables"]

    if key not in tables:
        # The same table name exists in more than one module with different
        # columns, so a miss is often a module mix-up rather than a typo.
        elsewhere = [m for m in module_names() if m != module and key in table_names(m)]
        message = (
            f"Module {module!r} has no table {table!r}. "
            f"See tables({module!r}) for the {len(tables)} tables it publishes."
        )
        if elsewhere:
            message += f" Module(s) {', '.join(elsewhere)} do publish a table with that name, "
            message += "with different columns."
        raise SchemaError(message)

    return key


def table_fields(module: str, table: str) -> dict:
    return bundle()["modules"][module]["tables"][table]["fields"]


def table_description(module: str, table: str) -> str | None:
    return bundle()["modules"][module]["tables"][table]["description"]


def primary_key(module: str, table: str) -> list[str]:
    return [c for c, f in table_fields(module, table).items() if f["primary_key"]]


def default_order(module: str, table: str) -> list[str]:
    """The order used for multi-page collection.

    Offset pagination over an unordered query has no defined row order in
    Postgres, so pages could overlap or skip; an explicit order makes the
    sequence reproducible. A declared primary key is a total order. Failing
    that, identifier-like columns are the best available key, and the collected
    count is still checked afterwards.
    """
    keys = primary_key(module, table)
    if keys:
        return [f"{k}.asc" for k in keys]

    fields = table_fields(module, table)
    identifiers = [c for c in fields if re.match(r"^(id|sq|co|nr|cd)_", c)]
    if identifiers:
        return [f"{c}.asc" for c in identifiers]

    return [f"{next(iter(fields))}.asc"]


def check_columns(module: str, table: str, columns, what: str, validate: bool = True) -> None:
    """Reject column names the frozen schema does not know."""
    if not validate or not columns:
        return

    known = table_fields(module, table)
    unknown = [c for c in dict.fromkeys(columns) if c not in known]

    if unknown:
        raise SchemaError(
            f"Unknown {what} column(s): {', '.join(repr(c) for c in unknown)}. "
            f"See fields({module!r}, {table!r}) for the columns this table publishes. "
            f"The packaged schema is from {built_at()}. If the API has gained a column "
            "since, pass validate=False."
        )
