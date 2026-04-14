import pytest

from boto3.dynamodb.conditions import ConditionBase

from dynamo_odata import build_filter
from dynamo_odata.odata_query import exceptions


def op(condition: ConditionBase) -> str:
    return condition.get_expression()["operator"]


def vals(condition: ConditionBase) -> tuple:
    return condition.get_expression()["values"]


class TestBuildFilter:
    def test_basic_eq(self):
        cond = build_filter("name eq 'Alice'")
        assert isinstance(cond, ConditionBase)
        assert op(cond) == "="

    def test_basic_ne(self):
        cond = build_filter("name ne 'Alice'")
        assert op(cond) == "<>"

    def test_and_condition(self):
        cond = build_filter("status eq 'active' and age gt 18")
        assert op(cond) == "AND"

    def test_or_condition(self):
        cond = build_filter("status eq 'active' or status eq 'pending'")
        assert op(cond) == "OR"

    def test_not_condition(self):
        cond = build_filter("not (status eq 'inactive')")
        assert op(cond) == "NOT"

    def test_eq_null(self):
        cond = build_filter("status eq null")
        assert op(cond) == "OR"
        assert op(vals(cond)[0]) == "attribute_not_exists"
        assert op(vals(cond)[1]) == "attribute_type"

    def test_ne_null(self):
        cond = build_filter("status ne null")
        assert op(cond) == "AND"
        assert op(vals(cond)[0]) == "attribute_exists"
        assert op(vals(cond)[1]) == "NOT"

    def test_exists_function(self):
        cond = build_filter("field exists")
        assert op(cond) == "attribute_exists"

    def test_not_exists_function(self):
        cond = build_filter("field not_exists")
        assert op(cond) == "attribute_not_exists"

    def test_contains_function(self):
        cond = build_filter("contains(name, 'Jo')")
        assert op(cond) == "contains"

    def test_startswith_function(self):
        cond = build_filter("startswith(name, 'Jo')")
        assert op(cond) == "begins_with"

    def test_in_operator(self):
        cond = build_filter("status in ('active', 'pending')")
        assert op(cond) == "IN"

    def test_between_operator(self):
        cond = build_filter("age between (18, 65)")
        assert op(cond) == "BETWEEN"

    def test_tolower_field_compare(self):
        cond = build_filter("tolower(name) eq 'alice'")
        assert op(cond) == "="

    def test_unsupported_function_raises(self):
        with pytest.raises(exceptions.UnsupportedFunctionException):
            build_filter("endswith(name, 'son')")
