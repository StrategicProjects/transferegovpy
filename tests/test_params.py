"""Filters are the endpoints' own query parameters.

There is no operator vocabulary to test; what matters is that a name or value
the API would ignore or reject never reaches it.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

import transferegovpy as tg
from transferegovpy import _params
from transferegovpy._errors import FilterError


def encode(module="parcerias", table="parceria", **filters):
    return _params.encode(module, table, filters)


def test_a_bare_value_becomes_the_parameters_value():
    assert encode(in_situacao_parceria="Aprovada") == [
        ("in_situacao_parceria", "Aprovada")
    ]
    assert encode(id_parceria=37840) == [("id_parceria", "37840")]


def test_several_filters_are_separate_parameters():
    assert encode(
        "parcerias", "proposta", situacao_proposta="Aprovada", sg_uf_recebedor="PE"
    ) == [("situacao_proposta", "Aprovada"), ("sg_uf_recebedor", "PE")]


def test_no_filters_produce_no_parameters():
    assert encode() == []


def test_none_drops_the_filter():
    assert encode(id_parceria=None) == []


# Encoding --------------------------------------------------------------------


def test_a_large_identifier_is_not_scientific_notation():
    assert encode(cd_parceria=202500037062) == [("cd_parceria", "202500037062")]
    assert encode(cd_parceria=100000.0) == [("cd_parceria", "100000")]


def test_dates_and_times_are_formatted_as_declared():
    assert encode(dh_assinatura=dt.date(2025, 3, 4)) == [
        ("dh_assinatura", "2025-03-04")
    ]
    assert encode(dh_assinatura=dt.datetime(2025, 3, 4, 5, 6, 7)) == [
        ("dh_assinatura", "2025-03-04T05:06:07")
    ]


def test_booleans_become_true_and_false():
    assert encode("especiais", "planos_acao_especiais", id_plano_acao=True) == [
        ("id_plano_acao", "true")
    ]


# Unknown parameters ----------------------------------------------------------
#
# The service answers 200 and ignores a parameter it does not recognise, so
# these are the tests that stop a typo returning the whole table.


def test_an_unknown_parameter_is_an_error_not_a_request():
    with pytest.raises(FilterError, match="Unknown filter"):
        encode("parcerias", "proposta", in_situacao_proposta="Aprovada")


def test_the_error_explains_why_an_ignored_parameter_is_dangerous():
    with pytest.raises(FilterError) as excinfo:
        encode("parcerias", "proposta", in_situacao_proposta="Aprovada")

    message = str(excinfo.value)
    assert "ignores a parameter it does not recognise" in message
    assert "returns every row" in message
    assert "'situacao_proposta'" in message      # the suggestion


def test_a_name_unlike_anything_known_gets_no_suggestion():
    with pytest.raises(FilterError) as excinfo:
        encode("parcerias", "proposta", zzzzzzzz=1)
    assert "Did you mean" not in str(excinfo.value)


def test_validation_can_be_switched_off_for_a_new_parameter():
    tg.configure(validate=False)
    try:
        assert encode("parcerias", "proposta", brand_new=1) == [("brand_new", "1")]
    finally:
        tg.configure(validate=True)


def test_a_column_that_is_not_filterable_is_still_unknown():
    # meta_proposta returns six columns and accepts twelve parameters, and the
    # two sets are not the same: filtering is not selecting.
    columns = set(tg.fields("parcerias", "meta_proposta")["field"])
    accepted = set(tg.params("parcerias", "meta_proposta")["param"])
    unfilterable = sorted(columns - accepted)

    if not unfilterable:
        pytest.skip("every column is filterable here")

    with pytest.raises(FilterError):
        encode("parcerias", "meta_proposta", **{unfilterable[0]: 1})


# Enumerated values -----------------------------------------------------------


def test_a_permitted_value_passes():
    assert encode("parcerias", "proposta", situacao_proposta="Aprovada") == [
        ("situacao_proposta", "Aprovada")
    ]


def test_a_value_outside_the_enumeration_is_rejected_with_the_list():
    with pytest.raises(FilterError) as excinfo:
        encode("parcerias", "proposta", situacao_proposta="Aprovado")

    message = str(excinfo.value)
    assert "not a permitted value" in message
    assert "'Aprovada'" in message


def test_enumerations_are_case_sensitive_as_the_api_is():
    with pytest.raises(FilterError):
        encode("parcerias", "proposta", sg_uf_recebedor="pe")


# Shapes the API cannot express -----------------------------------------------


def test_several_values_for_one_parameter_are_refused():
    with pytest.raises(FilterError, match="accepts one"):
        encode("parcerias", "proposta", sg_uf_recebedor=["PE", "PB"])


def test_a_missing_value_is_refused():
    with pytest.raises(FilterError, match="must not be missing"):
        encode(id_parceria=pd.NA)
    with pytest.raises(FilterError, match="must not be missing"):
        encode(id_parceria=float("nan"))


# Discovery -------------------------------------------------------------------


def test_params_describes_what_the_endpoint_accepts():
    frame = tg.params("parcerias", "proposta")

    assert list(frame.columns) == [
        "param", "dtype", "api_type", "values", "pattern", "description"
    ]
    assert "situacao_proposta" in set(frame["param"])


def test_enumerated_parameters_carry_values_and_the_rest_are_empty():
    frame = tg.params("parcerias", "proposta").set_index("param")

    assert "Aprovada" in frame.loc["situacao_proposta", "values"]
    assert frame.loc["id_proposta", "values"] == []
