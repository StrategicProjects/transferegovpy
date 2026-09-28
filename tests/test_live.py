"""Integration tests against the real APIs.

Skipped unless ``TRANSFEREGOVPY_LIVE_TESTS`` is set, so neither CI nor a
routine ``pytest`` run reaches the government's servers.
"""

from __future__ import annotations

import math
import os
import time
import warnings

import pytest

import transferegovpy as tg
from transferegovpy import _client, _schema

pytestmark = pytest.mark.skipif(
    not os.environ.get("TRANSFEREGOVPY_LIVE_TESTS"),
    reason="set TRANSFEREGOVPY_LIVE_TESTS to run live tests",
)


@pytest.fixture(autouse=True)
def live_settings():
    tg.configure(requests_per_minute=60, max_tries=4, timeout=60)
    tg.set_cache(True)
    yield


def raw(module, table, params):
    """A request with its status left for the test to read.

    Built and throttled by the package's own client: 113 unthrottled requests
    in a row drew transient failures from the service.
    """
    url = _client._prepare(
        f"{module}/{_schema.table_path(module, table)}", params, _client.base_url(module)
    )
    for attempt in range(4):
        _client._wait_turn()
        response = _client.session().get(url, timeout=60)
        if response.status_code not in (429, 502, 503, 504):
            return response
        time.sleep(2**attempt)
    return response


# Bank details declared as integers and sent masked as "***". The warning is
# the package working as intended, not drift.
MASKED = (
    "codigo_agencia_favorecido_gestao_financeira",
    "codigo_conta_favorecido_gestao_financeira",
    "codigo_agencia_beneficiario_subtransacao_gestao_financeira",
    "codigo_conta_beneficiario_subtransacao_gestao_financeira",
)


def strip(frame):
    out = frame.reset_index(drop=True).copy()
    out.attrs = {}
    return out


def test_every_table_in_the_frozen_schema_still_answers():
    # A type warning counts as a failure too: a column whose type changed
    # upstream still parses, as text with a warning, so an errors-only check
    # let `proposta.in_formato_etapas` turning from an integer into an
    # enumeration through.
    failures = []

    for _, row in tg.tables().iterrows():
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            try:
                tg.get(row["module"], row["table"], limit=50)
            except Exception as error:  # noqa: BLE001 - collecting every failure
                failures.append(f"{row['module']}/{row['table']}: {error}")
        for warning in caught:
            message = str(warning.message)
            if not any(column in message for column in MASKED):
                failures.append(f"{row['module']}/{row['table']}: {message}")

    assert failures == []


def test_each_modules_frozen_page_limit_is_the_one_its_service_enforces():
    for _, row in tg.modules().iterrows():
        module, limit = row["module"], int(row["max_page_size"])
        table = _schema.table_names(module)[0]
        assert raw(module, table, [("tamanho_da_pagina", str(limit))]).status_code == 200
        assert raw(module, table, [("tamanho_da_pagina", str(limit + 1))]).status_code == 422


def test_the_parameters_frozen_as_lists_are_the_ones_that_take_lists():
    # The OpenAPI documents do not say which parameters take a list, so the
    # schema builder asked the service. Ask again: a list-taking parameter
    # rejects a non-integer with a message about comma-separated integers.
    wrong = []
    for module in _schema.module_names():
        for table in _schema.table_names(module):
            for name, param in _schema.table_params(module, table).items():
                if not param["multiple"]:
                    continue
                body = raw(module, table, [(name, "x")]).text
                if "separados por v" not in body:
                    wrong.append(f"{module}/{table} {name}")

    assert wrong == []


def test_a_list_means_any_of_its_values_up_to_the_frozen_limit():
    one = tg.count("ted", "planos_acao_metas", id_plano_acao=3)
    other = tg.count("ted", "planos_acao_metas", id_plano_acao=4)
    assert tg.count("ted", "planos_acao_metas", id_plano_acao=[3, 4]) == one + other

    for module, table, name in (
        ("especiais", "devolucao_especiais", "id_devolucao"),
        ("ted", "planos_acao", "id_plano_acao"),
    ):
        limit = _schema.table_params(module, table)[name]["max_values"]
        statuses = [
            raw(module, table, [(name, ",".join(str(i) for i in range(1, n + 1)))]).status_code
            for n in (limit, limit + 1)
        ]
        assert statuses == [200, 400], f"{module}/{table} {name}"


def test_pages_of_1000_hold_the_same_rows_as_pages_of_200():
    big = tg.get("ted", "planos_acao_metas_etapas", limit=1000, offset=20000, page_size=1000)
    small = tg.get("ted", "planos_acao_metas_etapas", limit=1000, offset=20000, page_size=200)

    assert len(big) == 1000
    assert list(big["id_etapa"]) == list(small["id_etapa"])


def test_the_frozen_columns_match_what_the_services_send():
    drift = []

    for _, row in tg.tables().iterrows():
        # Only names are compared here; the masked columns' warning is covered
        # above.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
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
    assert len(tg.tables()) == 74
    assert tg.tables()["columns"].sum() == 1045
    assert tg.tables()["params"].sum() == 1059
    lists = sum(
        p["multiple"]
        for m in _schema.module_names()
        for t in _schema.table_names(m)
        for p in _schema.table_params(m, t).values()
    )
    assert lists == 113


def test_inf_collects_a_whole_small_table():
    total = tg.count("parcerias", "proposta_resultado_indicador")
    frame = tg.get("parcerias", "proposta_resultado_indicador", limit=math.inf)

    assert len(frame) == total
