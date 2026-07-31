"""Access the 'TransfereGov' open data APIs from Python.

TransfereGov is the Brazilian federal government's platform for transfers to
states, municipalities and civil society. It publishes three APIs — special
transfers, fund-to-fund transfers, and decentralized credit (TED) — covering
forty-eight tables between them.

All three are `PostgREST <https://postgrest.org>`_ services, so this package
exposes their filtering, column selection and ordering directly rather than
wrapping each table in a function of its own::

    import transferegovpy as tg

    tg.modules()
    tg.tables("ted")
    tg.fields("ted", "plano_acao")

    tg.get("ted", "plano_acao", aa_ano_plano_acao=tg.gte(2024), limit=50)

Table names, column names and categorical values are in Portuguese because
they belong to the API.
"""

from __future__ import annotations

__version__ = "0.1.0"

from ._cache import cache_clear, cache_dir
from ._cache import enabled as cache_enabled
from ._cache import set_enabled as set_cache
from ._cache import set_ttl as set_cache_ttl
from ._cache import ttl as cache_ttl
from ._client import configure
from ._errors import (
    ColumnTypeWarning,
    FilterError,
    HTTPError,
    IncompleteResultWarning,
    ResponseError,
    SchemaError,
    TransferegovError,
    URLTooLongError,
)
from .filters import (
    Filter,
    eq,
    gt,
    gte,
    ilike,
    in_,
    is_false,
    is_null,
    is_true,
    like,
    lt,
    lte,
    neq,
    not_,
    operators,
    re_imatch,
    re_match,
)
from .metadata import fields, modules, schema_date, tables
from .query import (
    MAX_PAGE,
    count,
    fundo_a_fundo,
    get,
    metadata,
    ted,
    transferencias_especiais,
)

__all__ = [
    "__version__",
    # queries
    "get",
    "count",
    "ted",
    "fundo_a_fundo",
    "transferencias_especiais",
    "metadata",
    "MAX_PAGE",
    # discovery
    "modules",
    "tables",
    "fields",
    "schema_date",
    # filters
    "Filter",
    "eq",
    "neq",
    "gt",
    "gte",
    "lt",
    "lte",
    "like",
    "ilike",
    "re_match",
    "re_imatch",
    "in_",
    "is_null",
    "is_true",
    "is_false",
    "not_",
    "operators",
    # configuration
    "configure",
    "cache_dir",
    "cache_clear",
    "cache_enabled",
    "cache_ttl",
    "set_cache",
    "set_cache_ttl",
    # errors
    "TransferegovError",
    "SchemaError",
    "FilterError",
    "URLTooLongError",
    "ResponseError",
    "HTTPError",
    "IncompleteResultWarning",
    "ColumnTypeWarning",
]
