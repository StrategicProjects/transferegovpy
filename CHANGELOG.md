# Changelog

## 0.2.0

The package now targets the public API host,
`api-publica.transferegov.gestao.gov.br`. That host serves a different kind of
service from the PostgREST one the package was built against, so this release
rewrites the client rather than extending it. Code written against 0.1.x will
need changing.

### What is covered

* **`parcerias` is new**: partnership management, 15 tables, including the
  partnerships and their proposals, budget commitments, payment orders and bank
  statements. It has no equivalent in the previous release.
* **`especiais` replaces `transferenciasespeciais`**, and grows from 14 tables
  to 20. The additions are the financial ones: transaction entries,
  sub-entries, account balances, beneficiaries, and three history tables.
* **`fundoafundo` stays**, at 20 tables against the previous 21, with several
  child tables folded into their parents as columns of lists.
* `"transferenciasespeciais"` still resolves, as an alias for `"especiais"`.
* **`ted` is gone.** Decentralized credit has not been published on the public
  API host; it exists only on the older service, which the government is
  decommissioning on 2026-08-31. `ted()` and `transferencias_especiais()` are
  removed, and `parcerias()` and `especiais()` take their place alongside
  `fundo_a_fundo()`.

55 tables and 811 columns in all, against 48 and 599 — the same totals the R
sibling freezes from the same documents.

### Filters

* Filters are now the endpoints' own typed query parameters rather than
  PostgREST operators. `params()` lists what each table accepts, with the
  permitted values of the enumerated ones.
* **The comparison operators are removed** — `eq()`, `neq()`, `gt()`, `gte()`,
  `lt()`, `lte()`, `like()`, `ilike()`, `re_match()`, `re_imatch()`, `in_()`,
  `is_null()`, `is_true()`, `is_false()`, `not_()`, `operators()` and the
  `Filter` class. These services compare for equality and nothing else.
* **An unknown parameter name is an error.** These services ignore a parameter
  they do not recognise and answer `200` with the whole table, so a typo would
  return a plausible, unfiltered result. Names are checked against the frozen
  schema before the request is made, and a near miss is suggested.
* Enumerated values are checked client-side too, so a bad value fails before
  the round trip rather than as a 422 after it.
* A filter given several values is refused. The service keeps the last
  occurrence of a repeated parameter and discards the rest without reporting
  it, so there is no way to express it.

### Pagination

* Pagination is by page number, and the cap is 200 rows per request rather than
  1000. `limit` and `offset` still count rows, including when the offset falls
  inside a page.
* **`order` and `select` are removed.** These APIs publish no ordering or
  column-selection parameter.
* Row order is therefore the server's. It was verified rather than assumed:
  the same rows come back in the same sequence across page sizes, across
  repeated calls, 100,000 rows deep, on tables with no key, and on tables with
  nested columns.

### Other changes

* `updated_at()` reports when a module's data was last loaded, from the
  `/data-atualizacao` endpoint each module publishes. It is the only freshness
  signal these APIs give.
* `fields()` gains a `nested` argument, describing the columns of the objects
  inside a column of lists. 18 columns across `fundoafundo` and `parcerias`
  arrive that way because the API folds a child table into its parent.
* `fields()` reports `api_type` rather than `pg_type`, and no longer reports a
  primary key: these documents declare none.
* `tables()` gains `path`, the endpoint a table maps to, and `params`, how many
  filters it accepts. A table may be named with either a hyphen or an
  underscore.
* `get()` and `count()` take `use_cache=` where they took `cache=`.
* A number the API declares but cannot deliver is now reported rather than
  silently emptied. `codigo_conta_beneficiario_subtransacao_gestao_financeira`
  is declared an integer and arrives as `"***"`, a masked account number; the
  column is kept as text with a `ColumnTypeWarning` instead of coming back all
  null.
* HTTP errors surface the validation detail the service reports, naming the
  parameter it objected to.

## 0.1.1

* The PyPI project page showed the full text of the MIT license where the
  license name belongs, because the metadata pointed at the file rather than
  naming the license. `pyproject.toml` now declares the SPDX expression
  (PEP 639), so the page reads "MIT".
* Recorded the Zenodo DOI: 10.5281/zenodo.21729827 for the project, with a
  DOI of its own for each version.

## 0.1.0

First release.

* Covers the three TransfereGov open data APIs — special transfers
  (`transferenciasespeciais`), fund-to-fund transfers (`fundoafundo`) and
  decentralized credit (`ted`) — and the forty-eight tables they publish.
* `get()` and `count()` query any table; `ted()`, `fundo_a_fundo()` and
  `transferencias_especiais()` fix the module.
* Filters are keyword arguments named after the columns they apply to. A bare
  value means "equals", a bare list means "is one of", and `operators()` lists
  the fifteen comparison operators the services accept. A column whose name
  collides with one of the keyword arguments goes through `filters=`.
* Values carrying commas, parentheses or surrounding spaces are quoted, and
  numbers are never sent in scientific notation, so a filter matches what it
  reads as.
* `modules()`, `tables()` and `fields()` describe the APIs offline, from a copy
  of their OpenAPI documents frozen into the package and rebuilt by
  `scripts/build_schema.py`. `tables(counts=True)` adds current row counts.
* Columns are typed from that schema rather than inferred, so a column that is
  entirely null on one page keeps its dtype on the next, and an empty result
  still carries the table's full set of columns. Identifiers declared as
  `bigint` come back as pandas' nullable `Int64`, which holds the full 64-bit
  range.
* Pagination collects as many rows as `limit` asks for, in pages of at most
  1000 — the service's own cap, which it applies silently. Every request
  carries an explicit order, so pages cannot overlap or skip rows, and the
  number collected is checked against the total the API reports.
* `metadata()` records the total the API reported, the rows and pages
  retrieved, the order and selection used, and whether the result was cached.
* Requests are throttled to sixty a minute and retried with exponential backoff
  on 429 and 5xx responses. A 400 is not retried, and its PostgREST error body
  is surfaced with the offending column named.
* A request whose URL grows past what the service accepts fails with a message
  naming the cause — a filter built with `in_()` over a long sequence.
* Responses are cached for an hour, by default in the session's temporary
  directory. `cache_dir()` switches to a persistent location and
  `cache_clear()` empties it.
