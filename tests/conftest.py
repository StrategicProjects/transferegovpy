"""Shared fixtures.

Responses are built from literal JSON rather than from a Python dict wherever
nulls matter: a dict round-tripped through ``json.dumps`` can express ``null``,
but writing the JSON out keeps the tests honest about what the API sends.
"""

from __future__ import annotations

import json

import pytest
import responses as responses_lib

import transferegovpy as tg
from transferegovpy import _cache

BASE = "https://api-publica.transferegov.gestao.gov.br"


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    """Every test starts with a cold cache and no throttling."""
    monkeypatch.delenv("TRANSFEREGOVPY_CACHE_DIR", raising=False)
    _cache._state.update({"dir": tmp_path / "cache", "enabled": False, "ttl": 3600.0})
    tg.configure(requests_per_minute=0, max_tries=1, validate=True, timeout=5)
    yield
    tg.configure(requests_per_minute=60, max_tries=4, validate=True, timeout=60)


@pytest.fixture
def mock():
    with responses_lib.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        yield rsps


def envelope(data, total=0, page=1, page_size=200, pages=None):
    """The paginated envelope, around ``data`` given as literal JSON."""
    if pages is None:
        pages = -(-total // max(page_size, 1))
    return (
        f'{{"data":{data},"total_pages":{pages},"total_items":{total},'
        f'"page_number":{page},"page_size":{page_size}}}'
    )


def page_body(n, start=1, total=None, page=1, page_size=200):
    """One page of ``parcerias/parceria`` rows, with ids from ``start``."""
    rows = [
        {
            "id_parceria": start + i,
            # Beyond 2**31 on purpose: cd_parceria genuinely is.
            "cd_parceria": 202500000000 + start + i,
            "id_proposta": start + i,
            "in_situacao_parceria": "Aprovada",
            "dh_assinatura": f"2025-01-0{(i % 9) + 1}T12:00:00",
            "tx_justificativa": None,
            "publicacoes_parceria": [],
        }
        for i in range(n)
    ]
    return envelope(
        json.dumps(rows),
        total=n if total is None else total,
        page=page,
        page_size=page_size,
    )


def add_page(mock, n, start=1, total=None, page=1, page_size=200,
             table="parceria", module="parcerias"):
    add_body(
        mock,
        page_body(n, start, total, page, page_size),
        table=table,
        module=module,
    )


def add_body(mock, body, status=200, table="parceria", module="parcerias"):
    mock.add(
        responses_lib.GET,
        f"{BASE}/{module}/{table}",
        body=body,
        status=status,
        content_type="application/json",
    )


def query_of(call):
    """The query string of a recorded request, as a list of pairs."""
    from urllib.parse import parse_qsl, urlsplit

    return parse_qsl(urlsplit(call.request.url).query, keep_blank_values=True)


def path_of(call):
    """The path of a recorded request, without the leading slash."""
    from urllib.parse import urlsplit

    return urlsplit(call.request.url).path.lstrip("/")
