from __future__ import annotations

from typing import Any


def sort_items(
    items: list[dict[str, Any]],
    field: str,
    direction: str = "asc",
) -> list[dict[str, Any]]:
    """Sort a list of DynamoDB items by a single field.

    Items missing the sort field are sorted last regardless of direction.
    String comparison is case-insensitive.

    Args:
        items: List of item dicts to sort (not mutated — a new list is returned).
        field: Attribute name to sort by.
        direction: ``"asc"`` (default) or ``"desc"``.

    Returns:
        A new list sorted by ``field``.

    Raises:
        ValueError: If ``direction`` is not ``"asc"`` or ``"desc"``.
    """
    if direction not in ("asc", "desc"):
        raise ValueError(f"direction must be 'asc' or 'desc', got {direction!r}")

    reverse = direction == "desc"
    _MISSING = object()

    def sort_key(item: dict[str, Any]) -> tuple:
        val = item.get(field, _MISSING)
        if val is _MISSING:
            # asc (no reverse): (1, "") > (0, val) → last ✓
            # desc (reverse): (-1, "") < (0, val) → last after inversion ✓
            return (-1, "") if reverse else (1, "")
        if isinstance(val, str):
            return (0, val.lower())
        return (0, val)

    return sorted(items, key=sort_key, reverse=reverse)
