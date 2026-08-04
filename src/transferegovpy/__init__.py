"""Access the 'TransfereGov' open data APIs from Python.

TransfereGov is the Brazilian federal government's platform for transfers to
states, municipalities and civil society. This package covers the three modules
published at ``api-publica.transferegov.gestao.gov.br`` — special transfers,
fund-to-fund transfers and partnership management — fifty-five tables between
them::

    import transferegovpy as tg

    tg.modules()
    tg.tables("parcerias")
    tg.fields("parcerias", "proposta")
    tg.params("parcerias", "proposta")

    tg.get("parcerias", "proposta", sg_uf_recebedor="PE", limit=50)

Filters are the endpoints' own query parameters, combined with AND. The
services compare for equality and nothing else, and they publish no ordering or
column-selection parameter.

A parameter name the packaged schema does not know is an error rather than a
request: these services ignore an unrecognised parameter and answer 200 with
the whole table, so an unchecked typo would return plausible, wrong data.

Table names, column names, parameter names and categorical values are in
Portuguese because they belong to the API.
"""

from __future__ import annotations

__version__ = "0.2.0"

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
from ._params import params
from .metadata import fields, modules, schema_date, tables
from .query import (
    MAX_PAGE,
    count,
    especiais,
    fundo_a_fundo,
    get,
    metadata,
    parcerias,
    updated_at,
)

__all__ = [
    "__version__",
    # queries
    "get",
    "count",
    "updated_at",
    "especiais",
    "fundo_a_fundo",
    "parcerias",
    "metadata",
    "MAX_PAGE",
    # discovery
    "modules",
    "tables",
    "fields",
    "params",
    "schema_date",
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
