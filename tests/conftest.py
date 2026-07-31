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

BASE = "https://api.transferegov.gestao.gov.br"


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


def page(n, start=1, total=None, first=None):
    """One page of ``ted/plano_acao`` rows, with identifiers from ``start``."""
    rows = [
        {
            "id_plano_acao": start + i,
            "aa_ano_plano_acao": 2024,
            "vl_total_plano_acao": (start + i) * 10.5,
            "dt_inicio_vigencia": f"2024-01-0{(i % 9) + 1}",
            "in_forma_execucao_direta": True,
            "tx_objeto_plano_acao": f"row {start + i}",
        }
        for i in range(n)
    ]

    first = start - 1 if first is None else first
    if total is None:
        content_range = f"{first}-{first + n - 1}/*"
    else:
        content_range = f"{first}-{first + n - 1}/{total}"

    return json.dumps(rows), content_range


def add_page(mock, n, start=1, total=None, first=None, table="plano_acao", module="ted"):
    body, content_range = page(n, start, total, first)
    mock.add(
        responses_lib.GET,
        f"{BASE}/{module}/{table}",
        body=body,
        status=200,
        content_type="application/json",
        headers={"Content-Range": content_range},
    )


def add_body(mock, body, status=200, content_range=None, table="plano_acao", module="ted"):
    headers = {"Content-Range": content_range} if content_range else {}
    mock.add(
        responses_lib.GET,
        f"{BASE}/{module}/{table}",
        body=body,
        status=status,
        content_type="application/json",
        headers=headers,
    )


def query_of(call):
    """The query string of a recorded request, as a list of pairs.

    A list rather than a dict because two conditions on one column are two
    parameters with the same name.
    """
    from urllib.parse import parse_qsl, urlsplit

    return parse_qsl(urlsplit(call.request.url).query, keep_blank_values=True)
