"""Regenerates src/transferegovpy/_schema.json from the OpenAPI documents the
TransfereGov open data APIs publish.

    python scripts/build_schema.py

The schema is frozen into the package rather than fetched at import time so
that filter validation, column typing and ``fields()`` work offline, and so
that a change upstream shows up as a reviewable diff instead of silently
altering how results are typed. Re-run when the APIs gain endpoints, columns
or query parameters, and record the change in the changelog.

Two things are frozen per endpoint, not one:

    fields  the columns a row carries, and the pandas dtype each is coerced to
    params  the query parameters the endpoint accepts, with their types and
            enumerated values

Freezing ``params`` is not a convenience. These services ignore a query
parameter they do not recognise and answer 200 with the whole table, so
``situacao_proposta`` misspelt as ``in_situacao_proposta`` silently returns
88,666 rows instead of 84,258. Only a client-side check against this list
turns that into an error.
"""

from __future__ import annotations

import datetime
import json
import pathlib
import sys
import urllib.request

BASE = "https://api-publica.transferegov.gestao.gov.br"
MODULES = ("especiais", "fundoafundo", "parcerias")

OUT = (
    pathlib.Path(__file__).resolve().parent.parent
    / "src"
    / "transferegovpy"
    / "_schema.json"
)

# Parameters the client owns. They are stripped from the frozen parameter list
# so that a caller cannot set them as if they were filters and desynchronise
# the collection loop from the rows it is counting.
PAGINATION = ("pagina", "tamanho_da_pagina")

# The endpoint every module publishes that is not a table: it answers with a
# single object rather than a paginated envelope.
TIMESTAMP_PATH = "data-atualizacao"

# The page size the services cap a request at. Asking for more is a 422 rather
# than a silent truncation.
MAX_PAGE = 200

DATE_PATTERN = "^[0-9]{4}-[0-9]{2}-[0-9]{2}$"


def unwrap_null(schema: dict) -> dict:
    """OpenAPI 3.1 writes "nullable T" as ``anyOf: [T, null]``.

    That is every optional parameter and most columns. Reading the wrapper
    instead of the alternative types every column as a string and loses every
    list column and every date.
    """
    alternatives = schema.get("anyOf")
    if not alternatives:
        return schema
    kept = [a for a in alternatives if a.get("type") != "null"]
    return kept[0] if len(kept) == 1 else schema


def pandas_dtype(schema: dict) -> str:
    """The pandas dtype a value is coerced to.

    Unlike the R sibling, an integer maps to a nullable 64-bit integer rather
    than a float: pandas' ``Int64`` holds the full range *and* a missing
    value, so there is nothing to trade away. These documents declare no
    ``format``, so int32 and int64 are indistinguishable, and identifiers here
    genuinely exceed 2**31 -- ``cd_parceria`` reaches 202500037062.
    """
    if "$ref" in schema or schema.get("type") == "array":
        return "object"

    kind = schema.get("type")
    if kind == "string":
        if schema.get("format") in ("date", "date-time"):
            return "datetime64[ns]"
        # Date filters are declared as a plain string carrying an anchored
        # pattern rather than `format: date`.
        if schema.get("pattern") == DATE_PATTERN:
            return "datetime64[ns]"
        return "string"

    return {"integer": "Int64", "number": "Float64", "boolean": "boolean"}.get(
        kind, "string"
    )


def api_type(schema: dict) -> str | None:
    """The type as the document declares it, for ``fields()`` to report."""
    if "$ref" in schema:
        return "object"
    kind = schema.get("type")
    if kind == "array":
        return "array"
    fmt = schema.get("format")
    return f"{kind} ({fmt})" if fmt else kind


def ref_name(schema: dict) -> str | None:
    """The schema a ``$ref`` points at, direct or through an array's items."""
    direct = schema.get("$ref")
    if direct:
        return direct.rsplit("/", 1)[-1]
    items = (schema.get("items") or {}).get("$ref")
    return items.rsplit("/", 1)[-1] if items else None


def clean(text: str | None) -> str | None:
    return (text.strip() or None) if text else None


def fetch(module: str) -> dict:
    print(f"fetching {module}", file=sys.stderr)
    request = urllib.request.Request(
        f"{BASE}/{module}/openapi.json",
        headers={
            "Accept": "application/json",
            "User-Agent": "transferegovpy schema builder",
        },
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.load(response)


def build_fields(properties: dict) -> dict:
    fields = {}
    for column, prop in properties.items():
        schema = unwrap_null(prop)
        fields[column] = {
            "dtype": pandas_dtype(schema),
            "api_type": api_type(schema),
            "nested": ref_name(schema),
            "description": clean(prop.get("description") or schema.get("description")),
        }
    return fields


def build_params(parameters: list) -> dict:
    params = {}
    for parameter in parameters:
        name = parameter["name"]
        if name in PAGINATION:
            continue
        schema = unwrap_null(parameter.get("schema", {}))
        params[name] = {
            "dtype": pandas_dtype(schema),
            "api_type": api_type(schema),
            # Enumerated parameters carry their permitted values; the rest
            # carry an empty list, so a caller can test truthiness without a
            # type check.
            "values": [str(v) for v in schema.get("enum", [])],
            "pattern": schema.get("pattern"),
            "description": clean(
                parameter.get("description")
                or parameter.get("schema", {}).get("description")
            ),
        }
    return params


def table_name(path: str) -> str:
    """The name the package exposes for an endpoint.

    ``-`` is not usable in a keyword argument and the modules are not even
    consistent with each other: ``especiais`` publishes
    ``/planos_acao_especiais`` while ``fundoafundo`` publishes ``/planos-acao``.
    The underscore form is the name; ``path`` keeps what the URL needs.
    """
    return path.lstrip("/").replace("-", "_")


def build_module(module: str) -> dict:
    spec = fetch(module)
    schemas = spec["components"]["schemas"]

    tables = {}
    for path, operations in spec["paths"].items():
        if table_name(path) == table_name(TIMESTAMP_PATH):
            continue

        operation = operations["get"]
        answer = operation["responses"]["200"]["content"]["application/json"]
        envelope = answer["schema"]["$ref"].rsplit("/", 1)[-1]
        item = schemas[envelope]["properties"]["data"]["items"]["$ref"].rsplit("/", 1)[-1]

        fields = build_fields(schemas[item]["properties"])
        params = build_params(operation.get("parameters", []))

        # These documents describe the query parameters but leave every
        # response column undescribed. Nearly every column is also filterable
        # under its own name, so the parameter's description is the column's
        # description from the same document.
        for column, field in fields.items():
            if column in params:
                field["description"] = params[column]["description"]

        # A column holding an array of objects becomes a list column. The
        # sub-schema is frozen alongside it so `fields()` can describe what is
        # inside instead of reporting an opaque object.
        nested = {
            column: build_fields(schemas[field["nested"]]["properties"])
            for column, field in fields.items()
            if field["nested"]
        }

        tables[table_name(path)] = {
            "path": path.lstrip("/"),
            "summary": clean(operation.get("summary")),
            "description": clean(operation.get("description")),
            "fields": fields,
            "nested": nested,
            "params": params,
        }

    return {
        "path": module,
        "base_url": BASE,
        "title": (spec.get("info", {}).get("title") or module).strip(),
        "timestamp_path": TIMESTAMP_PATH,
        "tables": dict(sorted(tables.items())),
    }


def main() -> None:
    schema = {module: build_module(module) for module in MODULES}

    tables = sum(len(m["tables"]) for m in schema.values())
    columns = sum(len(t["fields"]) for m in schema.values() for t in m["tables"].values())
    params = sum(len(t["params"]) for m in schema.values() for t in m["tables"].values())

    for module, built in schema.items():
        print(
            f"  {module}: {len(built['tables'])} tables, "
            f"{sum(len(t['fields']) for t in built['tables'].values())} columns, "
            f"{sum(len(t['params']) for t in built['tables'].values())} parameters"
        )
    print(f"total: {tables} tables, {columns} columns, {params} parameters")

    if len(schema) != 3 or tables != 55:
        raise SystemExit(f"expected 3 modules and 55 tables, got {len(schema)} and {tables}")

    bundle = {
        "built_at": datetime.date.today().isoformat(),
        "base_url": BASE,
        "max_page": MAX_PAGE,
        "labels": {
            "especiais": "Special transfers",
            "fundoafundo": "Fund-to-fund transfers",
            "parcerias": "Partnerships",
        },
        "aliases": {
            # The module was called this on the retired PostgREST host.
            "transferenciasespeciais": "especiais",
            "transferencias_especiais": "especiais",
            "especial": "especiais",
            "special": "especiais",
            "special_transfers": "especiais",
            "fundo_a_fundo": "fundoafundo",
            "fundo_afundo": "fundoafundo",
            "fund_to_fund": "fundoafundo",
            "parceria": "parcerias",
            "partnerships": "parcerias",
        },
        "modules": schema,
    }

    OUT.write_text(json.dumps(bundle, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
