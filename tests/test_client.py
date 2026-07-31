import pytest

import transferegovpy as tg
from transferegovpy import _client

from .conftest import add_body, add_page, query_of


def test_the_request_targets_the_module_and_table(mock):
    add_page(mock, 1, total=1)

    tg.get("ted", "plano_acao", limit=1)

    assert mock.calls[0].request.url.startswith(
        "https://api.transferegov.gestao.gov.br/ted/plano_acao?"
    )


def test_the_first_request_asks_for_an_exact_count(mock):
    # Without `Prefer: count=exact` the service reports the total as "*" and
    # multi-page collection has nothing to bound itself with.
    add_page(mock, 1, total=1)

    tg.get("ted", "plano_acao", limit=1)

    assert mock.calls[0].request.headers["Prefer"] == "count=exact"


def test_filters_select_and_order_reach_the_query_string(mock):
    add_page(mock, 1, total=1)

    tg.get(
        "ted",
        "plano_acao",
        aa_ano_plano_acao=tg.gte(2024),
        select=["id_plano_acao", "aa_ano_plano_acao"],
        order="id_plano_acao.desc",
        limit=1,
    )

    query = dict(query_of(mock.calls[0]))
    assert query["aa_ano_plano_acao"] == "gte.2024"
    assert query["select"] == "id_plano_acao,aa_ano_plano_acao"
    assert query["order"] == "id_plano_acao.desc"


def test_two_conditions_on_one_column_become_two_parameters(mock):
    add_page(mock, 1, total=1)

    tg.get(
        "ted",
        "plano_acao",
        dt_inicio_vigencia=[tg.gte("2024-01-01"), tg.lt("2025-01-01")],
        limit=1,
    )

    pairs = [p for p in query_of(mock.calls[0]) if p[0] == "dt_inicio_vigencia"]
    assert sorted(v for _, v in pairs) == ["gte.2024-01-01", "lt.2025-01-01"]


def test_an_order_is_always_sent(mock):
    # Offset pagination over an unordered query has no defined order in
    # Postgres and could repeat or skip rows across page boundaries.
    add_page(mock, 1, total=1)

    tg.get("ted", "plano_acao", limit=1)

    assert "order" in dict(query_of(mock.calls[0]))


def test_params_reach_the_query_verbatim(mock):
    add_page(mock, 1, total=1)

    tg.get(
        "ted",
        "plano_acao",
        params={"or": "(aa_ano_plano_acao.eq.2024,aa_ano_plano_acao.eq.2025)"},
        limit=1,
    )

    query = dict(query_of(mock.calls[0]))
    assert query["or"] == "(aa_ano_plano_acao.eq.2024,aa_ano_plano_acao.eq.2025)"


def test_params_cannot_hijack_pagination():
    with pytest.raises(ValueError, match="limit"):
        tg.get("ted", "plano_acao", params={"limit": 5})
    with pytest.raises(ValueError, match="offset"):
        tg.get("ted", "plano_acao", params={"offset": 5})


def test_a_column_named_like_an_argument_goes_through_filters(mock):
    # `select` is a keyword argument here, so a column of that name could not
    # be filtered on without the explicit mapping.
    add_page(mock, 1, total=1)
    tg.configure(validate=False)

    tg.get("ted", "plano_acao", filters={"select": tg.eq("x")}, limit=1)

    pairs = [p for p in query_of(mock.calls[0]) if p[0] == "select"]
    assert ("select", "eq.x") in pairs


def test_a_postgrest_error_body_is_surfaced(mock):
    add_body(
        mock,
        '{"code":"42703","details":null,"hint":null,'
        '"message":"column plano_acao.x does not exist"}',
        status=400,
    )

    with pytest.raises(tg.HTTPError, match="does not exist") as caught:
        tg.get("ted", "plano_acao", limit=1)

    assert caught.value.status == 400
    assert caught.value.detail["code"] == "42703"


def test_hint_and_details_are_shown_when_present(mock):
    add_body(
        mock,
        '{"code":"PGRST100","details":"unexpected end of input",'
        '"hint":"try again","message":"parse error"}',
        status=400,
    )

    with pytest.raises(tg.HTTPError, match="unexpected end of input"):
        tg.get("ted", "plano_acao", limit=1)


def test_an_error_body_that_is_not_an_object_still_reports_the_status(mock):
    add_body(mock, '"boom"', status=500)

    with pytest.raises(tg.HTTPError, match="HTTP 500"):
        tg.get("ted", "plano_acao", limit=1)


def test_an_unparseable_body_is_reported_as_such(mock):
    add_body(mock, "not json at all")

    with pytest.raises(tg.ResponseError):
        tg.get("ted", "plano_acao", limit=1)


def test_a_json_object_where_rows_belong_is_rejected(mock):
    # Reading `{"a": 1}` as a single row would turn an error page into data.
    add_body(mock, '{"message":"surprise"}')

    with pytest.raises(tg.ResponseError):
        tg.get("ted", "plano_acao", limit=1)


def test_only_transient_statuses_are_retried():
    assert 429 in _client.TRANSIENT
    assert 503 in _client.TRANSIENT
    assert 504 in _client.TRANSIENT
    # A 400 is PostgREST rejecting the query and will fail identically.
    assert 400 not in _client.TRANSIENT
    assert 404 not in _client.TRANSIENT


def test_a_transient_status_is_retried_then_succeeds(mock):
    tg.configure(max_tries=3)
    add_body(mock, "[]", status=503)
    add_page(mock, 1, total=1)

    result = tg.get("ted", "plano_acao", limit=1)

    assert len(mock.calls) == 2
    assert len(result) == 1


def test_an_over_long_url_is_reported_as_such():
    # curl answers a URL this long with "Error in the HTTP2 framing layer",
    # which says nothing about the query that caused it.
    with pytest.raises(tg.URLTooLongError, match="in_"):
        tg.get("ted", "plano_acao", id_plano_acao=tg.in_(list(range(3000))))


def test_a_normal_request_is_nowhere_near_the_url_limit(mock):
    add_page(mock, 1, total=1)

    tg.get("ted", "plano_acao", id_plano_acao=tg.in_(list(range(50))), limit=1)

    assert len(mock.calls[0].request.url) < _client.MAX_URL


def test_the_user_agent_identifies_the_package(mock):
    add_page(mock, 1, total=1)

    tg.get("ted", "plano_acao", limit=1)

    assert "transferegovpy" in mock.calls[0].request.headers["User-Agent"]


def test_configure_rejects_unknown_options():
    with pytest.raises(ValueError, match="Unknown option"):
        tg.configure(nonsense=1)


def test_content_range_is_read_in_every_form_the_service_sends():
    assert _client.parse_content_range("0-99/6176") == 6176
    assert _client.parse_content_range("items 0-9/10") == 10
    assert _client.parse_content_range("*/0") == 0
    assert _client.parse_content_range("0-2/*") is None
    assert _client.parse_content_range(None) is None
    assert _client.parse_content_range("") is None
    assert _client.parse_content_range("nonsense") is None
    assert _client.parse_content_range("0-99") is None


def test_a_total_beyond_integer_range_survives():
    assert _client.parse_content_range("0-9/3000000000") == 3e9
