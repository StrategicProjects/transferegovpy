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


def test_every_module_answers():
    for module in tg.modules()["module"]:
        table = tg.tables(module)["table"].iloc[0]
        assert len(tg.get(module, table, limit=1).columns) > 0


def test_every_table_still_has_the_columns_we_froze():
    tables = tg.tables()

    for _, row in tables.iterrows():
        frame = tg.get(row["module"], row["table"], limit=1)
        known = set(tg.fields(row["module"], row["table"])["field"])

        assert set(frame.columns) <= known, f"{row['module']}/{row['table']} has unknown columns"


def test_the_row_count_matches_a_full_fetch():
    total = tg.count("transferenciasespeciais", "programa_especial")
    rows = tg.get("transferenciasespeciais", "programa_especial", limit=math.inf, progress=False)

    assert len(rows) == total


def test_paging_is_stable_whatever_the_page_size():
    def key(frame):
        return sorted(frame.astype(str).agg("|".join, axis=1))

    one = tg.get("fundoafundo", "programa", limit=1000, progress=False)
    many = tg.get("fundoafundo", "programa", limit=math.inf, page_size=25, progress=False)

    assert tg.metadata(many)["pages"] > 1
    assert key(one) == key(many)


def test_the_service_still_caps_a_page_at_1000_rows():
    # `page_size` is capped at 1000 because the service silently truncates
    # anything larger. If that ever changes, the cap should be revisited.
    frame = tg.get("ted", "plano_acao_etapa", select=["id_etapa"], limit=1000, page_size=1000)

    assert len(frame) == 1000


def test_filters_reach_the_service_and_narrow_the_result():
    everything = tg.count("ted", "plano_acao")
    one_year = tg.count("ted", "plano_acao", aa_ano_plano_acao=2024)

    assert one_year < everything

    rows = tg.get("ted", "plano_acao", aa_ano_plano_acao=2024, limit=50)
    assert (rows["aa_ano_plano_acao"] == 2024).all()


def test_dates_and_timestamps_come_back_typed():
    plans = tg.get("ted", "plano_acao", limit=20)
    assert str(plans.dtypes["dt_inicio_vigencia"]) == "datetime64[ns]"

    financial = tg.get("ted", "programacao_financeira", limit=20)
    assert str(financial.dtypes["dh_recebimento_programacao"]) == "datetime64[ns]"


def test_an_unknown_column_is_rejected_by_the_service():
    tg.configure(validate=False)
    try:
        with pytest.raises(tg.HTTPError) as caught:
            tg.get("ted", "plano_acao", coluna_inexistente=1)
        assert caught.value.status == 400
    finally:
        tg.configure(validate=True)


def test_the_python_and_r_packages_see_the_same_totals():
    # Both freeze the same OpenAPI documents, so a divergence means one of the
    # two schemas is stale.
    assert len(tg.tables()) == 48
    assert int(tg.tables()["columns"].sum()) == 599
