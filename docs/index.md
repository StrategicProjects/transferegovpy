# transferegovpy

[![PyPI](https://img.shields.io/pypi/v/transferegovpy.svg)](https://pypi.org/project/transferegovpy/)
[![Python](https://img.shields.io/pypi/pyversions/transferegovpy.svg)](https://pypi.org/project/transferegovpy/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.21729827.svg)](https://doi.org/10.5281/zenodo.21729827)

Access the open data APIs of **TransfereGov**, the Brazilian federal
government's platform for transfers to states, municipalities and civil
society, from Python.

## What this package covers

The package targets the public API host,
`api-publica.transferegov.gestao.gov.br`, which publishes four modules and
**74 tables** in all:

| Module | Covers | Tables |
|---|---|---|
| `especiais` | Special transfers, created by Constitutional Amendment 105/2019 for individual parliamentary amendments | 23 |
| `fundoafundo` | Fund-to-fund transfers, from federal funds directly to state, district and municipal funds | 20 |
| `parcerias` | Partnership management: programs, proposals, partnerships, their financial execution and bank statements | 17 |
| `ted` | Decentralized credit between federal bodies (*termo de execução descentralizada*): programs, action plans, credit notes and financial programming | 14 |

Every table in the published data models is reachable. Where the API folds a
child table into its parent rather than giving it an endpoint of its own, it
arrives as a column of lists — 5 of them in `fundoafundo`, 13 in `parcerias`,
4 in `ted` — and `fields(nested=...)` describes what is inside.

This is the Python sibling of
[transferegovr](https://strategicprojects.github.io/transferegovr/); the two
cover the same ground with the same semantics.

### What it does not cover

* **The older PostgREST endpoints** at `api.transferegov.gestao.gov.br`, which
  version 0.1.x of this package used. The government announced their
  retirement for 2026-08-31.
* **The Discricionárias e Legais module (SICONV)**, which has no API: it is
  published as CSV archives at
  <https://api-publica.transferegov.gestao.gov.br/downloads>. The government
  has announced APIs for it in four stages between July 2026 and October 2027.

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
tg.tables("parcerias")
tg.fields("parcerias", "proposta")
tg.params("parcerias", "proposta")
```

`get()` retrieves rows. Each filter is named after one of the endpoint's own
query parameters, and parameters combine with AND:

```python
tg.get(
    "parcerias", "proposta",
    sg_uf_recebedor="PE",
    situacao_proposta="Aprovada",
    limit=20,
)
```

That is almost the whole filtering vocabulary. These services compare for
equality — no greater-than, no pattern match — and publish no ordering or
column-selection parameter. The one extension is on identifiers: 113 of them
take several values and match any, which `params()` marks as `multiple`:

```python
tg.get("ted", "planos_acao_metas", id_plano_acao=[3, 4])
```

`params()` lists what each table accepts, including the permitted values of the
enumerated parameters.

## A typo must not look like an answer

These services **ignore a query parameter they do not recognise** and answer
`200` with the whole table. Misspell `situacao_proposta` and you get every
proposal where the filter would have given the approved ones — a plausible
number, quietly wrong.

So every parameter name is checked against the packaged schema before a request
goes out:

```python
tg.count("parcerias", "proposta", in_situacao_proposta="Aprovada")
#> FilterError: Unknown filter(s): 'in_situacao_proposta'. The API ignores a
#> parameter it does not recognise and returns every row, so this would look
#> like a query that matched nothing in particular. Did you mean
#> 'situacao_proposta'? ...
```

Enumerated values are checked the same way, before the round trip rather than
after it.

## Size first, download second

Each request returns one page — at most 200 rows in `especiais` and
`parcerias`, 1000 in `fundoafundo` and `ted` — and these tables are not small.
Ask before you fetch:

```python
tg.count("especiais", "meta_especiais")
#> 156193
```

`limit` counts rows, not pages. Anything above one page is collected page by
page, and the total collected is checked against what the API reported:

```python
import math

metas = tg.get("especiais", "meta_especiais", limit=math.inf)

tg.metadata(metas)["total_rows"]
tg.metadata(metas)["pages"]
```

## Types

Columns are typed from the API's own schema rather than guessed, so a column
that happens to be entirely null on one page does not change dtype on the next:

```python
proposals = tg.get("parcerias", "proposta", limit=5)

proposals.dtypes["dt_proposta"]
#> dtype('<M8[ns]')
proposals.dtypes["id_proposta"]
#> Int64Dtype()
```

Identifiers are a nullable 64-bit integer. This is the one deliberate
divergence from the R sibling, which returns them as double: pandas' `Int64`
holds the full range *and* a missing value, so there is nothing to trade away.
`cd_parceria` reaches 202500037062.

## Freshness and caching

Each module reports when it was last loaded, which is the only freshness signal
these APIs give — they send no `ETag`, `Cache-Control` or `Last-Modified`:

```python
tg.updated_at("parcerias")
#> datetime.datetime(2026, 9, 28, 0, 0)
```

Responses are cached for an hour in a temporary directory, so nothing is
written outside the session unless you ask for it:

```python
tg.cache_dir("~/.cache/transferegovpy")
```

or set `TRANSFEREGOVPY_CACHE_DIR` in the environment. `cache_clear()` empties
it.

## Column names are in Portuguese

Table names, column names, parameter names and categorical values belong to the
API and are left as the government publishes them. The package's own functions
and documentation are in English.

## Official documentation

* <https://api-publica.transferegov.gestao.gov.br/especiais/docs>
* <https://api-publica.transferegov.gestao.gov.br/fundoafundo/docs>
* <https://api-publica.transferegov.gestao.gov.br/parcerias/docs>
* <https://api-publica.transferegov.gestao.gov.br/ted/docs>
