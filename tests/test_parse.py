import json

import pandas as pd
import pytest

import transferegovpy as tg
from transferegovpy._parse import to_frame

from .conftest import add_body, add_page


def rows(text):
    """Literal JSON, so that a `null` is a real null and not a Python default."""
    return json.loads(text)


def test_columns_are_typed_from_the_schema_not_guessed(mock):
    add_page(mock, 2, total=2)

    frame = tg.get("ted", "plano_acao", limit=2)

    assert frame.dtypes["id_plano_acao"] == "Int64"
    assert frame.dtypes["vl_total_plano_acao"] == "Float64"
    assert frame.dtypes["tx_objeto_plano_acao"] == "string"
    assert frame.dtypes["in_forma_execucao_direta"] == "boolean"
    assert str(frame.dtypes["dt_inicio_vigencia"]) == "datetime64[ns]"


def test_a_json_null_becomes_a_missing_value_of_the_columns_type(mock):
    add_body(
        mock,
        '[{"id_plano_acao":null,"dt_inicio_vigencia":null,'
        '"in_forma_execucao_direta":null,"tx_objeto_plano_acao":null}]',
        content_range="0-0/1",
    )

    frame = tg.get("ted", "plano_acao", limit=1)

    assert frame["id_plano_acao"].isna().all()
    assert frame.dtypes["id_plano_acao"] == "Int64"
    assert str(frame.dtypes["dt_inicio_vigencia"]) == "datetime64[ns]"
    assert frame.dtypes["in_forma_execucao_direta"] == "boolean"


def test_an_all_null_column_keeps_its_declared_dtype(mock):
    # Left to inference this column would come back object on a page where
    # every value is null and string on the next.
    add_body(
        mock,
        '[{"id_plano_acao":1,"dt_inicio_vigencia":null},'
        '{"id_plano_acao":2,"dt_inicio_vigencia":null}]',
        content_range="0-1/2",
    )

    frame = tg.get("ted", "plano_acao", limit=2)

    assert str(frame.dtypes["dt_inicio_vigencia"]) == "datetime64[ns]"


def test_an_empty_result_keeps_the_tables_columns_and_dtypes(mock):
    add_body(mock, "[]", content_range="*/0")

    frame = tg.get("ted", "plano_acao", limit=5)

    assert len(frame) == 0
    assert len(frame.columns) == 20
    assert str(frame.dtypes["dt_inicio_vigencia"]) == "datetime64[ns]"
    assert frame.dtypes["id_plano_acao"] == "Int64"


def test_the_date_dtype_does_not_depend_on_whether_rows_came_back(mock):
    # pandas 2 picks a datetime resolution from the values, so without pinning
    # it the same column arrives as datetime64[us] with rows and
    # datetime64[ns] without them.
    add_page(mock, 2, total=2)
    add_body(mock, "[]", content_range="*/0")

    with_rows = tg.get("ted", "plano_acao", limit=2)
    without = tg.get("ted", "plano_acao", limit=2)

    assert with_rows.dtypes["dt_inicio_vigencia"] == without.dtypes["dt_inicio_vigencia"]


def test_an_empty_result_narrowed_by_select_keeps_only_those_columns(mock):
    add_body(mock, "[]", content_range="*/0")

    frame = tg.get("ted", "plano_acao", select=["id_plano_acao"], limit=5)

    assert list(frame.columns) == ["id_plano_acao"]
    assert frame.dtypes["id_plano_acao"] == "Int64"


def test_an_unparseable_date_leaves_the_column_as_text_with_a_warning(mock):
    add_body(mock, '[{"id_plano_acao":1,"dt_inicio_vigencia":"not a date"}]', content_range="0-0/1")

    with pytest.warns(tg.ColumnTypeWarning):
        frame = tg.get("ted", "plano_acao", limit=1)

    assert frame.dtypes["dt_inicio_vigencia"] == "string"


def test_a_bigint_keeps_its_full_range():
    # The R sibling has to return these as a float; pandas' nullable Int64
    # holds the whole 64-bit range, so there is no trade to make.
    big = 9_007_199_254_740_993  # beyond what a float64 can represent exactly
    frame = to_frame([{"id_plano_acao": big}], "ted", "plano_acao", ["id_plano_acao"])

    assert frame["id_plano_acao"].iloc[0] == big
    assert frame.dtypes["id_plano_acao"] == "Int64"


def test_a_column_the_schema_does_not_know_is_kept_as_found():
    frame = to_frame([{"novo": 1}, {"novo": 2}], "ted", "plano_acao")

    assert list(frame.columns) == ["novo"]
    assert frame["novo"].tolist() == [1, 2]


def test_rows_presenting_columns_in_different_orders_are_aligned():
    frame = to_frame(
        rows('[{"id_plano_acao":1,"id_programa":2},{"id_programa":20,"id_plano_acao":10}]'),
        "ted",
        "plano_acao",
    )

    assert frame["id_plano_acao"].tolist() == [1, 10]
    assert frame["id_programa"].tolist() == [2, 20]


def test_a_timestamp_with_an_offset_is_converted_not_read_as_utc(mock):
    add_body(
        mock,
        '[{"id_programacao":1,"dh_recebimento_programacao":"2022-05-17T18:05:42-03:00"}]',
        content_range="0-0/1",
        table="programacao_financeira",
    )

    frame = tg.get("ted", "programacao_financeira", limit=1)
    value = frame["dh_recebimento_programacao"].iloc[0]

    assert value == pd.Timestamp("2022-05-17 21:05:42")
    assert value.tz is None
