import logging
from typing import Optional

from .. import ast, exceptions, visitor

log = logging.getLogger(__name__)


class AstToDynamoVisitor(visitor.NodeVisitor):
    """
    :class:`NodeVisitor` that transforms an :term:`AST` into a DynamoDB
    filter-expression builder string.

    Args:
        table_alias: Optional alias for the root table.
    """

    def __init__(self, table_alias: Optional[str] = None):
        super().__init__()
        self.table_alias = table_alias

    def visit_Identifier(self, node: ast.Identifier) -> str:
        ":meta private:"
        # Reconstruct full dotted path (e.g. item_information.created.create_date)
        full_name = (
            ".".join((*node.namespace, node.name)) if node.namespace else node.name
        )
        attr_name = f'"{full_name}"'

        if self.table_alias:
            attr_name = f'"{self.table_alias}".' + attr_name

        return attr_name

    def visit_Null(self, node: ast.Null) -> str:
        ":meta private:"
        return "NULL"

    def visit_Exists(self, node: ast.Exists) -> str:
        ":meta private:"
        return "exists"

    def visit_Not_Exists(self, node: ast.Not_Exists) -> str:
        ":meta private:"
        return "not_exists"

    def visit_Integer(self, node: ast.Integer) -> str:
        ":meta private:"
        return node.val

    def visit_Float(self, node: ast.Float) -> str:
        ":meta private:"
        return node.val

    def visit_Boolean(self, node: ast.Boolean) -> str:
        ":meta private:"
        return node.val.title()

    def visit_String(self, node: ast.String) -> str:
        ":meta private:"
        # Replace single quotes with double single-quotes acc SQL standard:
        val = node.val.replace("'", "''")
        # Wrap in single quotes for string constants acc SQL Standard
        return f"'{val}'"

    def visit_Date(self, node: ast.Date) -> str:
        ":meta private:"
        # Single quotes for date constants acc SQL Standard
        return f"DATE '{node.val}'"

    def visit_DateTime(self, node: ast.DateTime) -> str:
        ":meta private:"
        return f"'{node.val}'"

    def visit_Duration(self, node: ast.Duration) -> str:
        ":meta private:"
        sign, days, hours, minutes, seconds = node.unpack()

        sign = sign or ""
        intervals = []
        if days:
            intervals.append(f"INTERVAL '{days}' DAY")
        if hours:
            intervals.append(f"INTERVAL '{hours}' HOUR")
        if minutes:
            intervals.append(f"INTERVAL '{minutes}' MINUTE")
        if seconds:
            intervals.append(f"INTERVAL '{seconds}' SECOND")

        if len(intervals) == 0:
            # Shouldn't occur but whatever
            return ""
        if len(intervals) == 1:
            return f"{sign}{intervals[0]}"
        if len(intervals) > 1:
            interval = " + ".join(intervals)
            return f"{sign}({interval})"

        # Make Quality checks happy:
        raise Exception("This code is never reachable...")

    def visit_GUID(self, node: ast.GUID) -> str:
        ":meta private:"
        return f"'{node.val}'"

    def visit_List(self, node: ast.List) -> str:
        ":meta private:"
        options = ", ".join(self.visit(n) for n in node.val)
        return f"({options})"

    def visit_Add(self, node: ast.Add) -> str:
        ":meta private:"
        return "+"

    def visit_Sub(self, node: ast.Sub) -> str:
        ":meta private:"
        return "-"

    def visit_Mult(self, node: ast.Mult) -> str:
        ":meta private:"
        return "*"

    def visit_Div(self, node: ast.Div) -> str:
        ":meta private:"
        return "/"

    def visit_Mod(self, node: ast.Mod) -> str:
        ":meta private:"
        return "%"

    def visit_BinOp(self, node: ast.BinOp) -> str:
        ":meta private:"
        left = self.visit(node.left)
        right = self.visit(node.right)
        op = self.visit(node.op)

        return f"{left} {op} {right}"

    def visit_Eq(self, node: ast.Eq) -> str:
        ":meta private:"
        return "eq"

    def visit_NotEq(self, node: ast.NotEq) -> str:
        ":meta private:"
        return "ne"

    def visit_Lt(self, node: ast.Lt) -> str:
        ":meta private:"
        return "lt"

    def visit_LtE(self, node: ast.LtE) -> str:
        ":meta private:"
        return "lte"

    def visit_Gt(self, node: ast.Gt) -> str:
        ":meta private:"
        return "gt"

    def visit_GtE(self, node: ast.GtE) -> str:
        ":meta private:"
        return "gte"

    def visit_In(self, node: ast.In) -> str:
        ":meta private:"
        return "is_in"
        # return "in"

    def visit_Between(self, node: ast.Between) -> str:
        ":meta private:"
        return "between"

    def visit_Function(self, node: ast.Function) -> str:
        ":meta private:"
        left = self.visit(node.left)
        function = self.visit(node.function)
        return f"Attr({left}).{function}()"

    def visit_Compare(self, node: ast.Compare) -> str:
        ":meta private:"
        left = self.visit(node.left)
        right = self.visit(node.right)
        comparator = self.visit(node.comparator)

        # In case of a subexpression, wrap it in parentheses
        if isinstance(node.left, (ast.BoolOp, ast.Compare)):
            left = f"({left})"
        if isinstance(node.right, (ast.BoolOp, ast.Compare)):
            right = f"({right})"

        # DynamoDB has two distinct "no value" states:
        #   State 1 – attribute is absent (never stored / deleted via remove_key)
        #   State 2 – attribute exists with DynamoDB NULL type (Python None on write)
        #
        # 'field eq null'  → absent OR null-typed   (covers both states)
        # 'field ne null'  → exists AND not null-typed  (has a real value)
        #
        # The generic template would produce Attr(...).IS(NULL) which is SQL syntax
        # and would raise an AttributeError during eval().
        if isinstance(node.right, ast.Null):
            if isinstance(node.comparator, ast.Eq):
                return (
                    f"(Attr({left}).not_exists() | Attr({left}).attribute_type('NULL'))"
                )
            elif isinstance(node.comparator, ast.NotEq):
                return f"(Attr({left}).exists() & ~Attr({left}).attribute_type('NULL'))"

        # BETWEEN requires two separate positional args: between(low, high)
        # The OData list_expr `(low, high)` is an ast.List, so destructure it.
        if isinstance(node.comparator, ast.Between):
            if isinstance(node.right, ast.List) and len(node.right.val) == 2:
                low = self.visit(node.right.val[0])
                high = self.visit(node.right.val[1])
                return f"Attr({left}).between({low}, {high})"

        return f"Attr({left}).{comparator}({right})"

        # return f"{left} {comparator} {right}"

    def visit_And(self, node: ast.And) -> str:
        ":meta private:"
        return "&"

    def visit_Or(self, node: ast.Or) -> str:
        ":meta private:"
        return "|"

    def visit_BoolOp(self, node: ast.BoolOp) -> str:
        ":meta private:"
        left = self.visit(node.left)
        op = self.visit(node.op)
        right = self.visit(node.right)

        # In case of a subexpression, wrap it in parentheses
        # UNLESS it has the same operator as the current BoolOp, e.g.:
        # x AND y AND z
        if isinstance(node.left, ast.BoolOp) and node.left.op != node.op:
            left = f"({left})"
        if isinstance(node.right, ast.BoolOp) and node.right.op != node.op:
            right = f"({right})"

        return f"{left} {op} {right}"

    def visit_Not(self, node: ast.Not) -> str:
        ":meta private:"
        # Use Python's bitwise-NOT (~) which maps to boto3 condition __invert__().
        # "NOT" (uppercase) would be a SyntaxError in eval(); "not" (lowercase)
        # would call __bool__() on the condition instead of inverting it.
        return "~"

    def visit_UnaryOp(self, node: ast.UnaryOp) -> str:
        ":meta private:"
        op = self.visit(node.op)
        operand = self.visit(node.operand)

        # In case of a subexpression, wrap it in parentheses
        if isinstance(node.operand, ast.BoolOp):
            operand = f"({operand})"

        return f"{op} {operand}"

    def visit_Call(self, node: ast.Call) -> str:
        ":meta private:"
        try:
            # Grammar has already validated that the function is valid OData,
            # but that doesn't guarantee we can represent it in DynamoDB.
            func_gen = getattr(self, "func_" + node.func.name.lower())
        except AttributeError:
            raise exceptions.UnsupportedFunctionException(node.func.name)

        return func_gen(*node.args)

    def func_concat(self, *args: ast._Node) -> str:
        ":meta private:"
        raise exceptions.UnsupportedFunctionException("concat")

    def _to_pattern(self, arg: ast._Node, prefix: str = "", suffix: str = "") -> str:
        """
        Transform a node into a pattern usable in `LIKE` clauses.
        :meta private:
        """
        if isinstance(arg, (ast.Identifier, ast.Call)):
            res = self.visit(arg)
            if prefix:
                res = f"'{prefix}' || " + res
            if suffix:
                res = res + f" || '{suffix}'"
        else:
            res = str(arg.val).replace("%", "%%").replace("_", "__")  # type: ignore
            res = "'" + prefix + res + suffix + "'"
        return res

    # def visit_Eq(self, node: ast.Eq) -> str:
    #     ":meta private:"
    #     return "eq"

    # def visit_Contains(self, node: ast.Eq) -> str:
    #     ":meta private:"
    #     return "contains"
    def func_between(self, *args: ast._Node) -> str:
        ":meta private:"
        args_sql = [self.visit(arg) for arg in args]
        return f"Attr({args_sql[0]}).contains({args_sql[1]})"

    def func_contains(self, *args: ast._Node) -> str:
        ":meta private:"
        args_sql = [self.visit(arg) for arg in args]
        return f"Attr({args_sql[0]}).contains({args_sql[1]})"

    def func_in(self, *args: ast._Node) -> str:
        ":meta private:"
        args_sql = [self.visit(arg) for arg in args]
        return f"Attr({args_sql[0]}).contains({args_sql[1]})"

    def func_endswith(self, *args: ast._Node) -> str:
        ":meta private:"
        # DynamoDB FilterExpression has no ends-with / suffix-match operation.
        raise exceptions.UnsupportedFunctionException(
            "endswith is not supported by DynamoDB FilterExpression"
        )

    def func_indexof(self, *args: ast._Node) -> str:
        ":meta private:"
        raise exceptions.UnsupportedFunctionException("indexof")

    def func_length(self, arg: ast._Node) -> str:
        ":meta private:"
        raise exceptions.UnsupportedFunctionException("length")

    def func_startswith(self, *args: ast._Node) -> str:
        ":meta private:"
        args_sql = [self.visit(arg) for arg in args]
        return f"Attr({args_sql[0]}).begins_with({args_sql[1]})"

    def func_substring(self, *args: ast._Node) -> str:
        ":meta private:"
        raise exceptions.UnsupportedFunctionException("substring")

    def func_tolower(self, arg: ast._Node) -> str:
        ":meta private:"
        arg_sql: str = self.visit(arg)
        return arg_sql.lower()

    def func_toupper(self, arg: ast._Node) -> str:
        ":meta private:"
        raise exceptions.UnsupportedFunctionException("toupper")

    def func_trim(self, arg: ast._Node) -> str:
        ":meta private:"
        raise exceptions.UnsupportedFunctionException("trim")

    def func_year(self, arg: ast._Node) -> str:
        ":meta private:"
        raise exceptions.UnsupportedFunctionException("year")

    def func_month(self, arg: ast._Node) -> str:
        ":meta private:"
        raise exceptions.UnsupportedFunctionException("month")

    def func_day(self, arg: ast._Node) -> str:
        ":meta private:"
        raise exceptions.UnsupportedFunctionException("day")

    def func_hour(self, arg: ast._Node) -> str:
        ":meta private:"
        raise exceptions.UnsupportedFunctionException("hour")

    def func_minute(self, arg: ast._Node) -> str:
        ":meta private:"
        raise exceptions.UnsupportedFunctionException("minute")

    def func_date(self, arg: ast._Node) -> str:
        ":meta private:"
        raise exceptions.UnsupportedFunctionException("date")

    def func_now(self) -> str:
        ":meta private:"
        raise exceptions.UnsupportedFunctionException("now")

    def func_round(self, arg: ast._Node) -> str:
        ":meta private:"
        raise exceptions.UnsupportedFunctionException("round")

    def func_floor(self, arg: ast._Node) -> str:
        ":meta private:"
        raise exceptions.UnsupportedFunctionException("floor")

    def func_ceiling(self, arg: ast._Node) -> str:
        ":meta private:"
        raise exceptions.UnsupportedFunctionException("ceiling")

    def func_hassubset(self, *args: ast._Node) -> str:
        ":meta private:"
        raise exceptions.UnsupportedFunctionException("hassubset")
