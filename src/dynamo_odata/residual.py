"""Client-side evaluation of the OData predicates DynamoDB cannot express.

DynamoDB has no case-folding operator: a ``FilterExpression`` compares stored
bytes, so ``tolower(name)`` is not expressible as a key or filter expression at
any price.  Rendering it as one anyway is worse than rejecting it — the
expression compiles, parses, and returns a legitimate-looking empty page, so a
caller reads "no such record" off a filter that never ran.

The fix is a *split*: :func:`~dynamo_odata.dynamo_filter.build_filter_plan`
divides a filter's top-level conjunction into the part DynamoDB can evaluate
(sent as a ``FilterExpression``, unchanged) and a residual part evaluated here
in Python against each returned item.  ``AND`` distributes, so a conjunct
handled on either side yields the same result set; a conjunct that mixes a
case-folding call into an ``OR``/``NOT`` moves to Python whole, which is
correct and merely costs more bytes on the wire.

Evaluation deliberately mirrors DynamoDB's own semantics rather than Python's,
so a filter means the same thing whichever side runs it:

* A comparison against a missing attribute is **false** — including ``ne``.
  DynamoDB requires the attribute to exist before any comparator applies.
* A type mismatch is **false**, not an error.
* ``contains`` matches a substring of a string or membership of a list/set.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from .odata_query import ast, exceptions, visitor

#: Functions that fold case.  These are the reason a residual exists: DynamoDB
#: cannot evaluate them, so any conjunct mentioning one is evaluated in Python.
CASE_FOLDING_FUNCTIONS = frozenset({"tolower", "toupper"})


class _Missing:
    """Sentinel for "this item has no such attribute"."""

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<missing>"


MISSING = _Missing()


def uses_case_folding(node: ast._Node) -> bool:
    """True if ``node`` or any descendant calls a case-folding function."""
    if isinstance(node, ast.Call) and node.func.name.lower() in CASE_FOLDING_FUNCTIONS:
        return True
    return any(uses_case_folding(child) for child in _child_nodes(node))


def referenced_roots(node: ast._Node) -> set[str]:
    """Top-level attribute names ``node`` reads.

    Only the root segment of a dotted path is returned: projecting ``a`` returns
    the whole map at ``a``, which is a superset of ``a.b`` and cannot under-fetch
    what the predicate needs.
    """
    roots: set[str] = set()
    if isinstance(node, ast.Identifier):
        roots.add(node.namespace[0] if node.namespace else node.name)
        return roots
    if isinstance(node, ast.Call):
        # ``node.func`` is an Identifier holding the FUNCTION name, not a field —
        # walking it would project attributes called "contains" and "tolower".
        for arg in node.args:
            roots |= referenced_roots(arg)
        return roots
    for child in _child_nodes(node):
        roots |= referenced_roots(child)
    return roots


def evaluate(node: ast._Node, item: Mapping[str, Any]) -> bool:
    """Evaluate a boolean OData expression against one DynamoDB item."""
    return _truthy(_eval(node, item))


def _child_nodes(node: ast._Node) -> list[ast._Node]:
    children: list[ast._Node] = []
    for _, value in visitor.iter_dataclass_fields(node):
        if isinstance(value, ast._Node):
            children.append(value)
        elif isinstance(value, list):
            children.extend(v for v in value if isinstance(v, ast._Node))
    return children


def _truthy(value: Any) -> bool:
    return value is True


def _dotted_name(node: ast._Node) -> str | None:
    if isinstance(node, ast.Identifier):
        return ".".join((*node.namespace, node.name)) if node.namespace else node.name
    if isinstance(node, ast.Attribute):
        owner = _dotted_name(node.owner)
        return None if owner is None else f"{owner}.{node.attr}"
    return None


def _lookup(item: Mapping[str, Any], path: str) -> Any:
    current: Any = item
    for segment in path.split("."):
        if not isinstance(current, Mapping) or segment not in current:
            return MISSING
        current = current[segment]
    return current


def _eval(node: ast._Node, item: Mapping[str, Any]) -> Any:
    if isinstance(node, (ast.Identifier, ast.Attribute)):
        path = _dotted_name(node)
        return MISSING if path is None else _lookup(item, path)
    if isinstance(node, ast.Null):
        return None
    if isinstance(
        node,
        (
            ast.Integer,
            ast.Float,
            ast.Boolean,
            ast.String,
            ast.GUID,
            ast.Date,
            ast.Time,
            ast.DateTime,
            ast.Duration,
        ),
    ):
        return node.py_val
    if isinstance(node, ast.List):
        return [_eval(v, item) for v in node.val]
    if isinstance(node, ast.Call):
        return _eval_call(node, item)
    if isinstance(node, ast.Function):
        return _eval_function(node, item)
    if isinstance(node, ast.Compare):
        return _eval_compare(node, item)
    if isinstance(node, ast.BoolOp):
        left = _truthy(_eval(node.left, item))
        if isinstance(node.op, ast.And):
            return left and _truthy(_eval(node.right, item))
        if isinstance(node.op, ast.Or):
            return left or _truthy(_eval(node.right, item))
        raise exceptions.UnsupportedFunctionException(type(node.op).__name__)
    if isinstance(node, ast.UnaryOp):
        if isinstance(node.op, ast.Not):
            return not _truthy(_eval(node.operand, item))
        raise exceptions.UnsupportedFunctionException(type(node.op).__name__)
    raise exceptions.UnsupportedFunctionException(type(node).__name__)


def _eval_call(node: ast.Call, item: Mapping[str, Any]) -> Any:
    func_name = node.func.name.lower()

    if func_name in CASE_FOLDING_FUNCTIONS:
        value = _eval(node.args[0], item)
        if not isinstance(value, str):
            # A non-string (or absent) attribute has no folded form; treat it as
            # missing so every enclosing comparison is false, matching how
            # DynamoDB handles a type mismatch.
            return MISSING
        return value.lower() if func_name == "tolower" else value.upper()

    if func_name == "contains":
        haystack = _eval(node.args[0], item)
        needle = _eval(node.args[1], item)
        if haystack is MISSING or needle is MISSING:
            return False
        if isinstance(haystack, str):
            return isinstance(needle, str) and needle in haystack
        if isinstance(haystack, (list, set, frozenset, tuple)):
            return needle in haystack
        return False

    if func_name == "startswith":
        value = _eval(node.args[0], item)
        prefix = _eval(node.args[1], item)
        if not isinstance(value, str) or not isinstance(prefix, str):
            return False
        return value.startswith(prefix)

    raise exceptions.UnsupportedFunctionException(node.func.name)


def _eval_function(node: ast.Function, item: Mapping[str, Any]) -> Any:
    value = _eval(node.left, item)
    if isinstance(node.function, ast.Exists):
        return value is not MISSING
    if isinstance(node.function, ast.Not_Exists):
        return value is MISSING
    raise exceptions.UnsupportedFunctionException(type(node.function).__name__)


def _eval_compare(node: ast.Compare, item: Mapping[str, Any]) -> Any:
    left = _eval(node.left, item)

    if isinstance(node.right, ast.Null):
        is_null = left is MISSING or left is None
        if isinstance(node.comparator, ast.Eq):
            return is_null
        if isinstance(node.comparator, ast.NotEq):
            return not is_null

    if isinstance(node.comparator, ast.Between):
        values = _eval(node.right, item)
        if not isinstance(values, list) or len(values) != 2:
            raise exceptions.ArgumentTypeException("between", "two-item list")
        low, high = values
        return _ordered(low, left) and _ordered(left, high)

    right = _eval(node.right, item)

    if isinstance(node.comparator, ast.In):
        if left is MISSING:
            return False
        values = right if isinstance(right, list) else [right]
        return any(_equal(left, candidate) for candidate in values)

    # DynamoDB requires the attribute to exist before any comparator applies —
    # a missing attribute is false even under ``ne``.
    if left is MISSING or right is MISSING:
        return False

    if isinstance(node.comparator, ast.Eq):
        return _equal(left, right)
    if isinstance(node.comparator, ast.NotEq):
        return not _equal(left, right)
    if isinstance(node.comparator, ast.Lt):
        return _ordered(left, right) and not _equal(left, right)
    if isinstance(node.comparator, ast.LtE):
        return _ordered(left, right)
    if isinstance(node.comparator, ast.Gt):
        return _ordered(right, left) and not _equal(left, right)
    if isinstance(node.comparator, ast.GtE):
        return _ordered(right, left)

    raise exceptions.UnsupportedFunctionException(type(node.comparator).__name__)


def _numeric(value: Any) -> bool:
    return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)


def _comparable(left: Any, right: Any) -> bool:
    if _numeric(left) and _numeric(right):
        return True
    return type(left) is type(right) and isinstance(left, (str, bytes))


def _equal(left: Any, right: Any) -> bool:
    if left is MISSING or right is MISSING:
        return False
    if _numeric(left) and _numeric(right):
        return Decimal(str(left)) == Decimal(str(right))
    if isinstance(left, bool) or isinstance(right, bool):
        return left is right
    return type(left) is type(right) and bool(left == right)


def _ordered(left: Any, right: Any) -> bool:
    """``left <= right`` under DynamoDB's rules; a type mismatch is false."""
    if not _comparable(left, right):
        return False
    if _numeric(left):
        return Decimal(str(left)) <= Decimal(str(right))
    return bool(left <= right)
