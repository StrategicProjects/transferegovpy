#!/usr/bin/env python3
"""Mutation testing for the transferegovpy core.

    .venv/bin/python scripts/mutants.py

Each mutant is a deliberate defect. A mutant is KILLED if the test suite fails
with it applied, and SURVIVES if the suite still passes -- which means no test
covers that behaviour.

Three things the harness checks rather than assumes:

- The anchor appears exactly once and the edit is on disk before the suite
  runs. On the R sibling's first run two mutants "survived" only because the
  mutation never applied, which reads as a suite gap when it is a broken
  mutator.
- The suite imports the *mutated* copy. The development environment holds an
  editable install of the original, so a wrong ``sys.path`` would test the
  unmutated package and every mutant would survive.
- A mutant can hang rather than fail: removing the empty-page break makes the
  collection loop spin on ``responses`` replaying its last page. A timeout
  counts as a kill.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = "src/transferegovpy"
TIMEOUT = 180

# (name, file, old, new)
MUTANTS = [
    # Pagination
    ("first-page-off-by-one", f"{PKG}/query.py",
     "first_page = offset // page_size + 1",
     "first_page = offset // page_size"),
    ("offset-inside-page-ignored", f"{PKG}/query.py",
     "drop = offset % page_size",
     "drop = 0"),
    ("limit-not-trimmed", f"{PKG}/query.py",
     "return rows[: int(wanted)] if math.isfinite(wanted) else rows",
     "return rows"),
    ("empty-page-loops", f"{PKG}/query.py",
     "        if not page[\"rows\"]:\n            break",
     "        if False:\n            break"),
    ("total-ignored", f"{PKG}/query.py",
     "return min(limit, max(0.0, total - offset))",
     "return limit"),
    ("incomplete-not-warned", f"{PKG}/query.py",
     "if math.isfinite(wanted) and len(rows) != wanted:",
     "if False:"),
    ("page-param-misnamed", f"{PKG}/query.py",
     "return [(\"pagina\", str(number)), (\"tamanho_da_pagina\", str(size))]",
     "return [(\"page\", str(number)), (\"tamanho_da_pagina\", str(size))]"),
    ("page-size-cap-lifted", f"{PKG}/query.py",
     "page_size = _check_count(page_size, \"page_size\", maximum=max_page_size)",
     "page_size = _check_count(page_size, \"page_size\", maximum=100000)"),
    ("page-size-default-fixed", f"{PKG}/query.py",
     "        page_size = max_page_size\n",
     "        page_size = 200\n"),
    ("count-reads-wrong-field", f"{PKG}/query.py",
     "return int(page[\"total\"])",
     "return int(page[\"page_size\"])"),
    # Filter validation
    ("unknown-param-allowed", f"{PKG}/_params.py",
     "    if not unknown:\n        return",
     "    if True:\n        return"),
    ("enum-unchecked", f"{PKG}/_params.py",
     "if not permitted or encoded in permitted:",
     "if True:"),
    ("multi-value-silently-truncated", f"{PKG}/_params.py",
     "        if len(values) == 1:\n            value = values[0]",
     "        if len(values) >= 1:\n            value = values[-1]"),
    ("na-filter-allowed", f"{PKG}/_params.py",
     "if value is pd.NA or (isinstance(value, float) and value != value):",
     "if False:"),
    ("bools-as-numbers", f"{PKG}/_params.py",
     "    if isinstance(value, bool):\n        return \"true\" if value else \"false\"\n",
     ""),
    ("floats-in-scientific", f"{PKG}/_params.py",
     "return format(Decimal(repr(value)).normalize(), \"f\")",
     "return str(value)"),
    ("dates-in-wrong-format", f"{PKG}/_params.py",
     "        return value.isoformat()",
     "        return value.strftime(\"%d/%m/%Y\")"),
    # Lists
    ("list-limit-unchecked", f"{PKG}/_params.py",
     "if len(encoded) > max_values:",
     "if False:"),
    ("list-wrong-separator", f"{PKG}/_params.py",
     "return \",\".join(encoded)",
     "return \";\".join(encoded)"),
    ("list-accepts-fractions", f"{PKG}/_params.py",
     "return v.is_integer() and v >= 0",
     "return True"),
    ("list-flag-ignored", f"{PKG}/_params.py",
     "if entry.get(\"multiple\") and len(values) > 1:",
     "if False:"),
    ("list-duplicates-kept", f"{PKG}/_params.py",
     "encoded = list(dict.fromkeys(",
     "encoded = list(("),
    # Parsing
    ("types-inferred-not-declared", f"{PKG}/_parse.py",
     "        dtype = fields.get(name, {}).get(\"dtype\")",
     "        dtype = None"),
    ("list-column-flattened", f"{PKG}/_parse.py",
     "        return series.astype(\"object\")",
     "        return series.astype(\"string\")"),
    ("bad-dates-hidden", f"{PKG}/_parse.py",
     "if parsed is None or bool((present & parsed.isna()).any()):",
     "if parsed is None:"),
    ("datetime-resolution-unpinned", f"{PKG}/_parse.py",
     "        return parsed.astype(\"datetime64[ns]\")",
     "        return parsed"),
    ("empty-result-loses-columns", f"{PKG}/_parse.py",
     "names = _row_names(rows) or list(fields)",
     "names = _row_names(rows)"),
    # Transport
    ("envelope-not-validated", f"{PKG}/_client.py",
     "    if missing:\n        raise ResponseError(",
     "    if False:\n        raise ResponseError("),
    ("422-retried", f"{PKG}/_client.py",
     "TRANSIENT = frozenset({429, 500, 502, 503, 504})",
     "TRANSIENT = frozenset({422, 429, 500, 502, 503, 504})"),
    ("http-errors-ignored", f"{PKG}/_client.py",
     "    if response.status_code < 400:\n        return",
     "    if True:\n        return"),
    ("url-length-unchecked", f"{PKG}/_client.py",
     "if len(prepared.url) > MAX_URL:",
     "if False:"),
    # Schema
    ("table-path-ignored", f"{PKG}/query.py",
     "return f\"{module}/{_schema.table_path(module, table)}\"",
     "return f\"{module}/{table}\""),
    ("unknown-table-accepted", f"{PKG}/_schema.py",
     "    if key not in tables:\n",
     "    if False:\n"),
    ("module-alias-ignored", f"{PKG}/_schema.py",
     "key = aliases[key] if key in aliases else key.replace(\"_\", \"\")",
     "key = key.replace(\"_\", \"\")"),
]


def run(mutant):
    name, rel, old, new = mutant
    work = tempfile.mkdtemp(prefix="mut-")
    copy = os.path.join(work, "transferegovpy")
    shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns(
        ".git", ".venv", "dist", "site", "__pycache__", ".pytest_cache", ".ruff_cache"))

    try:
        path = os.path.join(copy, rel)
        text = open(path, encoding="utf-8").read()

        occurrences = text.count(old)
        if occurrences != 1:
            return name, "BROKEN", f"anchor found {occurrences}x, expected 1"

        mutated = text.replace(old, new)
        if mutated == text:
            return name, "BROKEN", "replacement changed nothing"
        open(path, "w", encoding="utf-8").write(mutated)
        if open(path, encoding="utf-8").read() != mutated:
            return name, "BROKEN", "edit did not land on disk"

        env = {**os.environ, "PYTHONPATH": os.path.join(copy, "src")}
        env.pop("TRANSFEREGOVPY_LIVE_TESTS", None)

        where = subprocess.run(
            [sys.executable, "-c", "import transferegovpy; print(transferegovpy.__file__)"],
            cwd=copy, env=env, capture_output=True, text=True,
        ).stdout.strip()
        if not where.startswith(copy):
            return name, "BROKEN", f"suite would import {where or 'nothing'}"

        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider"],
                cwd=copy, env=env, capture_output=True, text=True, timeout=TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            return name, "KILLED", f"hung past {TIMEOUT}s"

        out = proc.stdout + proc.stderr
        if proc.returncode == 0:
            return name, "SURVIVED", "suite passed"
        failed = re.search(r"(\d+) (failed|error)", out)
        return name, "KILLED", f"{failed.group(0) if failed else 'suite failed'}"
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main():
    counts = {"KILLED": 0, "SURVIVED": 0, "BROKEN": 0}
    for mutant in MUTANTS:
        name, verdict, detail = run(mutant)
        counts[verdict] += 1
        print(f"{verdict:9s} {name:34s} {detail}", flush=True)

    print(f"\nkilled {counts['KILLED']}/{len(MUTANTS)}, "
          f"survived {counts['SURVIVED']}, broken {counts['BROKEN']}")
    sys.exit(1 if counts["SURVIVED"] or counts["BROKEN"] else 0)


if __name__ == "__main__":
    main()
