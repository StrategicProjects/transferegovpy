# Collecting large tables safely

These tables are large and the page size is small. This page is about getting
all of a table without losing rows to pagination, and about knowing what a
download will cost before starting it.

```python
import math
import transferegovpy as tg
```

## Measure first

The fifty-five tables hold about 6.9 million rows between them, spread very
unevenly — from 15 rows in `especiais/programas_especiais` to over a million in
`fundoafundo/gestao_financeira_lancamentos`.

```python
sizes = tg.tables(counts=True)
sizes.sort_values("rows", ascending=False).head()
```

That call makes fifty-five requests, and caches them. For a single table:

```python
tg.count("fundoafundo", "gestao_financeira_lancamentos")
#> 1121046
```

`count()` takes the same filters as `get()`, so you can size the thing you
actually want rather than the whole table:

```python
tg.count("parcerias", "proposta", sg_uf_recebedor="PE")
```

## What a page costs

The services cap a page at **200 rows**. Unlike some APIs, they do not silently
truncate a larger request — asking for 201 is a `422`, and the package refuses
it before sending:

```python
tg.get("parcerias", "proposta", page_size=201)
#> ValueError: page_size must be a whole number between 1 and 200.
```

So the arithmetic is simple and worth doing. A million-row table is
`ceil(1121046 / 200)` = **5,606 requests**. At the default throttle of sixty a
minute, that is over an hour and a half.

```python
rows = tg.count("fundoafundo", "gestao_financeira_lancamentos")
math.ceil(rows / 200)
#> 5606
```

If you genuinely need a table that size, consider whether a filter narrows it
first, and raise the throttle deliberately rather than by accident:

```python
tg.configure(requests_per_minute=120)
```

## Limits and offsets count rows

`limit` and `offset` are in rows, not pages, whatever `page_size` is set to.

```python
tg.get("especiais", "meta_especiais", limit=450)
```

That is three requests: 200, 200, 50 — the last page is trimmed to the limit.
An offset that falls inside a page is handled by fetching the page it lands in
and dropping the rows before it:

```python
tg.get("especiais", "meta_especiais", limit=100, offset=137, page_size=60)
```

`math.inf` collects everything that matches:

```python
tg.get("especiais", "programas_especiais", limit=math.inf)
```

## Checking what you got

Every result carries the pagination state the API reported:

```python
metas = tg.get("especiais", "meta_especiais", limit=450)

tg.metadata(metas)
#> {'module': 'especiais', 'table': 'meta_especiais', 'total_rows': 156060.0,
#>  'rows_returned': 450, 'pages': 3, ...}
```

`total_rows` is how many rows matched, `rows_returned` how many you have. If
collection ends short of what the API said it would return, that is an
`IncompleteResultWarning` rather than a silent truncation.

## Why the row order is safe to rely on

These APIs publish no ordering parameter. Page two is simply "page two", and
whether that is a well-defined thing depends on the server keeping a stable
order between requests — which nothing in the documentation promises.

Postgres makes no such promise in general: a query without `ORDER BY` may
return rows in a different order between executions, and under page-based
pagination that means page two can repeat rows from page one and skip others
entirely. A row count would not reveal it. Two pages of 200 that overlap by 40
rows still add up to 400.

So it was tested rather than assumed. The check is to fetch the same rows at
two different page sizes and compare them as sequences:

```python
def strip(frame):
    out = frame.reset_index(drop=True).copy()
    out.attrs = {}
    return out

big = tg.get("especiais", "meta_especiais", limit=450, page_size=200)
small = tg.get("especiais", "meta_especiais", limit=450, page_size=50)

strip(big).equals(strip(small))
#> True
```

Three requests and nine requests, cutting the same 450 rows at different
boundaries, produce the same rows in the same order. That is what rules out
both overlap and skipping.

The same comparison holds 100,000 rows deep, across repeated calls, on tables
with no natural key, and on tables with nested columns. `tests/test_live.py`
re-runs all of it against the real services, so a change upstream shows up as a
failing test rather than as quietly wrong data.

## Caching

Responses are cached for an hour, so re-running a collection during a session
costs nothing:

```python
first = tg.get("especiais", "meta_especiais", limit=450)
again = tg.get("especiais", "meta_especiais", limit=450)

tg.metadata(again)["cached"]
#> True
```

The default cache lives in a temporary directory, so nothing is written outside
the session unless you ask. For a long collection you will want it to survive:

```python
tg.cache_dir("~/.cache/transferegovpy")
```

The APIs send no `ETag`, `Cache-Control` or `Last-Modified`, so HTTP caching
would store nothing — this cache is the package's own. Use `updated_at()` to
decide when a cached copy is stale.

## A pattern for very large tables

For anything in the hundreds of thousands, collect in slices and write each one
out, so an interrupted run does not start over:

```python
import pathlib

total = tg.count("fundoafundo", "gestao_financeira_lancamentos")
slice_size = 20_000

for start in range(0, total, slice_size):
    path = pathlib.Path(f"lancamentos-{start:08d}.parquet")
    if path.exists():
        continue

    rows = tg.get(
        "fundoafundo", "gestao_financeira_lancamentos",
        limit=slice_size, offset=start,
    )
    rows.to_parquet(path)
```

Because the order is stable, the slices reassemble into the whole table without
gaps or repeats.
