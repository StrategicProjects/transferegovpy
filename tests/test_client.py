"""The request builder and the error translation.

These services report a rejected query as a list of validation objects naming
the offending parameter, which is worth surfacing rather than reducing to a
status code.
"""

from __future__ import annotations

import datetime as dt

import pytest
import responses as responses_lib

import transferegovpy as tg
from transferegovpy import _client
from transferegovpy._errors import HTTPError, ResponseError, URLTooLongError

from .conftest import add_body, add_page, envelope, path_of


def test_the_base_url_is_the_public_api():
    assert _client.base_url() == "https://api-publica.transferegov.gestao.gov.br"
    assert _client.base_url("parcerias").startswith("https://api-publica.")


def test_configure_redirects_requests(mock):
    mock.add(
        responses_lib.GET,
        "https://example.org/parcerias/parceria",
        body=envelope("[]", total=0),
        content_type="application/json",
    )
    tg.configure(base_url="https://example.org")
    try:
        tg.get("parcerias", "parceria")
    finally:
        _client._config["base_url"] = None

    assert mock.calls[0].request.url.startswith("https://example.org/")


def test_base_url_argument_takes_precedence(mock):
    mock.add(
        responses_lib.GET,
        "https://elsewhere.test/parcerias/parceria",
        body=envelope("[]", total=0),
        content_type="application/json",
    )

    tg.get("parcerias", "parceria", base_url="https://elsewhere.test")

    assert mock.calls[0].request.url.startswith("https://elsewhere.test/")


def test_a_trailing_slash_does_not_double_up(mock):
    mock.add(
        responses_lib.GET,
        "https://example.org/parcerias/parceria",
        body=envelope("[]", total=0),
        content_type="application/json",
    )

    tg.get("parcerias", "parceria", base_url="https://example.org/")

    assert "org//" not in mock.calls[0].request.url


def test_the_request_carries_a_user_agent_naming_the_package(mock):
    add_page(mock, 1, total=1)

    tg.get("parcerias", "parceria", limit=1)

    assert "transferegovpy" in mock.calls[0].request.headers["User-Agent"]


# Errors ----------------------------------------------------------------------


def test_a_422_surfaces_the_parameter_the_service_objected_to(mock):
    add_body(
        mock,
        '{"detail":[{"type":"literal_error",'
        '"loc":["query","situacao_proposta"],'
        '"msg":"Input should be \'Aprovada\'"}]}',
        status=422,
        table="proposta",
    )

    with pytest.raises(HTTPError) as excinfo:
        tg.get("parcerias", "proposta")

    message = str(excinfo.value)
    assert "situacao_proposta: Input should be" in message
    assert "params()" in message
    assert excinfo.value.status == 422


def test_a_404_surfaces_its_plain_string_detail(mock):
    add_body(mock, '{"detail":"Not Found"}', status=404)

    with pytest.raises(HTTPError, match="Not Found"):
        tg.get("parcerias", "parceria")


def test_every_validation_error_is_reported_not_only_the_first(mock):
    add_body(
        mock,
        '{"detail":['
        '{"loc":["query","a"],"msg":"first problem"},'
        '{"loc":["query","b"],"msg":"second problem"}]}',
        status=422,
    )

    with pytest.raises(HTTPError) as excinfo:
        tg.get("parcerias", "parceria")

    assert "first problem" in str(excinfo.value)
    assert "second problem" in str(excinfo.value)


def test_an_error_body_that_is_not_json_still_reports_the_status(mock):
    add_body(mock, "<html>gateway</html>", status=502)

    with pytest.raises(HTTPError) as excinfo:
        tg.get("parcerias", "parceria")

    assert excinfo.value.status == 502


def test_a_body_that_is_not_json_at_all_is_reported_as_such(mock):
    add_body(mock, "not json")

    with pytest.raises(ResponseError, match="not valid JSON"):
        tg.get("parcerias", "parceria")


# Transient failures ----------------------------------------------------------


def test_only_the_statuses_worth_retrying_are_transient():
    assert 429 in _client.TRANSIENT
    assert 503 in _client.TRANSIENT
    # A 422 is the service rejecting the query itself; it will fail the same
    # way every time.
    assert 422 not in _client.TRANSIENT
    assert 404 not in _client.TRANSIENT


# URL length ------------------------------------------------------------------


def test_an_over_long_url_is_refused_with_a_readable_message(mock):
    # curl reports this as "Error in the HTTP2 framing layer", which says
    # nothing about the query that caused it.
    with pytest.raises(URLTooLongError):
        tg.get("parcerias", "proposta", ds_objeto="x" * _client.MAX_URL)

    assert len(mock.calls) == 0


# Freshness -------------------------------------------------------------------


def test_updated_at_parses_the_modules_timestamp(mock):
    add_body(
        mock,
        '{"data_ultima_atualizacao":"2026-08-03T00:00:00"}',
        table="data-atualizacao",
    )

    assert tg.updated_at("parcerias") == dt.datetime(2026, 8, 3)


def test_updated_at_asks_the_modules_own_endpoint(mock):
    add_body(
        mock,
        '{"data_ultima_atualizacao":"2026-08-03T00:00:00"}',
        table="data-atualizacao",
        module="fundoafundo",
    )

    tg.updated_at("fundo_a_fundo")

    assert path_of(mock.calls[0]) == "fundoafundo/data-atualizacao"


def test_a_response_without_the_timestamp_is_an_error(mock):
    add_body(mock, "{}", table="data-atualizacao")

    with pytest.raises(ResponseError, match="data_ultima_atualizacao"):
        tg.updated_at("parcerias")
