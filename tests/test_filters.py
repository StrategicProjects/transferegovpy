import datetime as dt

import pytest

import transferegovpy as tg
from transferegovpy.filters import to_params


def test_bare_value_is_equals_and_bare_list_is_one_of():
    assert to_params({"a": 2024}) == [("a", "eq.2024")]
    assert to_params({"uf": ["PE", "PB"]}) == [("uf", 'in.("PE","PB")')]


def test_each_operator_serialises_to_its_postgrest_form():
    assert str(tg.eq(1)) == "eq.1"
    assert str(tg.neq(1)) == "neq.1"
    assert str(tg.gt(1)) == "gt.1"
    assert str(tg.gte(1)) == "gte.1"
    assert str(tg.lt(1)) == "lt.1"
    assert str(tg.lte(1)) == "lte.1"
    assert str(tg.like("*a*")) == "like.*a*"
    assert str(tg.ilike("*a*")) == "ilike.*a*"
    assert str(tg.re_match("^a")) == "match.^a"
    assert str(tg.re_imatch("^a")) == "imatch.^a"
    assert str(tg.is_null()) == "is.null"
    assert str(tg.is_true()) == "is.true"
    assert str(tg.is_false()) == "is.false"
    assert str(tg.not_(tg.eq(1))) == "not.eq.1"
    assert str(tg.not_(tg.is_null())) == "not.is.null"


def test_every_documented_operator_is_exported():
    assert set(tg.operators()["operator"]) <= set(tg.__all__)


def test_dates_and_times_are_formatted_the_way_the_api_reads_them():
    assert str(tg.gte(dt.date(2024, 3, 1))) == "gte.2024-03-01"
    assert str(tg.lt(dt.datetime(2024, 3, 1, 10, 20, 30))) == "lt.2024-03-01T10:20:30"


def test_booleans_become_true_and_false():
    # `isinstance(True, int)` is True in Python, so the bool branch has to come
    # first or these would serialise as 1 and 0.
    assert str(tg.eq(True)) == "eq.true"
    assert str(tg.eq(False)) == "eq.false"


def test_numbers_avoid_scientific_notation():
    # "1e+05" would be compared as text against a numeric column and match
    # nothing, returning an empty result rather than an error.
    assert str(tg.eq(100000)) == "eq.100000"
    assert str(tg.gte(1234567890123)) == "gte.1234567890123"
    assert str(tg.eq(0.5)) == "eq.0.5"
    assert str(tg.eq(1e5)) == "eq.100000"


def test_values_carrying_postgrest_structure_are_quoted():
    # An unquoted comma would be read as a separator and widen the match.
    assert str(tg.eq("a,b")) == 'eq."a,b"'
    assert str(tg.eq("(x)")) == 'eq."(x)"'
    assert str(tg.eq(" pad ")) == 'eq." pad "'
    assert str(tg.eq("")) == 'eq.""'


def test_quotes_and_backslashes_are_escaped():
    assert str(tg.eq('say "hi"')) == 'eq."say \\"hi\\""'
    assert str(tg.eq("back\\slash")) == 'eq."back\\\\slash"'


def test_a_value_needing_no_quoting_is_left_alone():
    # Quoting a `like` pattern would change what it matches, not just how it
    # looks, so quoting must stay narrow.
    assert str(tg.like("*saude*")) == "like.*saude*"
    assert str(tg.eq("2024-01-01")) == "eq.2024-01-01"
    assert str(tg.eq("a.b")) == "eq.a.b"


def test_every_string_element_of_in_is_quoted():
    # Strings are always quoted so an unquoted comma inside a value cannot be
    # read as a separator. Numbers need no quoting and get none, which is what
    # the R sibling sends too.
    assert str(tg.in_(["a", "b,c"])) == 'in.("a","b,c")'
    assert str(tg.in_([1, 2])) == "in.(1,2)"


def test_a_list_of_operators_becomes_repeated_parameters():
    params = to_params({"dt": [tg.gte("2024-01-01"), tg.lt("2025-01-01")]})
    assert params == [("dt", "gte.2024-01-01"), ("dt", "lt.2025-01-01")]


def test_a_none_filter_is_dropped_rather_than_sent():
    assert to_params({"a": None}) == []


def test_missing_values_are_rejected_with_a_pointer_to_is_null():
    with pytest.raises(tg.FilterError, match="is_null"):
        tg.eq(None)
    with pytest.raises(tg.FilterError, match="is_null"):
        tg.in_([1, None])
    with pytest.raises(tg.FilterError, match="is_null"):
        to_params({"a": [1, None]})


def test_operators_reject_operands_of_the_wrong_shape():
    with pytest.raises(tg.FilterError):
        tg.eq([1, 2])
    with pytest.raises(tg.FilterError):
        tg.like(1)
    with pytest.raises(tg.FilterError):
        tg.in_([])
    with pytest.raises(tg.FilterError):
        tg.in_("PE")  # a string is a sequence; it must not be read as one


def test_not_needs_a_filter_and_refuses_to_double_negate():
    with pytest.raises(tg.FilterError):
        tg.not_(1)
    with pytest.raises(tg.FilterError):
        tg.not_(tg.not_(tg.eq(1)))


def test_a_column_mixing_operators_and_values_errors():
    with pytest.raises(tg.FilterError, match="one or the other"):
        to_params({"a": [tg.gte(1), 2]})
    with pytest.raises(tg.FilterError):
        to_params({"a": []})


def test_a_filter_reprs_as_the_string_it_will_send():
    assert "gte.2024" in repr(tg.gte(2024))
