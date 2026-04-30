"""
FastAPI + dynamo-odata $expand example.

Run:
    pip install dynamo-odata[fastapi,async]
    uvicorn examples.fastapi_expand:app --reload

Then open http://localhost:8000/docs to explore the API interactively.

Sample curl commands (shell — escape $ as needed):
    curl "http://localhost:8000/items?%24top=5"
    curl "http://localhost:8000/items?%24filter=status+eq+'active'"
    curl "http://localhost:8000/items?%24expand=owner"
    curl "http://localhost:8000/items?%24select=id,status,owner.name,owner.email&%24expand=owner"
    curl "http://localhost:8000/items?%24select=id,owner.name"
"""

from fastapi import Depends, FastAPI

from dynamo_odata import DynamoDb
from dynamo_odata.expand import ExpandConfig
from dynamo_odata.fastapi import ODataQueryParams, ODataService

app = FastAPI(
    title="dynamo-odata $expand example",
    docs_url="/docs",
)

# ─── DynamoDB setup ───────────────────────────────────────────────────────────
# Replace table_name and region with your real values.
# For local dev, pass endpoint_url="http://localhost:8000" to target DynamoDB Local / LocalStack.
db = DynamoDb(table_name="demo-table", region="us-west-2")

TENANT_PK = "TENANT#demo"
USER_PK = "USER#demo"

# ─── expand config ────────────────────────────────────────────────────────────
# owner_user_id on each item resolves to USER_PK / SK "USER#<owner_user_id>"
EXPAND_CONFIG: dict[str, ExpandConfig] = {
    "owner": ExpandConfig(
        local_key="owner_user_id",
        target_pk=USER_PK,
        remote_key="user_id",
        target_sk_prefix="USER#",
    ),
}

# ─── ODataService (one per endpoint, holds expand config) ─────────────────────
item_service = ODataService(expand_config=EXPAND_CONFIG)

# ─── routes ───────────────────────────────────────────────────────────────────


@app.get("/items")
async def list_items(params: ODataQueryParams = Depends(ODataQueryParams)):
    """
    List items with full OData support.

    Supported query params:
    - $filter  — OData filter expression (e.g. status eq 'active')
    - $select  — comma-separated field list; dotted paths trim expanded objects
    - $expand  — comma-separated FK aliases to resolve (e.g. owner)
    - $top     — page size (default 25)
    - $skipToken — opaque pagination cursor from @odata.nextLink
    """
    return await item_service.query_items(db, TENANT_PK, params)
