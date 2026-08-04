"""Integration tests against the real APIs.

Skipped unless ``TRANSFEREGOVPY_LIVE_TESTS`` is set, so neither CI nor a
routine ``pytest`` run reaches the government's servers.
"""

from __future__ import annotations

import math
import os

import pytest

import transferegovpy as tg

pytestmark = pytest.mark.skipif(
    not os.environ.get("TRANSFEREGOVPY_LIVE_TESTS"),
    reason="set TRANSFEREGOVPY_LIVE_TESTS to run live tests",
)


@pytest.fixture(autouse=True)
def live_settings():
    tg.configure(requests_per_minute=60, max_tries=4, timeout=60)
    tg.set_cache(True)
    yield


def strip(frame):
    out = frame.reset_index(drop=True).copy()
    out.attrs = {}
    return out


def test_every_table_in_the_frozen_schema_still_answers():
    failures = []

    for _, row in tg.tables().iterrows():
        try:
            tg.get(row["module"], row["table"], limit=1)
        except Exception as error:  # noqa: BLE001 - collecting every failure
            failures.append(f"{row['module']}/{row['table']}: {error}")

    assert failures == []


def test_the_frozen_columns_match_what_the_services_send():
    drift = []

    for _, row in tg.tables().iterrows():
        frame = tg.get(row["module"], row["table"], limit=1)
        if len(frame) == 0:
            continue

        expected = set(tg.fields(row["module"], row["table"])["field"])
        got = set(frame.columns)
        if got != expected:
            drift.append(
                f"{row['module']}/{row['table']}: "
                f"new {sorted(got - expected)} gone {sorted(expected - got)}"
            )

    assert drift == []


# Pagination ------------------------------------------------------------------
#
# A row count proves nothing about pagination. What proves pages neither
# overlap nor skip is fetching the same rows at two page sizes and comparing
# them, which is also what establishes that the server's order is stable.


def test_the_same_rows_come_back_whatever_the_page_size():
    big = tg.get("especiais", "meta_especiais", limit=450, page_size=200)
    small = tg.get("especiais", "meta_especiais", limit=450, page_size=50)

    assert len(big) == 450
    assert strip(big).equals(strip(small))
    assert tg.metadata(big)["pages"] == 3
    assert tg.metadata(small)["pages"] == 9


def test_the_order_is_stable_deep_into_a_large_table():
    first = tg.get("especiais", "meta_especiais", limit=100, offset=100_000, page_size=100)
    again = tg.get(
        "especiais", "meta_especiais", limit=100, offset=100_000, page_size=50,
        use_cache=False,
    )

    assert list(first["id_meta"]) == list(again["id_meta"])


def test_an_offset_lands_on_the_row_it_names():
    full = tg.get("especiais", "meta_especiais", limit=300, page_size=200)
    offset = tg.get("especiais", "meta_especiais", limit=100, offset=137, page_size=60)

    assert list(offset["id_meta"]) == list(full["id_meta"].iloc[137:237])


# Filters ---------------------------------------------------------------------


def test_a_filter_narrows_the_result_and_the_total_agrees():
    total = tg.count("parcerias", "proposta")
    filtered = tg.count("parcerias", "proposta", sg_uf_recebedor="PE")

    assert 0 < filtered < total

    rows = tg.get("parcerias", "proposta", sg_uf_recebedor="PE", limit=25)
    assert (rows["sg_uf_recebedor"] == "PE").all()
    assert tg.metadata(rows)["total_rows"] == filtered


def test_filters_combine_with_and():
    uf = tg.count("parcerias", "proposta", sg_uf_recebedor="PE")
    both = tg.count(
        "parcerias", "proposta", sg_uf_recebedor="PE", situacao_proposta="Aprovada"
    )

    assert both <= uf


def test_the_enumerations_the_schema_froze_are_the_ones_the_service_takes():
    values = tg.params("parcerias", "proposta").set_index("param")
    for value in values.loc["situacao_proposta", "values"]:
        tg.count("parcerias", "proposta", situacao_proposta=value)


# The property that motivates validating parameter names client-side ----------


def test_the_service_really_does_ignore_an_unknown_parameter():
    # If this ever starts failing because the service began rejecting unknown
    # parameters, the client-side check in _params could be relaxed. Until
    # then it is the only thing standing between a typo and a silently
    # unfiltered answer.
    tg.configure(validate=False)
    try:
        total = tg.count("parcerias", "proposta")
        bogus = tg.count("parcerias", "proposta", in_situacao_proposta="Aprovada")
    finally:
        tg.configure(validate=True)

    assert bogus == total


# Freshness -------------------------------------------------------------------


def test_every_module_reports_when_it_was_last_loaded():
    import datetime as dt

    for module in tg.modules()["module"]:
        stamp = tg.updated_at(module)
        assert stamp > dt.datetime(2020, 1, 1)


# Nested columns --------------------------------------------------------------


def test_a_nested_column_arrives_as_lists_matching_its_sub_schema():
    rows = tg.get("parcerias", "programa", limit=20)

    populated = [v for v in rows["ufs_habilitadas"] if isinstance(v, list) and v]
    if not populated:
        pytest.skip("no nested rows in this sample")

    expected = set(tg.fields("parcerias", "programa", nested="ufs_habilitadas")["field"])
    assert set(populated[0][0]) == expected


# Parity with the R sibling ---------------------------------------------------


def test_the_schema_matches_the_documented_totals():
    # transferegovr freezes the same documents and must agree.
    assert len(tg.tables()) == 55
    assert tg.tables()["columns"].sum() == 811
    assert tg.tables()["params"].sum() == 817


def test_inf_collects_a_whole_small_table():
    total = tg.count("parcerias", "proposta_resultado_indicador")
    frame = tg.get("parcerias", "proposta_resultado_indicador", limit=math.inf)

    assert len(frame) == total
