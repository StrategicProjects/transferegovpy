# Collecting large tables safely

```python
import math
import transferegovpy as tg
```

## The cap you cannot see

The service returns at most **1000 rows per request**, however many are asked
for, and it does so without complaint: ask for a hundred thousand and you are
given a thousand and a `206 Partial Content`. Nothing in the body says the
result was truncated. Only the `Content-Range` header does.

This package reads that header, which is why `limit` counts rows rather than
requests, and why anything above 1000 is collected page by page:

```python
plans = tg.get("ted", "plano_acao", limit=2500)

len(plans)
# 2500
tg.metadata(plans)["pages"]
# 3
```

`page_size` is capped at 1000 for the same reason. A larger value would be
accepted by the package, silently truncated by the service, and the shortfall
would look like missing data.

## Ask how big it is first

```python
tg.count("fundoafundo", "gestao_financeira_lancamentos")
# 1115444
```

To size everything at once, `tables()` takes a `counts` argument. It is the
only part of that function that touches the network — one request per table,
cached, so the second call in a session is free:

```python
tg.tables(counts=True).sort_values("rows", ascending=False).head()
```

| module | table | columns | rows |
|---|---|---:|---:|
| fundoafundo | gestao_financeira_lancamentos | 32 | 1115444 |
| fundoafundo | gestao_financeira_subtransacoes | 16 | 377666 |
| transferenciasespeciais | historico_pagamento_especial | 5 | 281163 |
| fundoafundo | plano_acao_historico | 5 | 183379 |
| transferenciasespeciais | meta_especial | 16 | 156016 |

A million rows is over a thousand requests. The package throttles itself to
sixty requests a minute by default, so that download takes something like
twenty minutes. That is usually the wrong shape for the question being asked.

## Narrow first, then collect

Two things make a large query smaller, and both happen on the server.

**Select only the columns you need.** `gestao_financeira_lancamentos` has 32
columns; if you want four of them, the other 28 need never cross the network.

```python
tg.get(
    "fundoafundo", "gestao_financeira_lancamentos",
    select=[
        "id_lancamento_gestao_financeira",
        "id_plano_acao",
        "data_lancamento_gestao_financeira",
        "valor_lancamento_gestao_financeira",
    ],
    limit=math.inf,
)
```

**Filter before you fetch.** A year's worth of a table is usually what was
wanted anyway:

```python
tg.count(
    "fundoafundo", "gestao_financeira_lancamentos",
    data_lancamento_gestao_financeira=[tg.gte("2025-01-01"), tg.lt("2026-01-01")],
)
```

## Why the order matters

Offset pagination asks for rows 0–999, then 1000–1999, and so on. In Postgres a
query without `ORDER BY` has **no defined row order**: the planner is free to
return rows differently between two executions, and if it does, page two can
repeat rows from page one and skip others entirely. The result has the right
number of rows and the wrong contents.

So every request this package makes carries an explicit order. By default it is
the table's primary key where the API declares one, and its identifier columns
otherwise:

```python
tg.metadata(plans)["order"]
# ['id_plano_acao.asc', 'id_programa.asc', 'sq_instrumento.asc']
```

You can supply your own, and pagination will use it:

```python
tg.get("ted", "plano_acao", order="vl_total_plano_acao.desc", limit=2500)
```

Bear in mind that ordering by a column with many ties leaves the order within
each tie undefined, which brings the problem back. Prefer an identifier, or add
one as a tiebreaker:

```python
tg.get(
    "ted", "plano_acao",
    order=["vl_total_plano_acao.desc", "id_plano_acao.asc"],
    limit=2500,
)
```

## Resuming, and taking it in pieces

`offset` skips rows that have already been collected, so a long download can be
taken in sittings:

```python
first = tg.get("ted", "plano_acao_etapa", limit=20000)
rest = tg.get("ted", "plano_acao_etapa", limit=math.inf, offset=20000)
```

Both parts must use the same order, or they are pages of two different
sequences. The default order is deterministic for a given table, so leaving
`order` alone is the safe choice here.

## Long `in_()` lists

A filter built with `in_()` over a few thousand identifiers produces a URL the
service cannot accept, and the failure it produces without this package is not
readable: curl reports `Error in the HTTP2 framing layer`, which says nothing
about the query. The package checks the length first:

```python
tg.get("ted", "plano_acao", id_plano_acao=tg.in_(range(3000)))
# URLTooLongError: The request URL is 20047 bytes, over the 7000 the service
# accepts. A filter built with in_() over a long sequence is the usual cause.
```

Take it in batches:

```python
import pandas as pd

def in_batches(module, table, column, values, size=300, **kwargs):
    values = list(values)
    parts = [
        tg.get(module, table, filters={column: tg.in_(values[i : i + size])},
               limit=math.inf, progress=False, **kwargs)
        for i in range(0, len(values), size)
    ]
    return pd.concat(parts, ignore_index=True)
```

## When the count and the contents disagree

The number of rows collected is checked against the total the API reported:

```
IncompleteResultWarning: Collected 4820 row(s) where the API reported 4900.
The table may have changed while it was being read; check metadata() on the
result.
```

This is a real possibility on a long download, since the underlying tables are
refreshed daily. It is a warning rather than an error because a nearly complete
result is still worth having — but it must be visible, and `metadata()` records
both numbers so the gap stays in the data rather than only in the console.

## Caching

Every request is cached for an hour, so re-running an analysis does not
re-fetch what it already has. Each page is cached separately, so an interrupted
collection resumes from the network only where it has to.

```python
tg.cache_dir()
# PosixPath('/tmp/transferegovpy-cache')
```

The default is the session's temporary directory, so nothing outlives the
session unless you ask for it:

```python
tg.cache_dir("~/.cache/transferegovpy")
```

Set `TRANSFEREGOVPY_CACHE_DIR` in your environment to make that permanent, and
adjust the lifetime with `tg.set_cache_ttl(86400)` — the data behind these APIs
is refreshed once a day, so an hour is conservative.

`tg.metadata(frame)["cached"]` tells you whether a result came from the network
or from disk.

## Rate limiting and retries

Requests are throttled to sixty a minute and retried up to four times on a 429
or a 5xx, with exponential backoff and jitter. A 400 is not retried: it means
the service rejected the query itself and will reject it identically next time.

Both are adjustable, but the defaults exist to keep the package a considerate
client of a public service:

```python
tg.configure(requests_per_minute=30, max_tries=6, timeout=120)
```
