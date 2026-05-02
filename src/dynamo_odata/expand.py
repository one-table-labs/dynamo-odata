"""$expand — generic FK resolution and dotted-$select trimming."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .db import DynamoDb

_MAX_ALIASES = 3
_MAX_BASE_ITEMS = 500


@dataclass(frozen=True)
class ExpandConfig:
    local_key: str
    target_pk: str
    remote_key: str
    target_sk_prefix: str = ""
    fields: tuple[str, ...] | None = None


async def expand_items_async(
    items: list[dict[str, Any]],
    expand_specs: dict[str, ExpandConfig],
    db: DynamoDb,
) -> list[dict[str, Any]]:
    """Join expanded objects onto base items using batch_get_async per alias."""
    if not expand_specs:
        return items

    if len(expand_specs) > _MAX_ALIASES:
        raise ValueError(f"Too many $expand aliases ({len(expand_specs)}); maximum is {_MAX_ALIASES}.")
    if len(items) > _MAX_BASE_ITEMS:
        raise ValueError(f"Too many base items ({len(items)}) when $expand is active; maximum is {_MAX_BASE_ITEMS}.")

    async def _fetch_alias(alias: str, cfg: ExpandConfig) -> tuple[str, dict[str, Any]]:
        fk_values = list({item[cfg.local_key] for item in items if item.get(cfg.local_key) is not None})
        if not fk_values:
            return alias, {}
        sks = [f"{cfg.target_sk_prefix}{fk}" for fk in fk_values]
        results = await db.batch_get_async(
            cfg.target_pk,
            sks,
            fields=list(cfg.fields) if cfg.fields is not None else None,
            item_only=True,
        )
        lookup: dict[str, Any] = {r[cfg.remote_key]: r for r in results if cfg.remote_key in r}
        return alias, lookup

    alias_results = await asyncio.gather(*(_fetch_alias(alias, cfg) for alias, cfg in expand_specs.items()))
    lookups: dict[str, dict[str, Any]] = dict(alias_results)

    result = []
    for item in items:
        item = dict(item)
        for alias, cfg in expand_specs.items():
            fk = item.get(cfg.local_key)
            item[alias] = lookups[alias].get(fk) if fk is not None else None
        result.append(item)
    return result


def apply_dotted_select(
    items: list[dict[str, Any]],
    select_str: str | None,
) -> list[dict[str, Any]]:
    """Trim expanded nested objects to only the dotted subfields requested in $select."""
    if not select_str:
        return items

    expand_trims: dict[str, list[str]] = {}
    for field in select_str.split(","):
        field = field.strip()
        if "." in field:
            prefix, subfield = field.split(".", 1)
            expand_trims.setdefault(prefix, []).append(subfield)

    if not expand_trims:
        return items

    result = []
    for item in items:
        item = dict(item)
        for alias, subfields in expand_trims.items():
            expanded = item.get(alias)
            if expanded is None:
                continue
            item[alias] = {k: expanded[k] for k in subfields if k in expanded}
        result.append(item)
    return result


def parse_expand(
    expand_str: str | None,
    allowed: dict[str, ExpandConfig],
) -> dict[str, ExpandConfig]:
    """Parse and validate a comma-separated $expand value against the allowed config."""
    if not expand_str:
        return {}
    aliases = [a.strip() for a in expand_str.split(",") if a.strip()]
    result: dict[str, ExpandConfig] = {}
    for alias in aliases:
        if alias not in allowed:
            allowed_list = sorted(allowed.keys())
            raise ValueError(f"Unknown expand field {alias!r}. Allowed: {allowed_list}")
        result[alias] = allowed[alias]
    return result
