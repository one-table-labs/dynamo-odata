from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .odata_query import ast, visitor


class PartitionKeyValidationError(ValueError):
    pass


class FilterPolicyViolationError(ValueError):
    pass


@dataclass(frozen=True)
class PartitionKeyGuard:
    allowed_prefixes: tuple[str, ...]

    def __post_init__(self) -> None:
        prefixes = tuple(prefix for prefix in self.allowed_prefixes if prefix)
        if not prefixes:
            raise ValueError("allowed_prefixes must contain at least one non-empty prefix")
        object.__setattr__(self, "allowed_prefixes", prefixes)

    def validate(self, partition_key: str) -> None:
        if any(partition_key.startswith(prefix) for prefix in self.allowed_prefixes):
            return
        allowed = ", ".join(self.allowed_prefixes)
        raise PartitionKeyValidationError(f"Partition key {partition_key!r} must start with one of: {allowed}")


@dataclass(frozen=True)
class FilterPolicy:
    allowed_fields: frozenset[str] | None = None
    allowed_functions: frozenset[str] | None = None
    allowed_comparators: frozenset[str] | None = None
    max_predicates: int | None = None
    max_depth: int | None = None

    def __post_init__(self) -> None:
        if self.max_predicates is not None and self.max_predicates < 1:
            raise ValueError("max_predicates must be >= 1")
        if self.max_depth is not None and self.max_depth < 1:
            raise ValueError("max_depth must be >= 1")
        if self.allowed_functions is not None:
            object.__setattr__(
                self,
                "allowed_functions",
                frozenset(name.lower() for name in self.allowed_functions),
            )
        if self.allowed_comparators is not None:
            object.__setattr__(
                self,
                "allowed_comparators",
                frozenset(name.lower() for name in self.allowed_comparators),
            )

    def validate(self, node: ast._Node) -> None:
        _FilterPolicyValidator(self).validate(node)


class _FilterPolicyValidator:
    def __init__(self, policy: FilterPolicy) -> None:
        self.policy = policy
        self.predicate_count = 0

    def validate(self, node: ast._Node) -> None:
        self._walk(node, depth=1)
        if self.policy.max_predicates is not None and self.predicate_count > self.policy.max_predicates:
            raise FilterPolicyViolationError(
                f"Filter contains {self.predicate_count} predicates; max is {self.policy.max_predicates}"
            )

    def _walk(self, node: ast._Node, depth: int) -> None:
        if self.policy.max_depth is not None and depth > self.policy.max_depth:
            raise FilterPolicyViolationError(f"Filter nesting depth {depth} exceeds max depth {self.policy.max_depth}")

        checker = getattr(self, f"_check_{node.__class__.__name__}", None)
        if checker is not None:
            checker(node)

        for _, value in visitor.iter_dataclass_fields(node):
            if isinstance(value, ast._Node):
                self._walk(value, depth + 1)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, ast._Node):
                        self._walk(item, depth + 1)

    def _check_Compare(self, node: ast.Compare) -> None:
        self.predicate_count += 1
        comparator_name = self._comparator_name(node.comparator)
        self._ensure_comparator_allowed(comparator_name)
        self._ensure_field_allowed(self._field_name(node.left))

    def _check_Function(self, node: ast.Function) -> None:
        self.predicate_count += 1
        function_name = self._function_name(node.function)
        self._ensure_function_allowed(function_name)
        self._ensure_field_allowed(self._field_name(node.left))

    def _check_Call(self, node: ast.Call) -> None:
        function_name = node.func.name.lower()
        self._ensure_function_allowed(function_name)
        if node.args:
            first_arg = node.args[0]
            if isinstance(first_arg, (ast.Identifier, ast.Attribute, ast.Call)):
                self._ensure_field_allowed(self._field_name(first_arg))
        if function_name != "tolower":
            self.predicate_count += 1

    def _ensure_field_allowed(self, field_name: str) -> None:
        if self.policy.allowed_fields is None:
            return
        if field_name in self.policy.allowed_fields:
            return
        raise FilterPolicyViolationError(f"Field {field_name!r} is not allowed")

    def _ensure_function_allowed(self, function_name: str) -> None:
        if self.policy.allowed_functions is None:
            return
        if function_name in self.policy.allowed_functions:
            return
        raise FilterPolicyViolationError(f"Function {function_name!r} is not allowed")

    def _ensure_comparator_allowed(self, comparator_name: str) -> None:
        if self.policy.allowed_comparators is None:
            return
        if comparator_name in self.policy.allowed_comparators:
            return
        raise FilterPolicyViolationError(f"Comparator {comparator_name!r} is not allowed")

    def _field_name(self, node: ast._Node) -> str:
        if isinstance(node, ast.Identifier):
            return ".".join((*node.namespace, node.name)) if node.namespace else node.name
        if isinstance(node, ast.Attribute):
            return f"{self._field_name(node.owner)}.{node.attr}"
        if isinstance(node, ast.Call) and node.func.name.lower() == "tolower":
            if not node.args:
                raise FilterPolicyViolationError("tolower requires a field argument")
            return self._field_name(node.args[0])
        raise FilterPolicyViolationError(f"Unsupported field reference type: {type(node).__name__}")

    @staticmethod
    def _comparator_name(node: ast._Node) -> str:
        mapping = {
            ast.Eq: "eq",
            ast.NotEq: "ne",
            ast.Lt: "lt",
            ast.LtE: "le",
            ast.Gt: "gt",
            ast.GtE: "ge",
            ast.In: "in",
            ast.Between: "between",
        }
        for comparator_type, name in mapping.items():
            if isinstance(node, comparator_type):
                return name
        return type(node).__name__.lower()

    @staticmethod
    def _function_name(node: Any) -> str:
        if isinstance(node, ast.Exists):
            return "exists"
        if isinstance(node, ast.Not_Exists):
            return "not_exists"
        return type(node).__name__.lower()
