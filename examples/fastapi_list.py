"""
FastAPI + ODataService.list_async example.

Demonstrates the three routing strategies in list_async:
  - LSI sort  (field is in sort_field_map)
  - Python-sort fallback  (field is not in sort_field_map)
  - Unsorted  (no sort param)

Both OData-convention (?$top, ?$skipToken) and REST-convention
(?limit, ?cursor, ?sort, ?order) params are accepted simultaneously.

Run:
    pip install dynamo-odata[fastapi,async]
    uvicorn examples.fastapi_list:app --reload

Then open http://localhost:8000/docs to explore the API interactively.

Sample curl commands:
    # Unsorted, default limit 25
    curl "http://localhost:8000/files"

    # LSI sort on name (asc), REST-style params
    curl "http://localhost:8000/files?sort=name&order=asc&limit=10"

    # Python-sort fallback on mime_type (not in LSI map)
    curl "http://localhost:8000/files?sort=mime_type&order=asc&limit=10"

    # OData-style top + skipToken
    curl "http://localhost:8000/files?%24top=5"

    # Paginate with next_cursor from a previous response
    curl "http://localhost:8000/files?sort=name&cursor=<next_cursor>"
"""

from fastapi import Depends, FastAPI

from dynamo_odata import DynamoDb
from dynamo_odata.expand import ExpandConfig
from dynamo_odata.fastapi import ODataQueryParams, ODataService

app = FastAPI(
    title="dynamo-odata list_async example",
    docs_url="/docs",
)

# ─── DynamoDB setup ───────────────────────────────────────────────────────────
# Replace table_name and region with your real values.
db = DynamoDb(table_name="demo-table", region="us-west-2")

TENANT_PK = "TENANT#demo"
USER_PK = "USER#demo"

# ─── expand config ────────────────────────────────────────────────────────────
EXPAND_CONFIG: dict[str, ExpandConfig] = {
    "owner": ExpandConfig(
        local_key="owner_user_id",
        target_pk=USER_PK,
        remote_key="user_id",
        target_sk_prefix="USER#",
    ),
}

# ─── sort field map ───────────────────────────────────────────────────────────
# Maps a sort field name to (lsi_index_name, lsi_sort_attribute).
# Fields NOT in this map are sorted in Python (fetch-all + sort_items).
SORT_FIELD_MAP = {
    "name":       ("lsi-s3-index", "lsis3"),
    "created_at": ("lsi-s1-index", "lsis1"),
}

svc = ODataService(expand_config=EXPAND_CONFIG)


async def get_db() -> DynamoDb:
    return db


# ─── endpoints ────────────────────────────────────────────────────────────────


@app.get("/files")
async def list_files(
    params: ODataQueryParams = Depends(),
    db: DynamoDb = Depends(get_db),
):
    """List files with sort, pagination, and optional owner expansion.

    Supports both OData params ($top, $skipToken, $filter, $select, $expand)
    and REST params (limit, cursor, sort, order).

    Routing:
    - sort=name or sort=created_at  → LSI index on DynamoDB
    - sort=mime_type (any other)    → Python-side sort (fetch all, sort, slice)
    - no sort                       → standard DynamoDB scan with limit/cursor
    """
    tenant_id = "demo"  # in production, extract from JWT / request context
    return await svc.list_async(
        db=db,
        pk=f"TENANT#{tenant_id}",
        params=params,
        sort_field_map=SORT_FIELD_MAP,
    )
