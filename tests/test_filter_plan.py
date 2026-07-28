"""build_filter_plan: the server/client split that makes tolower() real.

The bug these pin: ``contains(tolower(name),'x')`` compiled to a plain,
case-SENSITIVE ``Attr(name).contains('x')`` — a filter that parses, runs, and
returns an empty page for any capitalized value. Asserting on the emitted
expression string cannot catch that (the string is exactly what the code
produces); these assert on *which items survive*.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from boto3.dynamodb.conditions import ConditionBase

from dynamo_odata import FilterPolicy, FilterPolicyViolationError, build_filter_plan
from dynamo_odata.odata_query import exceptions

ITEMS = [
    {"name": "Fabry disease", "status": "active", "age": Decimal("40")},
    {"name": "fabry variant", "status": "archived", "age": Decimal("10")},
    {"name": "Gaucher disease", "status": "active", "age": Decimal("55")},
    {"status": "active"},  # no `name` attribute at all
]


def names(items):
    return [i.get("name") for i in items]


class TestSplit:
    def test_plain_filter_has_no_residual(self):
        plan = build_filter_plan("status eq 'active'")
        assert isinstance(plan.condition, ConditionBase)
        assert plan.has_residual is False
        assert plan.residual_fields == frozenset()
        # No residual means no client-side pass — items come back untouched.
        assert plan.apply(ITEMS) == ITEMS

    def test_case_folding_filter_is_entirely_residual(self):
        plan = build_filter_plan("contains(tolower(name),'fabry')")
        assert plan.condition is None
        assert plan.has_residual is True
        assert plan.residual_fields == frozenset({"name"})

    def test_conjunction_splits_across_both_sides(self):
        plan = build_filter_plan("status eq 'active' and contains(tolower(name),'fabry')")
        assert plan.condition is not None
        assert plan.condition.get_expression()["operator"] == "="
        assert plan.residual_fields == frozenset({"name"})

    def test_case_folding_under_or_moves_the_whole_conjunct(self):
        plan = build_filter_plan("contains(tolower(name),'fabry') or status eq 'archived'")
        # Correct but costlier: the OR cannot be split, so it evaluates client-side.
        assert plan.condition is None
        assert plan.residual_fields == frozenset({"name", "status"})
        assert names(plan.apply(ITEMS)) == ["Fabry disease", "fabry variant"]

    def test_policy_still_validated(self):
        policy = FilterPolicy(allowed_fields=frozenset({"status"}))
        with pytest.raises(FilterPolicyViolationError):
            build_filter_plan("contains(tolower(name),'fabry')", policy=policy)


class TestCaseInsensitiveMatching:
    def test_lowercase_needle_matches_capitalized_value(self):
        plan = build_filter_plan("contains(tolower(name),'fabry')")
        assert names(plan.apply(ITEMS)) == ["Fabry disease", "fabry variant"]

    def test_the_regression_case_from_the_issue(self):
        # "Fabry disease" contains 'disease' verbatim, so the old code found it;
        # 'fabry' — capitalized in the data — is what returned nothing.
        assert names(build_filter_plan("contains(tolower(name),'disease')").apply(ITEMS)) == [
            "Fabry disease",
            "Gaucher disease",
        ]

    def test_toupper(self):
        plan = build_filter_plan("contains(toupper(name),'FABRY')")
        assert names(plan.apply(ITEMS)) == ["Fabry disease", "fabry variant"]

    def test_equality_under_fold(self):
        plan = build_filter_plan("tolower(name) eq 'fabry disease'")
        assert names(plan.apply(ITEMS)) == ["Fabry disease"]

    def test_startswith_under_fold(self):
        plan = build_filter_plan("startswith(tolower(name),'fab')")
        assert names(plan.apply(ITEMS)) == ["Fabry disease", "fabry variant"]

    def test_missing_attribute_never_matches(self):
        plan = build_filter_plan("contains(tolower(name),'')")
        # Every present name contains the empty string; the attribute-less item
        # does not, because a missing attribute fails every predicate.
        assert len(plan.apply(ITEMS)) == 3


class TestDynamoSemanticsAreMirrored:
    """A conjunct means the same thing whichever side evaluates it.

    Each expression here is written so the WHOLE thing lands in the residual —
    a plain conjunct would be handed to DynamoDB and ``apply`` would (rightly)
    leave it alone.  ``or contains(tolower(name),'zzz')`` is a never-matching
    folded disjunct that forces client-side evaluation without changing the
    result.
    """

    def test_ne_is_false_for_a_missing_attribute(self):
        # DynamoDB requires the attribute to exist before any comparator applies,
        # so `ne` does NOT match the item that has no `name`.
        plan = build_filter_plan("tolower(name) ne 'fabry disease'")
        assert names(plan.apply(ITEMS)) == ["fabry variant", "Gaucher disease"]

    def test_type_mismatch_is_false_not_an_error(self):
        plan = build_filter_plan("age gt 'abc' or contains(tolower(name),'zzz')")
        assert plan.apply(ITEMS) == []

    def test_numeric_comparison_spans_decimal_and_int(self):
        plan = build_filter_plan("age ge 40 or contains(tolower(name),'zzz')")
        assert names(plan.apply(ITEMS)) == ["Fabry disease", "Gaucher disease"]

    def test_not_of_a_folded_predicate(self):
        plan = build_filter_plan("not contains(tolower(name),'fabry')")
        assert names(plan.apply(ITEMS)) == ["Gaucher disease", None]

    def test_exists_and_not_exists(self):
        exists = build_filter_plan("name exists or contains(tolower(name),'zzz')")
        assert names(exists.apply(ITEMS)) == ["Fabry disease", "fabry variant", "Gaucher disease"]
        absent = build_filter_plan("name not_exists or contains(tolower(name),'zzz')")
        assert names(absent.apply(ITEMS)) == [None]

    def test_null_comparison(self):
        assert names(build_filter_plan("name eq null or contains(tolower(name),'zzz')").apply(ITEMS)) == [None]

    def test_in_and_between(self):
        in_plan = build_filter_plan("status in ('archived',) or contains(tolower(name),'zzz')")
        assert names(in_plan.apply(ITEMS)) == ["fabry variant"]
        between = build_filter_plan("age between (11, 50) or contains(tolower(name),'zzz')")
        assert names(between.apply(ITEMS)) == ["Fabry disease"]

    def test_unsupported_function_inside_a_residual_still_raises(self):
        plan = build_filter_plan("endswith(tolower(name),'disease')")
        with pytest.raises(exceptions.UnsupportedFunctionException):
            plan.apply(ITEMS)
