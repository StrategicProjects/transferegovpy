"""Regenerates src/transferegovpy/_schema.json from the OpenAPI documents the
three TransfereGov APIs publish at their roots.

    python scripts/build_schema.py

The schema is frozen into the package rather than fetched at import time so
that filter validation, column typing and ``fields()`` work offline, and so
that a change upstream shows up as a reviewable diff instead of silently
altering how results are typed. Re-run when the APIs publish new tables or
columns, and record the change in the changelog.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys
import urllib.request

BASE = "https://api.transferegov.gestao.gov.br"
MODULES = ("transferenciasespeciais", "fundoafundo", "ted")

OUT = pathlib.Path(__file__).resolve().parent.parent / "src" / "transferegovpy" / "_schema.json"

# Postgres types, as reported in the OpenAPI `format` field, mapped to the
# pandas dtype each column is coerced to.
#
# Unlike the R sibling, `bigint` maps to a 64-bit integer rather than a float:
# pandas' nullable Int64 holds the full range, so there is no need to trade
# exactness for the ability to represent a missing value.
BY_FORMAT = {
    "date": "datetime64[ns]",
    "timestamp without time zone": "datetime64[ns]",
    "timestamp with time zone": "datetime64[ns]",
    "boolean": "boolean",
    "smallint": "Int64",
    "integer": "Int64",
    "bigint": "Int64",
    "numeric": "Float64",
    "double precision": "Float64",
    "real": "Float64",
    "character varying": "string",
    "character": "string",
    "text": "string",
}

BY_TYPE = {"integer": "Int64", "number": "Float64", "boolean": "boolean"}

PK_MARKER = "This is a Primary Key"


def pandas_dtype(fmt: str, json_type: str) -> str:
    if fmt in BY_FORMAT:
        return BY_FORMAT[fmt]
    return BY_TYPE.get(json_type, "string")


def clean(text: str | None) -> str | None:
    if not text:
        return None
    text = re.sub(r"\s*Note:\s*This is a (Primary|Foreign) Key.*$", "", text, flags=re.S)
    text = text.strip()
    return text or None


def fetch(module: str) -> dict:
    print(f"fetching {module}", file=sys.stderr)
    request = urllib.request.Request(
        f"{BASE}/{module}/",
        headers={
            "Accept": "application/openapi+json",
            "User-Agent": "transferegovpy schema builder",
        },
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.load(response)


def build_module(module: str) -> dict:
    spec = fetch(module)
    tables = {}

    for table, definition in sorted(spec["definitions"].items()):
        fields = {}
        for column, prop in definition.get("properties", {}).items():
            description = prop.get("description") or ""
            fields[column] = {
                "dtype": pandas_dtype(prop.get("format", ""), prop.get("type", "")),
                "pg_type": prop.get("format"),
                "primary_key": PK_MARKER in description,
                "description": clean(description),
            }
        tables[table] = {
            "description": clean(definition.get("description")),
            "fields": fields,
        }

    return {
        "path": module,
        "title": (spec.get("info", {}).get("title") or module).strip(),
        "tables": tables,
    }


def main() -> None:
    schema = {module: build_module(module) for module in MODULES}

    tables = sum(len(m["tables"]) for m in schema.values())
    columns = sum(len(t["fields"]) for m in schema.values() for t in m["tables"].values())

    if len(schema) != 3 or tables != 48:
        raise SystemExit(f"expected 3 modules and 48 tables, got {len(schema)} and {tables}")

    bundle = {
        "built_at": __import__("datetime").date.today().isoformat(),
        "base_url": BASE,
        "labels": {
            "transferenciasespeciais": "Special transfers",
            "fundoafundo": "Fund-to-fund transfers",
            "ted": "Decentralized credit (TED)",
        },
        "aliases": {
            "transferencias_especiais": "transferenciasespeciais",
            "especiais": "transferenciasespeciais",
            "special": "transferenciasespeciais",
            "special_transfers": "transferenciasespeciais",
            "fundo_a_fundo": "fundoafundo",
            "fundo_afundo": "fundoafundo",
            "fund_to_fund": "fundoafundo",
            "ted": "ted",
            "decentralized_credit": "ted",
            "decentralised_credit": "ted",
        },
        "modules": schema,
    }

    OUT.write_text(json.dumps(bundle, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    size = OUT.stat().st_size / 1024
    print(f"tables: {tables} | columns: {columns} | wrote {OUT} ({size:.1f} KB)")


if __name__ == "__main__":
    main()
