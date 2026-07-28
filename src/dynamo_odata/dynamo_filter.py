from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from boto3.dynamodb.conditions import Attr, ConditionBase

from .guardrails import FilterPolicy
from .odata_query import ast, exceptions, visitor
from .odata_query.grammar import parse_odata
from .residual import CASE_FOLDING_FUNCTIONS, evaluate, referenced_roots, uses_case_folding


class AstToDynamoConditionVisitor(visitor.NodeVisitor):
    """Build boto3 DynamoDB conditions directly from the OData AST."""

    def visit_Identifier(self, node: ast.Identifier) -> str:
        return ".".join((*node.namespace, node.name)) if node.namespace else node.name

    def visit_Attribute(self, node: ast.Attribute) -> str:
        owner = self.visit(node.owner)
        return f"{owner}.{node.attr}"

    def visit_Integer(self, node: ast.Integer) -> int:
        return node.py_val

    def visit_Float(self, node: ast.Float) -> float:
        return node.py_val

    def visit_Boolean(self, node: ast.Boolean) -> bool:
        return node.py_val

    def visit_String(self, node: ast.String) -> str:
        return node.py_val

    def visit_Null(self, node: ast.Null) -> None:
        return None

    def visit_GUID(self, node: ast.GUID):
        return node.py_val

    def visit_Date(self, node: ast.Date):
        return node.py_val

    def visit_Time(self, node: ast.Time):
        return node.py_val

    def visit_DateTime(self, node: ast.DateTime):
        return node.py_val

    def visit_Duration(self, node: ast.Duration):
        return node.py_val

    def visit_List(self, node: ast.List) -> list:
        return [self.visit(item) for item in node.val]

    def visit_Function(self, node: ast.Function) -> ConditionBase:
        field_name = self._field_name(node.left)
        if isinstance(node.function, ast.Exists):
            return Attr(field_name).exists()
        if isinstance(node.function, ast.Not_Exists):
            return Attr(field_name).not_exists()
        raise exceptions.UnsupportedFunctionException(type(node.function).__name__)

    def visit_Compare(self, node: ast.Compare) -> ConditionBase:
        field_name = self._field_name(node.left)
        field = Attr(field_name)

        if isinstance(node.right, ast.Null):
            if isinstance(node.comparator, ast.Eq):
                return field.not_exists() | field.attribute_type("NULL")
            if isinstance(node.comparator, ast.NotEq):
                return field.exists() & ~field.attribute_type("NULL")

        if isinstance(node.comparator, ast.Between):
            values = self.visit(node.right)
            if not isinstance(values, list) or len(values) != 2:
                raise exceptions.ArgumentTypeException("between", "two-item list")
            return field.between(values[0], values[1])

        value = self.visit(node.right)
        if isinstance(node.comparator, ast.Eq):
            return field.eq(value)
        if isinstance(node.comparator, ast.NotEq):
            return field.ne(value)
        if isinstance(node.comparator, ast.Lt):
            return field.lt(value)
        if isinstance(node.comparator, ast.LtE):
            return field.lte(value)
        if isinstance(node.comparator, ast.Gt):
            return field.gt(value)
        if isinstance(node.comparator, ast.GtE):
            return field.gte(value)
        if isinstance(node.comparator, ast.In):
            values = value if isinstance(value, list) else [value]
            return field.is_in(values)

        raise exceptions.UnsupportedFunctionException(type(node.comparator).__name__)

    def visit_BoolOp(self, node: ast.BoolOp) -> ConditionBase:
        left = self.visit(node.left)
        right = self.visit(node.right)

        if isinstance(node.op, ast.And):
            return left & right
        if isinstance(node.op, ast.Or):
            return left | right

        raise exceptions.UnsupportedFunctionException(type(node.op).__name__)

    def visit_UnaryOp(self, node: ast.UnaryOp) -> ConditionBase:
        operand = self.visit(node.operand)
        if isinstance(node.op, ast.Not):
            return ~operand
        raise exceptions.UnsupportedFunctionException(type(node.op).__name__)

    def visit_Call(self, node: ast.Call):
        func_name = node.func.name.lower()

        if func_name == "contains":
            field_name = self._field_name(node.args[0])
            return Attr(field_name).contains(self.visit(node.args[1]))
        if func_name == "startswith":
            field_name = self._field_name(node.args[0])
            return Attr(field_name).begins_with(self.visit(node.args[1]))
        if func_name in CASE_FOLDING_FUNCTIONS:
            # DynamoDB compares stored bytes; there is no case-folding operator,
            # so this cannot be part of a FilterExpression at any price. It used
            # to lowercase the *rendered argument* — for a field, the attribute
            # name, which is already lowercase — and so silently discarded the
            # fold, yielding a case-SENSITIVE match that returned nothing for any
            # capitalized value. Callers that want case-insensitive matching go
            # through build_filter_plan, which evaluates it in Python.
            raise exceptions.UnsupportedFunctionException(
                f"{node.func.name} cannot be evaluated by DynamoDB; use build_filter_plan() to evaluate it client-side"
            )

        raise exceptions.UnsupportedFunctionException(node.func.name)

    def _field_name(self, node: ast._Node) -> str:
        if isinstance(node, (ast.Identifier, ast.Attribute)):
            return self.visit(node)
        if isinstance(node, ast.Call) and node.func.name.lower() in CASE_FOLDING_FUNCTIONS:
            raise exceptions.UnsupportedFunctionException(
                f"{node.func.name} cannot be evaluated by DynamoDB; use build_filter_plan() to evaluate it client-side"
            )
        raise exceptions.ArgumentTypeException("field", "Identifier", type(node).__name__)


@dataclass(frozen=True)
class FilterPlan:
    """How to evaluate one OData ``$filter``, split across the two sides.

    ``condition`` is what DynamoDB evaluates as a ``FilterExpression``;
    ``residual`` holds the conjuncts DynamoDB cannot express (today: anything
    mentioning ``tolower``/``toupper``), evaluated in Python by :meth:`apply`.
    Either half may be empty — a filter that is nothing but a case-insensitive
    match has ``condition is None``, and the common case of a filter DynamoDB
    can evaluate whole has ``residual == ()`` and costs exactly what it did
    before this split existed.
    """

    condition: ConditionBase | None = None
    residual: tuple[ast._Node, ...] = ()
    #: Top-level attribute names ``residual`` reads. A projection that omits
    #: one of these would make the residual see a missing attribute and drop
    #: every row, so callers passing ``select`` must union these in.
    residual_fields: frozenset[str] = field(default_factory=frozenset)

    @property
    def has_residual(self) -> bool:
        return bool(self.residual)

    def matches(self, item: Mapping[str, Any]) -> bool:
        """True if ``item`` satisfies every residual conjunct."""
        return all(evaluate(node, item) for node in self.residual)

    def apply(self, items: Sequence[Mapping[str, Any]]) -> list[Any]:
        """Return the subset of ``items`` the residual accepts."""
        if not self.residual:
            return list(items)
        return [item for item in items if self.matches(item)]


def _split_conjuncts(node: ast._Node) -> list[ast._Node]:
    """Flatten a top-level ``and`` chain. ``AND`` distributes, so each conjunct
    can be evaluated on whichever side can express it."""
    if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.And):
        return _split_conjuncts(node.left) + _split_conjuncts(node.right)
    return [node]


def build_filter_plan(filter_str: str, policy: FilterPolicy | None = None) -> FilterPlan:
    """Parse an OData ``$filter`` into a server-side condition plus a residual.

    Use this instead of :func:`build_filter` whenever the filter may contain a
    case-folding function. ``build_filter`` raises on those rather than silently
    dropping the fold; this splits them out and evaluates them client-side.
    """
    ast_tree = parse_odata(filter_str)
    if policy is not None:
        policy.validate(ast_tree)

    server: list[ast._Node] = []
    residual: list[ast._Node] = []
    for conjunct in _split_conjuncts(ast_tree):
        (residual if uses_case_folding(conjunct) else server).append(conjunct)

    condition: ConditionBase | None = None
    if server:
        visitor_ = AstToDynamoConditionVisitor()
        for node in server:
            compiled = visitor_.visit(node)
            condition = compiled if condition is None else condition & compiled

    fields: set[str] = set()
    for node in residual:
        fields |= referenced_roots(node)

    return FilterPlan(
        condition=condition,
        residual=tuple(residual),
        residual_fields=frozenset(fields),
    )


def validate_filter(filter_str: str, policy: FilterPolicy) -> ast._Node:
    ast_tree = parse_odata(filter_str)
    policy.validate(ast_tree)
    return ast_tree


def build_filter(
    filter_str: str,
    policy: FilterPolicy | None = None,
) -> ConditionBase:
    """Parse an OData $filter expression and return a boto3 ConditionBase object.

    Args:
        filter_str: OData filter string, e.g. "status eq 'active' and age gt 18"

    Returns:
        A boto3 ConditionBase that can be passed directly as FilterExpression.

    Raises:
        InvalidQueryException: If the filter string cannot be parsed.
        UnsupportedFunctionException: If an unsupported OData function is used,
            including a case-folding function (``tolower``/``toupper``) that
            DynamoDB cannot evaluate — use :func:`build_filter_plan` for those.
    """
    ast_tree = parse_odata(filter_str)
    if policy is not None:
        policy.validate(ast_tree)
    return AstToDynamoConditionVisitor().visit(ast_tree)
