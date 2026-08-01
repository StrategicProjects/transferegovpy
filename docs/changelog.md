# Changelog

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
