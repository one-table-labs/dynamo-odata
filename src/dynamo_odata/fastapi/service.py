"""ODataService — FastAPI integration layer for dynamo-odata."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

try:
    from fastapi import HTTPException
except ImportError as e:
    raise ImportError("dynamo-odata[fastapi] is required — pip install dynamo-odata[fastapi]") from e

from ..expand import ExpandConfig, apply_dotted_select, expand_items_async, parse_expand

if TYPE_CHECKING:
    from ..db import DynamoDb
    from .params import ODataQueryParams


def _base_select(select_str: str | None, expand_specs: dict[str, ExpandConfig]) -> str | None:
    """Strip dotted fields and inject local_key fields so FK values are always projected."""
    if select_str is None:
        return None

    fields = [f.strip() for f in select_str.split(",") if f.strip()]
    base_fields = [f for f in fields if "." not in f]
    for cfg in expand_specs.values():
        if cfg.local_key not in base_fields:
            base_fields.append(cfg.local_key)
    return ",".join(base_fields) if base_fields else None


def _resolve_expand_specs(
    expand_str: str | None,
    select_str: str | None,
    expand_config: dict[str, ExpandConfig],
) -> dict[str, ExpandConfig]:
    """Merge explicit $expand and dotted $select into a unified expand spec dict."""
    try:
        specs = parse_expand(expand_str, expand_config)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if select_str:
        for field in select_str.split(","):
            field = field.strip()
            if "." in field:
                prefix = field.split(".", 1)[0]
                if prefix not in specs:
                    if prefix not in expand_config:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Unknown expand prefix {prefix!r} in $select. Allowed: {sorted(expand_config)}",
                        )
                    specs[prefix] = expand_config[prefix]
    return specs


class ODataService:
    def __init__(self, expand_config: dict[str, ExpandConfig] | None = None) -> None:
        self.expand_config: dict[str, ExpandConfig] = expand_config or {}

    async def query_items(
        self,
        db: DynamoDb,
        pk: str,
        params: ODataQueryParams,
    ) -> dict[str, Any]:
        expand_specs = _resolve_expand_specs(params.expand, params.select, self.expand_config)
        items, next_link = await db.get_all_async(
            pk=pk,
            filter=params.filter,
            select=_base_select(params.select, expand_specs),
            limit=params.top or 25,
            cursor=params.skip_token,
        )
        if expand_specs:
            items = await expand_items_async(items, expand_specs, db)
        items = apply_dotted_select(items, params.select)
        return {"value": items, "@odata.nextLink": next_link}
