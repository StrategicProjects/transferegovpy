"""Access to the frozen OpenAPI schema.

``_schema.json`` is built by ``scripts/build_schema.py`` from the documents the
three APIs publish. Freezing it means filter validation, column typing and
:func:`~transferegovpy.fields` work without a network connection, and that a
change upstream shows up as a reviewable diff.

It holds the accepted **query parameters** as well as the columns. That is not
symmetry for its own sake: these services ignore a parameter they do not
recognise and answer 200 with the whole table, so the frozen list is the only
thing standing between a typo and a plausible, unfiltered answer.
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


def max_page() -> int:
    """Rows per request the services cap at. Asking for more is a 422."""
    return int(bundle()["max_page"])


def module_names() -> list[str]:
    return list(bundle()["modules"])


def label(module: str) -> str:
    return bundle()["labels"][module]


def module_base_url(module: str) -> str:
    return bundle()["modules"][module]["base_url"]


def timestamp_path(module: str) -> str:
    """The endpoint reporting when a module's data was last loaded."""
    return bundle()["modules"][module]["timestamp_path"]


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
    """Resolve a table name within a module.

    The endpoints are not consistent between modules about ``-`` and ``_``, so
    both spellings resolve to the underscore form the package exposes.
    """
    if not isinstance(table, str):
        raise SchemaError(f"table must be a string, not {type(table).__name__}.")

    key = table.strip().replace("-", "_")
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


def _table(module: str, table: str) -> dict:
    return bundle()["modules"][module]["tables"][table]


def table_fields(module: str, table: str) -> dict:
    return _table(module, table)["fields"]


def table_params(module: str, table: str) -> dict:
    """The query parameters an endpoint accepts, keyed by name."""
    return _table(module, table)["params"]


def table_nested(module: str, table: str) -> dict:
    """The sub-schemas of the table's list columns, keyed by column."""
    return _table(module, table)["nested"]


def table_path(module: str, table: str) -> str:
    """The endpoint path, which may spell the name with hyphens."""
    return _table(module, table)["path"]


def table_description(module: str, table: str) -> str | None:
    entry = _table(module, table)
    return entry["description"] or entry["summary"]
