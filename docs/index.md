# transferegovpy

[![PyPI](https://img.shields.io/pypi/v/transferegovpy.svg)](https://pypi.org/project/transferegovpy/)
[![Python](https://img.shields.io/pypi/pyversions/transferegovpy.svg)](https://pypi.org/project/transferegovpy/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

Access the open data APIs of **TransfereGov**, the Brazilian federal
government's platform for transfers to states, municipalities and civil
society, from Python.

The platform publishes three APIs, covering **48 tables** in all:

| Module | Covers | Tables |
|---|---|---|
| `transferenciasespeciais` | Special transfers, created by Constitutional Amendment 105/2019 for individual parliamentary amendments | 14 |
| `fundoafundo` | Fund-to-fund transfers, from federal funds directly to state, district and municipal funds | 21 |
| `ted` | Decentralized credit between federal bodies (*termo de execução descentralizada*) | 13 |

All three are [PostgREST](https://postgrest.org) services, so this package
exposes their filtering, column selection and ordering directly, rather than
wrapping each table in a function of its own.

This is the Python sibling of
[transferegovr](https://strategicprojects.github.io/transferegovr/); the two
cover the same ground with the same semantics.

## Installation

```bash
pip install transferegovpy
```

A progress bar during long collections needs one extra:

```bash
pip install "transferegovpy[progress]"
```

## Getting started

```python
import transferegovpy as tg

tg.modules()
tg.tables("ted")
tg.fields("ted", "plano_acao")
```

`get()` retrieves rows. Name each filter after the column it applies to:

```python
tg.get("ted", "plano_acao", aa_ano_plano_acao=2024)
```

A bare value means "equals", a bare list means "is one of", and the operators
from `tg.operators()` cover the rest:

```python
tg.get(
    "ted", "plano_acao",
    aa_ano_plano_acao=tg.gte(2024),
    sigla_unidade_descentralizada=["CNPq", "CAPES"],
    tx_objeto_plano_acao=tg.ilike("*pesquisa*"),
    select=["id_plano_acao", "vl_total_plano_acao", "dt_inicio_vigencia"],
    order="vl_total_plano_acao.desc",
    limit=20,
)
```

Several conditions on one column go in a list, and the API combines them with
AND:

```python
tg.get(
    "fundoafundo", "plano_acao",
    data_inicio_vigencia_plano_acao=[tg.gte("2024-01-01"), tg.lt("2025-01-01")],
)
```

If a column name ever collides with one of the keyword arguments, pass it
through `filters=`:

```python
tg.get("ted", "plano_acao", filters={"select": "something"})
```

## Size first, download second

The service returns at most 1000 rows per request, and these tables are not
small — the largest holds over a million rows, which is more than a thousand
requests. Ask before you fetch:

```python
tg.count("fundoafundo", "gestao_financeira_lancamentos")
# 1115444
```

To size everything at once:

```python
tg.tables(counts=True).sort_values("rows", ascending=False)
```

`limit` counts rows, not pages. Anything above 1000 is collected page by page,
in an explicit order so that pages cannot overlap or skip rows, and the total
collected is checked against what the API reported:

```python
import math

plans = tg.get("ted", "plano_acao", limit=math.inf)

tg.metadata(plans)["total_rows"]
tg.metadata(plans)["pages"]
```

## Types

Columns are typed from the API's own schema rather than inferred, so a column
that happens to be entirely null on one page does not change dtype on the next:

```python
plans = tg.get("ted", "plano_acao", limit=5)

plans.dtypes["dt_inicio_vigencia"]   # datetime64[ns]
plans.dtypes["in_forma_execucao_direta"]  # boolean
plans.dtypes["id_plano_acao"]        # Int64
```

Identifiers declared as `bigint` come back as pandas' nullable `Int64`, which
holds the full 64-bit range — the R sibling has to use a float for these,
because R has no nullable integer that wide.

## Caching

Responses are cached for an hour in the session's temporary directory, so
nothing is written outside the session unless you ask for it. To keep them
between sessions:

```python
tg.cache_dir("~/.cache/transferegovpy")
```

or set `TRANSFEREGOVPY_CACHE_DIR` in your environment. `tg.cache_clear()`
empties it.

## Two things that bite

* **The 1000-row cap is silent.** Ask for more and the service returns 1000
  rows with a `206`, and nothing in the body says the result was cut short.
  Only `Content-Range` does. `limit` counts rows and is met by fetching pages.
* **Offset pagination needs an order.** A Postgres query without `ORDER BY` has
  no defined row order, so page two can repeat page one and skip rows
  elsewhere. Every request this package sends carries an explicit order, and
  the rows collected are checked against the total the API reported.

## Configuration

```python
tg.configure(
    requests_per_minute=30,   # default 60
    max_tries=6,              # default 4
    timeout=120,              # seconds, default 60
    validate=False,           # accept columns the packaged schema does not know
)
```

## Column names are in Portuguese

Table names, column names and categorical values belong to the API and are left
as the government publishes them. The package's own functions, arguments and
documentation are in English.

## Related

* [transferegovr](https://strategicprojects.github.io/transferegovr/) — the
  same APIs from R.
* [obrasgovr](https://github.com/StrategicProjects/obrasgovr) — the ObrasGov
  public works API, which carries the coordinates TransfereGov does not.

## Official documentation

* <https://docs.api.transferegov.gestao.gov.br/transferenciasespeciais/>
* <https://docs.api.transferegov.gestao.gov.br/fundoafundo/>
* <https://docs.api.transferegov.gestao.gov.br/ted/>

## Releasing

Publication uses [Trusted Publishing](https://docs.pypi.org/trusted-publishers/),
so no API token is stored anywhere. Register the publisher once on PyPI, under
*Your projects → transferegovpy → Publishing*, or as a pending publisher before
the first upload:

| Field | Value |
|---|---|
| PyPI Project Name | `transferegovpy` |
| Owner | `StrategicProjects` |
| Repository name | `transferegovpy` |
| Workflow name | `publish.yaml` |
| Environment name | `pypi` |

The same on [test.pypi.org](https://test.pypi.org), which is a separate service
with its own account and its own publisher registration. The environment name
is arbitrary and only has to match the workflow, so `pypi` works there too.

Then:

```bash
# a dry run to TestPyPI
gh workflow run publish.yaml -f target=testpypi

# the real thing
gh release create v0.1.0 --title "transferegovpy 0.1.0" --notes-file CHANGELOG.md
```

## License

MIT
