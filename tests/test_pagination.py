import math

import pytest

import transferegovpy as tg

from .conftest import add_body, add_page, query_of


def test_a_request_under_the_page_size_takes_one_round_trip(mock):
    add_page(mock, 5, total=5)

    result = tg.get("ted", "plano_acao", limit=5)

    assert len(mock.calls) == 1
    assert len(result) == 5
    assert tg.metadata(result)["pages"] == 1


def test_rows_beyond_the_page_size_are_collected_across_pages(mock):
    add_page(mock, 2, start=1, total=5)
    add_page(mock, 2, start=3, total=5, first=2)
    add_page(mock, 1, start=5, total=5, first=4)

    result = tg.get("ted", "plano_acao", limit=5, page_size=2, progress=False)

    assert len(mock.calls) == 3
    assert list(result["id_plano_acao"]) == [1, 2, 3, 4, 5]
    assert tg.metadata(result)["pages"] == 3


def test_each_page_asks_for_the_offset_that_follows_the_last(mock):
    add_page(mock, 2, start=1, total=5)
    add_page(mock, 2, start=3, total=5, first=2)
    add_page(mock, 1, start=5, total=5, first=4)

    tg.get("ted", "plano_acao", limit=5, page_size=2, progress=False)

    offsets = [dict(query_of(c))["offset"] for c in mock.calls]
    assert offsets == ["0", "2", "4"]


def test_the_last_page_asks_only_for_the_rows_still_missing(mock):
    # Asking for a full page and discarding the surplus would make the service
    # do work the caller never sees.
    add_page(mock, 2, start=1, total=5)
    add_page(mock, 1, start=3, total=5, first=2)

    tg.get("ted", "plano_acao", limit=3, page_size=2, progress=False)

    limits = [dict(query_of(c))["limit"] for c in mock.calls]
    assert limits == ["2", "1"]


def test_inf_collects_every_row_the_api_reports(mock):
    add_page(mock, 2, start=1, total=3)
    add_page(mock, 1, start=3, total=3, first=2)

    result = tg.get("ted", "plano_acao", limit=math.inf, page_size=2, progress=False)

    assert len(result) == 3
    assert tg.metadata(result)["total_rows"] == 3


def test_collection_stops_at_the_total_even_when_the_limit_is_higher(mock):
    add_page(mock, 3, total=3)

    result = tg.get("ted", "plano_acao", limit=100, page_size=10, progress=False)

    assert len(mock.calls) == 1
    assert len(result) == 3


def test_the_offset_is_subtracted_from_what_remains(mock):
    # Without this the loop would try to collect `total` rows starting from the
    # offset and run past the end of the table.
    add_page(mock, 2, start=9, total=10, first=8)

    result = tg.get("ted", "plano_acao", limit=math.inf, offset=8, page_size=5, progress=False)

    assert len(mock.calls) == 1
    assert len(result) == 2
    assert tg.metadata(result)["offset"] == 8


def test_an_offset_past_the_end_returns_no_rows_without_looping(mock):
    add_body(mock, "[]", content_range="*/5")

    result = tg.get("ted", "plano_acao", limit=math.inf, offset=99, progress=False)

    assert len(result) == 0
    assert len(mock.calls) == 1


def test_an_empty_page_stops_collection_instead_of_looping(mock):
    # The loop is bounded by the total the API reported. If the table shrinks
    # mid-collection that total is stale, and without this break the loop would
    # keep asking for rows that no longer exist.
    add_page(mock, 2, start=1, total=10)
    add_body(mock, "[]", content_range="2-1/10")

    with pytest.warns(tg.IncompleteResultWarning):
        result = tg.get("ted", "plano_acao", limit=math.inf, page_size=2, progress=False)

    assert len(mock.calls) == 2
    assert len(result) == 2


def test_collecting_fewer_rows_than_reported_warns(mock):
    add_page(mock, 2, start=1, total=10)
    add_page(mock, 1, start=3, total=10, first=2)
    add_body(mock, "[]", content_range="3-2/10")

    with pytest.warns(tg.IncompleteResultWarning, match="Collected 3 row"):
        tg.get("ted", "plano_acao", limit=math.inf, page_size=2, progress=False)


def test_a_complete_collection_warns_about_nothing(mock, recwarn):
    add_page(mock, 2, start=1, total=3)
    add_page(mock, 1, start=3, total=3, first=2)

    tg.get("ted", "plano_acao", limit=math.inf, page_size=2, progress=False)

    assert not [w for w in recwarn if issubclass(w.category, tg.IncompleteResultWarning)]


def test_a_missing_total_leaves_the_limit_as_the_only_bound(mock):
    add_page(mock, 2, start=1)
    add_page(mock, 2, start=3, first=2)

    result = tg.get("ted", "plano_acao", limit=4, page_size=2, progress=False)

    assert len(result) == 4
    assert tg.metadata(result)["total_rows"] is None


def test_metadata_reports_what_was_actually_retrieved(mock):
    add_page(mock, 2, start=1, total=5)
    add_page(mock, 2, start=3, total=5, first=2)

    result = tg.get(
        "ted", "plano_acao", limit=4, page_size=2, select=["id_plano_acao"], progress=False
    )
    meta = tg.metadata(result)

    assert meta["module"] == "ted"
    assert meta["table"] == "plano_acao"
    assert meta["total_rows"] == 5
    assert meta["rows_returned"] == 4
    assert meta["pages"] == 2
    assert meta["page_size"] == 2
    assert meta["select"] == ["id_plano_acao"]
    assert meta["cached"] is False


def test_metadata_is_none_for_anything_else():
    import pandas as pd

    assert tg.metadata(pd.DataFrame()) is None
    assert tg.metadata(1) is None


def test_count_reads_the_total_without_fetching_rows(mock):
    add_body(mock, "[]", content_range="*/6176")

    assert tg.count("ted", "plano_acao") == 6176

    query = dict(query_of(mock.calls[0]))
    assert query["select"] == ""
    assert query["limit"] == "1"
    assert mock.calls[0].request.headers["Prefer"] == "count=exact"


def test_count_applies_filters(mock):
    add_body(mock, "[]", content_range="*/12")

    tg.count("ted", "plano_acao", aa_ano_plano_acao=2024)

    assert dict(query_of(mock.calls[0]))["aa_ano_plano_acao"] == "eq.2024"


def test_count_raises_when_the_api_reports_no_total(mock):
    # Returning 0 here would read as "nothing matches" when the truth is
    # "the service did not say".
    add_body(mock, "[]", content_range="0-0/*")

    with pytest.raises(tg.ResponseError):
        tg.count("ted", "plano_acao")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"limit": 0},
        {"limit": -1},
        {"limit": 1.5},
        {"limit": "5"},
        {"limit": -math.inf},
        {"offset": -1},
        {"offset": math.inf},
        {"page_size": 0},
        # The service caps a page at 1000 rows however many are asked for, so a
        # larger page size would silently return fewer rows than requested.
        {"page_size": 1001},
    ],
)
def test_pagination_arguments_are_validated_before_any_request(kwargs):
    with pytest.raises(ValueError):
        tg.get("ted", "plano_acao", **kwargs)


def test_module_shortcuts_are_the_module_they_name(mock):
    add_page(mock, 1, total=1)
    add_page(mock, 1, total=1, module="fundoafundo", table="programa")
    add_page(mock, 1, total=1, module="transferenciasespeciais", table="programa_especial")

    tg.ted("plano_acao", limit=1)
    tg.fundo_a_fundo("programa", limit=1)
    tg.transferencias_especiais("programa_especial", limit=1)

    paths = [c.request.url.split("?")[0].rsplit("/", 2)[-2:] for c in mock.calls]
    assert paths == [
        ["ted", "plano_acao"],
        ["fundoafundo", "programa"],
        ["transferenciasespeciais", "programa_especial"],
    ]
