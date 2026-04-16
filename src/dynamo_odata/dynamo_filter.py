from __future__ import annotations

from boto3.dynamodb.conditions import Attr, ConditionBase

from .guardrails import FilterPolicy
from .odata_query import ast, exceptions, visitor
from .odata_query.grammar import parse_odata


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
        if func_name == "tolower":
            return self._field_name(node.args[0]).lower()

        raise exceptions.UnsupportedFunctionException(node.func.name)

    def _field_name(self, node: ast._Node) -> str:
        if isinstance(node, (ast.Identifier, ast.Attribute)):
            return self.visit(node)
        if isinstance(node, ast.Call) and node.func.name.lower() == "tolower":
            return self._field_name(node.args[0]).lower()
        raise exceptions.ArgumentTypeException("field", "Identifier", type(node).__name__)


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
        UnsupportedFunctionException: If an unsupported OData function is used.
    """
    ast_tree = parse_odata(filter_str)
    if policy is not None:
        policy.validate(ast_tree)
    return AstToDynamoConditionVisitor().visit(ast_tree)
