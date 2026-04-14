from __future__ import annotations

from typing import Dict, Iterable, Optional, Tuple


def build_projection(
    fields: Optional[Iterable[str]],
) -> Tuple[Optional[str], Dict[str, str]]:
    if not fields:
        return None, {}

    expression_parts = []
    expression_attribute_names: Dict[str, str] = {}

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