import pytest

import transferegovpy as tg
from transferegovpy import _schema

from .conftest import add_body


def test_the_frozen_schema_covers_three_modules_and_forty_eight_tables():
    assert len(tg.modules()) == 3
    assert len(tg.tables()) == 48
    assert int(tg.tables()["columns"].sum()) == 599


@pytest.mark.parametrize(
    "given,expected",
    [
        ("ted", "ted"),
        ("TED", "ted"),
        ("fundoafundo", "fundoafundo"),
        ("fundo_a_fundo", "fundoafundo"),
        ("fundo a fundo", "fundoafundo"),
        ("fund_to_fund", "fundoafundo"),
        ("transferenciasespeciais", "transferenciasespeciais"),
        ("transferencias_especiais", "transferenciasespeciais"),
        (" especiais ", "transferenciasespeciais"),
    ],
)
def test_module_names_aliases_case_and_punctuation_resolve(given, expected):
    assert _schema.match_module(given) == expected


def test_an_unknown_module_is_rejected():
    with pytest.raises(tg.SchemaError, match="Unknown module"):
        _schema.match_module("xpto")
    with pytest.raises(tg.SchemaError):
        _schema.match_module(1)


def test_a_table_missing_from_one_module_points_at_the_module_that_has_it():
    # `plano_acao` exists in fundoafundo and ted with different columns, so a
    # miss is usually the wrong module rather than a typo.
    with pytest.raises(tg.SchemaError, match="fundoafundo"):
        tg.fields("transferenciasespeciais", "plano_acao")


def test_tables_carrying_the_same_name_differ_between_modules():
    assert list(tg.fields("ted", "plano_acao")["field"]) != list(
        tg.fields("fundoafundo", "plano_acao")["field"]
    )


def test_column_dtypes_cover_every_postgres_type_the_apis_publish():
    seen = set()
    for _, row in tg.tables().iterrows():
        seen.update(tg.fields(row["module"], row["table"])["dtype"])

    assert seen == {"string", "Int64", "Float64", "boolean", "datetime64[ns]"}


def test_bigint_is_a_64_bit_integer_not_a_float():
    fields = tg.fields("ted", "plano_acao")
    bigint = fields[fields["pg_type"] == "bigint"]

    assert len(bigint) > 0
    assert set(bigint["dtype"]) == {"Int64"}


def test_the_default_order_names_real_columns_of_the_table():
    for _, row in tg.tables().iterrows():
        order = _schema.default_order(row["module"], row["table"])
        known = set(tg.fields(row["module"], row["table"])["field"])

        assert order
        assert all(o.endswith(".asc") for o in order)
        assert {o[: -len(".asc")] for o in order} <= known


def test_the_default_order_prefers_a_declared_primary_key():
    assert _schema.default_order("fundoafundo", "plano_acao") == ["id_plano_acao.asc"]
    # ted/plano_acao declares no primary key, so identifier columns are used.
    assert len(_schema.default_order("ted", "plano_acao")) > 1


def test_tables_lists_one_module_or_all_of_them():
    assert set(tg.tables("ted")["module"]) == {"ted"}
    assert len(tg.tables("ted")) == 13
    assert set(tg.tables()["module"]) == set(tg.modules()["module"])


def test_counts_false_makes_no_request(mock):
    # The schema half must stay usable offline; only `counts` touches the wire.
    assert "rows" not in tg.tables().columns
    assert len(mock.calls) == 0


def test_counts_true_adds_one_row_count_per_table(mock):
    # One request per table, so each table's URL needs its own response.
    for table in tg.tables("ted")["table"]:
        add_body(mock, "[]", content_range="*/42", table=table)

    result = tg.tables("ted", counts=True)

    assert len(mock.calls) == 13
    assert list(result["rows"]) == [42] * 13


def test_the_schema_records_when_it_was_built():
    import datetime as dt

    assert isinstance(tg.schema_date(), dt.date)


def test_an_unknown_filter_column_is_rejected_before_any_request(mock):
    # The service would answer 400 anyway, but failing here names the column
    # and costs no round trip.
    with pytest.raises(tg.SchemaError, match="coluna_falsa"):
        tg.get("ted", "plano_acao", coluna_falsa=1)

    assert len(mock.calls) == 0


def test_an_unknown_selected_column_is_rejected():
    with pytest.raises(tg.SchemaError, match="selected"):
        tg.get("ted", "plano_acao", select=["nao_existe"])


def test_an_unknown_ordering_column_is_rejected():
    with pytest.raises(tg.SchemaError, match="ordering"):
        tg.get("ted", "plano_acao", order="nao_existe.desc")


def test_count_rejects_an_unknown_filter_column():
    with pytest.raises(tg.SchemaError):
        tg.count("ted", "plano_acao", coluna_falsa=1)


def test_the_error_points_at_the_schema_date_and_the_escape_hatch():
    with pytest.raises(tg.SchemaError, match="validate=False"):
        tg.get("ted", "plano_acao", coluna_falsa=1)


def test_validation_can_be_turned_off_for_a_column_added_upstream(mock):
    from .conftest import add_page, query_of

    tg.configure(validate=False)
    add_page(mock, 1, total=1)

    tg.get("ted", "plano_acao", coluna_nova=1, limit=1)

    assert dict(query_of(mock.calls[0]))["coluna_nova"] == "eq.1"


def test_order_direction_and_null_placement_are_stripped_before_checking(mock):
    from .conftest import add_page

    add_page(mock, 1, total=1)

    tg.get(
        "ted",
        "plano_acao",
        order=["id_plano_acao.desc.nullslast", "id_programa.asc", "aa_instrumento"],
        limit=1,
    )

    assert len(mock.calls) == 1


def test_a_select_carrying_postgrest_syntax_is_passed_through_unchecked(mock):
    from .conftest import add_page

    add_page(mock, 1, total=1)

    tg.get("ted", "plano_acao", select=["apelido:id_plano_acao"], limit=1)

    assert len(mock.calls) == 1
