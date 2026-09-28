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
    params  the query parameters the endpoint accepts, with their types,
            enumerated values, and whether they take a list

Freezing ``params`` is not a convenience. These services ignore a query
parameter they do not recognise and answer 200 with the whole table, so
``situacao_proposta`` misspelt as ``in_situacao_proposta`` silently returns
every proposal instead of the approved ones. Only a client-side check against this list
turns that into an error.
"""

from __future__ import annotations

import datetime
import json
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://api-publica.transferegov.gestao.gov.br"
MODULES = ("especiais", "fundoafundo", "parcerias", "ted")

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

    ``-`` is not usable in a keyword argument, and the spelling is not stable:
    ``especiais`` published ``/planos_acao_especiais`` until September 2026 and
    ``/planos-acao-especiais`` after it, with every older spelling answering
    404. The underscore form is the name, so that change never reaches a
    caller's code; ``path`` keeps what the URL needs.
    """
    return path.lstrip("/").replace("-", "_")


# Multi-valued parameters -----------------------------------------------------
#
# Some parameters take a comma-separated list and match any of its values -- an
# "is one of" -- and the rest take a single value. The OpenAPI documents do not
# say which: both are declared as a plain string. Nor does the name: 113
# parameters take a list, two of them not named `id_*`, while several `id_*`
# strings do not. So it is asked of the service, which is how every other
# behaviour frozen here was established.
#
# A list-taking parameter rejects a non-integer with a 400 whose message says it
# wants "números inteiros separados por vírgula"; any other parameter treats
# "x" as an ordinary value. Sent more values than it allows, it answers with
# the limit -- 100 in `especiais`, 200 elsewhere -- so that is read per
# parameter too. About 700 requests, a few minutes.

LIST_MARKER = "separados por v"
LIMIT_PATTERN = re.compile(r"máximo de valores possíveis.* é ([0-9]+)")


def probe(module: str, path: str, name: str, value: str) -> tuple[int, str]:
    query = urllib.parse.urlencode({"tamanho_da_pagina": 1, name: value})
    request = urllib.request.Request(
        f"{BASE}/{module}/{path}?{query}",
        headers={"User-Agent": "transferegovpy schema builder"},
    )
    for attempt in range(4):
        time.sleep(0.2)
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return response.status, response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as error:
            if error.code in (429, 502, 503, 504) and attempt < 3:
                time.sleep(2**attempt)
                continue
            return error.code, error.read().decode("utf-8", "replace")
    raise RuntimeError("unreachable")


def probe_lists(module: str, path: str, params: dict) -> None:
    for name, param in params.items():
        param["multiple"] = False
        param["max_values"] = 1

        if param["api_type"] != "string" or param["values"] or param["pattern"]:
            continue

        status, body = probe(module, path, name, "x")
        if status != 400 or LIST_MARKER not in body:
            continue

        status, body = probe(module, path, name, ",".join(str(i) for i in range(1, 1002)))
        limit = LIMIT_PATTERN.search(body)
        if not limit:
            raise SystemExit(f"{module}/{path} {name} takes a list but did not report its limit")

        param["multiple"] = True
        param["max_values"] = int(limit.group(1))


def max_page_size(spec: dict, paths: list, module: str) -> int:
    """The largest page a module serves.

    Not the same everywhere: ``especiais`` and ``parcerias`` declare 200,
    ``fundoafundo`` and ``ted`` 1000, and each answers 422 one row above its
    own limit. Read from the document rather than assumed, and required to
    agree across a module's endpoints, since the client applies it per module.
    """
    maxima = set()
    for path in paths:
        size = [
            p for p in spec["paths"][path]["get"].get("parameters", [])
            if p["name"] == "tamanho_da_pagina"
        ]
        if len(size) != 1:
            raise SystemExit(f"{module}{path} declares no tamanho_da_pagina")
        maxima.add(unwrap_null(size[0]["schema"]).get("maximum"))
    if len(maxima) != 1 or None in maxima:
        raise SystemExit(f"{module} declares inconsistent page size limits: {maxima}")
    return int(maxima.pop())


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
        probe_lists(module, path.lstrip("/"), params)

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

    paths = [p for p in spec["paths"] if table_name(p) != table_name(TIMESTAMP_PATH)]

    return {
        "path": module,
        "base_url": BASE,
        "title": (spec.get("info", {}).get("title") or module).strip(),
        "timestamp_path": TIMESTAMP_PATH,
        "max_page_size": max_page_size(spec, paths, module),
        "tables": dict(sorted(tables.items())),
    }


def main() -> None:
    schema = {module: build_module(module) for module in MODULES}

    tables = sum(len(m["tables"]) for m in schema.values())
    columns = sum(len(t["fields"]) for m in schema.values() for t in m["tables"].values())
    params = sum(len(t["params"]) for m in schema.values() for t in m["tables"].values())

    lists = {
        module: sum(
            p["multiple"] for t in built["tables"].values() for p in t["params"].values()
        )
        for module, built in schema.items()
    }

    for module, built in schema.items():
        print(
            f"  {module}: {len(built['tables'])} tables, "
            f"{sum(len(t['fields']) for t in built['tables'].values())} columns, "
            f"{sum(len(t['params']) for t in built['tables'].values())} parameters, "
            f"pages of up to {built['max_page_size']}, {lists[module]} list parameters"
        )
    print(f"total: {tables} tables, {columns} columns, {params} parameters")

    if len(schema) != 4 or tables != 74:
        raise SystemExit(f"expected 4 modules and 74 tables, got {len(schema)} and {tables}")

    bundle = {
        "built_at": datetime.date.today().isoformat(),
        "base_url": BASE,
        # The page size every module accepts, kept for `MAX_PAGE`; each module's
        # own limit is its `max_page_size`.
        "max_page": min(m["max_page_size"] for m in schema.values()),
        "labels": {
            "especiais": "Special transfers",
            "fundoafundo": "Fund-to-fund transfers",
            "parcerias": "Partnerships",
            "ted": "Decentralized credit",
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
            "termo_de_execucao_descentralizada": "ted",
            "termo_execucao_descentralizada": "ted",
            "decentralized_credit": "ted",
        },
        "modules": schema,
    }

    OUT.write_text(json.dumps(bundle, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
