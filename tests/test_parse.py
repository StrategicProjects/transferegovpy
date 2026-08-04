import json

import pandas as pd
import pytest

import transferegovpy as tg
from transferegovpy._errors import ColumnTypeWarning
from transferegovpy._parse import to_frame

from .conftest import add_body, add_page, envelope


def rows(text):
    """Literal JSON, so that a `null` is a real null and not a Python default."""
    return json.loads(text)


def test_columns_are_typed_from_the_schema_not_guessed(mock):
    add_page(mock, 2, total=2)

    frame = tg.get("parcerias", "parceria", limit=2)

    assert frame.dtypes["id_parceria"] == "Int64"
    assert frame.dtypes["in_situacao_parceria"] == "string"
    assert str(frame.dtypes["dh_assinatura"]) == "datetime64[ns]"


def test_a_json_null_becomes_a_missing_value_of_the_columns_type(mock):
    add_body(
        mock,
        envelope(
            '[{"id_parceria":null,"dh_assinatura":null,'
            '"in_situacao_parceria":null}]',
            total=1,
        ),
    )

    frame = tg.get("parcerias", "parceria", limit=1)

    assert frame["id_parceria"].isna().all()
    assert frame.dtypes["id_parceria"] == "Int64"
    assert str(frame.dtypes["dh_assinatura"]) == "datetime64[ns]"
    assert frame.dtypes["in_situacao_parceria"] == "string"


def test_an_all_null_column_keeps_its_declared_dtype(mock):
    # Left to inference this column would come back object on a page where
    # every value is null and string on the next.
    add_body(
        mock,
        envelope(
            '[{"id_parceria":1,"dh_assinatura":null},'
            '{"id_parceria":2,"dh_assinatura":null}]',
            total=2,
        ),
    )

    frame = tg.get("parcerias", "parceria", limit=2)

    assert str(frame.dtypes["dh_assinatura"]) == "datetime64[ns]"


def test_an_empty_result_keeps_the_tables_columns_and_dtypes(mock):
    # A zero-row frame with no columns would break any code that concatenates
    # pages or selects a column, so an empty answer keeps the schema's shape.
    add_body(mock, envelope("[]", total=0))

    frame = tg.get("parcerias", "parceria")

    assert len(frame) == 0
    assert "id_parceria" in frame.columns
    assert frame.dtypes["id_parceria"] == "Int64"


def test_the_date_dtype_does_not_depend_on_whether_rows_came_back(mock):
    add_body(mock, envelope("[]", total=0))
    empty = tg.get("parcerias", "parceria")

    add_page(mock, 1, total=1)
    filled = tg.get("parcerias", "parceria", limit=1)

    assert str(empty.dtypes["dh_assinatura"]) == str(filled.dtypes["dh_assinatura"])


def test_an_unparseable_date_leaves_the_column_as_text_with_a_warning():
    with pytest.warns(ColumnTypeWarning):
        frame = to_frame(
            rows('[{"dh_assinatura":"not a date"}]'), "parcerias", "parceria"
        )

    assert frame.dtypes["dh_assinatura"] == "string"


def test_an_identifier_beyond_2_31_keeps_its_full_range(mock):
    # cd_parceria reaches 202500037062. Unlike the R sibling, pandas has a
    # nullable 64-bit integer, so there is nothing to trade away.
    add_page(mock, 1, total=1)

    frame = tg.get("parcerias", "parceria", limit=1)

    assert frame.dtypes["cd_parceria"] == "Int64"
    assert frame["cd_parceria"].iloc[0] == 202500000001


def test_a_column_the_schema_does_not_know_is_kept_as_found():
    frame = to_frame(rows('[{"novo":1},{"novo":2}]'), "parcerias", "parceria")

    assert list(frame.columns) == ["novo"]
    assert list(frame["novo"]) == [1, 2]


def test_rows_presenting_columns_in_different_orders_are_aligned():
    frame = to_frame(
        rows('[{"id_parceria":1,"id_proposta":2},{"id_proposta":20,"id_parceria":10}]'),
        "parcerias",
        "parceria",
    )

    assert list(frame["id_parceria"]) == [1, 10]
    assert list(frame["id_proposta"]) == [2, 20]


def test_a_timestamp_with_an_offset_is_converted_not_read_as_utc():
    frame = to_frame(
        rows('[{"dh_assinatura":"2025-03-04T05:06:07-03:00"}]'),
        "parcerias",
        "parceria",
    )

    assert frame["dh_assinatura"].iloc[0] == pd.Timestamp("2025-03-04 08:06:07")


# List columns ----------------------------------------------------------------


def test_a_declared_array_column_holds_its_lists():
    frame = to_frame(
        rows('[{"publicacoes_parceria":[{"dt_publicacao":"2025-01-01"}]}]'),
        "parcerias",
        "parceria",
    )

    assert frame.dtypes["publicacoes_parceria"] == "object"
    assert frame["publicacoes_parceria"].iloc[0] == [{"dt_publicacao": "2025-01-01"}]


def test_an_array_column_stays_object_even_when_every_row_is_empty():
    # So the dtype does not depend on which page was fetched.
    frame = to_frame(
        rows('[{"publicacoes_parceria":[]},{"publicacoes_parceria":[]}]'),
        "parcerias",
        "parceria",
    )

    assert frame.dtypes["publicacoes_parceria"] == "object"
    assert list(frame["publicacoes_parceria"]) == [[], []]
