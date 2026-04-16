"""
Comprehensive tests for OData → DynamoDB FilterExpression translation.

Every operator and function in AstToDynamoVisitor is covered.  Each test
verifies that the generated expression string:
  1. Can be eval()'d with only `Attr` in scope (mirroring database.py behaviour)
  2. Produces a valid boto3 ConditionBase object
  3. Has the expected boto3 operator name

Known DynamoDB limitations should raise UnsupportedFunctionException cleanly.

OData syntax notes:
  • Use `le` / `ge` for ≤ / ≥  (OData standard, not `lte` / `gte`)
  • `not` on a bare comparison needs parentheses: `not (field eq val)`
    (without parens `not field eq val` is fine after the grammar precedence fix)
  • String lists for IN / BETWEEN: `('a', 'b')` — single-item needs trailing
    comma: `('a',)` to distinguish from a paren-grouped expression.
"""

import pytest
from boto3.dynamodb.conditions import Attr, ConditionBase

from dynamo_odata.odata_query import exceptions
from dynamo_odata.odata_query.dynamo import AstToDynamoVisitor
from dynamo_odata.odata_query.grammar import parse_odata

# Eval context for OData expressions — must include Attr since all generated
# expressions reference it by name.  Keep this dict assignment so the linter
# can see Attr is actually used (eval() strings are invisible to ruff/pyflakes).
_EVAL_CTX = {"Attr": Attr}


# ─── helpers ─────────────────────────────────────────────────────────────────


def build(filter_str: str):
    """
    Parse an OData filter string and return (expr_str, boto3_condition).

    Mirrors the eval() call used by the current filter translation path so tests reflect real
    runtime behaviour.
    """
    ast_tree = parse_odata(filter_str)
    visitor = AstToDynamoVisitor()
    expr_str = visitor.visit(ast_tree)
    condition = eval(expr_str, _EVAL_CTX)  # noqa: S307 – intentional, mirrors database.py
    assert isinstance(condition, ConditionBase), (
        f"Expected ConditionBase, got {type(condition).__name__} for: {filter_str!r}\n"
        f"Generated expression: {expr_str}"
    )
    return expr_str, condition


def visit_only(filter_str: str) -> str:
    """Run only the parse+visit phase (no eval)."""
    ast_tree = parse_odata(filter_str)
    visitor = AstToDynamoVisitor()
    return visitor.visit(ast_tree)


def op(condition: ConditionBase) -> str:
    """Return the boto3 operator string from a condition."""
    return condition.get_expression()["operator"]


def vals(condition: ConditionBase) -> tuple:
    """Return the values tuple from a condition expression."""
    return condition.get_expression()["values"]


# ─── 1. Comparison operators ──────────────────────────────────────────────────


class TestComparisonOperators:
    """eq, ne, lt, le, gt, ge against strings, integers, floats, booleans."""

    @pytest.mark.parametrize(
        "odata,expected_op",
        [
            ("name eq 'Alice'", "="),
            ("name ne 'Alice'", "<>"),
            ("age lt 25", "<"),
            ("age le 25", "<="),  # OData uses 'le', not 'lte'
            ("age gt 25", ">"),
            ("age ge 25", ">="),  # OData uses 'ge', not 'gte'
        ],
    )
    def test_basic_comparison(self, odata, expected_op):
        _, cond = build(odata)
        assert op(cond) == expected_op

    def test_eq_integer(self):
        _, cond = build("age eq 25")
        assert op(cond) == "="

    def test_eq_float(self):
        _, cond = build("score eq 9.5")
        assert op(cond) == "="

    def test_eq_boolean_true(self):
        _, cond = build("active eq true")
        assert op(cond) == "="
        assert vals(cond)[1] is True

    def test_eq_boolean_false(self):
        _, cond = build("active eq false")
        assert op(cond) == "="
        assert vals(cond)[1] is False

    def test_string_with_escaped_single_quote(self):
        """Single quotes inside strings must be escaped as ''."""
        _, cond = build("name eq 'O''Brien'")
        assert op(cond) == "="

    def test_note_le_ge_not_lte_gte(self):
        """OData uses 'le'/'ge'; 'lte'/'gte' are not valid tokens."""
        with pytest.raises(exceptions.ODataException):
            visit_only("age lte 25")
        with pytest.raises(exceptions.ODataException):
            visit_only("age gte 25")


# ─── 2. Null handling ─────────────────────────────────────────────────────────


class TestNullHandling:
    """
    DynamoDB has two 'empty' states:
      State 1 – attribute absent (never stored / remove_key'd)
      State 2 – attribute exists with NULL type (Python None on write)

    'field eq null' must catch BOTH; 'field ne null' must require a real value.
    """

    def test_eq_null_produces_or_condition(self):
        _, cond = build("status eq null")
        assert op(cond) == "OR"

    def test_eq_null_left_is_attribute_not_exists(self):
        _, cond = build("status eq null")
        assert op(vals(cond)[0]) == "attribute_not_exists"

    def test_eq_null_right_is_attribute_type_null(self):
        _, cond = build("status eq null")
        type_cond = vals(cond)[1]
        assert op(type_cond) == "attribute_type"
        assert vals(type_cond)[1] == "NULL"

    def test_ne_null_produces_and_condition(self):
        _, cond = build("status ne null")
        assert op(cond) == "AND"

    def test_ne_null_left_is_attribute_exists(self):
        _, cond = build("status ne null")
        assert op(vals(cond)[0]) == "attribute_exists"

    def test_ne_null_right_is_not_attribute_type(self):
        _, cond = build("status ne null")
        assert op(vals(cond)[1]) == "NOT"

    def test_eq_null_combined_with_and(self):
        _, cond = build("status eq null and role_id ne null")
        assert op(cond) == "AND"

    def test_eq_null_combined_with_or(self):
        _, cond = build("status eq null or status ne null")
        assert op(cond) == "OR"


# ─── 3. Boolean logic ─────────────────────────────────────────────────────────


class TestBooleanLogic:
    def test_and(self):
        _, cond = build("a eq 'x' and b eq 'y'")
        assert op(cond) == "AND"

    def test_or(self):
        _, cond = build("a eq 'x' or b eq 'y'")
        assert op(cond) == "OR"

    def test_not_bare_compare(self):
        """not field eq val  — should work without parens after grammar fix."""
        _, cond = build("not a eq 'x'")
        assert op(cond) == "NOT"

    def test_not_parenthesized_compare(self):
        _, cond = build("not (a eq 'x')")
        assert op(cond) == "NOT"

    def test_not_parenthesized_boolop(self):
        _, cond = build("not (a eq 'x' and b eq 'y')")
        assert op(cond) == "NOT"

    def test_three_way_and(self):
        _, cond = build("a eq 'x' and b eq 'y' and c eq 'z'")
        assert op(cond) == "AND"

    def test_three_way_or(self):
        _, cond = build("a eq 'x' or b eq 'y' or c eq 'z'")
        assert op(cond) == "OR"

    def test_and_with_or_left_paren(self):
        _, cond = build("(a eq 'x' or b eq 'y') and c eq 'z'")
        assert op(cond) == "AND"
        assert op(vals(cond)[0]) == "OR"

    def test_and_with_or_right_paren(self):
        _, cond = build("a eq 'x' and (b eq 'y' or c eq 'z')")
        assert op(cond) == "AND"
        assert op(vals(cond)[1]) == "OR"

    def test_not_and_precedence(self):
        """
        not a eq 'x' and b eq 'y'
        After grammar fix: NOT has lower precedence than EQ but higher than AND,
        so this parses as  (not (a eq 'x')) and (b eq 'y').
        """
        _, cond = build("not a eq 'x' and b eq 'y'")
        assert op(cond) == "AND"
        assert op(vals(cond)[0]) == "NOT"

    def test_double_not(self):
        _, cond = build("not (not (a eq 'x'))")
        assert op(cond) == "NOT"


# ─── 4. String functions ──────────────────────────────────────────────────────


class TestStringFunctions:
    def test_contains(self):
        _, cond = build("contains(name, 'Jo')")
        assert op(cond) == "contains"

    def test_not_contains(self):
        """Regression: the original 'NOT' → SyntaxError bug."""
        _, cond = build("not contains(name, 'Jo')")
        assert op(cond) == "NOT"
        assert op(vals(cond)[0]) == "contains"

    def test_startswith(self):
        _, cond = build("startswith(name, 'Jo')")
        assert op(cond) == "begins_with"

    def test_not_startswith(self):
        _, cond = build("not startswith(name, 'Jo')")
        assert op(cond) == "NOT"
        assert op(vals(cond)[0]) == "begins_with"

    def test_contains_combined_with_and(self):
        _, cond = build("contains(name, 'Jo') and age gt 18")
        assert op(cond) == "AND"

    def test_not_contains_combined_with_and(self):
        """Mirrors the smart-group delta query pattern."""
        _, cond = build("not contains(groups, 'grp1') and status eq 'active'")
        assert op(cond) == "AND"
        assert op(vals(cond)[0]) == "NOT"

    def test_contains_combined_with_or(self):
        _, cond = build("contains(name, 'Smith') or contains(name, 'Jones')")
        assert op(cond) == "OR"

    def test_tolower_on_field_name(self):
        """
        tolower() applied to a field identifier just lowercases the identifier
        string — happens to produce a valid Attr() call for lowercase field names.
        """
        _, cond = build("tolower(name) eq 'alice'")
        assert op(cond) == "="


# ─── 5. Attribute existence ───────────────────────────────────────────────────


class TestAttributeExistence:
    def test_exists(self):
        _, cond = build("field exists")
        assert op(cond) == "attribute_exists"

    def test_not_exists(self):
        _, cond = build("field not_exists")
        assert op(cond) == "attribute_not_exists"

    def test_exists_combined_with_and(self):
        _, cond = build("field exists and status eq 'active'")
        assert op(cond) == "AND"

    def test_not_exists_combined(self):
        _, cond = build("field not_exists or status ne null")
        assert op(cond) == "OR"


# ─── 6. IN operator ───────────────────────────────────────────────────────────


class TestInOperator:
    def test_in_two_strings(self):
        _, cond = build("status in ('active', 'pending')")
        assert op(cond) == "IN"

    def test_in_three_integers(self):
        _, cond = build("age in (18, 21, 25)")
        assert op(cond) == "IN"

    def test_not_in(self):
        _, cond = build("not status in ('active', 'pending')")
        assert op(cond) == "NOT"
        assert op(vals(cond)[0]) == "IN"

    def test_in_combined_with_and(self):
        _, cond = build("status in ('active', 'pending') and age gt 18")
        assert op(cond) == "AND"


# ─── 7. BETWEEN operator ──────────────────────────────────────────────────────


class TestBetweenOperator:
    """BETWEEN must call Attr.between(low, high) with two separate args."""

    def test_between_integers(self):
        _, cond = build("age between (18, 65)")
        assert op(cond) == "BETWEEN"

    def test_between_strings(self):
        _, cond = build("name between ('A', 'Z')")
        assert op(cond) == "BETWEEN"

    def test_not_between(self):
        """
        'not age between (18, 65)' parses as '(not age) between (18, 65)' because
        BETWEEN has no precedence entry, causing NOT to reduce first.
        Use explicit parens: 'not (age between (18, 65))'.
        """
        _, cond = build("not (age between (18, 65))")
        assert op(cond) == "NOT"
        assert op(vals(cond)[0]) == "BETWEEN"

    def test_between_combined_with_and(self):
        _, cond = build("age between (18, 65) and active eq true")
        assert op(cond) == "AND"


# ─── 8. Compound realistic queries ───────────────────────────────────────────


class TestCompoundQueries:
    """End-to-end filters that mirror real production usage."""

    def test_smart_group_to_add(self):
        """Users matching rules who are NOT yet in the group."""
        _, cond = build("not contains(groups, 'grp1') and (status eq 'active')")
        assert op(cond) == "AND"

    def test_smart_group_to_remove(self):
        """Members who no longer match the rules."""
        _, cond = build("contains(groups, 'grp1') and not (status eq 'active')")
        assert op(cond) == "AND"

    def test_smart_group_staying(self):
        """Members who still match the rules."""
        _, cond = build("contains(groups, 'grp1') and (status eq 'active')")
        assert op(cond) == "AND"

    def test_multi_rule_group_filter(self):
        _, cond = build(
            "status eq 'active' and role_id ne null and contains(name, 'Smith')"
        )
        assert op(cond) == "AND"

    def test_complex_or_and_mix(self):
        _, cond = build(
            "(startswith(first_name, 'A') or startswith(last_name, 'B')) and active eq true"
        )
        assert op(cond) == "AND"
        assert op(vals(cond)[0]) == "OR"

    def test_null_plus_contains_plus_comparison(self):
        _, cond = build("status ne null and contains(groups, 'admins') and age ge 18")
        assert op(cond) == "AND"

    def test_deeply_nested_not(self):
        _, cond = build("not (status eq 'inactive' or status eq null)")
        assert op(cond) == "NOT"

    def test_four_clause_and_chain(self):
        _, cond = build("a eq '1' and b eq '2' and c eq '3' and d eq '4'")
        assert op(cond) == "AND"


# ─── 9. Known unsupported (DynamoDB can't represent these) ───────────────────


class TestUnsupportedFunctions:
    """
    Functions DynamoDB cannot represent should fail explicitly during translation.
    """

    def test_endswith_raises_unsupported(self):
        """endswith raises immediately at visit time — clean error."""
        with pytest.raises(exceptions.UnsupportedFunctionException):
            visit_only("endswith(name, 'son')")

    def test_toupper_on_field(self):
        with pytest.raises(exceptions.UnsupportedFunctionException):
            build("toupper(name) eq 'ALICE'")

    def test_trim_on_field(self):
        with pytest.raises(exceptions.UnsupportedFunctionException):
            build("trim(name) eq 'Alice'")

    def test_indexof(self):
        with pytest.raises(exceptions.UnsupportedFunctionException):
            build("indexof(name, 'Jo') eq 0")

    def test_length(self):
        with pytest.raises(exceptions.UnsupportedFunctionException):
            build("length(name) gt 5")

    def test_substring(self):
        with pytest.raises(exceptions.UnsupportedFunctionException):
            build("substring(name, 0, 3) eq 'Ali'")

    def test_concat(self):
        with pytest.raises(exceptions.UnsupportedFunctionException):
            build("concat(first_name, last_name) eq 'AliceBrown'")

    def test_year(self):
        with pytest.raises(exceptions.UnsupportedFunctionException):
            build("year(created_at) eq 2024")

    def test_month(self):
        with pytest.raises(exceptions.UnsupportedFunctionException):
            build("month(created_at) eq 12")

    def test_day(self):
        with pytest.raises(exceptions.UnsupportedFunctionException):
            build("day(created_at) eq 25")
