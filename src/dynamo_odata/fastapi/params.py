"""ODataQueryParams — FastAPI Depends-compatible OData query parameter container."""

from __future__ import annotations

try:
    from fastapi import Query
except ImportError as e:
    raise ImportError("dynamo-odata[fastapi] is required — pip install dynamo-odata[fastapi]") from e


class ODataQueryParams:
    def __init__(
        self,
        filter: str | None = Query(None, alias="$filter"),
        select: str | None = Query(None, alias="$select"),
        expand: str | None = Query(None, alias="$expand"),
        top: int | None = Query(None, alias="$top"),
        skip_token: str | None = Query(None, alias="$skipToken"),
    ) -> None:
        self.filter = filter
        self.select = select
        self.expand = expand
        self.top = top
        self.skip_token = skip_token
