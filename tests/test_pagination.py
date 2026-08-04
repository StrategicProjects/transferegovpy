"""Pagination is by page number.

What matters is that the page sequence is right, that ``limit`` and ``offset``
keep meaning rows rather than pages, and that a short read is reported instead
of passing as complete.
"""

from __future__ import annotations

import math

import pytest

import transferegovpy as tg
from transferegovpy._errors import IncompleteResultWarning, ResponseError

from .conftest import add_body, add_page, envelope, path_of, query_of


def test_a_single_page_is_one_request(mock):
    add_page(mock, 3, total=3)

    frame = tg.get("parcerias", "parceria", limit=10)

    assert len(frame) == 3
    assert len(mock.calls) == 1
    assert tg.metadata(frame)["pages"] == 1


def test_the_endpoint_path_is_the_one_the_schema_records(mock):
    add_page(mock, 1, total=1, table="planos-acao", module="fundoafundo")

    tg.get("fundoafundo", "planos_acao", limit=1)

    # The table is `planos_acao` in Python and `planos-acao` in the URL.
    assert path_of(mock.calls[0]) == "fundoafundo/planos-acao"


def test_the_first_request_asks_for_page_one_at_the_requested_size(mock):
    add_page(mock, 2, total=2)

    tg.get("parcerias", "parceria", limit=2, page_size=50)

    query = dict(query_of(mock.calls[0]))
    assert query["pagina"] == "1"
    assert query["tamanho_da_pagina"] == "50"


def test_successive_pages_are_requested_by_number(mock):
    for page in (1, 2, 3):
        add_page(mock, 2, start=2 * page - 1, total=6, page=page, page_size=2)

    frame = tg.get("parcerias", "parceria", limit=6, page_size=2)

    assert list(frame["id_parceria"]) == [1, 2, 3, 4, 5, 6]
    assert [dict(query_of(c))["pagina"] for c in mock.calls] == ["1", "2", "3"]


def test_collection_stops_at_the_limit_not_the_total(mock):
    add_page(mock, 2, start=1, total=100, page=1, page_size=2)
    add_page(mock, 2, start=3, total=100, page=2, page_size=2)

    frame = tg.get("parcerias", "parceria", limit=4, page_size=2)

    assert len(frame) == 4
    assert len(mock.calls) == 2


def test_a_page_carrying_more_rows_than_wanted_is_trimmed(mock):
    add_page(mock, 2, start=1, total=100, page=1, page_size=2)
    add_page(mock, 2, start=3, total=100, page=2, page_size=2)

    frame = tg.get("parcerias", "parceria", limit=3, page_size=2)

    assert list(frame["id_parceria"]) == [1, 2, 3]


def test_inf_collects_every_matching_row(mock):
    add_page(mock, 2, start=1, total=5, page=1, page_size=2)
    add_page(mock, 2, start=3, total=5, page=2, page_size=2)
    add_page(mock, 1, start=5, total=5, page=3, page_size=2)

    frame = tg.get("parcerias", "parceria", limit=math.inf, page_size=2)

    assert list(frame["id_parceria"]) == [1, 2, 3, 4, 5]


# Offset ----------------------------------------------------------------------


def test_an_offset_on_a_page_boundary_starts_at_that_page(mock):
    add_page(mock, 2, start=5, total=10, page=3, page_size=2)

    frame = tg.get("parcerias", "parceria", limit=2, offset=4, page_size=2)

    assert dict(query_of(mock.calls[0]))["pagina"] == "3"
    assert list(frame["id_parceria"]) == [5, 6]


def test_an_offset_inside_a_page_drops_the_rows_before_it(mock):
    # 5 rows to skip at a page size of 4 means fetching page 2 and dropping its
    # first row, so `offset` keeps meaning rows whatever `page_size` is.
    add_page(mock, 4, start=5, total=12, page=2, page_size=4)
    add_page(mock, 4, start=9, total=12, page=3, page_size=4)

    frame = tg.get("parcerias", "parceria", limit=4, offset=5, page_size=4)

    assert dict(query_of(mock.calls[0]))["pagina"] == "2"
    assert list(frame["id_parceria"]) == [6, 7, 8, 9]


def test_an_offset_past_the_end_returns_nothing(mock):
    add_body(mock, envelope("[]", total=10, page=99))

    assert len(tg.get("parcerias", "parceria", offset=500)) == 0


def test_the_rows_left_after_the_offset_bound_the_collection(mock):
    add_page(mock, 2, start=9, total=10, page=5, page_size=2)

    frame = tg.get("parcerias", "parceria", limit=math.inf, offset=8, page_size=2)

    assert len(frame) == 2


# Short reads -----------------------------------------------------------------


def test_a_collection_short_of_the_reported_total_warns(mock):
    add_page(mock, 2, start=1, total=6, page=1, page_size=2)
    add_body(mock, envelope("[]", total=6, page=2, page_size=2))

    with pytest.warns(IncompleteResultWarning):
        tg.get("parcerias", "parceria", limit=6, page_size=2)


def test_an_empty_first_page_is_not_a_short_read(mock):
    add_body(mock, envelope("[]", total=0))

    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("error", IncompleteResultWarning)
        assert len(tg.get("parcerias", "parceria")) == 0


# Envelope --------------------------------------------------------------------


def test_a_bare_array_is_reported_as_the_wrong_shape(mock):
    # A bare array is what the retired PostgREST service answered with, so this
    # is the shape a misconfigured base URL produces.
    add_body(mock, "[]")

    with pytest.raises(ResponseError, match="paginated envelope"):
        tg.get("parcerias", "parceria")


def test_an_envelope_missing_a_pagination_field_is_an_error(mock):
    add_body(
        mock,
        '{"data":[],"total_pages":1,"page_number":1,"page_size":200}',
    )

    with pytest.raises(ResponseError, match="total_items"):
        tg.get("parcerias", "parceria")


def test_an_envelope_whose_data_is_not_an_array_is_an_error(mock):
    add_body(mock, envelope("{}", total=1))

    with pytest.raises(ResponseError, match="array of rows"):
        tg.get("parcerias", "parceria")


def test_an_envelope_without_a_usable_total_is_an_error(mock):
    add_body(
        mock,
        '{"data":[],"total_pages":1,"total_items":null,'
        '"page_number":1,"page_size":200}',
    )

    with pytest.raises(ResponseError, match="no usable total_items"):
        tg.get("parcerias", "parceria")


# Metadata --------------------------------------------------------------------


def test_metadata_reports_what_was_collected_and_how(mock):
    add_page(mock, 2, start=1, total=9, page=1, page_size=2)
    add_page(mock, 2, start=3, total=9, page=2, page_size=2)

    frame = tg.get(
        "parcerias", "parceria", limit=4, page_size=2, in_situacao_parceria="Aprovada"
    )
    meta = tg.metadata(frame)

    assert meta["module"] == "parcerias"
    assert meta["table"] == "parceria"
    assert meta["total_rows"] == 9
    assert meta["rows_returned"] == 4
    assert meta["pages"] == 2
    assert meta["page_size"] == 2
    assert meta["filters"] == {"in_situacao_parceria": "Aprovada"}
    assert meta["cached"] is False


def test_metadata_is_none_for_anything_else():
    assert tg.metadata(1) is None


# Counting --------------------------------------------------------------------


def test_count_reads_the_total_from_a_one_row_page(mock):
    add_page(mock, 1, total=6176)

    assert tg.count("parcerias", "parceria") == 6176

    query = dict(query_of(mock.calls[0]))
    assert query["tamanho_da_pagina"] == "1"
    assert query["pagina"] == "1"


def test_count_sends_the_filters_it_was_given(mock):
    add_page(mock, 1, total=3)

    tg.count("parcerias", "parceria", in_situacao_parceria="Aprovada")

    assert dict(query_of(mock.calls[0]))["in_situacao_parceria"] == "Aprovada"


# Arguments -------------------------------------------------------------------


def test_the_page_size_is_bounded_by_what_the_service_accepts(mock):
    # The message is asserted, not just the failure: without a mocked response
    # an out-of-range page size would fail anyway when the request went out.
    with pytest.raises(ValueError, match="between 1 and 200"):
        tg.get("parcerias", "parceria", page_size=201)
    with pytest.raises(ValueError, match="between 1 and 200"):
        tg.get("parcerias", "parceria", page_size=0)

    assert len(mock.calls) == 0


def test_limit_and_offset_must_be_whole_numbers():
    with pytest.raises(ValueError):
        tg.get("parcerias", "parceria", limit=1.5)
    with pytest.raises(ValueError):
        tg.get("parcerias", "parceria", offset=-1)
    with pytest.raises(TypeError):
        tg.get("parcerias", "parceria", limit="10")


def test_an_infinite_offset_is_refused():
    with pytest.raises(ValueError):
        tg.get("parcerias", "parceria", offset=math.inf)
