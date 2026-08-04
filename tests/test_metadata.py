"""Discovery, and the schema the package freezes."""

from __future__ import annotations

import datetime as dt

import pytest

import transferegovpy as tg
from transferegovpy import _schema
from transferegovpy._errors import SchemaError

from .conftest import add_body, envelope


def test_the_frozen_schema_covers_three_modules_and_fifty_five_tables():
    assert len(tg.modules()) == 3
    assert len(tg.tables()) == 55
    assert tg.tables()["columns"].sum() == 811
    assert tg.tables()["params"].sum() == 817


def test_module_names_aliases_case_and_punctuation_all_resolve():
    assert _schema.match_module("parcerias") == "parcerias"
    assert _schema.match_module("PARCERIAS") == "parcerias"
    assert _schema.match_module("fundoafundo") == "fundoafundo"
    assert _schema.match_module("fundo_a_fundo") == "fundoafundo"
    assert _schema.match_module("fundo a fundo") == "fundoafundo"
    assert _schema.match_module("fund_to_fund") == "fundoafundo"
    assert _schema.match_module(" especiais ") == "especiais"


def test_the_old_module_name_resolves_to_the_module_that_replaced_it():
    # The package used to query `transferenciasespeciais` on the PostgREST
    # service; the same data is `especiais` here.
    assert _schema.match_module("transferenciasespeciais") == "especiais"
    assert _schema.match_module("transferencias_especiais") == "especiais"


def test_an_unknown_module_is_rejected():
    with pytest.raises(SchemaError):
        _schema.match_module("xpto")
    with pytest.raises(SchemaError):
        _schema.match_module(1)


def test_a_table_missing_from_one_module_points_at_the_module_that_has_it():
    with pytest.raises(SchemaError, match="parcerias"):
        tg.fields("especiais", "programa")


def test_an_unknown_table_is_rejected():
    with pytest.raises(SchemaError):
        tg.fields("parcerias", "nao_existe")
    with pytest.raises(SchemaError):
        tg.fields("parcerias", 1)


def test_a_table_may_be_named_with_a_hyphen_as_the_endpoint_spells_it():
    assert tg.fields("parcerias", "meta-proposta").equals(
        tg.fields("parcerias", "meta_proposta")
    )


def test_column_dtypes_cover_every_json_type_the_apis_publish():
    seen = set()
    for _, row in tg.tables().iterrows():
        seen.update(tg.fields(row["module"], row["table"])["dtype"])

    assert seen == {"Int64", "Float64", "boolean", "string", "datetime64[ns]", "object"}


def test_an_identifier_is_a_64_bit_integer_not_a_float():
    # The deliberate divergence from the R sibling: pandas has a nullable
    # 64-bit integer, so there is no need to trade exactness for a missing
    # value.
    frame = tg.fields("parcerias", "parceria").set_index("field")

    assert frame.loc["cd_parceria", "dtype"] == "Int64"
    assert frame.loc["cd_parceria", "api_type"] == "integer"


def test_every_table_records_the_endpoint_path_it_maps_to():
    frame = tg.tables()

    assert frame["path"].notna().all()
    assert (frame["path"] != frame["table"]).any()
    assert (frame["path"].str.replace("-", "_") == frame["table"]).all()


def test_a_nested_column_can_be_described():
    frame = tg.fields("parcerias", "programa")
    nested = frame.loc[frame["nested"].notna(), "field"].tolist()

    assert nested

    inner = tg.fields("parcerias", "programa", nested=nested[0])
    assert len(inner) > 0


def test_asking_for_a_nested_column_that_is_not_one_is_an_error():
    with pytest.raises(SchemaError):
        tg.fields("parcerias", "programa", nested="id_programa")
    with pytest.raises(SchemaError):
        tg.fields("parcerias", "parceria", nested="nao_existe")


def test_tables_lists_one_module_or_all_of_them():
    assert set(tg.tables("parcerias")["module"]) == {"parcerias"}
    assert len(tg.tables("parcerias")) == 15
    assert set(tg.tables()["module"]) == set(tg.modules()["module"])


def test_modules_reports_each_modules_own_base_url():
    frame = tg.modules()

    assert frame["url"].str.startswith("https://api-publica.").all()
    assert frame["tables"].sum() == 55


def test_the_schema_records_when_it_was_built():
    assert isinstance(tg.schema_date(), dt.date)


def test_counts_false_makes_no_request(mock):
    assert "rows" not in tg.tables().columns
    assert len(mock.calls) == 0


def test_counts_true_adds_one_row_count_per_table(mock):
    for table in tg.tables("parcerias")["path"]:
        add_body(mock, envelope("[]", total=42), table=table)

    frame = tg.tables("parcerias", counts=True)

    assert len(mock.calls) == 15
    assert list(frame["rows"]) == [42] * 15
