from __future__ import annotations

from collections.abc import Iterable


def build_projection(
    fields: Iterable[str] | None,
) -> tuple[str | None, dict[str, str]]:
    """Build a DynamoDB ProjectionExpression from a list of field names.

    All fields are aliased via ExpressionAttributeNames to avoid conflicts
    with DynamoDB reserved keywords (e.g. 'name', 'status', 'id').

    Args:
        fields: Iterable of field names, supporting dotted notation for nested
                attributes (e.g. "address.city").

    Returns:
        A tuple of (ProjectionExpression string, ExpressionAttributeNames dict).
        Returns (None, {}) if fields is empty or None.

    Raises:
        TypeError: If ``fields`` is a str. A str satisfies Iterable[str] by
            yielding characters, so it would otherwise alias each character and
            return a corrupt expression instead of failing.
    """
    # Must precede the empty check: "" is falsy, so the early return would hand
    # back (None, {}) and silently drop the projection rather than flag the type.
    if isinstance(fields, str):
        raise TypeError(
            "build_projection() expects an iterable of field names, not a str; "
            "pass a list such as ['a', 'b'] (or fields.split(',') for a "
            "comma-separated $select value)"
        )

    if not fields:
        return None, {}

    expression_parts = []
    expression_attribute_names: dict[str, str] = {}

    for field in fields:
        if not field:
            continue
        alias_parts = []
        for part in field.split("."):
            alias = f"#{part}"
            expression_attribute_names[alias] = part
            alias_parts.append(alias)
        expression_parts.append(".".join(alias_parts))

    if not expression_parts:
        return None, {}

    return ",".join(expression_parts), expression_attribute_names
